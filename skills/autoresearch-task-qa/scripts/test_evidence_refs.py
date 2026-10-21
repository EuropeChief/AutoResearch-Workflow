"""Synthetic location validation; never import or execute a submitted file."""
import json
from pathlib import Path
import tempfile
import unittest

import evidence_refs
import harbor_review
import implementation_review


class EvidenceLocationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "file.py").write_text("first\nsecond\nthird\n", encoding="utf-8")
        (self.root / "notes.md").write_text("# Notes\n", encoding="utf-8")
        (self.root / "result.json").write_text(json.dumps({
            "score": None, "metrics": {"items": [{"score": 2}]},
            "agent_execution": [False], "a/b": {"~key": 3}, "": 0,
        }), encoding="utf-8")
        self.consumers = (evidence_refs.resolve_ref, implementation_review.evidence_path,
                          harbor_review.resolve_ref)

    def check_refs(self, refs, valid):
        for consumer in self.consumers:
            for ref in refs:
                with self.subTest(consumer=consumer.__module__, ref=ref):
                    if valid:
                        self.assertTrue(consumer(self.root, ref).is_file())
                    else:
                        with self.assertRaises(ValueError):
                            consumer(self.root, ref)

    def test_valid_lines_and_ranges(self):
        self.check_refs(["file.py:1", "file.py:1-3", "file.py#L3", "file.py#L1-L3",
                         "file.py#L1-3", "file.py:3#descriptive-note", "result.json#L1"], True)

    def test_invalid_lines_and_ranges(self):
        self.check_refs(["file.py:0", "file.py:-1", "file.py:4", "file.py:3-1",
                         "file.py:1-4", "file.py#L0", "file.py#L-1", "file.py#L4",
                         "file.py#L3-L1", "file.py#L1-L4"], False)

    def test_existing_json_fields_and_pointer(self):
        self.check_refs(["result.json#score", "result.json#agent_execution",
                         "result.json#agent_execution[0]", "result.json#metrics.items[0].score",
                         "result.json#$.metrics.items[0].score", "result.json#field=score",
                         "result.json#/metrics/items/0/score", "result.json#/a~1b/~0key",
                         "result.json#/", "result.json#/%73core"], True)

    def test_nonexistent_fields_and_array_bounds(self):
        self.check_refs(["result.json#absent", "result.json#metrics.absent",
                         "result.json#agent_execution[1]", "result.json#field=absent",
                         "result.json#$.metrics.items[0].absent", "result.json#/metrics/items/1",
                         "result.json#/metrics/items/-1", "result.json#/metrics/items/01",
                         "result.json#/a~2b", "result.json#/score/child"], False)

    def test_plain_and_descriptive_references_remain_compatible(self):
        self.check_refs(["file.py", "result.json", "notes.md#summary", "notes.md#section.name",
                         "result.json#说明", "result.json#score-notes",
                         "result.json#score explanation", "file.py#function_name"], True)

    def test_invalid_json_is_read_only_when_explicitly_located(self):
        (self.root / "bad.json").write_text("not json")
        self.check_refs(["bad.json", "bad.json#说明"], True)
        self.check_refs(["bad.json#score", "bad.json#/score"], False)

    def test_bundle_safety_for_all_forms(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / "outside.py"
            target.write_text("outside\n")
            (self.root / "escape.py").symlink_to(target)
            self.check_refs([str(target), str(self.root / "file.py"), "../outside.py:1",
                             "escape.py", "escape.py:1", "escape.py#L1"], False)

    def test_review_evidence_uses_shared_validation(self):
        with self.assertRaises(ValueError):
            implementation_review.review_evidence(self.root, ["file.py:99"], "test")
        self.assertEqual(implementation_review.review_evidence(
            self.root, ["result.json#score"], "test"), ["result.json#score"])

    def test_locator_does_not_assert_semantic_support(self):
        # A location exists even when its text says nothing about the claim.
        self.check_refs(["file.py:1", "result.json#score"], True)


if __name__ == "__main__":
    unittest.main()
