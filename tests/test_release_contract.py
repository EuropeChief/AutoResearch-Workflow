"""Release regressions. No model, Docker or credentials required."""
import json
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

    def test_release_requires_explicit_evidence_before_running_checks(self):
        flow = Path(__file__).resolve().parents[1]
        result = subprocess.run([sys.executable, str(flow/'tools/release_check.py'), '--release'],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--evidence-manifest', result.stderr)
        self.assertNotIn('Ran ', result.stderr)


if __name__ == "__main__":
    unittest.main()
