"""PCA contracts: synthetic evidence, no Docker/model/QA calls."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoresearch_flow.core import FlowError, _sha256
from autoresearch_flow.trajectory import validate_round, raw_public_metric
from autoresearch_flow.pca_contract import check_task, check_execution_receipt, check_stability, task_digest


def synthetic_receipt(root, task):
    log = root / "synthetic-harbor.log"; log.write_text("SYNTHETIC ONLY: build, handoff, separate, reward\n")
    reward = root / "synthetic-reward.txt"; reward.write_text("0.5\n")
    def ref(path):
        return {"path": str(path.relative_to(root)), "sha256": _sha256(path)}
    names = ("dual_build", "agent_finished", "candidate_transferred", "separate_effective",
             "verifier_self_contained", "candidate_permissions", "trusted_reward", "best_restored", "frozen_scoring")
    return {"kind": "harbor_end_to_end", "task_sha256": task_digest(task),
            "harbor_version": "synthetic", "provider": "synthetic", "trial_id": "synthetic",
            "reviewer": "synthetic", "agent_image": "sha256:"+"a"*64,
            "verifier_image": "sha256:"+"b"*64, "data_scope": "authorized_selftest",
            "data_authorization": ref(log), "command": ["synthetic-harbor"], "reward": ref(reward),
            "observations": {name: {"passed": True, "locator": "line 1 SYNTHETIC",
                                   "evidence": ref(log)} for name in names}}


class EnvironmentContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.task = self.root / "harbor_task"
        for name, content in {
            "instruction.md": "synthetic", "environment/Dockerfile": "FROM scratch\n",
            "environment/starter/main.py": "# starter", "tests/Dockerfile": "FROM scratch\n",
            "tests/test.sh": "#!/bin/sh\nexit 0\n",
            "task.toml": 'artifacts=["/workspace/solution"]\n[environment]\n[agent]\n[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n'
        }.items():
            path=self.task/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)

    def test_structure_is_not_execution_and_no_grader_filename_forcing(self):
        result = check_task(self.task)
        self.assertEqual(result["status"], "structure_checked_not_execution")
        with self.assertRaises(FlowError):
            check_execution_receipt(self.root, {}, self.task)

    def test_missing_private_image_escape_and_artifacts_rejected(self):
        dockerfile = self.task / "tests/Dockerfile"
        dockerfile.unlink()
        with self.assertRaises(FlowError): check_task(self.task)
        dockerfile.write_text("FROM scratch\nCOPY ../secret /secret\n")
        with self.assertRaises(FlowError): check_task(self.task)
        dockerfile.write_text("FROM scratch\n")
        toml = self.task / "task.toml"
        toml.write_text(toml.read_text().replace('/workspace/solution', '/workspace'))
        with self.assertRaises(FlowError): check_task(self.task)

    def test_receipt_requires_current_task_and_raw_evidence(self):
        receipt = synthetic_receipt(self.root, self.task)
        checked = check_execution_receipt(self.root, receipt, self.task)
        self.assertTrue(checked["official_hidden_pending"])
        (self.root / "synthetic-harbor.log").write_text("changed")
        with self.assertRaises(FlowError): check_execution_receipt(self.root, receipt, self.task)
        receipt = synthetic_receipt(self.root, self.task)
        (self.task / "tests/test.sh").chmod(0o755)
        with self.assertRaises(FlowError): check_execution_receipt(self.root, receipt, self.task)

    def test_final_requires_best_and_frozen_score(self):
        receipt = synthetic_receipt(self.root, self.task)
        del receipt['observations']['frozen_scoring']
        with self.assertRaises(FlowError):
            check_execution_receipt(self.root, receipt, self.task, frozen_scoring=True)

    def test_final_receipt_candidate_binding_rejects_changed_code(self):
        receipt = synthetic_receipt(self.root, self.task)
        best = self.root / 'best'; best.mkdir()
        code = best / 'main.py'; code.write_text('# actual best')
        manifest = self.root / 'candidate.json'
        manifest.write_text(json.dumps({'root': '/workspace/solution', 'files': [
            {'path': 'main.py', 'sha256': _sha256(code), 'size_bytes': code.stat().st_size}]}))
        receipt.update(score_contract_sha256='c'*64, best_method_sha256=task_digest(best),
            candidate_manifest={'path': 'candidate.json', 'sha256': _sha256(manifest)})
        check_execution_receipt(self.root, receipt, self.task, final=True,
            score_contract_sha256='c'*64, best_method=best)
        code.write_text('# different candidate')
        with self.assertRaises(FlowError):
            check_execution_receipt(self.root, receipt, self.task, final=True,
                score_contract_sha256='c'*64, best_method=best)

    def test_stability_bound_to_image_and_real_interval(self):
        receipt = synthetic_receipt(self.root, self.task)
        stability = {"image": receipt["agent_image"], "container_id": "synthetic",
            "stable_seconds": 43200, "oom_killed": False, "unexpected_exit": False,
            "started_at": "2026-09-29T00:00:00Z", "observed_at": "2026-09-29T12:00:00Z",
            "reviewer": "synthetic", "evidence": receipt["data_authorization"]}
        check_stability(self.root, stability, expected_image=receipt['agent_image'])
        with self.assertRaises(FlowError): check_stability(self.root, stability, expected_image="other")
        stability['stable_seconds'] = 50000
        with self.assertRaises(FlowError): check_stability(self.root, stability, expected_image=receipt['agent_image'])


def round_record(number=1, summary="调整方法，公开评测成功。"):
    return {"round": number, "policy_name": "candidate", "method_summary": summary,
            "status": "ok", "score": 4.5, "failure_reason": None,
            "retained_best": True, "time": "2026-09-30 10:00:00"}


class TrajectoryContractTests(unittest.TestCase):
    def test_eight_fields_preserved_and_raw_not_normalized(self):
        row = round_record()
        self.assertEqual(validate_round(row, 1), row)
        self.assertEqual(raw_public_metric({"status": "succeeded", "score": .5,
            "raw_metric": {"name": "error", "direction": "minimize", "value": 4.5}}), 4.5)

    def test_old_schema_and_invalid_types_rejected(self):
        bad = [{"round": 1, "method_summary": "旧记录"}]
        for key, value in (("round", True), ("score", True), ("score", float("nan")),
                           ("time", "2026-02-30 10:00:00"), ("time", "2026-9-3 1:00:00"),
                           ("retained_best", 1), ("failure_reason", "失败")):
            row = round_record(); row[key] = value; bad.append(row)
        for row in bad:
            with self.subTest(row=row), self.assertRaises(FlowError):
                validate_round(row, 1)

    def test_failure_is_not_an_invented_enum(self):
        row = round_record()
        row.update(status="provider_interruption", score=None,
                   failure_reason="外部异常，原会话恢复。", retained_best=False)
        self.assertEqual(validate_round(row, 1), row)
        row["retained_best"] = True
        with self.assertRaises(FlowError):
            validate_round(row, 1)

    def test_no_invented_score_for_failure(self):
        self.assertIsNone(raw_public_metric({"status": "failed", "score": -1}))
        with self.assertRaises(FlowError):
            raw_public_metric({"status": "succeeded", "score": .5})


if __name__ == "__main__":
    unittest.main()
