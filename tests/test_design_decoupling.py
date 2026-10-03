"""运行包不依赖设计工作区；不调用 Docker、模型或真实题目。"""
import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FLOW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import Registry, TaskStore, _atomic_json, _sha256


def tool(name):
    spec = importlib.util.spec_from_file_location(name, FLOW / f"tools/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DesignDecouplingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ar-decoupled-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = self.root / FLOW.name
        manifest = json.loads((FLOW / "rules/manifest.json").read_text())
        refs = [manifest["catalog"], *manifest["sources"], *manifest["w0_inputs"],
                {"path": f"{FLOW.name}/rules/manifest.json"}]
        for ref in refs:
            relative = Path(ref["path"])
            if relative.parts[0] == "AutoResearch新流程设计":
                continue
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FLOW.parent / relative, target)
        self.task = self.root / "new-task"
        self.task.mkdir()

    def test_initialize_without_design_and_reject_provenance_tampering(self):
        registry = Registry(self.flow)
        self.assertFalse((self.root / "AutoResearch新流程设计").exists())
        self.assertEqual(registry.check_sources(), [])
        store = TaskStore(self.task, repository_root=self.root)
        state = store.initialize(registry, "decoupled-smoke")
        self.assertEqual(state["current_stage"], "1")
        self.assertEqual(store.check()["issues"], [])
        provenance = self.flow / "rules/provenance/PCA_RULE_ALIGNMENT.md"
        self.assertEqual(_sha256(provenance),
                         "0d912ce79951afe0bcda85688ea1aad69b1be8da935b9cd8d9dc78a383455609")
        provenance.write_text(provenance.read_text() + "\nsynthetic drift\n")
        issues = registry.check_sources()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "SOURCE_DRIFT")

    def test_source_collection_keeps_pilot_code_but_excludes_generated_and_secrets(self):
        module = tool("release_check")
        fixture = self.root / "source-fixture"
        include = {"cli.py", "README.md", ".gitignore", ".gitattributes",
                   "tests/test_example.py", "pilots/cpu/probe.py"}
        exclude = {".git/config.json", ".ruff_cache/report.json", "runtime/state.json",
                   ".autoresearch-flow/state.json", "pilots/cpu/runs/record.json",
                   "pilots/cpu/build/main.py", "model_profiles/auth.json",
                   "model_profiles/.env", "templates/credentials.json",
                   "autoresearch_flow/__pycache__/trace.json"}
        for relative in include | exclude:
            p = fixture / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("{}")
        with patch.object(module, "FLOW", fixture):
            actual = {str(p.relative_to(fixture)) for p in module.source_files()}
        self.assertEqual(actual, include)

    def test_payload_contains_no_design_directory_and_is_relocatable(self):
        module = tool("release_check")
        files = module.payload_files() + module.release_files()
        for p in files:
            relative = p.relative_to(FLOW.parent)
            self.assertNotIn("AutoResearch新流程设计", relative.parts)
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        self.assertFalse((self.root / "AutoResearch新流程设计").exists())
        self.assertFalse((self.flow / "pilots/pca_cpu/runs").exists())
        with patch.object(module, "ROOT", self.root), patch.object(module, "FLOW", self.flow):
            module.check_documents(module.source_files())
        self.assertEqual(Registry(self.flow).check_sources(), [])

    def test_path_only_upgrade_is_explicit_and_preserves_passed_stages(self):
        manifest_path = self.flow / "rules/manifest.json"
        current_bytes = manifest_path.read_bytes()
        current = json.loads(current_bytes)
        old = copy.deepcopy(current)
        provenance_ref = next(r for r in old["w0_inputs"]
                              if r["path"].endswith("/PCA_RULE_ALIGNMENT.md"))
        current_path = self.root / provenance_ref["path"]
        provenance_ref["path"] = "AutoResearch新流程设计/PCA_RULE_ALIGNMENT.md"
        old_path = self.root / provenance_ref["path"]
        old_path.parent.mkdir()
        shutil.copyfile(current_path, old_path)
        old.pop("package_revision", None)
        _atomic_json(manifest_path, old)
        store = TaskStore(self.task, repository_root=self.root)
        before = store.initialize(Registry(self.flow), "path-only")
        before["stages"]["1"]["status"] = "passed"
        for step in before["stages"]["1"]["substeps"].values():
            step["status"] = "passed"
        before["current_stage"] = "2"
        _atomic_json(store.state_path, before)
        original_state_bytes = store.state_path.read_bytes()
        manifest_path.write_bytes(current_bytes)
        old_path.unlink()
        old_path.parent.rmdir()
        registry = Registry(self.flow)
        self.assertEqual(store.check()["issues"][0]["code"], "SOURCE_DRIFT")
        preview = store.upgrade(registry, apply=False)
        self.assertTrue(preview["changed"])
        self.assertFalse(preview["applied"])
        self.assertEqual(preview["changed_rules"], [])
        self.assertEqual(preview["affected_stages"], [])
        self.assertFalse(preview["policy_changed"])
        self.assertEqual(store.state_path.read_bytes(), original_state_bytes)
        store.upgrade(registry, apply=True)
        after = json.loads(store.state_path.read_text())
        self.assertEqual(after["stages"], before["stages"])
        self.assertEqual(after["workflow_policy"], before["workflow_policy"])
        self.assertEqual(after["current_stage"], "2")
        self.assertEqual(after["history"][-1]["previous_lock"], before["rules_lock"])
        self.assertEqual(store.check()["issues"], [])

    def test_replacing_receipts_preserves_previous_pair_without_rewriting_it(self):
        module = tool("release_check")
        release = self.root / "receipts"
        release.mkdir()
        original = {"acceptance.json": b'{"old": "acceptance"}\n',
                    "source_manifest.json": b'{"old": "manifest"}\n'}
        for name, data in original.items():
            (release / name).write_bytes(data)
        module.preserve_receipts(release)
        module.preserve_receipts(release)
        histories = list((release / "history").iterdir())
        self.assertEqual(len(histories), 1)
        for name, data in original.items():
            self.assertEqual((histories[0] / name).read_bytes(), data)
            (release / name).write_text('{}\n')
        module.preserve_receipts(release)
        self.assertEqual(len(list((release / "history").iterdir())), 2)
        for name, data in original.items():
            self.assertEqual((histories[0] / name).read_bytes(), data)

    def test_preview_archive_rejects_unready_release_and_stale_manifest(self):
        checker = tool("release_check")
        packager = tool("build_migration")
        for p in checker.payload_files():
            target = self.root / p.relative_to(FLOW.parent)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        with patch.object(checker, "ROOT", self.root), patch.object(checker, "FLOW", self.flow):
            paths = checker.payload_files()
        release = self.flow / "release"
        release.mkdir(exist_ok=True)
        manifest = {"version": checker.FLOW_VERSION, "package_revision": "test",
                    "files": [{"path": str(p.relative_to(self.root)), "sha256": _sha256(p)}
                              for p in paths]}
        manifest_path = release / "source_manifest.json"
        _atomic_json(manifest_path, manifest)
        report = {"version": checker.FLOW_VERSION, "package_revision": "test",
                  "status": "contracts_passed", "release_ready": False,
                  "source_manifest_sha256": _sha256(manifest_path)}
        _atomic_json(release / "acceptance.json", report)
        with patch.object(packager, "ROOT", self.root), patch.object(packager, "FLOW", self.flow):
            with self.assertRaisesRegex(RuntimeError, "not a ready record"):
                packager._payload()
            payload = packager._payload(preview=True)
            self.assertFalse(any("AutoResearch新流程设计/" in p for p in payload))
            self.assertIn(f"{FLOW.name}/.gitattributes", payload)
            # Current inputs must match the checked manifest, even in preview.
            (self.flow / "autoresearch_flow/added_after_check.py").write_text("# changed\n")
            with self.assertRaisesRegex(RuntimeError, "manifest.*(stale|drift)"):
                packager._payload(preview=True)


if __name__ == "__main__":
    unittest.main()
