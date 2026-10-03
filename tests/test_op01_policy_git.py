"""OP-0/1 contracts at task/CLI boundaries; temporary repositories, no model calls."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))
from autoresearch_flow.core import Registry, TaskStore
from autoresearch_flow.stages import StageFlow


class PolicyGitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-op01-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.task = self.root / "task"
        self.task.mkdir()
        self.store = TaskStore(self.task)
        self.store.initialize(Registry(), "policy-git-test")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")

    def cli(self, *args, expected=0):
        p = subprocess.run([sys.executable, str(PACKAGE_ROOT / "cli.py"), "--format", "json",
                            "task", *args, "--task-root", str(self.task)],
                           env=self.env, text=True, capture_output=True, check=False)
        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
        return json.loads(p.stdout)

    def git(self, *args, cwd=None):
        result = subprocess.run(["git", "-C", str(cwd or self.task), *args],
                                env=self.env, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def identity(self, cwd=None):
        self.git("config", "user.name", "Synthetic Test", cwd=cwd)
        self.git("config", "user.email", "synthetic@example.invalid", cwd=cwd)

    def preview_file(self, *paths):
        args = []
        for path in paths:
            args += ["--path", path]
        preview = self.cli("git-preview", *args)
        target = self.root / "preview.json"
        target.write_text(json.dumps(preview))
        return target, preview

    def test_new_repository_requires_confirmation_and_real_initial_commit(self):
        (self.task / "README.md").write_text("task sources\n")
        plan = self.cli("git-status")
        self.assertEqual(plan["mode"], "new")
        self.assertFalse((self.task / ".git").exists())
        self.cli("git-setup", "--repository-root", str(self.task), expected=2)
        self.assertFalse((self.task / ".git").exists())
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.assertFalse(self.cli("git-status")["ready"])
        self.identity()
        manifest, plan = self.preview_file(".")
        self.assertIn("README.md", [f["path"] for f in plan["files"]])
        self.cli("git-checkpoint", "--file", str(manifest), "--message", "initial", expected=2)
        result = self.cli("git-checkpoint", "--file", str(manifest), "--message", "initial", "--confirm-commit")
        self.assertEqual(result["commit"], self.git("rev-parse", "HEAD"))
        self.assertTrue(self.cli("git-status")["ready"])
        self.assertIn("README.md", self.git("ls-tree", "-r", "--name-only", "HEAD").splitlines())

    def test_new_policy_is_visible_and_legacy_read_is_nonmutating(self):
        response = self.cli("policy")
        policy = response["workflow_policy"]
        self.assertEqual(policy["git_required"], True)
        self.assertEqual(policy["duration_policy"],
                         {"mode": "default_10h", "minimum_effective_seconds": 36000})
        self.assertEqual(policy["ui_mode"], "native_tui")
        self.assertNotIn("pending_implementation", response)
        self.assertEqual(response["delivery_checkpoints"],
                         ["qa_verified", "archives_verified", "form_ready"])
        data = json.loads(self.store.state_path.read_text())
        del data["workflow_policy"]
        self.store.state_path.write_text(json.dumps(data))
        before = self.store.state_path.read_bytes()
        legacy = self.cli("policy", expected=2)
        self.assertEqual(legacy["issues"][0]["code"], "INVALID_POLICY")
        self.assertEqual(self.store.state_path.read_bytes(), before)

    def test_upgrade_command_is_unavailable_and_preserves_state(self):
        before = self.store.state_path.read_bytes()
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        result = subprocess.run([sys.executable, str(cli), "task", "upgrade",
            "--task-root", str(self.task)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)
        self.assertEqual(self.store.state_path.read_bytes(), before)

    def test_unsupported_runtime_policy_is_rejected_instead_of_silently_ignored(self):
        data = json.loads(self.store.state_path.read_text())
        data["workflow_policy"]["ui_mode"] = "tui"
        self.store.state_path.write_text(json.dumps(data))
        result = self.cli("check", expected=2)
        self.assertEqual(result["issues"][0]["code"], "POLICY_NOT_IMPLEMENTED")

    def test_previous_exec_policy_is_rejected_without_rewriting_evidence(self):
        data = json.loads(self.store.state_path.read_text())
        data["workflow_policy"]["revision"] = "2026-10-03.public"
        data["workflow_policy"]["ui_mode"] = "exec_json"
        self.store.state_path.write_text(json.dumps(data))
        before = self.store.state_path.read_bytes()
        result = self.cli("check", expected=2)
        self.assertEqual(result["issues"][0]["code"], "INVALID_POLICY")
        self.assertEqual(self.store.state_path.read_bytes(), before)

    def test_stage_one_requires_git_but_legacy_does_not_acquire_a_new_gate(self):
        proof = self.task / "design.md"
        proof.write_text("input evidence")
        flow = StageFlow(self.task)
        spec = {"step": "1.1", "status": "passed", "reviewer": "synthetic",
                "summary": "test only", "evidence": flow.reference(["design.md"])["evidence"], "checks": {}}
        from autoresearch_flow.core import FlowError
        with self.assertRaises(FlowError) as caught:
            flow.record(spec)
        self.assertEqual(caught.exception.code, "GIT_NOT_READY")
        data = json.loads(self.store.state_path.read_text())
        del data["workflow_policy"]
        self.store.state_path.write_text(json.dumps(data))
        before = self.store.state_path.read_bytes()
        with self.assertRaises(FlowError) as caught:
            flow.record(spec)
        self.assertEqual(caught.exception.code, "INVALID_POLICY")
        self.assertEqual(self.store.state_path.read_bytes(), before)

    def test_parent_repository_preserves_unrelated_staged_and_unstaged_work(self):
        self.git("init", "--quiet", cwd=self.root)
        self.identity(self.root)
        outside = self.root / "outside.txt"
        outside.write_text("original\n")
        self.git("add", "outside.txt", cwd=self.root)
        self.git("commit", "-qm", "existing", cwd=self.root)
        outside.write_text("staged user work\n")
        self.git("add", "outside.txt", cwd=self.root)
        outside.write_text("unstaged user work\n")
        staged_before = self.git("diff", "--cached", cwd=self.root)
        (self.task / "source.py").write_text("print('research')\n")
        self.assertEqual(self.cli("git-status")["mode"], "reuse_parent")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git", expected=2)
        self.cli("git-setup", "--repository-root", str(self.root), "--confirm-git")
        plan, _ = self.preview_file(".")
        self.cli("git-checkpoint", "--file", str(plan), "--message", "task only", "--confirm-commit")
        self.assertFalse((self.task / ".git").exists())
        self.assertEqual(staged_before, self.git("diff", "--cached", cwd=self.root))
        self.assertEqual(outside.read_text(), "unstaged user work\n")
        self.assertEqual(self.git("show", "HEAD:outside.txt", cwd=self.root), "original")
        paths = self.git("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", cwd=self.root).splitlines()
        self.assertTrue(paths and all(p.startswith("task/") for p in paths))

    def test_identity_and_preview_drift_do_not_claim_ready(self):
        source = self.task / "source.py"
        source.write_text("print(1)\n")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        # Old Git versions may not support GIT_CONFIG_GLOBAL; blank local values
        # simulate missing identity without reading/changing the real global file.
        self.git("config", "user.name", "")
        self.git("config", "user.email", "")
        plan, _ = self.preview_file("source.py")
        result = self.cli("git-checkpoint", "--file", str(plan), "--message", "initial", "--confirm-commit", expected=2)
        self.assertEqual(result["issues"][0]["code"], "GIT_IDENTITY_REQUIRED")
        self.assertFalse(self.cli("git-status")["ready"])
        self.identity()
        source.write_text("print(2)\n")
        result = self.cli("git-checkpoint", "--file", str(plan), "--message", "stale", "--confirm-commit", expected=2)
        self.assertEqual(result["issues"][0]["code"], "STALE_GIT_PLAN")
        self.assertEqual(self.git("diff", "--cached"), "")

    def test_ignore_merge_nested_repository_and_secrets_are_excluded(self):
        ignore = self.task / ".gitignore"
        ignore.write_text("# user patterns\ncustom-cache/\n")
        for rel in ["auth/gpt/auth.json", "data/train.dat", "model.pt", "trace.log", ".env", "notes.txt"]:
            p = self.task / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("private" if rel != "notes.txt" else "sk-" + "x" * 25)
        nested = self.task / "official"
        nested.mkdir()
        self.git("init", "--quiet", cwd=nested)
        (nested / "implementation.py").write_text("# upstream")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.assertTrue(ignore.read_text().startswith("# user patterns\ncustom-cache/\n"))
        self.assertEqual(ignore.read_text().count("# AutoResearch task hygiene"), 1)
        _, preview = self.preview_file(".")
        files = {f["path"] for f in preview["files"]}
        self.assertEqual(files, {".gitignore", ".autoresearch-flow/state.json"})
        reasons = {f["path"]: f["reason"] for f in preview["excluded"]}
        self.assertEqual(reasons["official"], "nested_repository")
        self.assertEqual(reasons["notes.txt"], "possible_secret")
        self.assertTrue((nested / ".git").exists())

    def test_selected_partial_staging_is_not_overwritten(self):
        (self.task / "source.py").write_text("print(1)\n")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        self.git("add", "source.py")
        (self.task / "source.py").write_text("print(2)\n")
        before = self.git("diff", "--cached")
        plan, _ = self.preview_file("source.py")
        result = self.cli("git-checkpoint", "--file", str(plan), "--message", "partial", "--confirm-commit", expected=2)
        self.assertEqual(result["issues"][0]["code"], "GIT_STAGED_OVERLAP")
        self.assertEqual(self.git("diff", "--cached"), before)
        self.assertEqual((self.task / "source.py").read_text(), "print(2)\n")

    def test_checkpoint_includes_removed_source_files(self):
        source = self.task / "obsolete.py"
        source.write_text("# old method")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        plan, _ = self.preview_file(".")
        self.cli("git-checkpoint", "--file", str(plan), "--message", "before", "--confirm-commit")
        source.unlink()
        plan, preview = self.preview_file(".")
        removed = [f for f in preview["files"] if f["path"] == "obsolete.py"]
        self.assertEqual(len(removed), 1)
        self.assertTrue(removed[0]["deleted"])
        self.cli("git-checkpoint", "--file", str(plan), "--message", "remove obsolete", "--confirm-commit")
        self.assertNotIn("obsolete.py", self.git("ls-tree", "-r", "--name-only", "HEAD").splitlines())

    def test_symlink_alias_cannot_bypass_private_directory_exclusion(self):
        secret = self.task / "auth"
        secret.mkdir()
        (secret / "opaque.json").write_text('{"token":"opaque-value"}')
        (self.task / "alias").symlink_to(secret, target_is_directory=True)
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        _, plan = self.preview_file("alias/opaque.json")
        self.assertEqual(plan["files"], [])
        self.assertEqual(plan["excluded"][0]["reason"], "symlink")

    def test_setup_rejects_symlink_ignore_without_touching_target(self):
        target = self.root / "outside-ignore"
        target.write_text("keep\n")
        (self.task / ".gitignore").symlink_to(target)
        result = self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git", expected=2)
        self.assertEqual(result["issues"][0]["code"], "GIT_SCOPE")
        self.assertEqual(target.read_text(), "keep\n")
        self.assertFalse((self.task / ".git").exists())

    def test_chinese_filename_executable_mode_and_large_file_exclusion(self):
        script = self.task / "中文脚本.sh"
        script.write_text("#!/bin/sh\nexit 0\n")
        script.chmod(0o755)
        with (self.task / "large.unknown").open("wb") as stream:
            stream.truncate(11 * 1024 * 1024)
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        manifest, preview = self.preview_file(".")
        self.assertNotIn("large.unknown", [f["path"] for f in preview["files"]])
        self.cli("git-checkpoint", "--file", str(manifest), "--message", "中文源码", "--confirm-commit")
        self.assertTrue(self.git("ls-tree", "HEAD", "--", "中文脚本.sh").startswith("100755"))
        self.assertEqual(self.git("show", "HEAD:中文脚本.sh"), script.read_text().strip())

    def test_git_ignore_failure_does_not_mark_repository_configured(self):
        (self.task / ".gitignore").write_bytes(b"\xff")
        result = self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git", expected=2)
        self.assertEqual(result["issues"][0]["code"], "GIT_IGNORE_ENCODING")
        self.assertFalse(self.cli("git-status")["configured"])
        self.assertFalse((self.task / ".git").exists())

    def test_future_state_schema_is_rejected(self):
        data = json.loads(self.store.state_path.read_text())
        data["workflow_policy"]["schema_version"] = 99
        self.store.state_path.write_text(json.dumps(data))
        result = self.cli("policy", expected=2)
        self.assertEqual(result["issues"][0]["code"], "INVALID_POLICY")

    def test_invalid_policy_revision_is_a_structured_error(self):
        original = json.loads(self.store.state_path.read_text())
        for value in ([], {}, None):
            with self.subTest(value=value):
                data = dict(original)
                data["workflow_policy"] = dict(original["workflow_policy"], revision=value)
                self.store.state_path.write_text(json.dumps(data))
                self.assertEqual(self.cli("policy", expected=2)["issues"][0]["code"], "INVALID_POLICY")

    def test_missing_policy_does_not_rewrite_existing_step_history(self):
        data = json.loads(self.store.state_path.read_text())
        data.pop("workflow_policy")
        self.store.state_path.write_text(json.dumps(data))
        before = self.store.state_path.read_bytes()
        self.assertEqual(self.cli("check", expected=2)["issues"][0]["code"], "INVALID_POLICY")
        self.assertEqual(self.store.state_path.read_bytes(), before)

    def test_snapshot_preserves_mode_even_when_existing_repo_ignores_mode_changes(self):
        script = self.task / "script.sh"
        script.write_text("#!/bin/sh\nexit 0\n")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        manifest, _ = self.preview_file(".")
        self.cli("git-checkpoint", "--file", str(manifest), "--message", "before", "--confirm-commit")
        self.git("config", "core.filemode", "false")
        script.chmod(0o755)
        manifest, _ = self.preview_file("script.sh")
        self.cli("git-checkpoint", "--file", str(manifest), "--message", "mode", "--confirm-commit")
        self.assertTrue(self.git("ls-tree", "HEAD", "--", "script.sh").startswith("100755"))
        self.assertEqual(self.git("config", "--get", "core.filemode"), "false")

    def test_concurrent_worktree_edit_does_not_change_reviewed_commit(self):
        from unittest.mock import patch

        from autoresearch_flow.task_git import TaskGit
        source = self.task / "source.py"
        source.write_text("# reviewed\n")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        vcs = TaskGit(self.task)
        plan = vcs.preview(["source.py"])
        original_run = subprocess.run

        def concurrent_editor(command, **kwargs):
            result = original_run(command, **kwargs)
            if "hash-object" in command:
                source.write_text("# later user edit\n")
            return result

        with patch("subprocess.run", side_effect=concurrent_editor):
            checkpoint = vcs.checkpoint(plan, "reviewed snapshot", confirm=True)
        self.assertEqual(self.git("show", checkpoint["commit"] + ":source.py"), "# reviewed")
        self.assertEqual(source.read_text(), "# later user edit\n")
        self.assertIn("later user edit", self.git("diff", "--", "source.py"))

    def test_other_git_index_lock_is_not_removed(self):
        (self.task / "README.md").write_text("test")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        manifest, _ = self.preview_file(".")
        lock = self.task / ".git/index.lock"
        lock.write_text("other operation")
        result = self.cli("git-checkpoint", "--file", str(manifest), "--message", "busy", "--confirm-commit", expected=2)
        self.assertEqual(result["issues"][0]["code"], "GIT_INDEX_BUSY")
        self.assertEqual(lock.read_text(), "other operation")

    def test_pending_merge_is_not_advanced_or_cleaned_by_checkpoint(self):
        source = self.task / "source.py"
        source.write_text("# initial\n")
        self.cli("git-setup", "--repository-root", str(self.task), "--confirm-git")
        self.identity()
        plan, _ = self.preview_file(".")
        self.cli("git-checkpoint", "--file", str(plan), "--message", "initial", "--confirm-commit")
        branch = self.git("symbolic-ref", "--short", "HEAD")
        self.git("checkout", "-qb", "other")
        (self.task / "other.txt").write_text("merge input")
        self.git("add", "other.txt")
        self.git("commit", "-qm", "other commit")
        self.git("checkout", "-q", branch)
        self.git("merge", "--no-ff", "--no-commit", "other")
        source.write_text("# proposed checkpoint\n")
        head, staged = self.git("rev-parse", "HEAD"), self.git("diff", "--cached")
        merge = (self.task / ".git/MERGE_HEAD").read_bytes()
        plan, _ = self.preview_file("source.py")
        result = self.cli("git-checkpoint", "--file", str(plan), "--message", "wrong time", "--confirm-commit", expected=2)
        self.assertEqual(result["issues"][0]["code"], "GIT_OPERATION_IN_PROGRESS")
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(self.git("diff", "--cached"), staged)
        self.assertEqual((self.task / ".git/MERGE_HEAD").read_bytes(), merge)
        self.assertFalse(self.cli("git-status")["ready"])


if __name__ == "__main__":
    unittest.main()
