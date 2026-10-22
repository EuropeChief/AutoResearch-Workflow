"""Independent coherence regressions from synthetic evidence; no task execution."""
import json
from pathlib import Path
import tempfile
import unittest

import implementation_review as qa
import resource_review
import trajectory_review
import test_implementation_review as fixtures


class SelfcheckEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ImplementationReviewTests()
        self.fixture.setUp()
        self.root = self.fixture.root

    def tearDown(self):
        self.fixture.tearDown()

    def review(self):
        review = self.fixture.review()
        review["checks"][16].update(remediation="Correct the identified configuration.",
                                    acceptance_evidence="Existing configuration and evidence agree.")
        return review

    def resource_review(self):
        review = self.review()["resource_review"]
        review["estimate"] = {**review["runs"][0], "basis": "Synthetic target estimate from existing implementation."}
        return review

    def assess_resources(self, review):
        current = resource_review.collect(self.root, qa.inventory(self.root))
        return resource_review.apply_review(current, review, self.root, qa.review_evidence)

    def test_explicit_estimate_cannot_silently_hide_higher_supplied_score_resources(self):
        for field, value in (("gpu_count", 99), ("cpu_cores", 128), ("score_seconds", 120)):
            with self.subTest(field=field):
                review = self.resource_review()
                review["runs"][0][field] = value
                result = self.assess_resources(review)
                self.assertEqual(result["status"], "manual")
                self.assertTrue(any(field in conflict for conflict in result["observation_conflicts"]))

    def test_explained_historical_score_measurement_does_not_force_retraining(self):
        review = self.resource_review()
        review["runs"][0].update(gpu_count=1, gpu_type="A100", cpu_cores=128)
        review["estimate"]["observation_reconciliation"] = {
            "summary": "This retained measurement used an older GPU prototype; the cited current implementation is CPU-only and the target estimate is an inference.",
            "evidence": ["instruction.md", "trajectory_a.json"],
        }
        result = self.assess_resources(review)
        self.assertEqual(result["status"], "pass")
        self.assertTrue(result["observation_conflicts"])
        self.assertEqual(result["runs"][0]["gpu_type"], "A100")

    def test_reconciliation_needs_existing_evidence_and_explanation(self):
        for reconciliation in ({"summary": "", "evidence": ["instruction.md"]},
                               {"summary": "Old measurement", "evidence": []},
                               {"summary": "Old measurement", "evidence": ["missing.log"]}):
            with self.subTest(reconciliation=reconciliation):
                review = self.resource_review()
                review["estimate"]["observation_reconciliation"] = reconciliation
                with self.assertRaises(ValueError):
                    self.assess_resources(review)

    def test_estimate_over_limit_still_fails_with_reconciliation(self):
        review = self.resource_review()
        review["estimate"].update(cpu_cores=128, observation_reconciliation={
            "summary": "The historical and target measurements are distinguished.", "evidence": ["instruction.md"]})
        self.assertEqual(self.assess_resources(review)["status"], "fail")

    def test_historical_training_run_does_not_automatically_contradict_score_estimate(self):
        review = self.resource_review()
        review["runs"].append({**review["runs"][0], "run_id": "old-training", "scope": "training",
                               "gpu_count": 16, "gpu_type": "A100", "cpu_cores": 128})
        self.assertEqual(self.assess_resources(review)["status"], "pass")

    def test_malformed_toml_environment_has_h02_failure_instead_of_crash(self):
        config = self.root / "task.toml"
        config.write_text('environment = []\nartifacts = ["/workspace/solution"]\n[metadata]\nname="fixture"\n[verifier]\nenvironment_mode="separate"\n')
        review = self.review()
        report = qa.apply_review(self.fixture.report(), review, self.root)
        h02 = next(row for row in report["harbor"]["checks"] if row["id"] == "H02")
        self.assertEqual(h02["status"], "fail")
        self.assertIn("environment", h02["summary"])
        self.assertEqual(report["summary"]["decision"], "FAIL")

    def test_invalid_summary_agent_shapes_are_reported_as_binding_errors(self):
        for invalid in (None, 5, "bad", {}, [None]):
            with self.subTest(invalid=invalid):
                review = self.review()
                path = self.root / "expert_evidence/run_summary.json"
                data = json.loads(path.read_text())
                data["agent_execution"] = invalid
                path.write_text(json.dumps(data))
                report = qa.apply_review(self.fixture.report(), review, self.root)
                self.assertEqual(report["summary"]["decision"], "INCOMPLETE")
                self.assertIn("agent_execution", report["trajectory_review"]["binding_errors"][0]["error"])

    def test_cli_writes_all_report_files_for_malformed_summary(self):
        review = self.review()
        (self.root / "expert_evidence/run_summary.json").write_text('{"agent_execution":null}')
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            review_path = out / "review.json"
            review_path.write_text(json.dumps(review))
            self.assertEqual(qa.main([str(self.root), "--out-dir", str(out), "--review", str(review_path)]), 0)
            for name in ("report.json", "report.md", "report.txt", "return_to_expert.txt"):
                self.assertTrue((out / name).is_file())
            self.assertEqual(json.loads((out / "report.json").read_text())["summary"]["decision"], "INCOMPLETE")

    def test_malformed_tool_type_is_unreadable_instead_of_crashing_collection(self):
        for invalid in ([], {}, 5):
            with self.subTest(invalid=invalid):
                self.review()
                path = self.root / "expert_evidence/session_0.jsonl"
                path.write_text(json.dumps({"type": invalid, "name": "exec_command", "arguments": "echo synthetic"}) + "\n")
                report = self.fixture.report()
                source = next(row for row in report["trajectory_review"]["sources"] if row["path"] == "expert_evidence/session_0.jsonl")
                self.assertEqual(source["status"], "unreadable")
                self.assertIn("record type", source["error"])
                self.assertEqual(report["summary"]["decision"], "INCOMPLETE")

    def test_fixed_infra_failure_without_score_effect_can_pass(self):
        review = self.review()
        review["trajectory_review"]["trajectories"][0]["findings"] = [{
            "classification": "infra_bug", "stage": "download", "certainty": "confirmed",
            "summary": "Synthetic failed download was fixed before scoring.", "evidence": ["trajectory_a.json"],
            "score_effect": "none", "affected_rounds": [1], "candidate_ids": [],
        }]
        report = qa.apply_review(self.fixture.report(), review, self.root)
        self.assertEqual(report["summary"]["decision"], "PASS")

    def test_confirmed_leakage_cannot_be_downgraded_to_no_score_effect(self):
        review = self.review()
        review["trajectory_review"]["trajectories"][0]["findings"] = [{
            "classification": "leakage", "certainty": "confirmed", "summary": "Synthetic confirmed leakage.",
            "evidence": ["trajectory_a.json"], "score_effect": "none", "affected_rounds": [1], "candidate_ids": [],
        }]
        with self.assertRaisesRegex(ValueError, "must invalidate"):
            qa.apply_review(self.fixture.report(), review, self.root)


if __name__ == "__main__":
    unittest.main()
