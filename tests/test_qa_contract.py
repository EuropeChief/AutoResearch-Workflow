"""Current contract regressions using explicitly synthetic reports."""
import copy
import unittest

from autoresearch_flow.core import FlowError
from autoresearch_flow.qa_contract import validate_qa_report


def synthetic_report(package=None):
    def row(key, status="pass"):
        return {"id": key, "status": status, "summary": "Synthetic contract fixture only",
                "evidence": [] if status == "not_applicable" else ["fixture.txt"]}
    checks = [row(f"QA{i:02d}") for i in range(1, 22)]
    return {
        "schema_version": 6,
        "source": {"path": str(package) if package else "/synthetic", "kind": "directory", "sha256": None},
        "policy": {"name": "implementation", "revision": "innerfield-deployment-v6"},
        "checks": checks,
        "content_gates": {"schema_version": 1, "checks": [row(f"G{i:02d}") for i in range(1, 4)]},
        "overview": {},
        "runtime_review": {"status": "pass"},
        "trajectory_review": {"content_status": "pass", "status": "pass", "binding_errors": []},
        "resource_review": {"status": "pass"},
        "task_fingerprint": {"status": "pass"},
        "format_alignment": {"review": {"status": "aligned_with_extras"}},
        "review": {"completed": True, "stage": "semantic_review"},
        "summary": {"decision": "PASS"},
        "harbor": {
            "ruleset": "harbor-compatibility-2026-10-15-v0.3.10",
            "deployment_contract": {"status": "pass"},
            "checks": [row(f"H{i:02d}", "not_applicable" if i == 5 else "pass") for i in range(1, 7)],
            "runtime_status": "evidence_consistent", "static_status": "pass", "qa17_status": "pass",
            "trial_evidence": {"agent": "nop", "trial_dir": "expert_evidence/nop_trial/t1",
                               "rewards": {"reward": 0.0}, "task_binding": {"status": "pass"}},
            "hidden_review": {"status": "pass"}, "artifact_contract": {"status": "pass"},
            "path_contract": {"status": "pass", "findings": []}
        }
    }


class QaContractTests(unittest.TestCase):
    def test_pass_requires_nop_evidence(self):
        result = validate_qa_report(synthetic_report(), require_pass=True)
        self.assertEqual(result["runtime_status"], "evidence_consistent")

    def test_missing_nop_failure_can_be_attached_but_not_closed(self):
        report = synthetic_report()
        for key in ("H06", "QA17"):
            row = next(x for x in report["harbor"]["checks"] + report["checks"] if x["id"] == key)
            row.update(status="fail", evidence=[], remediation="补 NOP", acceptance_evidence="NOP 原件")
        report["harbor"].update(runtime_status="not_run", qa17_status="fail", trial_evidence=None)
        report["summary"]["decision"] = "FAIL"
        validate_qa_report(report)
        with self.assertRaises(FlowError):
            validate_qa_report(report, require_pass=True)

    def test_old_optional_nop_pass_and_wrong_agent_are_rejected(self):
        for mutation in ("old_ruleset", "not_applicable", "wrong_agent", "missing_trial"):
            report = synthetic_report()
            if mutation == "old_ruleset": report["harbor"]["ruleset"] = "harbor-compatibility-2026-09-30-v0.3.1"
            if mutation == "not_applicable": report["harbor"]["checks"][-1]["status"] = "not_applicable"
            if mutation == "wrong_agent": report["harbor"]["trial_evidence"]["agent"] = "candidate"
            if mutation == "missing_trial": report["harbor"]["trial_evidence"] = None
            with self.subTest(mutation=mutation), self.assertRaises(FlowError):
                validate_qa_report(report, require_pass=True)

    def test_old_schema_and_removed_or_duplicate_items_are_rejected(self):
        for mutation in ("schema", "revision", "duplicate", "missing"):
            r = synthetic_report()
            if mutation == "schema": r["schema_version"] = 3
            if mutation == "revision": r["policy"]["revision"] = "research-quality-v2"
            if mutation == "duplicate": r["checks"][1] = copy.deepcopy(r["checks"][0])
            if mutation == "missing": r["harbor"]["checks"].pop()
            with self.subTest(mutation=mutation), self.assertRaises(FlowError):
                validate_qa_report(r)

    def test_old_qa_exemptions_are_not_allowed(self):
        for key in ("QA06", "QA09", "QA10", "QA15", "QA17"):
            r = synthetic_report()
            next(x for x in r["checks"] if x["id"] == key)["status"] = "not_applicable"
            with self.subTest(key=key), self.assertRaises(FlowError):
                validate_qa_report(r)

    def test_failure_can_be_attached_but_cannot_close_delivery(self):
        r = synthetic_report()
        r["checks"][0].update(status="fail", remediation="repair", acceptance_evidence="updated entry")
        r["summary"]["decision"] = "FAIL"
        validate_qa_report(r)
        with self.assertRaises(FlowError): validate_qa_report(r, require_pass=True)
        r["summary"]["decision"] = "PASS"
        with self.assertRaises(FlowError): validate_qa_report(r)

    def test_trial_evidence_and_runtime_status_cannot_be_hidden(self):
        r = synthetic_report()
        r["harbor"]["checks"][-1]["evidence"] = []
        with self.assertRaises(FlowError): validate_qa_report(r)
        r = synthetic_report()
        r["harbor"]["runtime_status"] = "not_run"
        with self.assertRaises(FlowError): validate_qa_report(r)

    def test_path_fail_and_unfinished_review_cannot_claim_pass(self):
        r = synthetic_report()
        r["harbor"]["path_contract"]["findings"] = [{"status": "fail"}]
        with self.assertRaises(FlowError): validate_qa_report(r)
        r = synthetic_report()
        r["review"]["completed"] = False
        with self.assertRaises(FlowError): validate_qa_report(r)

    def test_collection_and_unresolved_new_gates_cannot_claim_pass(self):
        for field in ("stage", "trajectory", "resources", "deployment", "binding", "fingerprint", "inspection"):
            report = synthetic_report()
            if field == "stage": report["review"]["stage"] = "collection"
            if field == "trajectory": report["trajectory_review"]["content_status"] = "manual"
            if field == "resources": report["resource_review"]["status"] = "manual"
            if field == "deployment": report["harbor"]["deployment_contract"]["status"] = "fail"
            if field == "binding": report["trajectory_review"]["binding_errors"] = ["task_hash_mismatch"]
            if field == "fingerprint": report["task_fingerprint"]["status"] = "manual"
            if field == "inspection": report["inspection_error"] = "could not inspect"
            with self.subTest(field=field), self.assertRaises(FlowError):
                validate_qa_report(report, require_pass=True)
