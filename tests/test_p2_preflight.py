"""Offline P2 contracts; synthetic reports are not scientific/QA evidence."""
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


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.checker = Preflight(self.root)

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value,
                        encoding="utf-8")
        return path

    def row(self, result, key):
        return next(item for item in result["obligations"] if item["id"] == key)

    def complete(self, stage, **kwargs):
        requirements = self.checker.check(stage, **kwargs)["obligations"]
        roles = {role for item in requirements for role in item["required_evidence"]}
        evidence = {}
        for role in roles:
            path = self.write(f"evidence/{role}.md", "synthetic source, never real QA proof\n")
            evidence[role] = path.relative_to(self.root).as_posix()
        bindings = {key: hashlib.sha256((self.root / path).read_bytes()).hexdigest()
                    for key, path in evidence.items()}
        self.write("check.json", {"status": "passed", "issues": []})
        self.write("review.md", "fixture reviewer conclusion and supporting sources\n")
        keys = [item["id"] for item in requirements]
        return {"evidence": evidence,
                "checks": [{"obligations": keys, "report": "check.json", "bindings": bindings}],
                "reviews": [{"obligations": keys, "report": "review.md", "bindings": bindings,
                             "reviewer": "fixture", "summary": "synthetic assessment",
                             "conclusion": "PASS"}]}

    def exception(self, key="M01-S1", status="waived", **changes):
        self.write("approval.md", "expert explicitly approved this synthetic test exception\n")
        fields = {"status": status, "scope": key, "before": "research_contract",
                  "rule_version": self.checker.version, "reason": "fixture-only reason",
                  "evidence": "approval.md", "approver": "fixture expert", "limits": "this task/version only"}
        fields.update(changes)
        path = self.root / ".autoresearch/decision-log.md"
        path.parent.mkdir(exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write("## 2026-10-11T00:00:00Z — exception\n" +
                         "\n".join(f"- {key}: {value}" for key, value in fields.items()) + "\n")

    def test_enter_without_inputs_is_pending_read_only_and_needs_no_ledger(self):
        before = list(self.root.rglob("*"))
        result = self.checker.check(1)
        self.assertEqual(result["status"], "PENDING")
        self.assertIsNone(result["ready"])
        self.assertEqual(before, list(self.root.rglob("*")))
        self.assertFalse((self.root / ".autoresearch-flow").exists())

    def test_missing_due_evidence_blocks_gate_and_exit(self):
        result = self.checker.check(1, before="research_contract")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["ready"])
        self.assertTrue(all(item["due"] for item in result["obligations"]))
        self.assertFalse(self.checker.check(1, phase="exit")["ready"])

    def test_existing_mechanical_and_review_results_can_cover_multiple_obligations(self):
        inputs = self.complete(1, before="research_contract")
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertEqual(result["status"], "PENDING")
        self.assertTrue(result["checks_ready"])
        self.assertFalse(result["ready"])  # P3: evidence readiness cannot approve the gate.

    def test_file_presence_does_not_replace_mechanical_or_semantic_review(self):
        inputs = self.complete(1, before="research_contract")
        inputs["reviews"] = []
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertFalse(result["ready"])
        self.assertEqual(self.row(result, "M03-S1")["status"], "PENDING")
        inputs["checks"] = []
        self.assertEqual(self.row(self.checker.check(1, inputs), "M03-S1")["status"], "PENDING")

    def test_dual_launch_reads_prior_evidence_and_only_prepares_future_outputs(self):
        result = self.checker.check(4, before="dual_track_launch")
        self.assertTrue(self.row(result, "M03-S3")["due"])
        trajectory = self.row(result, "M09-S4")
        self.assertIn("trajectory_contract", trajectory["required_evidence"])
        self.assertNotIn("trajectory_codex", trajectory["required_evidence"])
        self.assertNotIn("timing_ledger", self.row(result, "M08-S4")["required_evidence"])
        inputs = self.complete(4, before="dual_track_launch")
        self.assertTrue(self.checker.check(4, inputs, before="dual_track_launch")["checks_ready"])
        # Short launch checks must not pass completed-trajectory obligations.
        self.assertFalse(self.checker.check(4, inputs, phase="exit")["ready"])

    def test_best_retest_and_qa_have_no_future_result_cycles(self):
        result = self.checker.check(5, before="best_method_retest")
        self.assertNotIn("best_retest_runs", self.row(result, "M03-S5")["required_evidence"])
        self.assertFalse(self.row(result, "M04-S5")["due"])
        inputs = self.complete(5, before="best_method_retest")
        self.assertTrue(self.checker.check(5, inputs, before="best_method_retest")["ready"])
        result = self.checker.check(6, before="independent_qa")
        self.assertFalse(self.row(result, "M13-S6")["due"])
        self.assertTrue(self.row(self.checker.check(6, phase="exit"), "M13-S6")["due"])

    def test_existing_report_errors_or_pending_are_not_passed(self):
        inputs = self.complete(1)
        self.write("check.json", {"status": "passed", "issues": [{"code": "FAIL", "message": "bad"}]})
        self.assertEqual(self.row(self.checker.check(1, inputs), "M03-S1")["status"], "BLOCKED")
        self.write("check.json", {"status": "passed", "issues": [], "pending": ["not replayed"]})
        self.assertEqual(self.row(self.checker.check(1, inputs), "M03-S1")["status"], "PENDING")

    def test_changed_binding_requires_targeted_review(self):
        inputs = self.complete(1)
        self.write(inputs["evidence"]["protocol_draft"], "changed protocol\n")
        result = self.checker.check(1, inputs)
        self.assertEqual(self.row(result, "M03-S1")["status"], "BLOCKED")
        self.assertIn("需定向复核", self.row(result, "M03-S1")["reason"])

    def test_invalid_json_nonfinite_and_explicit_hash_fail(self):
        for contents, suffix in (("{", "json"), ('{"x": NaN}', "json"), ("x = [", "toml")):
            path = self.write("invalid." + suffix, contents)
            with self.assertRaises((ValueError, FlowError)):
                self.checker._reference(path.name)
        self.write("notes.md", "evidence\n")
        with self.assertRaisesRegex(FlowError, "哈希变化"):
            self.checker._reference({"path": "notes.md", "sha256": "0" * 64})

    def test_boundary_rejects_escape_symlink_directory_and_empty_file(self):
        self.write("notes.md", "evidence\n")
        (self.root / "link.md").symlink_to(self.root / "notes.md")
        self.write("empty.md", "")
        for ref in ("../outside", "/etc/passwd", "bad\\path", "link.md", ".", "empty.md"):
            with self.assertRaises(FlowError, msg=ref):
                self.checker._reference(ref)

    def test_explicit_confirmed_exception_does_not_claim_original_pass(self):
        self.exception()
        result = self.checker.check(1, before="research_contract")
        row = self.row(result, "M01-S1")
        self.assertEqual(row["status"], "WAIVED")
        self.assertIn("不是原要求已通过", row["reason"])
        self.assertFalse(result["ready"])

    def test_exception_without_approval_or_current_version_is_ineffective(self):
        for changes in ({"rule_version": "old"}, {"evidence": "missing.md"}, {"approver": ""},
                        {"before": "dual_track_launch"}):
            self.exception(**changes)
            result = self.checker.check(1, before="research_contract")
            self.assertNotEqual(self.row(result, "M01-S1")["status"], "WAIVED")
            self.assertTrue(result["decision_log_issues"])

    def test_rejection_revokes_old_exception(self):
        self.exception()
        self.exception(status="rejected")
        self.assertNotEqual(self.row(self.checker.check(1), "M01-S1")["status"], "WAIVED")

    def test_rule_text_changes_invalidate_prior_version_exception(self):
        copied = self.root / "flow"
        shutil.copytree(FLOW / "rules", copied / "rules")
        self.exception()
        path = copied / "rules/README.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        updated = Preflight(self.root, rules=StageRules(copied))
        self.assertNotEqual(updated.version, self.checker.version)
        self.assertNotEqual(self.row(updated.check(1), "M01-S1")["status"], "WAIVED")

    def test_advisory_failure_does_not_block_other_due_items(self):
        inputs = self.complete(1, before="research_contract")
        self.checker.by_id["M01-S1"]["severity"] = "advisory"
        inputs["reviews"].append({**inputs["reviews"][0], "obligations": ["M01-S1"],
                                  "conclusion": "BLOCKED"})
        result = self.checker.check(1, inputs, before="research_contract")
        self.assertFalse(self.row(result, "M01-S1")["due"])
        self.assertTrue(result["checks_ready"])

    def test_not_applicable_only_for_conditional_rules(self):
        self.exception(status="not_applicable")
        self.assertNotEqual(self.row(self.checker.check(1), "M01-S1")["status"], "NOT_APPLICABLE")
        self.exception("C02-S6", status="not_applicable", before="independent_qa")
        result = self.checker.check(6, before="independent_qa")
        self.assertEqual(self.row(result, "C02-S6")["status"], "NOT_APPLICABLE")

    def test_existing_review_can_establish_conditional_inapplicability_without_extra_approval(self):
        inputs = self.complete(6, before="independent_qa")
        inputs["reviews"].append({**inputs["reviews"][0], "obligations": ["C02-S6"],
                                  "conclusion": "NOT_APPLICABLE", "summary": "已有可见面核查未发现 .git"})
        row = self.row(self.checker.check(6, inputs, before="independent_qa"), "C02-S6")
        self.assertEqual(row["status"], "NOT_APPLICABLE")
        self.assertIsNone(row["exception"])
        inputs["reviews"].append({**inputs["reviews"][0], "obligations": ["M01-S1"],
                                  "conclusion": "NOT_APPLICABLE"})
        self.assertEqual(self.row(self.checker.check(6, inputs), "M01-S1")["status"], "BLOCKED")

    def test_changes_only_hint_affected_stages_no_stale_cascade_or_write(self):
        inputs = self.complete(1)
        paths = {str(path) for path in self.root.rglob("*")}
        result = self.checker.check(1, inputs, changed=["M03-S1"])
        self.assertEqual(result["status"], "PASS")
        self.assertIn("M03-S3", result["recheck"]["obligations"])
        self.assertIn(4, result["recheck"]["stages"])
        self.assertEqual(paths, {str(path) for path in self.root.rglob("*")})

    def test_builtin_protocol_and_trajectory_reuse_existing_contracts(self):
        self.write("protocol.json", {})
        self.write("trajectory.json", {"rounds": []})
        for name, kind in (("protocol.json", "protocol"), ("trajectory.json", "trajectory")):
            with self.assertRaises(FlowError):
                self.checker._reference({"path": name, "validator": kind})
        self.write("data.md", "nothing executable\n")
        with self.assertRaises(FlowError):
            self.checker._reference({"path": "data.md", "validator": "shell"})

    def test_invalid_scope_input_is_not_silently_accepted(self):
        for kwargs in ({"stage": 4, "before": "anchor_freeze"}, {"stage": 1, "changed": ["fake"]},
                       {"stage": 1, "inputs": []}, {"stage": 1, "inputs": {"checks": [{"obligations": ["fake"]}]}},
                       {"stage": 1, "inputs": {"status": "PASS"}}):
            with self.assertRaises(FlowError):
                self.checker.check(**kwargs)

    def test_cli_entry_is_state_free_and_has_honest_exit_codes(self):
        for extra, expected in (([], 0), (["--before", "research_contract"], 2)):
            result = subprocess.run([sys.executable, str(FLOW / "cli.py"), "--format", "json",
                "preflight", "--task-root", str(self.root), "--stage", "1", *extra],
                capture_output=True, text=True, cwd=FLOW)
            self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(json.loads(result.stdout)["action"], "preflight")
        self.assertFalse((self.root / ".autoresearch-flow").exists())

    def test_runtime_payload_includes_preflight_entry_docs_and_templates(self):
        from tools import release_check
        paths = {path.relative_to(FLOW).as_posix() for path in release_check.payload_files()}
        self.assertTrue({"autoresearch_flow/preflight.py", "docs/preflight.md",
                         "templates/preflight-inputs.example.json",
                         "templates/decision-log.example.md"} <= paths)


if __name__ == "__main__":
    unittest.main()
