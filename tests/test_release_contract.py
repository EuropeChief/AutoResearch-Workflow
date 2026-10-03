"""Release regressions. No model, Docker or credentials required."""
import json
import importlib.util
from unittest.mock import patch
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoresearch_flow.runtime import BOUNDARY_PROBE, model_config


class ReleaseContracts(unittest.TestCase):
    def test_login_credentials_denied_to_agent_tools(self):
        config = model_config({"model": "synthetic", "reasoning_effort": "high",
                               "auth_ref": {"kind": "codex_login"}})
        filesystem = tomllib.loads(config)["permissions"]["autoresearch"]["filesystem"]
        self.assertEqual(filesystem.get("/codex/auth.json"), "deny")

    def test_writable_directory_is_not_mistaken_for_readonly(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", BOUNDARY_PROBE,
                                     json.dumps({"readable": [], "readonly": [directory],
                                                 "unreadable": []})],
                                    capture_output=True, text=True, check=False)
            issues = json.loads(result.stdout)["issues"]
            self.assertIn("unexpected write access: " + directory, issues)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_prior_live_reuse_checks_runtime_and_original_evidence(self):
        flow = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("release_check", flow / "tools/release_check.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            copied = root / "flow"
            for relative, data in {
                "autoresearch_flow/runtime.py": "# synthetic runtime",
                "model_profiles/seed.toml": 'model="synthetic"',
                "templates/agent-prompt.zh.md": "synthetic prompt",
                "raw-transfer.json": "{}",
                "raw-state.json": "{}",
                "raw-trajectory.jsonl": "{}"
            }.items():
                p = copied / relative
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(data)
            def ref(relative):
                p = copied / relative
                return {"path": str(p.relative_to(root)), "sha256": module._sha256(p)}
            evidence = {k: ref(v) for k, v in {
                "harbor_transfer_report": "raw-transfer.json", "seed_state": "raw-state.json",
                "seed_trajectory": "raw-trajectory.jsonl"}.items()}
            release = copied / "release"
            release.mkdir()
            (release / "source_manifest.json").write_text(json.dumps({"files": [
                ref(p) for p in ("autoresearch_flow/runtime.py", "model_profiles/seed.toml",
                                 "templates/agent-prompt.zh.md")]}))
            (release / "acceptance.json").write_text(json.dumps({
                "release_ready": True, "version": module.FLOW_VERSION, "at": "synthetic-date",
                "bounded_live_evidence": evidence}))
            with patch.object(module, "ROOT", root), patch.object(module, "FLOW", copied):
                result = module.prior_live_evidence()
                self.assertFalse(result["reuse"]["new_live_run"])
                runtime = copied / "autoresearch_flow/runtime.py"
                runtime.write_text("# changed runtime")
                with self.assertRaises(AssertionError): module.prior_live_evidence()
                runtime.write_text("# synthetic runtime")
                (copied / "raw-state.json").write_text('{"changed": true}')
                with self.assertRaises(AssertionError): module.prior_live_evidence()


if __name__ == "__main__":
    unittest.main()
