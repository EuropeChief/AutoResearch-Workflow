"""Public rule bundle contracts; no model calls, Docker or scientific claims."""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

FLOW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import FlowError, Registry, TaskStore


class PublicRulesTests(unittest.TestCase):
    def test_only_workflow_directory_is_needed_at_an_arbitrary_location(self):
        with tempfile.TemporaryDirectory(prefix="ar-public-rules-") as temp:
            root = Path(temp)
            copied = root / "renamed-workflow"
            shutil.copytree(FLOW, copied, ignore=shutil.ignore_patterns(
                ".git", "__pycache__", "runs", "build", "local"))
            registry = Registry(copied)
            self.assertEqual(registry.repository_root, copied)
            self.assertEqual(registry.check_sources(), [])
            task = root / "new-task"
            task.mkdir()
            store = TaskStore(task, repository_root=copied)
            store.initialize(registry, "new-task")
            self.assertEqual(store.check()["issues"], [])
            self.assertFalse((root / "通用规则").exists())
            self.assertFalse((root / ".codex").exists())
            self.assertFalse((root / "AutoResearch新流程设计").exists())
            source = copied / next(s["path"] for s in registry.manifest["sources"]
                                   if s["id"] == "tutorial")
            source.write_bytes(source.read_bytes() + b"\nsynthetic drift\n")
            self.assertTrue(any(i["code"] == "SOURCE_DRIFT" for i in store.check()["issues"]))
            self.assertEqual(len(store.check()["issues"]), 1)

    def test_source_bundle_has_complete_skills_and_no_history_dependency(self):
        registry = Registry()
        self.assertNotIn("w0_inputs", registry.manifest)
        refs = {item["path"] for item in registry.manifest["bundled_files"]}
        for name in ("autoresearch-task-qa", "autoresearch-baseline-quality"):
            skill = FLOW / "skills" / name
            self.assertTrue((skill / "SKILL.md").is_file())
            files = {str(p.relative_to(FLOW)) for p in skill.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts}
            self.assertTrue(files <= refs)
        self.assertTrue(any(p.endswith(".zip") for p in refs))
        self.assertFalse(any("history/" in p or "provenance/" in p for p in refs))

    def test_old_task_versions_are_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory(prefix="ar-old-state-") as temp:
            store = TaskStore(Path(temp))
            state = store.initialize(Registry(), "version-test")
            for change in ({"schema_version": 1, "flow_version": "0.2.0"},
                           {"flow_version": "unknown"}):
                with self.subTest(change=change):
                    store.state_path.write_text(json.dumps({**state, **change}))
                    before = store.state_path.read_bytes()
                    with self.assertRaises(FlowError) as caught:
                        store.check()
                    self.assertEqual(caught.exception.code, "UNSUPPORTED_TASK_VERSION")
                    self.assertEqual(store.state_path.read_bytes(), before)

    def test_step_view_informs_before_evidence_must_be_collected(self):
        registry = Registry()
        early = registry.show(step="2.3")
        rows = {rule["id"]: rule for rule in early["rules"]}
        self.assertIn("AR-024", rows)
        self.assertIn("AR-025", rows)
        self.assertEqual(rows["AR-025"]["applicability"], "requires_review")
        self.assertEqual(rows["AR-025"]["compliance"], "not_evaluated")
        self.assertLess(len(rows), len(registry.catalog["rules"]))
        rule = registry.show(rule_id="AR-032")["rules"][0]
        self.assertEqual(rule["id"], "AR-032")
        self.assertTrue(rule["source_locations"])
        self.assertTrue(all((FLOW / s["path"]).is_file() for s in rule["source_locations"]))
        with self.assertRaises(FlowError):
            registry.show(step="2.99")

    def test_coverage_tracks_locked_skill_checks_instead_of_a_fixed_count(self):
        registry = Registry()
        registry.manifest["qa_checks"].append("QA22")
        with self.assertRaises(FlowError) as caught:
            registry._validate_catalog()
        self.assertEqual(caught.exception.code, "INVALID_CATALOG")
        registry.catalog["coverage"]["QA22"] = ["AR-001"]
        registry._validate_manifest()
        registry._validate_catalog()

    def test_every_rule_view_resolves_all_original_references(self):
        registry = Registry()
        for rule in registry.catalog["rules"]:
            with self.subTest(rule=rule["id"]):
                displayed = registry.show(rule_id=rule["id"])["rules"][0]
                self.assertEqual(set(rule["source_refs"]),
                                 {item["ref"] for item in displayed["source_locations"]})
                self.assertEqual(len(displayed["source_locations"]), len(rule["source_refs"]))
                for item in displayed["source_locations"]:
                    if item["ref"].startswith("Q:baseline-quality/"):
                        self.assertEqual(item["path"], "skills/autoresearch-baseline-quality/SKILL.md")
                    elif item["ref"].startswith("Q:SKILL.md"):
                        self.assertEqual(item["path"], "skills/autoresearch-task-qa/SKILL.md")


if __name__ == "__main__":
    unittest.main()
