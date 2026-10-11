"""State-free native scoring: raw Trial evidence, not authored pass receipts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from autoresearch_flow.common import FlowError


class NativeHarborTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, mode="candidate", *, destination="workspace/solution", artifact_toml=None):
        from autoresearch_flow.harbor_native import CANDIDATE_AGENT, inventory
        trial = self.root / "trial"
        trial.mkdir()
        candidate = self.root / "candidate"
        candidate.mkdir()
        (candidate / "method.py").write_text("def predict(x): return x\n")
        (candidate / "model.bin").write_bytes(b"synthetic-model\x00")
        import shutil
        shutil.copytree(candidate, trial / "artifacts" / destination)
        task = self.root / "task"
        task.mkdir()
        (task / "task.toml").write_text(artifact_toml if artifact_toml is not None else
                                      'artifacts=["/workspace/solution"]\n')
        agent = {"name": "nop"} if mode == "nop" else {
            "import_path": CANDIDATE_AGENT, "kwargs": {"candidate_path": str(candidate)}}
        config = {"task": {"path": str(self.root / "task")}, "agent": agent}
        result = {"config": {**config, "environment": {"type": "docker"},
                              "verifier": {"disable": False}},
                  "agent_info": {"name": "nop" if mode == "nop" else "autoresearch-candidate"},
                  "verifier_environment_mode": "separate", "exception_info": None,
                  "verifier_result": {"rewards": {"reward": -0.5}},
                  "started_at": "2026-10-09T00:00:00Z", "finished_at": "2026-10-09T00:00:04Z",
                  "agent_execution": {"finished_at": "2026-10-09T00:00:01Z"},
                  "verifier": {"started_at": "2026-10-09T00:00:02Z"}}
        (trial / "config.json").write_text(json.dumps(config))
        (trial / "result.json").write_text(json.dumps(result))
        (trial / "trial.log").write_text("native trial log\n")
        (trial / "verifier").mkdir()
        (trial / "verifier/reward.txt").write_text("-0.5\n")
        (trial / "verifier/test-stdout.txt").write_text("real scoring\n")
        if mode == "candidate":
            (trial / "agent").mkdir()
            (trial / "agent/candidate_transfer.json").write_text(json.dumps({"files": inventory(candidate)}))
        return trial, candidate, result

    def test_snapshot_omits_git_but_preserves_model_and_original(self):
        from autoresearch_flow.harbor_native import snapshot, inventory
        source = self.root / "source"
        source.mkdir()
        (source / ".git").mkdir()
        (source / ".git/private-ref").write_text("reference")
        (source / "model.pt").write_bytes(b"\x00model")
        frozen = self.root / "frozen"
        records = snapshot(source, frozen)
        self.assertEqual(records, inventory(frozen))
        self.assertFalse((frozen / ".git").exists())
        self.assertTrue((source / ".git/private-ref").exists())
        with self.assertRaises(FlowError):
            snapshot(source, frozen)

    def test_snapshot_rejects_credentials_links_and_overlap(self):
        from autoresearch_flow.harbor_native import snapshot
        source = self.root / "source"
        source.mkdir()
        (source / "auth.json").write_text("{}")
        with self.assertRaises(FlowError):
            snapshot(source, self.root / "out")
        (source / "auth.json").unlink()
        (source / "method.py").symlink_to("/etc/passwd")
        with self.assertRaises(FlowError):
            snapshot(source, self.root / "other")
        with self.assertRaises(FlowError):
            snapshot(source, source / "nested")

    def test_native_negative_reward_and_full_model_transfer_are_valid(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture()
        report = inspect_trial(trial, mode="candidate", expected_files=inventory(candidate), task_path=self.root / "task")
        self.assertEqual(report["status"], "native_trial_verified")
        self.assertEqual(report["rewards"], {"reward": -0.5})
        self.assertIn("model.bin", report["candidate_files"])

    def test_candidate_explicit_destination_preserves_full_inventory(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture(destination="solution", artifact_toml=
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="solution"\nservice="main"\n')
        report = inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                               expected_files=inventory(candidate))
        self.assertEqual(report["status"], "native_trial_verified")
        self.assertEqual(report["candidate_files"], inventory(candidate))
        self.assertEqual(report["artifact_path"], "artifacts/solution")

    def test_nop_nested_destination(self):
        from autoresearch_flow.harbor_native import inspect_trial
        trial, _, _ = self.fixture("nop", destination="collected/solution", artifact_toml=
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="collected/solution"\n')
        report = inspect_trial(trial, mode="nop", task_path=self.root / "task")
        self.assertEqual(report["artifact_path"], "artifacts/collected/solution")
        self.assertEqual(report["coverage"], "nop_executed_branch_only")

    def test_object_omitted_and_empty_destination_use_default(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture()
        for suffix in ('', 'destination=""\n'):
            with self.subTest(suffix=suffix):
                (self.root / "task/task.toml").write_text(
                    '[[artifacts]]\nsource="/workspace/solution"\n' + suffix)
                report = inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                                       expected_files=inventory(candidate))
                self.assertEqual(report["artifact_path"], "artifacts/workspace/solution")

    def test_explicit_missing_destination_never_falls_back(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture(artifact_toml=
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="absent"\n')
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                          expected_files=inventory(candidate))
        self.assertEqual(caught.exception.code, "HARBOR_INPUT")

    def test_destination_declarations_reject_invalid_paths_and_types(self):
        from autoresearch_flow.harbor_native import solution_artifact_destination
        for value in (None, False, 42, [], {}, "/solution", "../solution", "x/../solution",
                      "x\\solution", ".", "./", "manifest.json", "manifest.json/solution"):
            with self.subTest(value=value), self.assertRaises(FlowError):
                solution_artifact_destination({"artifacts": [
                    {"source": "/workspace/solution", "destination": value}]})

    def test_artifact_match_requires_unique_main_source(self):
        from autoresearch_flow.harbor_native import solution_artifact_destination
        entries = [[], ["/workspace"], [False], [{"source": 7}],
                   [{"source": "/workspace/solution", "service": "other"}],
                   [{"source": "/workspace/solution", "service": False}],
                   ["/workspace/solution", {"source": "/workspace/solution"}],
                   ["/workspace/solution", {"source": "/workspace/solution", "service": "main"}],
                   ["/workspace/solution", {"source": "/workspace/solution/", "service": "main"}],
                   ["/workspace/solution", {"source": "/workspace/solution/config", "destination": 12}]]
        for value in entries + [None, "not-an-array", {}]:
            with self.subTest(value=value), self.assertRaises(FlowError):
                solution_artifact_destination({"artifacts": value})
        for service in (None, "main", " main "):
            self.assertEqual(solution_artifact_destination({"artifacts": [
                {"source": "/workspace/solution", "service": service}]}), "workspace/solution")

    def test_artifact_directory_symlinks_cannot_escape_trial(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture(artifact_toml=
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="collected/solution"\n')
        (trial / "artifacts/collected").symlink_to(candidate.parent, target_is_directory=True)
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                          expected_files=inventory(candidate))
        self.assertEqual(caught.exception.code, "HARBOR_ARTIFACTS")
        (trial / "artifacts/collected").unlink()
        (trial / "artifacts/collected").symlink_to("collected", target_is_directory=True)
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                          expected_files=inventory(candidate))
        self.assertIn(caught.exception.code, {"HARBOR_ARTIFACTS", "HARBOR_INPUT"})
        (trial / "artifacts/collected").unlink()
        (trial / "artifacts").rename(self.root / "external-artifacts")
        (trial / "artifacts").symlink_to(self.root / "external-artifacts", target_is_directory=True)
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                          expected_files=inventory(candidate))
        self.assertEqual(caught.exception.code, "HARBOR_ARTIFACTS")

    def test_explicit_destination_keeps_model_transfer_and_original_checks(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture(destination="solution", artifact_toml=
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="solution"\n')
        expected = inventory(candidate)
        model = trial / "artifacts/solution/model.bin"
        model.write_bytes(b"changed-model")
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task", expected_files=expected)
        self.assertEqual(caught.exception.code, "HARBOR_ARTIFACTS")
        model.write_bytes((candidate / "model.bin").read_bytes())
        transfer = trial / "agent/candidate_transfer.json"
        original = transfer.read_text()
        transfer.write_text(json.dumps({"files": {}}))
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task", expected_files=expected)
        self.assertEqual(caught.exception.code, "HARBOR_ARTIFACTS")
        transfer.write_text(original)
        (trial / "trial.log").write_text("")
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task", expected_files=expected)
        self.assertEqual(caught.exception.code, "HARBOR_ORIGINALS")

    def test_task_toml_must_be_bound_parseable_original(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture()
        path = self.root / "task/task.toml"
        path.write_text("malformed [")
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                          expected_files=inventory(candidate))
        self.assertEqual(caught.exception.code, "HARBOR_ARTIFACTS")
        path.unlink()
        path.symlink_to(candidate / "method.py")
        with self.assertRaises(FlowError) as caught:
            inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                          expected_files=inventory(candidate))
        self.assertEqual(caught.exception.code, "HARBOR_ARTIFACTS")

    def test_explicit_destination_does_not_bypass_trial_integrity(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, result = self.fixture(destination="solution", artifact_toml=
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="solution"\n')
        mutations = [
            ("HARBOR_SEPARATE", lambda r: r.update(verifier_environment_mode="shared")),
            ("HARBOR_AGENT", lambda r: r["agent_info"].update(name="other")),
            ("HARBOR_PROVIDER", lambda r: r["config"]["environment"].update(type="other")),
            ("HARBOR_TIMING", lambda r: r["verifier"].update(started_at="2026-10-08T00:00:00Z")),
            ("HARBOR_REWARD", lambda r: r["verifier_result"].update(rewards={"reward": 1.0})),
            ("HARBOR_TASK_BINDING", lambda r: r["config"]["task"].update(path="/other-task")),
        ]
        for code, mutate in mutations:
            with self.subTest(code=code):
                changed = copy.deepcopy(result)
                mutate(changed)
                (trial / "result.json").write_text(json.dumps(changed))
                with self.assertRaises(FlowError) as caught:
                    inspect_trial(trial, mode="candidate", task_path=self.root / "task",
                                  expected_files=inventory(candidate), expected_environment={"type": "docker"})
                self.assertEqual(caught.exception.code, code)

    def test_json_reward_has_priority_and_zero_is_valid(self):
        from autoresearch_flow.harbor_native import inspect_trial
        trial, _, result = self.fixture("nop")
        result["verifier_result"]["rewards"] = {"accuracy": 0.0}
        (trial / "result.json").write_text(json.dumps(result))
        (trial / "verifier/reward.json").write_text('{"accuracy": 0}')
        report = inspect_trial(trial, mode="nop", task_path=self.root / "task")
        self.assertEqual(report["rewards"], {"accuracy": 0.0})
        self.assertEqual(report["coverage"], "nop_executed_branch_only")

    def test_native_failure_cannot_be_hidden_by_cli_exit_or_stale_reward(self):
        from autoresearch_flow.harbor_native import inspect_trial
        trial, _, result = self.fixture()
        result["exception_info"] = {"exception_type": "RewardFileNotFoundError"}
        (trial / "result.json").write_text(json.dumps(result))
        with self.assertRaisesRegex(FlowError, "RewardFileNotFoundError"):
            inspect_trial(trial, mode="candidate", task_path=self.root / "task")

    def test_shared_disabled_wrong_identity_or_order_are_rejected(self):
        from autoresearch_flow.harbor_native import inspect_trial
        trial, _, original = self.fixture("nop")
        cases = []
        r = copy.deepcopy(original); r["verifier_environment_mode"] = "shared"; cases.append(r)
        r = copy.deepcopy(original); r["config"]["verifier"]["disable"] = True; cases.append(r)
        r = copy.deepcopy(original); r["agent_info"]["name"] = "oracle"; cases.append(r)
        r = copy.deepcopy(original); r["verifier"]["started_at"] = "2026-10-08T00:00:00Z"; cases.append(r)
        r = copy.deepcopy(original); r["config"]["task"]["path"] = "/other"; cases.append(r)
        for result in cases:
            with self.subTest(result=result):
                (trial / "result.json").write_text(json.dumps(result))
                with self.assertRaises(FlowError):
                    inspect_trial(trial, mode="nop", task_path=self.root / "task")

    def test_nonfinite_reward_and_missing_or_changed_model_fail(self):
        from autoresearch_flow.harbor_native import inspect_trial, inventory
        trial, candidate, _ = self.fixture()
        expected = inventory(candidate)
        (trial / "artifacts/workspace/solution/model.bin").write_bytes(b"other")
        with self.assertRaises(FlowError):
            inspect_trial(trial, mode="candidate", expected_files=expected, task_path=self.root / "task")
        (trial / "verifier/reward.txt").write_text("nan\n")
        with self.assertRaises(FlowError):
            inspect_trial(trial, mode="candidate", task_path=self.root / "task")

    def test_job_has_one_native_trial_no_budget_override_or_state(self):
        from autoresearch_flow.harbor_native import job_config, CANDIDATE_AGENT
        config = job_config(self.root / "task", self.root / "out", candidate=self.root / "candidate")
        self.assertEqual(config["agents"][0]["import_path"], CANDIDATE_AGENT)
        self.assertEqual(config["environment"], {"type": "docker"})
        self.assertFalse(config["verifier"]["disable"])
        self.assertEqual(config["retry"]["max_retries"], 0)
        self.assertNotIn("override_timeout_sec", config["verifier"])
        self.assertEqual(job_config(self.root / "task", self.root / "out")["agents"], [{"name": "nop"}])

    def test_task_snapshot_does_not_copy_pilot_runs_or_builds(self):
        from autoresearch_flow.harbor_native import snapshot, TASK_INPUTS
        source = self.root / "task"
        source.mkdir()
        (source / "task.toml").write_text("artifacts=[]\n")
        (source / "build").mkdir()
        (source / "build/auth.json").write_text("private-build-credential")
        (source / "runs").mkdir()
        (source / "runs/history").write_text("not-task-input")
        copied = snapshot(source, self.root / "task-copy", top_names=TASK_INPUTS)
        self.assertEqual(set(copied), {"task.toml"})

    def test_readonly_reuse_checks_snapshots_and_raw_bytes(self):
        from autoresearch_flow.harbor_native import inspect_run, inventory, job_config
        from autoresearch_flow.common import _sha256
        trial, candidate, result = self.fixture()
        output = self.root / "run"
        output.mkdir()
        task = output / "task/task"
        task.mkdir(parents=True)
        (task / "task.toml").write_text('artifacts=["/workspace/solution"]\n')
        impl = output / "implementation"
        impl.mkdir()
        (impl / "driver.py").write_text("frozen driver")
        import shutil
        shutil.copytree(candidate, output / "candidate")
        (output / "jobs/score").mkdir(parents=True)
        moved = output / "jobs/score/trial"
        trial.rename(moved)
        for path in (moved / "config.json", moved / "result.json"):
            obj = json.loads(path.read_text())
            cfg = obj.get("config", obj)
            cfg["task"]["path"] = str(task)
            path.write_text(json.dumps(obj))
        from autoresearch_flow.harbor_native import inspect_trial
        job = job_config(task, output, candidate=output / "candidate")
        actual = inspect_trial(moved, mode="candidate", task_path=task,
                               expected_files=inventory(candidate), expected_environment=job["environment"])
        (output / "job.json").write_text(json.dumps(job))
        report = {**actual, "native": {"harbor_version": "0.23.0"}, "task_snapshot": "task/task",
                  "task_files": inventory(task), "program_files": inventory(impl),
                  "job_sha256": _sha256(output / "job.json"), "frozen_candidate_files": inventory(candidate)}
        (output / "report.json").write_text(json.dumps(report))
        with patch("subprocess.run", side_effect=AssertionError("must not run Harbor")):
            self.assertEqual(inspect_run(output, task=task, candidate=candidate)["rewards"], {"reward": -0.5})
        original_toml = (task / "task.toml").read_text()
        (task / "task.toml").write_text(
            '[[artifacts]]\nsource="/workspace/solution"\ndestination="solution"\n')
        with self.assertRaises(FlowError) as caught:
            inspect_run(output)
        self.assertEqual(caught.exception.code, "HARBOR_DRIFT")
        (task / "task.toml").write_text(original_toml)
        (moved / "trial.log").write_text("modified original")
        with self.assertRaises(FlowError):
            inspect_run(output)

    def test_thin_gpu_provider_can_leave_explicit_cpu_phase_without_devices(self):
        import importlib.util
        import types
        stub = types.ModuleType("harbor.environments.docker.docker")
        class Docker:
            def __init__(self, *args, **kwargs):
                self._effective_gpus = kwargs["count"]
                self._is_windows_container = False
        stub.DockerEnvironment = Docker
        stub._sanitize_docker_compose_project_name = lambda value: value
        spec = importlib.util.spec_from_file_location("autoresearch_flow._gpu_test", Path(__file__).parents[1] / "autoresearch_flow/harbor_gpu.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict("sys.modules", {"harbor.environments.docker.docker": stub}):
            spec.loader.exec_module(module)
        with patch.object(module.importlib.metadata, "version", return_value="0.23.0"):
            cpu = module.GpuDockerEnvironment(gpu_ids=["2"], count=0, cpu_only_when_zero=True)
            self.addCleanup(cpu._gpu_temp.cleanup)
            self.assertEqual(cpu._gpu_ids, [])
            self.assertIn("devices: !override []", cpu._gpu_overlay.read_text())
            with self.assertRaises(ValueError):
                module.GpuDockerEnvironment(gpu_ids=["2"], count=0)
            with self.assertRaises(ValueError):
                module.GpuDockerEnvironment(gpu_ids=["2"], count=2, cpu_only_when_zero=True)

    def test_cli_uses_no_legacy_state_and_propagates_native_failure(self):
        import cli
        with patch("autoresearch_flow.harbor_native.run", return_value={"status": "native_trial_failed"}), \
             patch("autoresearch_flow.runtime_cli.independent", side_effect=AssertionError("legacy runtime loaded")), \
             patch("cli._emit"):
            code = cli.main(["harbor", "run", "--harbor-task", str(self.root),
                             "--harbor-python", "/python", "--output-dir", "/new", "--allow-live"])
        self.assertEqual(code, 2)

    def test_materials_interface_preserves_native_trial_original_bytes(self):
        from autoresearch_flow.materials_assemble import assemble
        trial, candidate, _ = self.fixture("nop")
        originals = {name: (trial / name).read_bytes() for name in ["config.json", "result.json", "verifier/reward.txt"]}
        output = self.root / "submission"
        assemble({"expert_evidence/nop_trial": str(trial)}, candidate, output, source_root=self.root)
        for name, raw in originals.items():
            self.assertEqual((output / "expert_evidence/nop_trial" / name).read_bytes(), raw)
        self.assertEqual((output / "expert_evidence/best_method/model.bin").read_bytes(), b"synthetic-model\x00")

    def test_native_schema_timeout_keeps_diagnostics_without_starting_trial(self):
        import subprocess
        import sys
        from autoresearch_flow.harbor_native import run, snapshot, TASK_INPUTS
        source = Path(__file__).parents[1] / "pilots/pca_cpu"
        task = self.root / "task"
        snapshot(source, task, top_names=TASK_INPUTS)
        output = self.root / "out"
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("native-validate", 30)), \
             patch("autoresearch_flow.harbor_native._process", side_effect=AssertionError("must not start trial")):
            report = run(task, output, harbor_python=sys.executable, allow_live=True)
        self.assertEqual(report["status"], "native_trial_failed")
        self.assertEqual(report["error"]["code"], "TimeoutExpired")
        self.assertTrue((output / "validation.log").is_file())
        self.assertTrue((output / "report.json").is_file())

    def test_fixture_clears_rewards_before_candidate_and_uses_atomic_replace(self):
        import ast
        path = Path(__file__).parents[1] / "pilots/pca_cpu/tests/grader.py"
        tree = ast.parse(path.read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
        candidate_line = next(n.lineno for n in calls if ast.unparse(n.func) == "subprocess.run")
        clear_line = next(n.lineno for n in calls if isinstance(n.func, ast.Attribute) and n.func.attr == "unlink")
        replace_line = next(n.lineno for n in calls if ast.unparse(n.func) == "os.replace")
        self.assertLess(clear_line, candidate_line)
        self.assertGreater(replace_line, candidate_line)


if __name__ == "__main__":
    unittest.main()
