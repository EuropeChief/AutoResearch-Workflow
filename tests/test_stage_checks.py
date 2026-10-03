"""Current-step checks are read-only and do not certify scientific judgment."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_w5_stages as w5
from autoresearch_flow.core import FlowError


class StageCheckTests(unittest.TestCase):
    def setUp(self):
        self.fx = w5.StageTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.flow = self.fx.flow

    def test_check_reuses_real_git_gate_without_recording_or_approval(self):
        before = self.flow.store.state_path.read_bytes()
        result = self.flow.check("1.1")
        self.assertEqual(result["status"], "checked")
        self.assertEqual(result["machine_check"]["status"], "passed")
        self.assertTrue(result["machine_check"]["result"]["ready"])
        self.assertFalse(result["scientific_conclusion_certified"])
        self.assertEqual(self.flow.store.state_path.read_bytes(), before)
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        run = subprocess.run([sys.executable, str(cli), "--format", "json", "stage",
                              "check", "--task-root", str(self.fx.root), "--step", "1.1"],
                             capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["status"], "checked")
        self.assertFalse((self.flow.store.state_dir / "stage_records").exists())

    def test_machine_success_does_not_approve_a_missing_surface_review(self):
        self.fx.record("1.1")
        result = self.flow.check("1.2")
        self.assertEqual(result["machine_check"]["status"], "passed")
        self.assertEqual(result["semantic_review"]["status"], "awaiting_evidence")
        self.assertEqual(result["status"], "blocked")
        spec = {"step": "1.2", "status": "passed", "reviewer": "synthetic expert",
                "summary": "allowed algorithm changes are merely asserted here",
                "evidence": [self.fx.fx.proof], "checks": {}}
        with self.assertRaises(FlowError) as caught:
            self.flow.record(spec)
        self.assertEqual(caught.exception.code, "SCIENTIFIC_REVIEW_REQUIRED")
        spec["reviews"] = [{"rule_id": "AR-002", "status": "awaiting_evidence",
                            "rationale": "Only an assertion exists; no interface/code review yet",
                            "evidence": [self.fx.fx.proof], "unresolved": ["actual allowed edits"],
                            "due_stage": 1}]
        with self.assertRaises(FlowError):
            self.flow.record(spec)
        spec["status"] = "awaiting_evidence"
        spec["due_stage"] = 1
        self.assertEqual(self.flow.record(spec)["step_status"], "awaiting_evidence")
        self.assertEqual(self.flow.status()["next_step"], "1.2")
        spec["status"] = "passed"
        spec["reviews"][0].update(status="pass", unresolved=[],
                                   rationale="Synthetic interface and code evidence reviewed")
        accepted = self.flow.record(spec)
        self.assertEqual(accepted["semantic_review"]["status"], "recorded")
        self.assertFalse(accepted["scientific_conclusion_certified"])

    def test_finish_uses_existing_evidence_without_repeating_tutorial_chapters(self):
        for step in ("1.1", "1.2", "1.3", "1.4"):
            self.fx.record(step)
        spec = self.fx.finish_spec("1")
        self.assertNotIn("tutorial_review", spec)
        self.assertEqual(self.flow.finish("1", spec)["current_stage"], "2")

    def test_record_binds_prior_protocol_and_live_report_without_copying_results(self):
        self.fx.stage_one()
        self.fx.record("2.1")
        self.fx.record("2.2")
        self.fx.record("2.3", {"protocol_id": "p1"})
        for seed, value in zip((1, 2, 3), (9, 10, 11)):
            self.fx.fx.finish(self.fx.fx.start("baseline", seed), value)
        checked = self.flow.check("2.4")
        self.assertEqual(checked["status"], "checked")
        self.assertEqual(checked["resolved_checks"]["protocol_id"], "p1")
        recorded = self.fx.record("2.4")
        self.assertEqual(recorded["gate"]["groups"]["baseline"]["mean"], 10)
        receipt = json.loads((self.fx.root / recorded["receipt"]["path"]).read_text())
        self.assertEqual(receipt["spec"]["checks"], {"protocol_id": "p1"})
        self.assertIn("protocol_sha256", receipt["gate"])

    def test_status_focuses_on_current_step_and_early_evidence(self):
        self.fx.record("1.1")
        status = self.flow.status()
        self.assertEqual(status["next_step"], "1.2")
        self.assertEqual(status["rule_ids"], ["AR-002", "AR-004"])
        self.assertEqual(status["semantic_review_requirements"][0]["rule_id"], "AR-002")
        self.assertFalse(status["scientific_conclusion_certified"])
        self.fx.record("1.2")
        self.fx.record("1.3")
        self.fx.record("1.4")
        self.flow.finish("1", self.fx.finish_spec("1"))
        self.fx.record("2.1")
        self.fx.record("2.2")
        status = self.flow.status()
        self.assertEqual(status["next_step"], "2.3")
        self.assertTrue({"AR-024", "AR-025"} <= {r["rule_id"] for r in status["prepare_evidence"]})

    def test_due_cross_method_review_cannot_close_on_machine_statistics_alone(self):
        self.fx.stage_two()
        self.fx.record("3.1")
        for seed, value in zip((1, 2, 3), (14, 15, 16)):
            self.fx.fx.finish(self.fx.fx.start("reference", seed), value)
        self.fx.record("3.2")
        review = self.fx.fx.review()
        review["checks"]["B03"].update(status="deferred", due_stage=3,
                                       current_part_passed=True, pending_requirement="still unresolved")
        ref = self.fx.fx.ref("unresolved-review.json", json.dumps(review))
        checked = self.flow.check("3.3", {"checks": {"baseline_review": ref}})
        self.assertEqual(checked["status"], "blocked")
        self.assertIn("B03", json.dumps(checked["issues"], ensure_ascii=False))
        with self.assertRaises(FlowError):
            self.fx.record("3.3", {"baseline_review": ref})
        self.assertEqual(self.flow.status()["next_step"], "3.3")

    def test_successful_baseline_runs_do_not_replace_a_reasonableness_review(self):
        self.fx.stage_one()
        self.fx.record("2.1")
        self.fx.record("2.2")
        self.fx.record("2.3", {"protocol_id": "p1"})
        for seed, value in zip((1, 2, 3), (9, 10, 11)):
            self.fx.fx.finish(self.fx.fx.start("baseline", seed), value)
        self.fx.record("2.4")
        ref = self.fx.phase_two_review()
        path = self.fx.root / ref["path"]
        review = json.loads(path.read_text())
        review["checks"]["B06"].update(status="needs_evidence",
            rationale="Runs completed, but representativeness has not been established")
        ref = self.fx.fx.ref("not-just-runnable.json", json.dumps(review))
        checked = self.flow.check("2.5", {"checks": {"baseline_review": ref}})
        self.assertEqual(checked["status"], "blocked")
        with self.assertRaises(FlowError):
            self.fx.record("2.5", {"baseline_review": ref})
        self.assertEqual(self.flow.status()["next_step"], "2.5")


if __name__ == "__main__":
    unittest.main()
