"""P1 无状态任务工作区合同；使用临时仓库，不接触真实题目。"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from autoresearch_flow.task_workspace import TaskWorkspace


class TaskWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-p1-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.previous_git_env = {
            key: os.environ.get(key) for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM", "HOME")
        }
        os.environ.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", HOME=str(self.root))
        self.addCleanup(self.restore_git_env)

    def restore_git_env(self):
        for key, value in self.previous_git_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def git(self, *args: str) -> str:
        result = subprocess.run(["git", "-C", str(self.root), *args], env=self.env,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def test_new_workspace_requires_explicit_init_and_writes_safe_ignore(self):
        workspace = TaskWorkspace(self.root)
        self.assertEqual(workspace.status()["mode"], "new")
        with self.assertRaisesRegex(Exception, "确认"):
            workspace.init_git()
        workspace.init_git(confirm=True)
        ignore = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("auth.json", ignore)
        self.assertIn("!/.autoresearch/decision-log.md", ignore)
        self.assertFalse((self.root / ".autoresearch-flow").exists())

    def test_preview_excludes_credentials_private_files_and_nested_repo(self):
        workspace = TaskWorkspace(self.root)
        workspace.init_git(confirm=True)
        (self.root / "instruction.md").write_text("public task\n", encoding="utf-8")
        (self.root / "auth.json").write_text('{"api_key":"sk-secret"}', encoding="utf-8")
        (self.root / "logs").mkdir()
        (self.root / "logs/run.log").write_text("runtime\n", encoding="utf-8")
        nested = self.root / "official"
        nested.mkdir()
        subprocess.run(["git", "init", "--quiet", "--template=", str(nested)], check=True, env=self.env)
        plan = workspace.preview(["."])
        selected = {row["path"] for row in plan["files"]}
        excluded = {row["path"]: row["reason"] for row in plan["excluded"]}
        self.assertIn("instruction.md", selected)
        self.assertNotIn("auth.json", selected)
        self.assertEqual(excluded["auth.json"], "credential_filename")
        self.assertEqual(excluded["logs/run.log"], "private_or_runtime_directory")
        self.assertEqual(excluded["official"], "nested_repository")

    def test_checkpoint_requires_identity_and_stale_plan_is_rejected(self):
        workspace = TaskWorkspace(self.root)
        workspace.init_git(confirm=True)
        (self.root / "instruction.md").write_text("v1\n", encoding="utf-8")
        plan = workspace.preview(["instruction.md"])
        with self.assertRaisesRegex(Exception, "user.name"):
            workspace.checkpoint(plan, "start", confirm=True)
        self.git("config", "user.name", "P1 Test")
        self.git("config", "user.email", "p1@example.invalid")
        (self.root / "instruction.md").write_text("v2\n", encoding="utf-8")
        with self.assertRaisesRegex(Exception, "重新预览"):
            workspace.checkpoint(plan, "stale", confirm=True)
        plan = workspace.preview(["instruction.md"])
        result = workspace.checkpoint(plan, "record research contract inputs", confirm=True)
        self.assertEqual(result["status"], "committed")
        self.assertTrue(self.git("log", "-1", "--format=%s").startswith("record research"))
        self.assertTrue((self.root / ".autoresearch/git-checkpoints.jsonl").is_file())

    def test_decision_log_returns_latest_gate_and_reports_missing_fields(self):
        path = self.root / ".autoresearch/decision-log.md"
        path.parent.mkdir()
        path.write_text(
            "## 2026-10-11T00:00:00Z — research_contract\n"
            "- status: approved\n- scope: surface\n- evidence: notes.md\n"
            "- approver: reviewer\n- limits: verify anchors\n"
            "## 2026-10-12T00:00:00Z — anchor_freeze\n"
            "- status: pending\n- scope: anchors\n",
            encoding="utf-8",
        )
        result = TaskWorkspace(self.root).read_decisions()
        self.assertEqual(result["latest"]["research_contract"]["status"], "approved")
        self.assertIn("缺字段", "\n".join(result["issues"]))

    def test_module_entry_is_in_runtime_payload(self):
        from tools import release_check
        paths = {path.relative_to(release_check.FLOW).as_posix() for path in release_check.payload_files()}
        self.assertIn("autoresearch_flow/task_workspace.py", paths)


if __name__ == "__main__":
    unittest.main()
