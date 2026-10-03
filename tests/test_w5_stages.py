"""W5 parts 1–2: state/evidence integration, no GPU or model calls."""
import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_w2_contract as w2
from autoresearch_flow.core import FlowError, _sha256, _canonical_digest
from autoresearch_flow.stages import StageFlow
from test_pca_contract import synthetic_receipt
from autoresearch_flow.task_git import TaskGit


class StageTests(unittest.TestCase):
    def setUp(self):
        self.fx = w2.W2Tests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        self.flow = StageFlow(self.root)
        self.flow.configure({"task_type": "S2", "adapter": self.fx.method})
        task = self.root / "workspace/harbor_task"
        for name, content in {
            "instruction.md": "synthetic", "environment/Dockerfile": "FROM scratch\n",
            "environment/starter/main.py": "# starter", "tests/Dockerfile": "FROM scratch\n",
            "tests/test.sh": "#!/bin/sh\nexit 0\n",
            "task.toml": 'artifacts=["/workspace/solution"]\n[environment]\n[agent]\n[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n'
        }.items():
            path = task / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(content)
        self.harbor_ref = self.fx.ref("harbor-receipt.json", json.dumps(synthetic_receipt(self.root, task)))
        vcs = TaskGit(self.root)
        vcs.setup(self.root, confirm=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Synthetic Test"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "synthetic@example.invalid"], check=True)
        vcs.checkpoint(vcs.preview([".gitignore", ".autoresearch-flow/state.json"]), "test fixture", confirm=True)

    def record(self, step, checks=None, **changes):
        if step == "2.1" and checks is None:
            checks = {"harbor_task": "workspace/harbor_task", "harbor_execution": self.harbor_ref}
        if step == "3.5" and checks is not None:
            checks = {**checks, "harbor_task": "workspace/harbor_task", "harbor_execution": self.scoring_receipt(checks['score_contract'])}
        spec = {"step": step, "status": "passed", "reviewer": "synthetic expert",
                "summary": "合成证据，不能冒充真实标注", "evidence": [self.fx.proof],
                "checks": checks or {}, **changes}
        rule = {"1.2": "AR-002", "1.3": "AR-003", "2.2": "AR-002"}.get(step)
        if rule:
            spec.setdefault("reviews", [{"rule_id": rule, "status": "pass",
                "rationale": "Synthetic fixture; not a real scientific judgment",
                "evidence": [self.fx.proof], "unresolved": []}])
        return self.flow.record(spec)

    def scoring_receipt(self, score):
        receipt = json.loads((self.root / self.harbor_ref['path']).read_text())
        receipt['score_contract_sha256'] = _canonical_digest(json.loads((self.root / score['path']).read_text()))
        return self.fx.ref('scoring-harbor-receipt.json', json.dumps(receipt))

    def finish_spec(self, stage):
        approval = self.fx.ref(f"approval-{stage}.json", json.dumps({
            "approved_by": "synthetic user", "approved": True, "scope": f"stage-{stage}",
            "decision": "测试中明确确认", "evidence": [self.fx.proof]}))
        return {"reviewer": "expert", "conclusion": "synthetic complete", "approval": approval}

    def stage_one(self):
        for step in ("1.1", "1.2", "1.3", "1.4"):
            self.record(step)
        self.flow.finish("1", self.finish_spec("1"))

    def phase_two_review(self):
        report = self.fx.book.report("p1", ("baseline",))
        review = {"protocol_sha256": report["protocol_sha256"],
                  "experiment_sha256": report["experiment_sha256"],
                  "baseline_method_sha256": report["groups"]["baseline"]["method_sha256"],
                  "checks": {f"B{i:02d}": {"status": "pass", "reviewer": "expert",
                     "rationale": "synthetic", "evidence": [self.fx.proof]} for i in range(1, 9)}}
        for key in ("B03", "B07"):
            review["checks"][key].update(status="deferred", due_stage=3, current_part_passed=True,
                                        pending_requirement="Reference 尚未运行；待同协议对照")
        return self.fx.ref("phase-2-review.json", json.dumps(review))

    def stage_two(self):
        self.stage_one()
        self.record("2.1")
        self.record("2.2")
        self.record("2.3", {"protocol_id": "p1"})
        for seed, value in zip((1, 2, 3), (9, 10, 11)):
            self.fx.finish(self.fx.start("baseline", seed), value)
        self.record("2.4", {"protocol_id": "p1"})
        self.record("2.5", {"protocol_id": "p1", "baseline_review": self.phase_two_review()})
        self.flow.finish("2", self.finish_spec("2"))

    def test_missing_evidence_no_skip_and_no_overwrite(self):
        with self.assertRaises(FlowError):
            self.record("1.2")
        with self.assertRaises(FlowError):
            self.record("1.1", evidence=[])
        self.record("1.1")
        with self.assertRaises(FlowError) as caught:
            self.record("1.1")
        self.assertEqual(caught.exception.code, "STEP_FROZEN")
        with self.assertRaises(FlowError):
            self.flow.finish("1", self.finish_spec("1"))

    def test_fresh_process_status_identifies_next_action(self):
        self.record("1.1")
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        result = subprocess.run([sys.executable, str(cli), "--format", "json", "stage", "status",
                                 "--task-root", str(self.root)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["next_step"], "1.2")
        self.assertTrue(status["rule_ids"])
        self.assertTrue(status["required_rules"])
        self.assertEqual(StageFlow(self.root).status()["next_step"], "1.2")

    def test_finish_requires_real_confirmation_and_checks_optional_source_findings(self):
        for step in ("1.1", "1.2", "1.3", "1.4"):
            self.record(step)
        spec = self.finish_spec("1")
        spec["source_review"] = {"findings": "Synthetic ambiguity", "resolution": "reviewed",
                                 "evidence": []}
        with self.assertRaises(FlowError) as caught:
            self.flow.finish("1", spec)
        self.assertEqual(caught.exception.code, "MISSING_EVIDENCE")
        spec = self.finish_spec("1")
        del spec["approval"]
        with self.assertRaises(FlowError):
            self.flow.finish("1", spec)
        self.assertEqual(self.flow.store._load()["current_stage"], "1")

    def test_evidence_drift_and_reopen_keep_history(self):
        self.stage_one()
        original = self.flow.store._load()["stages"]["1"]["substeps"]["1.2"]["history"]
        (self.root / self.fx.proof["path"]).write_text("changed")
        self.assertEqual(self.flow.status()["status"], "blocked")
        self.flow.reopen("1.1", {"reason": "证据改变", "reviewer": "expert"})
        after = self.flow.store._load()
        self.assertEqual(after["current_stage"], "1")
        self.assertEqual(after["stages"]["1"]["status"], "needs_recheck")
        self.assertEqual(after["stages"]["1"]["substeps"]["1.2"]["history"][:-1], original)
        self.assertTrue((self.root / original[-1]["receipt"]["path"]).is_file())

    def test_actual_w2_freeze_deferred_then_close_with_reference(self):
        self.stage_two()
        status = self.flow.status()
        self.assertEqual(status["current_stage"], "3")
        self.assertEqual({x["check"] for x in status["pending_cross_method_checks"]}, {"B03", "B07"})
        self.record("3.1")
        with self.assertRaises(FlowError):
            self.record("3.2", {"protocol_id": "p1"})
        for seed, value in zip((1, 2, 3), (14, 15, 16)):
            self.fx.finish(self.fx.start("reference", seed), value)
        self.record("3.2", {"protocol_id": "p1"})
        review = self.fx.ref("phase-3-review.json", json.dumps(self.fx.review()))
        score = self.fx.ref("score.json", json.dumps({"protocol_sha256": self.fx.lock["sha256"],
             "upper_bound": 20, "metric_ceiling": 100, "rationale": "synthetic ex ante", "evidence": [self.fx.proof]}))
        self.record("3.3", {"protocol_id": "p1", "baseline_review": review})
        self.record("3.4", {"protocol_id": "p1", "score_contract": score})
        self.record("3.5", {"protocol_id": "p1", "score_contract": score, "baseline_review": review})
        self.flow.finish("3", self.finish_spec("3"))
        self.assertEqual(self.flow.status()["current_stage"], "4")
        self.assertEqual(self.flow.status()["pending_cross_method_checks"], [])
        self.assertEqual(self.flow.status()["status"], "ready")
        with self.assertRaises(FlowError):
            self.record("4.1")  # No real W3 preflight or cost authorization.

    def test_formal_result_drift_detected_again_at_stage_finish(self):
        self.stage_one()
        for step in ("2.1", "2.2"):
            self.record(step)
        self.record("2.3", {"protocol_id": "p1"})
        for seed, value in zip((1, 2, 3), (9, 10, 11)):
            self.fx.finish(self.fx.start("baseline", seed), value)
        self.record("2.4", {"protocol_id": "p1"})
        self.record("2.5", {"protocol_id": "p1", "baseline_review": self.phase_two_review()})
        (self.root / "baseline-1" / "result.json").write_text("{}")
        with self.assertRaises(FlowError):
            self.flow.finish("2", self.finish_spec("2"))
        self.assertEqual(self.flow.store._load()["current_stage"], "2")

    def test_three_to_five_sigma_requires_extra_runs_and_bound_review(self):
        self.fx.pair(b=(9, 10, 11), r=(12.2, 13.2, 14.2))
        self.assertEqual(self.fx.book.report("p1")["status"], "needs_review")
        with self.assertRaises(FlowError):
            self.flow._statistical_review(self.fx.book, "p1", {})
        self.fx.book.extend("p1", {"seeds": [4, 5], "reason": "append actual repeats before platform review"})
        for role, values in (("baseline", (9, 11)), ("reference", (12.2, 14.2))):
            for seed, value in zip((4, 5), values):
                self.fx.finish(self.fx.start(role, seed), value)
        report = self.fx.book.report("p1")
        self.assertEqual(report["status"], "needs_review")
        ref = self.fx.ref("statistics-review.json", json.dumps({
            "protocol_sha256": report["protocol_sha256"], "experiment_sha256": report["experiment_sha256"],
            "platform_review_required": True, "reviewer": "expert", "rationale": "synthetic conditional evidence",
            "evidence": [self.fx.proof]}))
        review = self.fx.ref("review-statistics.json", json.dumps(self.fx.review()))
        score = self.fx.ref("score-statistics.json", json.dumps({"protocol_sha256": report["protocol_sha256"],
             "upper_bound": 16, "metric_ceiling": 100, "rationale": "synthetic", "evidence": [self.fx.proof]}))
        checks = {"protocol_id": "p1", "baseline_review": review, "score_contract": score, "statistical_review": ref,
                  "harbor_task": "workspace/harbor_task", "harbor_execution": self.scoring_receipt(score)}
        self.assertIn("statistical_review", self.flow._gate("3.5", checks))
        del checks["statistical_review"]
        with self.assertRaises(FlowError):
            self.flow._gate("3.5", checks)

    def test_qa_dispositions_cannot_omit_failures_or_relabel_them_passed(self):
        report = {"checks": [{"id": "QA01", "status": "pass"}, {"id": "QA16", "status": "fail"},
                             {"id": "QA15", "status": "not_applicable"}]}
        with self.assertRaises(FlowError):
            self.flow._qa_coverage(report, [{"id": "QA01", "status": "pass"}])
        with self.assertRaises(FlowError):
            self.flow._qa_coverage(report, [{"id": "QA01", "status": "pass"},
                                            {"id": "QA16", "status": "pass"},
                                            {"id": "QA15", "status": "skip"}])
        for status in ("exception", "platform_only", "not_applicable"):
            with self.subTest(status=status), self.assertRaises(FlowError):
                self.flow._qa_coverage(report, [{"id": "QA01", "status": "pass"},
                                                {"id": "QA16", "status": status},
                                                {"id": "QA15", "status": "skip"}])
        report["checks"][1]["status"] = "pass"
        self.flow._qa_coverage(report, [{"id": "QA01", "status": "pass"},
                                        {"id": "QA16", "status": "pass"},
                                        {"id": "QA15", "status": "skip"}])

    def test_unapproved_confirmation_is_rejected(self):
        spec = self.finish_spec("1")
        path = self.root / spec["approval"]["path"]
        value = json.loads(path.read_text())
        value["approved"] = False
        path.write_text(json.dumps(value))
        ref = {"path": str(path.relative_to(self.root)), "sha256": _sha256(path)}
        with self.assertRaises(FlowError) as caught:
            self.flow._approval(ref, "stage-1")
        self.assertEqual(caught.exception.code, "CONFIRMATION_MISSING")

    def test_stage_reference_hash_and_path_boundary(self):
        refs = self.flow.reference([self.fx.proof["path"]])["evidence"]
        self.assertEqual(refs[0], self.fx.proof)
        with self.assertRaises(FlowError):
            self.flow.reference(["../outside"])

    def test_partial_work_can_resume_without_completion_claim(self):
        self.record("1.1", status="in_progress")
        self.assertEqual(self.flow.status()["next_step"], "1.1")
        self.record("1.1", status="awaiting_evidence", due_stage="1")
        self.assertEqual(self.flow.status()["next_step"], "1.1")
        self.record("1.1")
        self.assertEqual(len(self.flow.store._load()["stages"]["1"]["substeps"]["1.1"]["history"]), 3)


if __name__ == "__main__":
    unittest.main()
