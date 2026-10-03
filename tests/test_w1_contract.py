"""来源锁、显式初始化、只读检查；不迁移历史任务。"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT
sys.path.insert(0, str(PACKAGE_ROOT))

from autoresearch_flow.core import FlowError, Registry, TaskStore  # noqa: E402


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class W1ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="autoresearch-w1-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.task_root = self.root / "practice-task"
        self.task_root.mkdir()

    def _copied_registry(self) -> Registry:
        manifest = json.loads((PACKAGE_ROOT / "rules" / "manifest.json").read_text(encoding="utf-8"))
        paths = [manifest["catalog"]["path"], *(source["path"] for source in manifest["sources"]), *(entry["path"] for entry in manifest["bundled_files"])]
        paths.append("rules/manifest.json")
        for relative in paths:
            destination = self.root / "AutoResearch新流程" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPOSITORY_ROOT / relative, destination)
        return Registry(self.root / "AutoResearch新流程")

    def test_central_registry_has_complete_machine_coverage(self) -> None:
        registry = Registry()
        self.assertEqual(registry.check_sources(), [])
        self.assertEqual(len(registry.catalog["rules"]), 50)
        self.assertEqual(len(registry.catalog["coverage"]), 38)
        self.assertEqual(registry.catalog["skipped_checks"], ["QA15"])

    def test_explicit_initialize_and_read_only_check(self) -> None:
        store = TaskStore(self.task_root)
        state = store.initialize(Registry(), "practice-001")
        self.assertEqual(state["current_stage"], "1")
        self.assertEqual(state["task_config"]["adapter"]["kind"], "unconfigured")
        self.assertEqual(store.check()["issues"], [])
        self.assertEqual(store.check()["stage_statuses"]["1"], "pending")
        self.assertEqual(store.check()["substep_statuses"]["1"]["1.1"], "pending")
        with self.assertRaisesRegex(FlowError, "不覆盖"):
            store.initialize(Registry(), "practice-001")

    def test_missing_or_legacy_task_is_not_silently_initialized(self) -> None:
        with self.assertRaises(FlowError) as missing:
            TaskStore(self.root / "missing")
        self.assertEqual(missing.exception.code, "TASK_ROOT_MISSING")
        (self.task_root / ".autoresearch").mkdir()
        with self.assertRaises(FlowError) as legacy:
            TaskStore(self.task_root).initialize(Registry(), "practice-001")
        self.assertEqual(legacy.exception.code, "LEGACY_STATE_PRESENT")
        self.assertFalse((self.task_root / ".autoresearch-flow").exists())

    def test_invalid_future_stage_claim_is_rejected(self) -> None:
        store = TaskStore(self.task_root)
        store.initialize(Registry(), "practice-001")
        state = json.loads(store.state_path.read_text(encoding="utf-8"))
        state["stages"]["4"]["status"] = "passed"
        _write_json(store.state_path, state)
        with self.assertRaises(FlowError) as invalid:
            store.check()
        self.assertEqual(invalid.exception.code, "INVALID_STATE")

    def test_source_drift_blocks_task_without_changing_lock(self) -> None:
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=registry.package_root)
        original = store.initialize(registry, "practice-001")
        source = registry.package_root / registry.manifest["sources"][0]["path"]
        source.write_text(source.read_text(encoding="utf-8") + "\n测试用漂移\n", encoding="utf-8")
        result = store.check()
        self.assertTrue(any(issue["code"] == "SOURCE_DRIFT" for issue in result["issues"]))
        self.assertEqual(json.loads(store.state_path.read_text(encoding="utf-8"))["rules_lock"], original["rules_lock"])

    def test_same_version_rule_change_blocks_without_rewriting_passed_state(self):
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=registry.package_root)
        state = store.initialize(registry, "practice-001")
        state["stages"]["1"]["status"] = "passed"
        for step in state["stages"]["1"]["substeps"].values():
            step["status"] = "passed"
        state["current_stage"] = "2"
        _write_json(store.state_path, state)
        before = store.state_path.read_bytes()
        path = registry.catalog_path
        catalog = json.loads(path.read_text())
        catalog["rules"][0]["statement"] += " synthetic change"
        _write_json(path, catalog)
        self.assertTrue(store.check()["issues"])
        self.assertEqual(store.state_path.read_bytes(), before)

    def test_cli_requires_confirmation_before_any_task_write(self) -> None:
        command = [sys.executable, str(PACKAGE_ROOT / "cli.py"), "--format", "json", "task", "init", "--task-root", str(self.task_root), "--task-id", "practice-001"]
        process = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertEqual(process.returncode, 2)
        self.assertEqual(json.loads(process.stdout)["issues"][0]["code"], "CONFIRMATION_REQUIRED")
        self.assertFalse((self.task_root / ".autoresearch-flow").exists())

    def test_cli_confirmed_init_and_read_only_check(self) -> None:
        base = [sys.executable, str(PACKAGE_ROOT / "cli.py"), "--format", "json", "task"]
        initialized = subprocess.run(
            [*base, "init", "--task-root", str(self.task_root), "--task-id", "practice-001", "--confirm-init"],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.assertEqual(json.loads(initialized.stdout)["status"], "initialized")
        state_before = (self.task_root / ".autoresearch-flow" / "state.json").read_bytes()
        checked = subprocess.run(
            [*base, "check", "--task-root", str(self.task_root)],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)
        self.assertEqual(json.loads(checked.stdout)["substep_statuses"]["1"]["1.1"], "pending")
        self.assertEqual((self.task_root / ".autoresearch-flow" / "state.json").read_bytes(), state_before)

    def test_substeps_are_declared_but_not_claimed_complete(self) -> None:
        store = TaskStore(self.task_root)
        state = store.initialize(Registry(), "practice-001")
        self.assertEqual(len(state["stages"]["1"]["substeps"]), 4)
        self.assertEqual(len(state["stages"]["6"]["substeps"]), 5)
        self.assertTrue(all(
            substep["status"] == "pending"
            for stage in state["stages"].values()
            for substep in stage["substeps"].values()
        ))
        state["stages"]["1"]["substeps"]["1.1"]["status"] = "awaiting_evidence"
        _write_json(store.state_path, state)
        with self.assertRaises(FlowError) as invalid:
            store.check()
        self.assertEqual(invalid.exception.code, "INVALID_STATE")

    def test_removed_rule_cannot_silently_replace_task_lock(self):
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=registry.package_root)
        store.initialize(registry, "practice-001")
        before = store.state_path.read_bytes()
        catalog = json.loads(registry.catalog_path.read_text())
        catalog["rules"].pop()
        catalog["rule_count"] = len(catalog["rules"])
        _write_json(registry.catalog_path, catalog)
        self.assertTrue(store.check()["issues"])
        self.assertEqual(store.state_path.read_bytes(), before)

    def test_changed_qa_reference_blocks_without_rewriting_task(self):
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=registry.package_root)
        store.initialize(registry, "practice-001")
        before = store.state_path.read_bytes()
        ref = next(s for s in registry.manifest["sources"] if s["id"] == "harbor_harness")
        path = registry.package_root / ref["path"]
        path.write_text(path.read_text() + "\nsynthetic drift\n")
        self.assertTrue(store.check()["issues"])
        self.assertEqual(store.state_path.read_bytes(), before)

    def test_task_config_rejects_secret_and_escaping_entrypoint(self) -> None:
        store = TaskStore(self.task_root)
        store.initialize(Registry(), "practice-001")
        state = json.loads(store.state_path.read_text(encoding="utf-8"))
        state["task_config"]["api_key"] = "must-not-be-stored"
        _write_json(store.state_path, state)
        with self.assertRaises(FlowError) as invalid:
            store.check()
        self.assertEqual(invalid.exception.code, "INVALID_STATE")
        del state["task_config"]["api_key"]
        state["task_config"]["adapter"] = {"kind": "command-v1", "entrypoint": "../outside.sh"}
        _write_json(store.state_path, state)
        with self.assertRaises(FlowError) as invalid:
            store.check()
        self.assertEqual(invalid.exception.code, "INVALID_STATE")



if __name__ == "__main__":
    unittest.main()
