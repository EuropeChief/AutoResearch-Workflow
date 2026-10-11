"""P3 recorded expert decisions: offline fixtures, never actual authorization."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from autoresearch_flow.common import FlowError
from autoresearch_flow.preflight import Preflight
from autoresearch_flow.stage_rules import StageRules

FLOW = Path(__file__).resolve().parents[1]


class StageGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checker = Preflight(self.root)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return path

    def complete(self, stage, *, before=None, phase="enter"):
        result = self.checker.check(stage, before=before, phase=phase)
        roles = {role for row in result["obligations"] for role in row["required_evidence"]}
        for item in self.checker.rules.stages():
            if item["id"] <= stage:
                roles.update(item.get("confirmation_evidence", []))
        evidence = {role: f"sources/{role}.md" for role in roles}
        for path in evidence.values():
            self.write(path, "SYNTHETIC source, not scientific evidence or real consent\n")
        bindings = {role: hashlib.sha256((self.root / path).read_bytes()).hexdigest()
                    for role, path in evidence.items()}
        keys = [row["id"] for row in result["obligations"]]
        self.write("check.json", {"status": "passed", "issues": []})
        self.write("review.md", "synthetic assessment by fixture reviewer\n")
        return {"evidence": evidence,
                "checks": [{"obligations": keys, "report": "check.json", "bindings": bindings}],
                "reviews": [{"obligations": keys, "report": "review.md", "bindings": bindings,
                             "reviewer": "fixture", "summary": "synthetic assessment", "conclusion": "PASS"}]}

    def confirmation(self, result, gate):
        return next(row for row in result["confirmations"] if row["gate"] == gate)

    def decide(self, gate, inputs, **changes):
        stage = next(s["id"] for s in self.checker.rules.stages() if s["gate"] == gate)
        result = self.checker.check(stage, inputs, before=gate)
        proposal = self.confirmation(result, gate)["proposal"]
        fields = {**proposal, "status": "approved", "approver": "fixture expert",
                  "limits": "this synthetic scope only, no resource authorization"}
        fields.update(changes)
        heading = fields.pop("gate")
        body = "## 2026-10-11T00:00:00Z — " + heading + "\n"
        body += "\n".join(f"- {key}: {json.dumps(value) if isinstance(value, dict) else value}"
                          for key, value in fields.items()) + "\n"
        path = self.root / ".autoresearch/decision-log.md"
        current = path.read_text() if path.exists() else ""
        self.write(path.relative_to(self.root).as_posix(), current + body)
        return fields

    def test_all_checks_pass_cannot_approve_research_contract(self):
        inputs = self.complete(1, before="research_contract")
        before = {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(result["checks_ready"])
        self.assertFalse(result["confirmations_ready"])
        self.assertFalse(result["ready"])
        self.assertEqual(self.confirmation(result, "research_contract")["status"], "PENDING")
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse((self.root / ".autoresearch").exists())

    def test_approved_current_bindings_allow_research_exit(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        self.assertTrue(self.checker.check(1, inputs, before="research_contract")["ready"])
        self.assertTrue(self.checker.check(1, inputs, phase="exit")["ready"])

    def test_approval_cannot_cover_failed_or_pending_checks(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        self.write("check.json", {"status": "failed"})
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(result["confirmations_ready"])
        self.assertFalse(result["checks_ready"])
        self.assertFalse(result["ready"])

    def test_missing_invalid_and_latest_rejected_records_do_not_reuse_old_approval(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        for change in ({"status": "rejected"}, {"approver": ""}, {"bindings": "invalid-json"},
                       {"rule_version": "old"}, {"evidence": "not-the-bound-files"}):
            with self.subTest(change=change):
                self.decide("research_contract", inputs, **change)
                result = self.checker.check(1, inputs, before="research_contract")
                self.assertFalse(result["ready"])
                self.assertEqual(self.confirmation(result, "research_contract")["status"], "BLOCKED")

    def test_changed_confirmation_file_rejects_even_with_fresh_passed_assessment(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        role = "research_contract"
        self.write(inputs["evidence"][role], "changed optimization surface\n")
        digest = hashlib.sha256((self.root / inputs["evidence"][role]).read_bytes()).hexdigest()
        inputs["checks"][0]["bindings"][role] = digest
        inputs["reviews"][0]["bindings"][role] = digest
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(result["checks_ready"])
        self.assertFalse(result["confirmations_ready"])
        self.assertFalse(result["ready"])

    def test_different_current_file_cannot_borrow_matching_content_approval(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        self.write("different-contract.md", (self.root / inputs["evidence"]["research_contract"]).read_text())
        inputs["evidence"]["research_contract"] = "different-contract.md"
        self.assertFalse(self.checker.check(1, inputs, before="research_contract")["ready"])

    def test_anchor_and_dual_launch_require_only_their_prior_and_own_decisions(self):
        inputs = self.complete(4, before="dual_track_launch")
        self.decide("dual_track_launch", inputs)
        result = self.checker.check(4, inputs, before="dual_track_launch")
        self.assertTrue(result["checks_ready"])
        self.assertFalse(result["ready"])
        self.decide("research_contract", inputs)
        self.assertFalse(self.checker.check(4, inputs, before="dual_track_launch")["ready"])
        self.decide("anchor_freeze", inputs)
        self.assertTrue(self.checker.check(3, inputs, before="anchor_freeze")["confirmations_ready"])
        self.assertTrue(self.checker.check(4, inputs, before="dual_track_launch")["ready"])

    def test_joint_anchor_freeze_needs_fair_evidence_and_both_decisions(self):
        inputs = self.complete(3, before="anchor_freeze")
        self.decide("research_contract", inputs)
        self.assertFalse(self.checker.check(3, inputs, before="anchor_freeze")["ready"])
        self.decide("anchor_freeze", inputs)
        self.assertTrue(self.checker.check(3, inputs, before="anchor_freeze")["ready"])
        self.write("check.json", {"status": "failed"})
        self.assertFalse(self.checker.check(3, inputs, before="anchor_freeze")["ready"])

    def test_preparation_is_not_blocked_and_implementation_has_no_new_human_gate(self):
        inputs = self.complete(2, before="task_ready")
        self.assertIsNone(self.checker.check(2, inputs)["ready"])
        result = self.checker.check(2, inputs, before="task_ready")
        self.assertEqual([row["gate"] for row in result["confirmations"]], ["research_contract"])
        self.assertFalse(result["ready"])
        self.decide("research_contract", inputs)
        self.assertTrue(self.checker.check(2, inputs, before="task_ready")["ready"])

    def test_original_approval_can_be_read_without_copying_prior_refs_into_new_inputs(self):
        inputs = self.complete(2, before="task_ready")
        self.decide("research_contract", inputs)
        current_roles = {role for row in self.checker.check(2, before="task_ready")["obligations"]
                         for role in row["required_evidence"]}
        inputs["evidence"] = {role: path for role, path in inputs["evidence"].items() if role in current_roles}
        self.assertTrue(self.checker.check(2, inputs, before="task_ready")["ready"])

    def test_goal_resume_and_completed_track_exit_do_not_require_launch_again(self):
        inputs = self.complete(4, phase="exit")
        result = self.checker.check(4, inputs, phase="exit")
        self.assertTrue(result["ready"])
        self.assertFalse(any(row["due"] for row in result["confirmations"]))

    def test_explicit_check_exception_and_recorded_gate_confirmation_both_required(self):
        inputs = self.complete(1, before="research_contract")
        inputs["reviews"].append({**inputs["reviews"][0], "conclusion": "BLOCKED",
                                  "obligations": ["M01-S1"]})
        self.write("exception.md", "fixture expert approved the specific exception\n")
        body = "## 2026-10-11T00:00:00Z — exception\n" + "\n".join([
            "- status: waived", "- scope: M01-S1, M02-S1", "- before: research_contract",
            "- rule_version: " + self.checker.version, "- reason: fixture-only justification",
            "- evidence: exception.md", "- approver: fixture expert", "- limits: this scope only"]) + "\n"
        self.write(".autoresearch/decision-log.md", body)
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(result["checks_ready"])
        self.assertFalse(result["ready"])
        self.decide("research_contract", inputs)
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(result["ready"])
        self.assertEqual(next(row for row in result["obligations"] if row["id"] == "M01-S1")["status"], "WAIVED")

    def test_waived_gate_still_requires_reason_and_binding_does_not_waive_checks(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs, status="waived")
        self.assertFalse(self.checker.check(1, inputs, before="research_contract")["ready"])
        self.decide("research_contract", inputs, status="waived", reason="fixture scoped exception")
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(result["ready"])
        self.assertEqual(self.confirmation(result, "research_contract")["status"], "WAIVED")
        self.write("check.json", {"status": "failed"})
        self.assertFalse(self.checker.check(1, inputs, before="research_contract")["ready"])

    def test_qa_and_retest_do_not_demand_historical_approvals(self):
        for stage, action in ((5, "best_method_retest"), (6, "independent_qa")):
            with self.subTest(stage=stage):
                inputs = self.complete(stage, before=action)
                result = self.checker.check(stage, inputs, before=action)
                self.assertTrue(result["ready"])
                self.assertEqual(result["confirmations"], [])

    def test_decision_parent_symlink_is_rejected_before_reading_outside(self):
        outside = self.root / "outside"
        outside.mkdir()
        self.write("outside/decision-log.md", "untrusted outside decision")
        (self.root / ".autoresearch").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(FlowError) as caught:
            self.checker.check(1)
        self.assertEqual(caught.exception.code, "DECISION_LOG_UNSAFE")

    def test_duplicate_fields_are_not_accepted_as_expert_confirmation(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        path = self.root / ".autoresearch/decision-log.md"
        self.write(".autoresearch/decision-log.md", path.read_text() + "- status: approved\n")
        self.assertFalse(self.checker.check(1, inputs, before="research_contract")["ready"])

    def test_cli_does_not_report_machine_pass_as_permission(self):
        inputs = self.complete(1, before="research_contract")
        path = self.write("inputs.json", inputs)
        args = [sys.executable, str(FLOW / "cli.py"), "--format", "json", "preflight",
                "--task-root", str(self.root), "--stage", "1", "--before", "research_contract", "--inputs", str(path)]
        result = subprocess.run(args, cwd=FLOW, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.decide("research_contract", inputs)
        result = subprocess.run(args, cwd=FLOW, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_changed_rule_version_needs_reviewed_confirmation_not_state_cascade(self):
        inputs = self.complete(1, before="research_contract")
        self.decide("research_contract", inputs)
        copied = self.root / "flow"
        shutil.copytree(FLOW / "rules", copied / "rules")
        path = copied / "rules/README.md"
        path.write_text(path.read_text() + "\n")
        updated = Preflight(self.root, rules=StageRules(copied))
        result = updated.check(1, inputs, before="research_contract")
        self.assertFalse(result["ready"])
        self.assertEqual(self.confirmation(result, "research_contract")["status"], "BLOCKED")
        self.assertFalse((self.root / ".autoresearch-flow").exists())


if __name__ == "__main__":
    unittest.main()
