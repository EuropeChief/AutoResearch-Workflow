"""Bounded CPU subprocesses exercise the queue; no models or GPU training."""
import copy
import json
import os
import signal
import subprocess
import sys
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoresearch_flow.core import FlowError
from autoresearch_flow.experiment_runner import ExperimentRunner
import test_w2_contract as w2


ADAPTER = '''import json, os, sys, time
from pathlib import Path
request = json.loads(Path(sys.argv[1]).read_text())
run = request["run"]
time.sleep(0.05)
assert os.environ["PYTHONHASHSEED"] == str(run["seed"])
assert Path.cwd() == Path(request["output_directory"])
assert Path(request["method_directory"], "method.py").is_file()
result = {key: run[key] for key in ("seed", "role", "method_sha256", "seed_plan_sha256", "protocol_sha256")}
result.update(status="succeeded", raw_metric=run["seed"] * 2.0, quality_passed=True,
              fixed=request["protocol"]["fixed"], actual_budget={"updates": 100},
              devices=request["assigned_devices"])
Path("adapter-result.json").write_text(json.dumps(result))
print("synthetic completed seed", run["seed"], flush=True)
'''


class QueueTests(unittest.TestCase):
    ref = w2.W2Tests.ref

    def setUp(self):
        w2.W2Tests.setUp(self)
        method = self.ref(".autoresearch-flow/delivery/best_versions/synthetic/method.py", "# synthetic method\n")
        selection = self.ref(".autoresearch-flow/delivery/best_versions/synthetic/selection.json",
                             json.dumps({"snapshot_files": [method], "selected_track": "seed"}))
        self.ref(".autoresearch-flow/delivery/best_current.json", json.dumps({
            "version": "synthetic", "selection_sha256": selection["sha256"]}))
        self.plan = {"schema_version": 1, "id": "final", "protocol_id": "p1", "seeds": [1, 2, 3],
                     "selection": selection, "adapter_files": [self.ref("adapter.py", ADAPTER)],
                     "command": [sys.executable, "{adapter_root}/adapter.py", "{request}"],
                     "output_root": "retests/final", "timeout_seconds": 10,
                     "resources": {"gpu_ids": [], "gpus_per_run": 0, "max_parallel": 1,
                                   "cpu_threads": 1, "metric_sensitive": False, "hardware_sensitive": False,
                                   "authorization": self.proof}}

    def test_serial_parallel_equal_and_completed_results_reused(self):
        runner = ExperimentRunner(self.root)
        serial = runner.execute(self.plan)
        self.assertEqual(serial["status"], "ok", serial)
        self.assertEqual(serial["report"]["groups"]["best_method"]["mean"], 4.0)
        self.assertEqual(serial["report"]["groups"]["best_method"]["sample_std"], 2.0)
        digest = serial["report"]["experiment_sha256"]
        repeated = runner.execute(self.plan)
        self.assertEqual(repeated["launched"], [])
        self.assertEqual(repeated["report"]["experiment_sha256"], digest)
        directories = [self.root / path for path in repeated["run_directories"].values()]
        self.assertEqual(len(set(directories)), 3)
        for directory in directories:
            execution = json.loads((directory / "execution.json").read_text())
            self.assertEqual(execution["exit_code"], 0)
            self.assertEqual(execution["devices"], ["cpu"])
            self.assertIn("synthetic completed", (directory / "run.log").read_text())
        p2 = copy.deepcopy(self.p)
        p2["id"] = "p2"
        self.book.lock(p2)
        plan = copy.deepcopy(self.plan)
        plan.update(id="parallel", protocol_id="p2", output_root="retests/parallel")
        plan["resources"]["max_parallel"] = 3
        parallel = runner.execute(plan)
        self.assertEqual(parallel["status"], "ok", parallel)
        self.assertEqual(parallel["report"]["groups"], serial["report"]["groups"])

    def test_failures_are_recorded_and_only_explicit_infra_retry_is_allowed(self):
        # A missing executable is infrastructure; a nonzero adapter is not.
        self.plan["command"][0] = "/no/such/queue-python"
        runner = ExperimentRunner(self.root)
        failed = runner.execute(self.plan)
        self.assertEqual(failed["status"], "blocked")
        self.assertEqual({r["status"] for r in failed["report"]["attempts"]}, {"infra_error"})
        self.assertEqual(runner.execute(self.plan)["launched"], [])
        retried = runner.execute(self.plan, retry_of=[failed["launched"][0]])
        self.assertEqual(len(retried["launched"]), 1)
        self.assertEqual(len(retried["report"]["attempts"]), 4)
        with self.assertRaises(FlowError):
            runner.execute(self.plan, retry_of=[failed["launched"][0]])

    def test_nonzero_timeout_and_malformed_results_never_join_aggregate(self):
        adapters = [("nonzero", "import sys; sys.exit(9)", "failed"),
                    ("bad", "from pathlib import Path; Path('adapter-result.json').write_text('{bad')", "format_error"),
                    ("slow", "import time; time.sleep(5)", "timeout")]
        for name, source, expected in adapters:
            with self.subTest(name=name):
                p = copy.deepcopy(self.p); p["id"] = name
                self.book.lock(p)
                plan = copy.deepcopy(self.plan)
                plan.update(id=name, protocol_id=name, output_root="retests/" + name, timeout_seconds=0.2)
                plan["adapter_files"] = [self.ref(name + ".py", source)]
                plan["command"][1] = "{adapter_root}/" + name + ".py"
                result = ExperimentRunner(self.root).execute(plan)
                self.assertEqual(result["status"], "blocked")
                self.assertEqual({r["status"] for r in result["report"]["attempts"]}, {expected})
                self.assertEqual(result["report"]["groups"]["best_method"]["count"], 0)
                with self.assertRaises(FlowError):
                    ExperimentRunner(self.root).execute(plan, retry_of=[result["launched"][0]])

    def test_second_controller_rejected_while_first_is_running(self):
        self.plan["adapter_files"] = [self.ref("adapter.py", ADAPTER.replace("time.sleep(0.05)", "time.sleep(0.3)"))]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(ExperimentRunner(self.root).execute, self.plan)
            for _ in range(100):
                if list((self.root / "retests/final").glob("*/execution.json")):
                    break
                time.sleep(0.01)
            with self.assertRaises(FlowError) as caught:
                ExperimentRunner(self.root).execute(self.plan)
            self.assertEqual(caught.exception.code, "QUEUE_ACTIVE")
            self.assertEqual(future.result()["status"], "ok")

    def test_killed_controller_does_not_duplicate_live_seed_or_invent_exit(self):
        self.plan["adapter_files"] = [self.ref("adapter.py", ADAPTER.replace("time.sleep(0.05)", "time.sleep(0.6)"))]
        self.ref("plan.json", json.dumps(self.plan))
        code = ("import json,sys; from autoresearch_flow.experiment_runner import ExperimentRunner; "
                "from pathlib import Path; p=Path(sys.argv[1]); ExperimentRunner(p).execute(json.loads((p/'plan.json').read_text()))")
        controller = subprocess.Popen([sys.executable, "-c", code, str(self.root)],
                                      cwd=Path(__file__).resolve().parents[1], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.PIPE, start_new_session=True)
        try:
            for _ in range(200):
                paths = list((self.root / "retests/final").glob("*/execution.json"))
                if paths:
                    break
                if controller.poll() is not None:
                    self.fail(controller.stderr.read().decode())
                time.sleep(0.01)
            self.assertTrue(paths)
            os.kill(controller.pid, signal.SIGKILL)
            controller.wait(timeout=5)
            resumed = ExperimentRunner(self.root).execute(self.plan)
            self.assertEqual(resumed["status"], "running")
            self.assertEqual(resumed["launched"], [])
            self.assertEqual(len(resumed["active"]), 1)
            time.sleep(0.7)
            recovered = ExperimentRunner(self.root).execute(self.plan)
            self.assertEqual(len(recovered["launched"]), 2)
            self.assertEqual(recovered["report"]["groups"]["best_method"]["count"], 2)
            self.assertEqual(recovered["report"]["attempts"][0]["status"], "infra_error")
            execution = json.loads((paths[0]).read_text())
            self.assertIsNone(execution["exit_code"])
            self.assertIn("missing_reason", execution)
        finally:
            if controller.poll() is None:
                controller.kill(); controller.wait()
            controller.stderr.close()

    def test_authorized_gpu_pool_busy_wait_no_overlap_and_actual_binding(self):
        self.plan["resources"].update(gpu_ids=["4", "6"], gpus_per_run=1, max_parallel=2, hardware_sensitive=True)
        devices = [{"id": i, "uuid": "GPU-synthetic-" + i, "name": "synthetic", "driver": "none", "busy": True}
                   for i in ("4", "6")]
        runner = ExperimentRunner(self.root, device_probe=lambda: copy.deepcopy(devices))
        waiting = runner.execute(self.plan)
        self.assertEqual(waiting["status"], "waiting_for_resources")
        self.assertEqual(waiting["launched"], [])
        self.assertEqual(waiting["pending_seeds"], [1, 2, 3])
        for device in devices:
            device["busy"] = False
        result = runner.execute(self.plan)
        self.assertEqual(result["status"], "ok", result)
        executions = [json.loads((self.root / d / "execution.json").read_text()) for d in result["run_directories"].values()]
        self.assertEqual({x["devices"][0] for x in executions}, {"GPU-synthetic-4", "GPU-synthetic-6"})
        for item in executions:
            self.assertEqual(item["environment"]["CUDA_VISIBLE_DEVICES"], item["devices"][0])
            self.assertEqual(len(item["device_inventory"]), 1)
        # Completion of the first two is required before the third reuses a card.
        self.assertGreaterEqual(executions[2]["started_at"], executions[0]["finished_at"])
        reused = ExperimentRunner(self.root, device_probe=lambda: []).execute(self.plan)
        self.assertEqual(reused["status"], "ok")
        self.assertEqual(reused["launched"], [])

    def test_heterogeneous_gpu_and_parallel_timing_rejected_without_launch(self):
        self.plan["resources"].update(max_parallel=2, metric_sensitive=True)
        with self.assertRaises(FlowError):
            ExperimentRunner(self.root).execute(self.plan)
        self.plan["resources"].update(metric_sensitive=False, gpu_ids=["4", "6"], gpus_per_run=1, hardware_sensitive=True)
        devices = [{"id": i, "uuid": "GPU-synthetic-" + i, "name": i, "driver": "none", "busy": False}
                   for i in ("4", "6")]
        with self.assertRaises(FlowError) as caught:
            ExperimentRunner(self.root, device_probe=lambda: devices).execute(self.plan)
        self.assertEqual(caught.exception.code, "RESOURCE_POLICY")

    def test_plan_drift_wrong_seed_and_modified_method_rejected(self):
        runner = ExperimentRunner(self.root)
        bad = copy.deepcopy(self.plan); bad["seeds"] = [1, 2]
        with self.assertRaises(FlowError):
            runner.execute(bad)
        result = runner.execute(self.plan)
        self.assertEqual(result["status"], "ok")
        bad = copy.deepcopy(self.plan); bad["resources"]["cpu_threads"] = 2
        with self.assertRaises(FlowError) as caught:
            runner.execute(bad)
        self.assertEqual(caught.exception.code, "QUEUE_DRIFT")
        method = self.root / ".autoresearch-flow/delivery/best_versions/synthetic/method.py"
        method.write_text("# changed\n")
        with self.assertRaises(FlowError):
            runner.execute(self.plan)

    def test_method_copy_mutation_rejected_and_training_evidence_reaches_w2(self):
        self.plan["adapter_files"] = [self.ref("adapter.py", ADAPTER + '\nPath(request["method_directory"], "method.py").write_text("mutated")\n')]
        result = ExperimentRunner(self.root).execute(self.plan)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["report"]["groups"]["best_method"]["count"], 0)
        p = copy.deepcopy(self.p); p.update(id="training", training=True)
        self.book.lock(p)
        training = ADAPTER + '''
import hashlib
model = Path("model.bin"); model.write_text(str(run["seed"]))
artifact = {"seed": run["seed"], "role": "best_method", "method_sha256": run["method_sha256"],
            "sha256": hashlib.sha256(model.read_bytes()).hexdigest(), "size_bytes": model.stat().st_size,
            "reload_metric": result["raw_metric"], "format": "synthetic"}
Path("artifact.json").write_text(json.dumps(artifact)); Path("reload.log").write_text("synthetic reload")
result.update(training_origin="initialization", reload_passed=True, reload_metric=result["raw_metric"],
              artifacts={"model": "model.bin", "artifact": "artifact.json", "reload_log": "reload.log"})
Path("adapter-result.json").write_text(json.dumps(result))
'''
        plan = copy.deepcopy(self.plan)
        plan.update(id="training", protocol_id="training", output_root="retests/training")
        plan["adapter_files"] = [self.ref("train.py", training)]
        plan["command"][1] = "{adapter_root}/train.py"
        result = ExperimentRunner(self.root).execute(plan)
        self.assertEqual(result["status"], "ok", result)
        self.assertEqual(result["report"]["groups"]["best_method"]["count"], 3)

    def test_cli_execute_and_report_share_ledger(self):
        plan = self.ref("plan.json", json.dumps(self.plan))
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        command = [sys.executable, str(cli), "--format", "json", "experiment", "execute", "--task-root", str(self.root),
                   "--plan", str(self.root / plan["path"])]
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["report"]["groups"]["best_method"]["mean"], 4.0)

    def test_malformed_failure_is_not_reclassified_as_retryable_infrastructure(self):
        broken = ADAPTER + '\nresult["status"]="failed"\nPath("adapter-result.json").write_text(json.dumps(result))\n'
        self.plan["adapter_files"] = [self.ref("adapter.py", broken)]
        runner = ExperimentRunner(self.root)
        result = runner.execute(self.plan)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual({r["status"] for r in result["report"]["attempts"]}, {"format_error"})
        with self.assertRaises(FlowError):
            runner.execute(self.plan, retry_of=[result["launched"][0]])

    def test_crash_between_ledger_start_and_queue_index_can_resume(self):
        self.ref("plan.json", json.dumps(self.plan))
        # Fault injection at the OS atomic replacement boundary, not a mock of
        # W2/queue logic: the real ledger is durable before SIGKILL.
        code = '''import json,os,signal,sys
from pathlib import Path
from autoresearch_flow.experiment_runner import ExperimentRunner
root=Path(sys.argv[1]); replace=os.replace
def crash(source,dest):
    ledger=root/".autoresearch-flow/experiments.json"
    if Path(dest).name=="queue.json" and ledger.exists() and json.loads(ledger.read_text())["runs"]:
        os.kill(os.getpid(),signal.SIGKILL)
    return replace(source,dest)
os.replace=crash
ExperimentRunner(root).execute(json.loads((root/"plan.json").read_text()))
'''
        result = subprocess.run([sys.executable, "-c", code, str(self.root)],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        runner = ExperimentRunner(self.root)
        recovered = runner.execute(self.plan)
        self.assertEqual(len(recovered["launched"]), 2)
        failed = [r for r in recovered["report"]["attempts"] if r["status"] == "infra_error"]
        self.assertEqual(len(failed), 1)
        retried = runner.execute(self.plan, retry_of=[failed[0]["run_id"]])
        self.assertEqual(retried["status"], "ok", retried)
        self.assertEqual(len(retried["report"]["attempts"]), 4)

    def test_unpublished_launch_preparation_crashes_leave_no_formal_run(self):
        for when in ("before", "after"):
            p = copy.deepcopy(self.p); p["id"] = when
            self.book.lock(p)
            plan = copy.deepcopy(self.plan)
            plan.update(id=when, protocol_id=when, output_root="retests/" + when)
            self.ref("plan.json", json.dumps(plan))
            code = '''import json,os,signal,sys
from pathlib import Path
from autoresearch_flow.experiment_runner import ExperimentRunner
root=Path(sys.argv[1]); when=sys.argv[2]; replace=os.replace
def crash(source,dest):
    hit=Path(dest).name=="launch-intent.json"
    if hit and when=="before": os.kill(os.getpid(),signal.SIGKILL)
    result=replace(source,dest)
    if hit and when=="after": os.kill(os.getpid(),signal.SIGKILL)
    return result
os.replace=crash
ExperimentRunner(root).execute(json.loads((root/"plan.json").read_text()))
'''
            result = subprocess.run([sys.executable, "-c", code, str(self.root), when],
                                    cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
            self.assertEqual(result.returncode, -signal.SIGKILL)
            recovered = ExperimentRunner(self.root).execute(plan)
            self.assertEqual(recovered["status"], "ok", recovered)
            self.assertEqual(len(recovered["launched"]), 3)


if __name__ == "__main__":
    unittest.main()
