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
        refs = [manifest["catalog"], *manifest["sources"], *manifest["bundled_files"],
                {"path": "rules/manifest.json"}]
        for ref in refs:
            relative = Path(ref["path"])
            if relative.parts[0] == "AutoResearch新流程设计":
                continue
            target = self.flow / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FLOW / relative, target)
        self.task = self.root / "new-task"
        self.task.mkdir()

    def test_initialize_without_design_and_reject_bundled_asset_tampering(self):
        registry = Registry(self.flow)
        self.assertFalse((self.root / "AutoResearch新流程设计").exists())
        self.assertEqual(registry.check_sources(), [])
        store = TaskStore(self.task, repository_root=self.flow)
        state = store.initialize(registry, "decoupled-smoke")
        self.assertEqual(state["current_stage"], "1")
        self.assertEqual(store.check()["issues"], [])
        asset = self.flow / next(r["path"] for r in registry.manifest["bundled_files"]
                                  if r["path"].endswith(".zip"))
        asset.write_bytes(asset.read_bytes() + b"synthetic drift")
        issues = registry.check_sources()
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["code"], "SOURCE_DRIFT")

    def test_source_collection_keeps_pilot_code_but_excludes_generated_and_secrets(self):
        module = tool("release_check")
        fixture = self.root / "source-fixture"
        include = {"cli.py", "README.md", "AGENTS.md", ".gitignore", ".gitattributes",
                   "docs/stages.md", "docs/interfaces/runtime.md",
                   "skills/autoresearch-workflow/SKILL.md",
                   "tests/test_example.py", "pilots/cpu/probe.py",
                   "model_profiles/codex.example.toml", "model_profiles/seed.example.toml"}
        exclude = {".git/config.json", ".ruff_cache/report.json", "runtime/state.json",
                   ".autoresearch-flow/state.json", "pilots/cpu/runs/record.json",
                   "pilots/cpu/build/main.py", "model_profiles/auth.json",
                   "model_profiles/.env", "templates/credentials.json",
                   "autoresearch_flow/__pycache__/trace.json", "local/model_profiles/codex.toml",
                   "model_profiles/codex.toml", "model_profiles/my-private-profile.toml"}
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
            relative = p.relative_to(FLOW)
            self.assertNotIn("AutoResearch新流程设计", relative.parts)
            target = self.flow / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        self.assertFalse((self.root / "AutoResearch新流程设计").exists())
        self.assertFalse((self.flow / "pilots/pca_cpu/runs").exists())
        with patch.object(module, "ROOT", self.flow), patch.object(module, "FLOW", self.flow):
            module.check_documents(module.source_files())
        self.assertEqual(Registry(self.flow).check_sources(), [])

    def test_historical_provenance_is_not_a_runtime_dependency(self):
        registry = Registry(self.flow)
        self.assertNotIn("w0_inputs", registry.manifest)
        self.assertFalse((self.flow / "rules/provenance").exists())
        store = TaskStore(self.task, repository_root=self.flow)
        store.initialize(registry, "without-history")
        before = store.state_path.read_bytes()
        self.assertEqual(store.check()["issues"], [])
        self.assertEqual(store.state_path.read_bytes(), before)

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
            target = self.flow / p.relative_to(FLOW)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
        with patch.object(checker, "ROOT", self.flow), patch.object(checker, "FLOW", self.flow):
            paths = checker.payload_files()
        release = self.flow / "release"
        release.mkdir(exist_ok=True)
        manifest = {"schema_version": 2, "version": checker.FLOW_VERSION, "package_revision": "test",
                    "files": checker.source_snapshot(paths, self.flow)}
        manifest_path = release / "source_manifest.json"
        _atomic_json(manifest_path, manifest)
        report = {"schema_version": 2, "version": checker.FLOW_VERSION, "package_revision": "test",
                  "status": "contracts_passed", "release_ready": False,
                  "source_manifest_sha256": _sha256(manifest_path)}
        _atomic_json(release / "acceptance.json", report)
        with patch.object(packager, "ROOT", self.flow), patch.object(packager, "FLOW", self.flow):
            with self.assertRaisesRegex(RuntimeError, "not a ready record"):
                packager._payload()
            payload = packager._payload(preview=True)
            self.assertFalse(any("AutoResearch新流程设计/" in p for p in payload))
            self.assertIn(".gitattributes", payload)
            entry = self.flow/'cli.py'
            old_mode = entry.stat().st_mode & 0o777
            entry.chmod(old_mode ^ 0o100)
            with self.assertRaisesRegex(RuntimeError, "manifest.*(stale|drift)"):
                packager._payload(preview=True)
            entry.chmod(old_mode)
            # Current inputs must match the checked manifest, even in preview.
            (self.flow / "autoresearch_flow/added_after_check.py").write_text("# changed\n")
            with self.assertRaisesRegex(RuntimeError, "manifest.*(stale|drift)"):
                packager._payload(preview=True)


if __name__ == "__main__":
    unittest.main()
