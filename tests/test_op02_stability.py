"""OP-2 policy and delivery boundaries; synthetic files, no Docker/model calls."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_w4_contract as w4
from test_pca_contract import synthetic_receipt
from test_qa_contract import synthetic_report

from autoresearch_flow.core import (
    FlowError,
    Registry,
    TaskStore,
    _canonical_digest,
    _sha256,
)
from autoresearch_flow.pca_contract import task_digest
from autoresearch_flow.stages import StageFlow


class StabilityPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-op02-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = TaskStore(self.root)
        self.store.initialize(Registry(), "synthetic-op02")

    def test_new_policy_and_delivery_template_do_not_require_soak(self):
        before = self.store.state_path.read_bytes()
        status = self.store.check()
        self.assertFalse(status["workflow_policy"]["require_stability_receipt"])
        self.assertEqual(status["workflow_policy"]["duration_policy"]["minimum_effective_seconds"], 36000)
        self.assertEqual(status["workflow_policy"]["ui_mode"], "exec_json")
        self.assertNotIn("optional_stability", status["pending_implementation"])
        self.assertNotIn("stability", StageFlow(self.root).template("6.5")["spec"]["checks"])
        self.assertEqual(before, self.store.state_path.read_bytes())

    def test_op01_upgrade_is_explicit_and_only_reopens_delivery(self):
        state = json.loads(self.store.state_path.read_text())
        state["workflow_policy"].update(revision="2026-10-03.op01", require_stability_receipt=True)
        state["current_stage"] = "6"
        for number in range(1, 6):
            stage = state["stages"][str(number)]
            stage["status"] = "passed"
            for substep in stage["substeps"].values():
                substep["status"] = "passed"
        state["stages"]["6"]["status"] = "in_progress"
        state["stages"]["6"]["substeps"]["6.1"]["status"] = "passed"
        self.store.state_path.write_text(json.dumps(state))
        runtime = self.store.state_dir / "runtime"
        runtime.mkdir()
        log = runtime / "existing.log"
        log.write_text("original run evidence")
        before = self.store.state_path.read_bytes()
        self.assertIn("stability", StageFlow(self.root).template("6.5")["spec"]["checks"])
        self.assertFalse(self.store.upgrade(Registry(), apply=False)["changed"])
        preview = self.store.upgrade(Registry(), apply=False, adopt_policy=True)
        self.assertEqual(preview["affected_stages"], [6])
        self.assertEqual(before, self.store.state_path.read_bytes())
        self.store.upgrade(Registry(), apply=True, adopt_policy=True)
        self.assertFalse(self.store.check()["workflow_policy"]["require_stability_receipt"])
        self.assertEqual(log.read_text(), "original run evidence")
        upgraded = json.loads(self.store.state_path.read_text())
        self.assertEqual(upgraded["stages"]["4"], state["stages"]["4"])
        self.assertEqual(upgraded["stages"]["6"]["substeps"]["6.1"]["status"], "needs_recheck")
        self.assertEqual(upgraded["rules_lock"], state["rules_lock"])
        policy_event = next(r for r in upgraded["history"] if r["action"] == "workflow_policy_upgrade")
        self.assertEqual(policy_event["previous_policy"], state["workflow_policy"])

    def test_legacy_and_op01_do_not_silently_lose_gate(self):
        for revision in (None, "2026-10-03.op01"):
            state = json.loads(self.store.state_path.read_text())
            if revision is None:
                state.pop("workflow_policy", None)
            else:
                from autoresearch_flow.policies import new_policy
                state["workflow_policy"] = new_policy() | {"revision": revision, "require_stability_receipt": True}
            self.store.state_path.write_text(json.dumps(state))
            before = self.store.state_path.read_bytes()
            self.assertTrue(self.store.check()["workflow_policy"]["require_stability_receipt"])
            self.assertIn("stability", StageFlow(self.root).template("6.5")["spec"]["checks"])
            self.assertEqual(before, self.store.state_path.read_bytes())


class StabilityDeliveryTests(unittest.TestCase):
    def setUp(self):
        # Existing synthetic package builder; only upstream experiment/runtime
        # producers are simulated. Package, Harbor and QA gates run unchanged.
        self.fx = w4.DeliveryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        best = self.fx.prepare_best()
        spec = self.fx.prepare_package_sources()
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", return_value=best), \
             patch("autoresearch_flow.w4_package.ExperimentBook.report", side_effect=self.fx.reports(best)):
            self.package = Path(self.fx.package.build(spec)["package_path"])
        task = self.package / "workspace/harbor_task"
        receipt = synthetic_receipt(self.package, task)
        method = self.package / "expert_evidence/best_method"
        manifest = self.package / "candidate.json"
        manifest.write_text(json.dumps({"root": "/workspace/solution", "files": [
            {"path": p.relative_to(method).as_posix(), "sha256": _sha256(p), "size_bytes": p.stat().st_size}
            for p in method.rglob("*") if p.is_file()]}))
        score = json.loads((self.package / "expert_evidence/expert_annotation.json").read_text())["score_contract"]
        receipt.update(score_contract_sha256=_canonical_digest(score), best_method_sha256=task_digest(method),
                       candidate_manifest={"path": "candidate.json", "sha256": _sha256(manifest)})
        self.receipt = self.package / "harbor.json"
        self.receipt.write_text(json.dumps(receipt))
        self.flow = StageFlow(self.root)
        state = json.loads(self.flow.store.state_path.read_text())
        state["current_stage"] = "6"
        for stage in state["stages"].values():
            stage["status"] = "passed"
            for step in stage["substeps"].values():
                step["status"] = "passed"
        state["stages"]["6"]["status"] = "in_progress"
        state["stages"]["6"]["substeps"]["6.5"]["status"] = "pending"
        self.flow.store.state_path.write_text(json.dumps(state))
        self.rebind()

    def rebind(self):
        handoff = self.fx.package.qa_handoff(self.package)
        report = synthetic_report(self.package)
        report_path = self.root / "synthetic-qa.json"
        report_path.write_text(json.dumps(report))
        self.fx.package.qa_bind(self.package, report_path)
        review = self.root / "qa-review.json"
        rows = report["checks"] + report["content_gates"]["checks"] + report["harbor"]["checks"]
        review.write_text(json.dumps({"package_sha256": handoff["package_sha256"],
            "report_sha256": _sha256(report_path), "unresolved_local_items": [], "reviewer": "synthetic",
            "conclusion": "synthetic only", "dispositions": [
                {"id": r["id"], "status": r["status"], "rationale": "synthetic"} for r in rows]}))
        self.checks = {"package_root": str(self.package.relative_to(self.root)),
                       "harbor_execution": self.fx.ref(self.receipt), "qa_review": self.fx.ref(review)}

    def record(self):
        return self.flow.record({"step": "6.5", "status": "passed", "reviewer": "synthetic",
            "summary": "synthetic only", "evidence": [self.fx.ref(self.receipt)], "checks": self.checks})

    def test_delivery_without_soak_records_not_run(self):
        result = self.record()
        self.assertEqual(result["step_status"], "passed")
        self.assertEqual(result["gate"]["stability"], {"status": "not_run", "required": False})

    def test_stage_six_can_finish_without_stability_record(self):
        state = json.loads(self.flow.store.state_path.read_text())
        for substep in state["stages"]["6"]["substeps"].values():
            substep["status"] = "pending"
        self.flow.store.state_path.write_text(json.dumps(state))
        for number in range(1, 6):
            self.flow.record({"step": f"6.{number}", "status": "passed", "reviewer": "synthetic",
                "summary": "synthetic only", "evidence": [self.fx.ref(self.receipt)], "checks": self.checks})
        approval = self.root / "approval.json"
        approval.write_text(json.dumps({"approved_by": "synthetic", "approved": True, "scope": "stage-6",
            "decision": "synthetic fixture only", "evidence": [self.fx.ref(self.receipt)]}))
        source = next(s for s in state["rules_lock"]["sources"] if s["id"] == "tutorial")
        self.flow.finish("6", {"reviewer": "synthetic", "conclusion": "synthetic closure",
            "approval": self.fx.ref(approval), "tutorial_review": {"sha256": source["sha256"],
            "sections": ["synthetic AR-010 and U-20261003-03"], "findings": "synthetic", "resolution": "synthetic"}})
        self.assertIsNone(self.flow.store.check()["current_stage"])

    def test_failed_environment_observation_still_blocks(self):
        receipt = json.loads(self.receipt.read_text())
        receipt["observations"]["dual_build"]["passed"] = False
        self.receipt.write_text(json.dumps(receipt))
        self.rebind()
        with self.assertRaises(FlowError) as caught:
            self.record()
        self.assertEqual(caught.exception.code, "HARBOR_EVIDENCE")

    def test_missing_harbor_still_blocks(self):
        del self.checks["harbor_execution"]
        with self.assertRaises(FlowError):
            self.record()

    def stability(self, **changes):
        receipt = json.loads(self.receipt.read_text())
        return {"image": receipt["agent_image"], "container_id": "synthetic",
            "stable_seconds": 43200, "oom_killed": False, "unexpected_exit": False,
            "started_at": "2026-10-01T00:00:00Z", "observed_at": "2026-10-01T12:00:00Z",
            "reviewer": "synthetic", "evidence": receipt["data_authorization"], **changes}

    def test_provided_valid_receipt_preserved_and_checked(self):
        path = self.package / "stability.json"
        path.write_text(json.dumps(self.stability()))
        before = path.read_bytes()
        self.rebind()
        self.checks["stability"] = self.fx.ref(path)
        result = self.record()["gate"]["stability"]
        self.assertEqual(result["status"], "evidence_checked_not_stress_test")
        self.assertFalse(result["required"])
        self.assertEqual(path.read_bytes(), before)

    def test_old_policy_still_requires_receipt(self):
        state = json.loads(self.flow.store.state_path.read_text())
        state["workflow_policy"].update(revision="2026-10-03.op01", require_stability_receipt=True)
        self.flow.store.state_path.write_text(json.dumps(state))
        with self.assertRaises(FlowError) as caught:
            self.record()
        self.assertEqual(caught.exception.code, "INVALID_EVIDENCE")

    def test_optional_evidence_cannot_escape_package(self):
        path = self.root / "outside-stability.json"
        path.write_text(json.dumps(self.stability()))
        self.checks["stability"] = self.fx.ref(path)
        with self.assertRaises(FlowError) as caught:
            self.record()
        self.assertEqual(caught.exception.code, "PACKAGE_EVIDENCE_BOUNDARY")

    def test_qa_drift_still_blocks_without_soak(self):
        (self.package / "extra.txt").write_text("changed after QA")
        with self.assertRaises(FlowError) as caught:
            self.record()
        self.assertEqual(caught.exception.code, "QA_PACKAGE_DRIFT")

    def test_optional_cli_rejects_short_run_faults_and_wrong_image(self):
        path = self.package / "stability.json"
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        cases = [({}, 0), ({"stable_seconds": 36000, "observed_at": "2026-10-01T10:00:00Z"}, 2),
                 ({"oom_killed": True}, 2), ({"unexpected_exit": True}, 2), ({"image": "other"}, 2)]
        for changes, code in cases:
            with self.subTest(changes=changes):
                path.write_text(json.dumps(self.stability(**changes)))
                before = path.read_bytes()
                p = subprocess.run([sys.executable, str(cli), "--format", "json", "environment", "verify-stability",
                    "--task-root", str(self.package), "--file", str(path), "--agent-image", "sha256:" + "a" * 64],
                    capture_output=True, text=True, check=False)
                self.assertEqual(p.returncode, code, p.stdout + p.stderr)
                if code == 0:
                    self.assertEqual(json.loads(p.stdout)["stable_seconds"], 43200)
                self.assertEqual(before, path.read_bytes())

    def test_provided_failed_diagnostic_is_not_silently_ignored(self):
        path = self.package / "stability.json"
        path.write_text(json.dumps({"image": "sha256:" + "a" * 64, "stable_seconds": 43200,
                                    "oom_killed": True}))
        self.rebind()
        self.checks["stability"] = self.fx.ref(path)
        with self.assertRaises(FlowError) as caught:
            self.record()
        self.assertEqual(caught.exception.code, "STABILITY_EVIDENCE")


if __name__ == "__main__":
    unittest.main()
