"""LP-7: new-task entry points do not lead users into the retired state ledger."""
import subprocess
import sys
import unittest
from pathlib import Path

FLOW = Path(__file__).resolve().parents[1]


class Lp7EntryTests(unittest.TestCase):
    def test_default_help_exposes_stateless_capabilities_only(self):
        result = subprocess.run(
            [sys.executable, str(FLOW / "cli.py"), "--help"],
            cwd=FLOW, capture_output=True, text=True, check=True,
        )
        help_text = result.stdout
        for capability in ("materials", "package", "harbor", "runtime", "experiment"):
            self.assertIn(capability, help_text)
        for retired in ("task", "stage", "delivery"):
            self.assertNotRegex(help_text, rf"(?m)^\s+{retired}\s")

    def test_legacy_parser_routes_remain_available_without_default_guidance(self):
        result = subprocess.run(
            [sys.executable, str(FLOW / "cli.py"), "--help"],
            cwd=FLOW, capture_output=True, text=True, check=True,
        )
        self.assertNotIn("旧账本接口", result.stdout)
        self.assertNotIn("状态账本", result.stdout)
        cli_source = (FLOW / "cli.py").read_text()
        self.assertIn('commands.add_parser("task", help=argparse.SUPPRESS', cli_source)
        self.assertIn('commands.add_parser("stage", help=argparse.SUPPRESS', cli_source)

        experiment = subprocess.run(
            [sys.executable, str(FLOW / "cli.py"), "experiment", "--help"],
            cwd=FLOW, capture_output=True, text=True, check=True,
        ).stdout
        self.assertIn("{run,summarize}", experiment)
        self.assertNotIn("baseline-check", experiment)

    def test_release_smoke_no_longer_initializes_legacy_state(self):
        source = (FLOW / "tools/release_check.py").read_text()
        self.assertNotIn('["task", "init"', source)
        self.assertNotIn('["stage", "status"', source)
        self.assertIn('"fresh_cli_capabilities": True', source)

    def test_default_docs_do_not_start_with_retired_state_commands(self):
        readme = (FLOW / "README.md").read_text()
        troubleshooting = (FLOW / "docs/troubleshooting.md").read_text()
        self.assertNotIn("Codex 底座待后续工作项", readme)
        self.assertNotIn("其他旧命令尚未全部解耦", readme)
        self.assertNotIn("先运行 `task check` 与 `stage status`", troubleshooting)
        self.assertIn("runtime status", troubleshooting)


if __name__ == "__main__":
    unittest.main()
