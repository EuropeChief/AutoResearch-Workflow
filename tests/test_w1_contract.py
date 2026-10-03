"""W1 的来源锁、显式初始化、只读检查与升级合同。"""

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
REPOSITORY_ROOT = PACKAGE_ROOT.parent
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
        paths = [manifest["catalog"]["path"], *(source["path"] for source in manifest["sources"]), *(entry["path"] for entry in manifest["w0_inputs"])]
        paths.append("AutoResearch新流程/rules/manifest.json")
        for relative in paths:
            destination = self.root / relative
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
        store = TaskStore(self.task_root, repository_root=self.root)
        original = store.initialize(registry, "practice-001")
        source = self.root / registry.manifest["sources"][0]["path"]
        source.write_text(source.read_text(encoding="utf-8") + "\n测试用漂移\n", encoding="utf-8")
        result = store.check()
        self.assertTrue(any(issue["code"] == "SOURCE_DRIFT" for issue in result["issues"]))
        self.assertEqual(json.loads(store.state_path.read_text(encoding="utf-8"))["rules_lock"], original["rules_lock"])

    def test_upgrade_preview_does_not_write_and_apply_invalidates_dependents(self) -> None:
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=self.root)
        store.initialize(registry, "practice-001")
        state = json.loads(store.state_path.read_text(encoding="utf-8"))
        state["current_stage"] = None
        for item in state["stages"].values():
            item["status"] = "passed"
            for substep in item["substeps"].values():
                substep["status"] = "passed"
        _write_json(store.state_path, state)
        old_bytes = store.state_path.read_bytes()

        catalog_path = self.root / "AutoResearch新流程" / "rules" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        changed_rule = next(rule for rule in catalog["rules"] if rule["id"] == "AR-049")
        changed_rule["statement"] += "（升级测试）"
        _write_json(catalog_path, catalog)
        manifest_path = self.root / "AutoResearch新流程" / "rules" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["catalog"]["sha256"] = _sha256(catalog_path)
        _write_json(manifest_path, manifest)
        upgraded_registry = Registry(self.root / "AutoResearch新流程")

        preview = store.upgrade(upgraded_registry, apply=False)
        self.assertFalse(preview["applied"])
        self.assertIn("AR-049", preview["changed_rules"])
        self.assertEqual(preview["affected_stages"], [2, 3, 4, 5, 6])
        self.assertEqual(store.state_path.read_bytes(), old_bytes)

        result = store.upgrade(upgraded_registry, apply=True)
        self.assertTrue(result["applied"])
        updated = json.loads(store.state_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["current_stage"], "2")
        self.assertEqual(updated["stages"]["1"]["status"], "passed")
        self.assertTrue(all(updated["stages"][str(number)]["status"] == "needs_recheck" for number in range(2, 7)))
        self.assertTrue(all(
            substep["status"] == "needs_recheck"
            for number in range(2, 7)
            for substep in updated["stages"][str(number)]["substeps"].values()
        ))
        self.assertEqual(len(updated["history"]), 1)
        self.assertEqual(updated["history"][0]["previous_lock"]["catalog_sha256"], state["rules_lock"]["catalog_sha256"])
        self.assertEqual(store.check()["issues"], [])

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

    def test_removed_rule_uses_previous_lock_for_invalidation(self) -> None:
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=self.root)
        store.initialize(registry, "practice-001")
        catalog_path = self.root / "AutoResearch新流程" / "rules" / "catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        catalog["rules"] = [rule for rule in catalog["rules"] if rule["id"] != "AR-049"]
        for notice in catalog.get("workflow_notices", []):
            notice["affected_rule_ids"] = [rule for rule in notice["affected_rule_ids"] if rule != "AR-049"]
        catalog["rule_count"] = len(catalog["rules"])
        _write_json(catalog_path, catalog)
        manifest_path = self.root / "AutoResearch新流程" / "rules" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["catalog"]["sha256"] = _sha256(catalog_path)
        _write_json(manifest_path, manifest)
        plan = store.plan_upgrade(Registry(self.root / "AutoResearch新流程"))
        self.assertIn("AR-049", plan["changed_rules"])
        self.assertEqual(plan["affected_stages"], [2, 3, 4, 5, 6])

    def test_changed_qa_reference_only_invalidates_related_rules(self) -> None:
        registry = self._copied_registry()
        store = TaskStore(self.task_root, repository_root=self.root)
        store.initialize(registry, "practice-001")
        manifest_path = self.root / "AutoResearch新流程" / "rules" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        source = next(item for item in manifest["sources"] if item["id"] == "harbor_harness")
        source_path = self.root / source["path"]
        source_path.write_text(source_path.read_text(encoding="utf-8") + "\n测试用来源变化\n", encoding="utf-8")
        source["sha256"] = _sha256(source_path)
        _write_json(manifest_path, manifest)
        plan = store.plan_upgrade(Registry(self.root / "AutoResearch新流程"))
        self.assertIn("AR-034", plan["changed_rules"])
        self.assertNotIn("AR-001", plan["changed_rules"])

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
