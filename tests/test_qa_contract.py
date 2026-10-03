"""v0.3.1 contract regressions using explicitly synthetic reports."""
import copy
import unittest

from autoresearch_flow.core import FlowError
from autoresearch_flow.qa_contract import validate_qa_report


def synthetic_report(package=None):
    def row(key, status="pass"):
        return {"id": key, "status": status, "summary": "Synthetic contract fixture only",
                "evidence": [] if status == "not_applicable" else ["fixture.txt"]}
    checks = [row(f"QA{i:02d}", "not_applicable" if i == 15 else "pass") for i in range(1, 22)]
    return {
        "schema_version": 4,
        "source": {"path": str(package) if package else "/synthetic", "kind": "directory", "sha256": None},
        "policy": {"name": "implementation", "revision": "research-quality-v3"},
        "checks": checks,
        "content_gates": {"schema_version": 1, "checks": [row(f"G{i:02d}") for i in range(1, 4)]},
        "overview": {},
        "runtime_review": {"status": "pass"},
        "format_alignment": {"review": {"status": "aligned_with_extras"}},
        "review": {"completed": True},
        "summary": {"decision": "PASS"},
        "harbor": {
            "checks": [row(f"H{i:02d}", "not_applicable" if i >= 5 else "pass") for i in range(1, 7)],
            "runtime_status": "not_run", "static_status": "pass", "qa17_status": "pass",
            "hidden_review": {"status": "pass"}, "artifact_contract": {"status": "pass"},
            "path_contract": {"status": "pass", "findings": []}
        }
    }


class QaContractTests(unittest.TestCase):
    def test_static_pass_allows_no_trial_without_claiming_execution(self):
        result = validate_qa_report(synthetic_report(), require_pass=True)
        self.assertEqual(result["runtime_status"], "not_run")

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
        for key in ("QA06", "QA09", "QA10", "QA17"):
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
        r["harbor"]["checks"][-1]["evidence"] = ["trial/result.json"]
        with self.assertRaises(FlowError): validate_qa_report(r)
        r = synthetic_report()
        r["harbor"]["runtime_status"] = "evidence_consistent"
        with self.assertRaises(FlowError): validate_qa_report(r)

    def test_path_fail_and_unfinished_review_cannot_claim_pass(self):
        r = synthetic_report()
        r["harbor"]["path_contract"]["findings"] = [{"status": "fail"}]
        with self.assertRaises(FlowError): validate_qa_report(r)
        r = synthetic_report()
        r["review"]["completed"] = False
        with self.assertRaises(FlowError): validate_qa_report(r)
