"""Exercise the public run/summarize seam without rules, state, Docker or model calls."""
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FLOW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.common import FlowError, _atomic_json
from autoresearch_flow.experiment_run import run
from autoresearch_flow.experiment_data import summarize, write_summary, normalize


class IndependentExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ar-independent-experiment-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.method = self.root / "源码 with spaces"
        self.method.mkdir()
        (self.method / "__init__.py").touch()
        shutil.copyfile(FLOW / "tests/fixtures/experiment_method.py", self.method / "main.py")
        self.p = {"data": "synthetic-v1", "split": "dev", "training": False,
                  "evaluation_mode": "random", "seeds": [1, 2, 3],
                  "metric": {"name": "error", "direction": "minimize", "unit": "pp"},
                  "budget": {"steps": {"mode": "exact", "value": 1, "unit": "step"}}}
        self.command = [sys.executable, "{method}/main.py"]

    def execute(self, name="baseline", p=None, extra=(), **kwargs):
        return run(self.method, p or self.p, self.root / name, self.command + list(extra), role=name, **kwargs)

    def read(self, role, seed):
        return json.loads((self.root / role / f"seed_{seed}/result.json").read_text())

    def test_without_state_run_pair_and_exact_known_statistics(self):
        self.assertEqual(self.execute()["status"], "COMPLETE")
        self.execute("reference", extra=["--offset", "-4"])
        report = summarize([self.root / "baseline", self.root / "reference"])
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["statistics"]["baseline_mean"], 12)
        self.assertEqual(report["statistics"]["baseline_sample_std"], 1)
        self.assertEqual(report["statistics"]["mean_paired_improvement"], 4)
        self.assertTrue(report["significance_rule"]["passed"])
        self.assertEqual(report["significance_rule"]["strength"], "needs_more_runs_and_review")
        self.assertIsNone(report["normalization"])
        scored = summarize([self.root / "baseline", self.root / "reference"],
                           score_contract={"upper_bound": 6, "rationale": "synthetic known limit"})
        self.assertAlmostEqual(scored["normalization"]["reference"], 2 / 3)
        self.assertEqual(scored["scientific_review"], "NOT_PERFORMED")
        self.assertFalse(any(self.root.rglob("state.json")))

    def test_resume_skips_completed_and_preserves_failed_attempt(self):
        extra = ["--fail-once", str(self.root / "failure.flag")]
        first = self.execute(extra=extra, jobs=2)
        self.assertEqual(first["failed_seeds"], [2])
        prior = (self.root / "baseline/seed_2/attempt_001/run.log").read_bytes()
        partial = summarize([self.root / "baseline"])
        self.assertEqual(partial["status"], "PARTIAL")
        self.assertEqual(partial["groups"]["baseline"]["count"], 2)
        finished = self.execute(extra=extra, resume=True, jobs=2)
        self.assertEqual(finished["status"], "COMPLETE")
        self.assertEqual(finished["reused_seeds"], [1, 3])
        self.assertEqual((self.root / "baseline/seed_2/attempt_001/run.log").read_bytes(), prior)
        self.assertTrue((self.root / "baseline/seed_2/attempt_002/result.json").exists())
        self.assertEqual(summarize([self.root / "baseline"])["groups"]["baseline"]["count"], 3)

    def test_missing_seed_and_single_sample_are_provisional(self):
        p = {**self.p, "seeds": [1], "purpose": "exploratory"}
        self.execute(p=p)
        one = summarize([self.root / "baseline"])
        self.assertIsNone(one["groups"]["baseline"]["sample_std"])
        self.assertFalse(one["formal_sample_complete"])
        self.execute("reference")
        # Omission is detected even if the user supplies a subset of existing files.
        report = summarize([self.root / "reference/seed_1/result.json", self.root / "reference/seed_2/result.json"])
        self.assertEqual(report["status"], "PARTIAL")
        self.assertEqual(report["groups"]["reference"]["missing_seeds"], [3])

    def test_source_protocol_and_receipt_drift_never_reuse(self):
        self.execute()
        with self.assertRaisesRegex(FlowError, "方法/命令/协议"):
            self.execute(p={**self.p, "split": "hidden"}, resume=True)
        with (self.method / "main.py").open("a") as f:
            f.write("\n# changed source\n")
        with self.assertRaisesRegex(FlowError, "方法/命令/协议"):
            self.execute(resume=True)
        shutil.copyfile(FLOW / "tests/fixtures/experiment_method.py", self.method / "main.py")
        result = self.read("baseline", 1)
        result["metrics"]["raw"] = 999
        _atomic_json(self.root / "baseline/seed_1/result.json", result)
        with self.assertRaisesRegex(FlowError, "原始测量矛盾"):
            self.execute(resume=True)

    def test_invalid_metric_wrong_seed_timeout_and_exit_keep_raw_logs(self):
        for role, extra, timeout in [("nonfinite", ["--nan"], None),
                                      ("wrong", ["--wrong-seed"], None),
                                      ("timeout", ["--delay", "1"], 0.05)]:
            r = self.execute(role, p={**self.p, "seeds": [1]}, extra=extra, timeout_seconds=timeout)
            self.assertEqual(r["failed_seeds"], [1])
            result = self.read(role, 1)
            self.assertEqual(result["status"], "INVALID")
            self.assertTrue(result["failure_reason"])
            self.assertTrue((self.root / role / result["artifacts"]["log"]["path"]).stat().st_size)
            json.dumps(result, allow_nan=False)

    def test_cpu_parallel_execution_does_not_mix_outputs(self):
        self.execute(jobs=3, extra=["--delay", "0.25"])
        runs = [self.read("baseline", s) for s in self.p["seeds"]]
        self.assertEqual(len({r["execution"]["pid"] for r in runs}), 3)
        self.assertLess(max(r["execution"]["started_at"] for r in runs),
                        min(r["execution"]["finished_at"] for r in runs))
        self.assertEqual([r["metrics"]["raw"] for r in runs], [11, 12, 13])
        self.assertTrue(all(r["execution"]["environment"]["CUDA_VISIBLE_DEVICES"] == "" for r in runs))

    def test_gpu_assignment_is_simple_mocked_observation(self):
        devices = [{"id": str(i), "uuid": f"GPU-{i}", "name": "synthetic", "driver": "test", "busy": False}
                   for i in (4, 6)]
        with patch("autoresearch_flow.experiment_run.nvidia_devices", return_value=devices):
            self.execute(gpu_ids=["4", "6"], jobs=2, extra=["--delay", "0.1"])
        first = [self.read("baseline", s)["execution"]["environment"]["CUDA_VISIBLE_DEVICES"] for s in (1, 2)]
        self.assertEqual(set(first), {"GPU-4", "GPU-6"})
        with patch("autoresearch_flow.experiment_run.nvidia_devices", return_value=[{**d, "busy": True} for d in devices]):
            r = self.execute("busy", gpu_ids=["4"])
        self.assertEqual(r["pending_seeds"], [1, 2, 3])
        self.assertFalse(list((self.root / "busy").glob("seed_*")))

    def test_training_artifacts_are_seed_specific_and_reload_bound(self):
        self.execute(p={**self.p, "training": True}, extra=["--training"], jobs=3)
        report = summarize([self.root / "baseline"])
        self.assertEqual(report["status"], "COMPLETE")
        model_paths = [self.read("baseline", s)["artifacts"]["model"]["path"] for s in self.p["seeds"]]
        self.assertEqual(len(set(model_paths)), 3)
        (self.root / "baseline" / model_paths[1]).write_text("broken")
        self.assertEqual(summarize([self.root / "baseline"])["status"], "PARTIAL")
        with self.assertRaises(FlowError):
            self.execute(p={**self.p, "training": True}, extra=["--training"], resume=True)

    def test_historical_metric_forms_and_explicit_protocol_mapping(self):
        old = {"metric": "error", "metric_direction": "minimize", "evaluation_split": "dev"}
        paths = []
        for role, shift in (("baseline", 0), ("reference", -4)):
            for seed in self.p["seeds"]:
                path = self.root / f"old-{role}-{seed}.json"
                metric = {"name": "error", "direction": "minimize", "value": 10 + seed + shift}
                _atomic_json(path, {"status": "COMPLETE", "role": role, "seed": seed,
                                    "metrics": metric if role == "baseline" else {"primary": metric},
                                    "quality_gate": {"valid": True, "violations": []}, "protocol": old})
                paths.append(path)
        before = [x.read_bytes() for x in paths]
        report = summarize(paths, protocol_value={**self.p, "source_protocol": old})
        self.assertEqual(report["statistics"]["mean_paired_improvement"], 4)
        self.assertFalse(report["formal_sample_complete"])
        self.assertEqual(before, [x.read_bytes() for x in paths])
        wrong = summarize(paths, protocol_value={**self.p, "source_protocol": {**old, "evaluation_split": "hidden"}})
        self.assertFalse(wrong["paired_results"])
        contradicted = json.loads(paths[0].read_text())
        contradicted["quality_gate"]["passed"] = False
        _atomic_json(paths[0], contradicted)
        self.assertFalse(summarize(paths, protocol_value={**self.p, "source_protocol": old})["paired_results"])

    def test_existing_foreign_results_readonly_with_supplied_protocol(self):
        paths = []
        for role, shift in (("baseline", 0), ("reference", -4)):
            for s in self.p["seeds"]:
                path = self.root / f"historical-{role}-{s}.json"
                _atomic_json(path, {"status": "succeeded", "role": role, "seed": s,
                                    "raw_metric": 10 + s + shift, "quality_passed": True})
                paths.append(path)
        before = {p: p.read_bytes() for p in paths}
        report = summarize(paths, protocol_value=self.p)
        self.assertEqual(report["statistics"]["mean_paired_improvement"], 4)
        self.assertEqual(report["status"], "PARTIAL")
        self.assertIsNone(report["significance_rule"]["passed"])
        self.assertEqual(before, {p: p.read_bytes() for p in paths})
        write_summary(report, self.root / "summary")
        self.assertTrue((self.root / "summary/summary.md").exists())

    def test_mixed_protocol_and_duplicate_seed_do_not_silently_pair(self):
        self.execute()
        self.execute("reference", p={**self.p, "split": "hidden"})
        r = summarize([self.root / "baseline", self.root / "reference"])
        self.assertEqual(r["status"], "PARTIAL")
        self.assertEqual(r["paired_results"], {})
        copy_path = self.root / "copy.json"
        shutil.copyfile(self.root / "baseline/seed_1/result.json", copy_path)
        with self.assertRaisesRegex(FlowError, "重复"):
            summarize([self.root / "baseline", copy_path])

    def test_deterministic_and_maximize_no_clipping(self):
        p = {**self.p, "evaluation_mode": "deterministic", "seeds": [1],
             "determinism_basis": "合成算术、固定输入，无随机算子",
             "metric": {"name": "accuracy", "direction": "maximize", "unit": "pp"}}
        self.execute(p=p)
        self.execute("reference", p=p, extra=["--offset", "5"])
        r = summarize([self.root / "baseline", self.root / "reference"],
                      score_contract={"upper_bound": 13, "rationale": "synthetic"})
        self.assertTrue(r["significance_rule"]["passed"])
        self.assertEqual(r["normalization"]["reference"], 2.5)
        self.assertFalse(r["normalization"]["reference_in_range"])
        self.assertEqual(normalize(0, 12, 6, "minimize"), 2)

    def test_documented_deterministic_training_does_not_require_extra_seeds(self):
        p = {**self.p, 'training': True, 'evaluation_mode': 'deterministic', 'seeds': [1],
             'determinism_basis': 'Synthetic fixed arithmetic and saved bytes; no random operator.'}
        self.execute(p=p, extra=['--training'])
        self.execute('reference', p=p, extra=['--training', '--offset', '-4'])
        result = summarize([self.root / 'baseline', self.root / 'reference'])
        self.assertTrue(result['formal_sample_complete'])
        self.assertTrue(result['significance_rule']['passed'])
        self.assertIsNone(result['statistics']['baseline_sample_std'])

    def test_cli_run_and_summary_do_not_import_state_or_runtime(self):
        config = self.root / "protocol.json"
        _atomic_json(config, {**self.p, "seeds": [1], "purpose": "exploratory"})
        run_args = ["--format", "json", "experiment", "run", "--method", str(self.method),
                    "--protocol", str(config), "--output-dir", str(self.root / "cli"), "--", *self.command]
        code = "import cli,sys; rc=cli.main(sys.argv[1:]); assert 'autoresearch_flow.core' not in sys.modules; assert 'autoresearch_flow.runtime' not in sys.modules; sys.exit(rc)"
        result = subprocess.run([sys.executable, "-c", code, *run_args], cwd=FLOW, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["status"], "COMPLETE")
        summary = subprocess.run([sys.executable, str(FLOW / "cli.py"), "--format", "json", "experiment", "summarize",
                                  "--results", str(self.root / "cli")], capture_output=True, text=True)
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertFalse(json.loads(summary.stdout)["formal_sample_complete"])

    def test_complete_receipt_tampering_is_detected_by_readonly_summary(self):
        self.execute()
        r = self.read("baseline", 1)
        r["metrics"]["raw"] = 100
        _atomic_json(self.root / "baseline/seed_1/result.json", r)
        report = summarize([self.root / "baseline"])
        self.assertEqual(report["status"], "PARTIAL")
        self.assertFalse(report["formal_sample_complete"])
        self.assertTrue(report["evidence_issues"])

    def test_live_group_rejects_duplicate_resume_then_lost_receipt_is_not_success(self):
        p = {**self.p, "seeds": [1], "purpose": "exploratory"}
        config = self.root / "p.json"
        _atomic_json(config, p)
        command = self.command + ["--delay", "0.5"]
        args = [sys.executable, str(FLOW / "cli.py"), "--format", "json", "experiment", "run",
                "--method", str(self.method), "--protocol", str(config), "--output-dir", str(self.root / "live"),
                "--role", "live", "--", *command]
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import time
            deadline = time.monotonic() + 5
            while not (self.root / "live/seed_1/result.json").exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            with self.assertRaisesRegex(FlowError, "运行"):
                run(self.method, p, self.root / "live", command, role="live", resume=True)
            stdout, stderr = proc.communicate(timeout=5)
            self.assertEqual(proc.returncode, 0, stdout + stderr)
        finally:
            if proc.poll() is None:
                proc.terminate()
                proc.communicate(timeout=5)
        # Simulate an unobserved terminal receipt, not a real controller fault.
        r = self.read("live", 1)
        r["status"] = "RUNNING"
        r["execution"].update(exit_code=None, finished_at=None, duration_seconds=None)
        _atomic_json(self.root / "live/seed_1/result.json", r)
        _atomic_json(self.root / "live/seed_1/attempt_001/result.json", r)
        resumed = run(self.method, p, self.root / "live", command, role="live", resume=True)
        self.assertEqual(resumed["reused_seeds"], [])
        old = json.loads((self.root / "live/seed_1/attempt_001/result.json").read_text())
        self.assertEqual(old["status"], "INTERRUPTED")
        self.assertIsNone(old["execution"]["exit_code"])
        self.assertTrue(old["execution"]["missing_reason"])

    def test_output_protection_and_invalid_inputs(self):
        with self.assertRaisesRegex(FlowError, "分开"):
            run(self.method, self.p, self.method / "out", self.command)
        self.execute()
        with self.assertRaisesRegex(FlowError, "已存在"):
            self.execute()
        for p in ({**self.p, "seeds": [1, 1]},
                  {**self.p, "evaluation_mode": "deterministic"},
                  {**self.p, "budget": {"steps": {"mode": "exact", "value": -1, "unit": "step"}}}):
            with self.assertRaises(FlowError):
                run(self.method, p, self.root / "invalid", self.command)
        self.assertFalse((self.root / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
