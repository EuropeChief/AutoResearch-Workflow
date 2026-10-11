"""轻量题目工作区预检、Git 检查点和阶段门决定记录。

不创建统一任务状态机，也不要求题目初始化 .autoresearch-flow。
"""

from __future__ import annotations

import hashlib
import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import FlowError, _require


GATES = {"research_contract", "anchor_freeze", "dual_track_launch"}
DECISION_STATUSES = {"approved", "pending", "waived", "rejected"}
CHECK_DECISIONS = {"exception"}
PRIVATE_PARTS = {
    ".git", ".codex", ".ssh", ".pi", "auth", "credentials", "secrets", "data",
    "datasets", "checkpoints", "weights", "models", "logs", "runtime", "deliverables",
    "archives", "__pycache__", ".venv", "venv", ".cache", "node_modules",
}
PRIVATE_SUFFIXES = {
    ".pt", ".pth", ".ckpt", ".safetensors", ".bin", ".npz", ".npy", ".pyc",
    ".pem", ".key", ".log", ".sock", ".zip", ".7z", ".rar", ".tar", ".gz",
}
SECRET_PATTERN = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bAKIA[A-Z0-9]{16}\b"
)
IGNORE_MARKER = "# AutoResearch task hygiene (P1); review before committing."
IGNORE_BLOCK = f"""{IGNORE_MARKER}
auth/
credentials/
secrets/
auth.json
*.auth.json
.env
.env.*
!.env.example
!.env.template
*.pem
*.key
.codex/
.ssh/
.pi/
data/
datasets/
checkpoints/
weights/
models/
logs/
runtime/
deliverables/
archives/
__pycache__/
.venv/
venv/
.cache/
node_modules/
*.pyc
*.pt
*.pth
*.ckpt
*.safetensors
*.bin
*.npz
*.npy
*.log
*.sock
*.zip
*.zip.*
*.7z
*.rar
*.tar
*.gz
/.autoresearch/*
!/.autoresearch/decision-log.md
!/.autoresearch/git-checkpoints.jsonl
# End AutoResearch task hygiene
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relative(root: Path, value: str) -> Path:
    path = Path(value)
    _require(
        isinstance(value, str) and value and not path.is_absolute() and ".." not in path.parts and "\\" not in value,
        "GIT_SCOPE", "只接受题目目录内的 POSIX 相对路径",
    )
    _require((root / path).resolve().is_relative_to(root), "GIT_SCOPE", "路径越出题目目录")
    return path


@dataclass(frozen=True)
class GitInfo:
    repository_root: Path | None
    mode: str
    scope: str
    head: str | None
    branch: str | None


class TaskWorkspace:
    """题目目录的无状态 Git/决定记录能力。"""

    def __init__(self, task_root: Path | str):
        root = Path(task_root).expanduser().resolve()
        _require(root.is_dir() and not root.is_symlink(), "TASK_ROOT_MISSING", f"题目目录不存在或是符号链接：{root}")
        self.root = root

    def _git(self, *args: str, check: bool = False) -> subprocess.CompletedProcess[bytes]:
        env = {
            key: value for key, value in os.environ.items()
            if not key.startswith("GIT_") or key in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}
        }
        env.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
        try:
            result = subprocess.run(
                ["git", "--literal-pathspecs", "-c", "core.hooksPath=/dev/null", "-C", str(self.root), *args],
                env=env, capture_output=True, timeout=60, check=False,
            )
        except FileNotFoundError as exc:
            raise FlowError("GIT_MISSING", "宿主缺少 git；安装后重试") from exc
        except subprocess.TimeoutExpired as exc:
            raise FlowError("GIT_TIMEOUT", "Git 命令超时；不标记检查点成功") from exc
        _require(not check or result.returncode == 0, "GIT_COMMAND_FAILED", f"Git 命令失败（exit={result.returncode}）")
        return result

    def git_info(self) -> GitInfo:
        probe = self._git("rev-parse", "--show-toplevel")
        if probe.returncode:
            marker = self.root / ".git"
            _require(not marker.exists() and not marker.is_symlink(), "GIT_REPOSITORY_UNREADABLE", "存在不可读取的 .git；先人工修复，不覆盖")
            return GitInfo(None, "new", ".", None, None)
        repository = Path(os.fsdecode(probe.stdout).strip()).resolve()
        _require(self.root.is_relative_to(repository), "GIT_SCOPE", "Git 根未包含题目目录")
        _require(not (repository / ".git").is_symlink(), "GIT_SCOPE", "Git 元数据目录不能是符号链接")
        head = self._git("rev-parse", "--verify", "HEAD").stdout.decode().strip() or None
        branch = self._git("symbolic-ref", "--short", "-q", "HEAD").stdout.decode().strip() or None
        mode = "reuse_task" if repository == self.root else "reuse_parent"
        return GitInfo(repository, mode, self.root.relative_to(repository).as_posix(), head, branch)

    def status(self) -> dict[str, Any]:
        info = self.git_info()
        dirty = False
        pending = None
        if info.repository_root:
            dirty = bool(self._git("status", "--porcelain=v1", "--untracked-files=all").stdout)
            for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer"):
                path = info.repository_root / ".git" / marker
                if path.exists() or path.is_symlink():
                    pending = marker
                    break
        ignore = self.root / ".gitignore"
        return {
            "status": "ok", "mode": info.mode, "repository_root": str(info.repository_root or self.root),
            "scope": info.scope, "head": info.head, "branch": info.branch, "tracked_dirty": dirty,
            "operation_in_progress": pending, "gitignore_present": ignore.is_file() and not ignore.is_symlink(),
            "decision_log": self.read_decisions(),
            "next_action": (
                "先人工处理未结束的 Git 操作，不代为 abort 或清理" if pending else
                "执行 init-git --confirm-git，再预览起始检查点" if info.repository_root is None else
                "审查 git-preview 输出并建立起始检查点" if not info.head else
                "按题面、环境、评分器和实验脚本的关键变更建立检查点"
            ),
        }

    def init_git(self, *, confirm: bool = False) -> dict[str, Any]:
        _require(confirm, "CONFIRMATION_REQUIRED", "审查 git-status 后明确确认并加入 --confirm-git")
        info = self.git_info()
        _require(info.repository_root is None, "GIT_ALREADY_CONFIGURED", "题目已在 Git 仓库中，直接使用现有仓库")
        self._git("init", "--quiet", "--template=", check=True)
        self._ensure_gitignore()
        return self.status()

    def _ensure_gitignore(self) -> dict[str, Any]:
        path = self.root / ".gitignore"
        _require(not path.is_symlink() and (not path.exists() or path.is_file()), "GIT_SCOPE", ".gitignore 必须是普通文件")
        original = path.read_text(encoding="utf-8") if path.exists() else ""
        if IGNORE_MARKER not in original:
            path.write_text(original + ("\n" if original and not original.endswith("\n") else "") + IGNORE_BLOCK, encoding="utf-8")
            return {"changed": True, "path": ".gitignore"}
        return {"changed": False, "path": ".gitignore"}

    def _reason(self, relative: str) -> str | None:
        path = Path(relative)
        if any(part.lower() in PRIVATE_PARTS for part in path.parts):
            return "private_or_runtime_directory"
        if path.name.lower() in {"auth.json", "credentials.json"} or path.name.lower().endswith(".auth.json"):
            return "credential_filename"
        if path.name.startswith(".env") and path.name not in {".env.example", ".env.template"}:
            return "credential_filename"
        if path.suffix.lower() in PRIVATE_SUFFIXES or ".zip." in path.name:
            return "private_or_large_artifact"
        return None

    def _walk(self, path: Path) -> tuple[set[str], dict[str, str]]:
        files: set[str] = set()
        excluded: dict[str, str] = {}
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(self.root).as_posix()
            reason = "symlink" if path.is_symlink() else self._reason(relative)
            if reason:
                excluded[relative] = reason
            else:
                files.add(relative)
            return files, excluded
        for directory, dirs, names in os.walk(path, followlinks=False):
            kept_dirs = []
            for name in dirs:
                candidate_dir = Path(directory) / name
                if name == ".git":
                    continue
                if (candidate_dir / ".git").exists() or (candidate_dir / ".git").is_symlink():
                    excluded[candidate_dir.relative_to(self.root).as_posix()] = "nested_repository"
                    continue
                kept_dirs.append(name)
            dirs[:] = kept_dirs
            for name in names:
                candidate = Path(directory) / name
                relative = candidate.relative_to(self.root).as_posix()
                reason = "symlink" if candidate.is_symlink() else self._reason(relative)
                if reason:
                    excluded[relative] = reason
                else:
                    files.add(relative)
        return files, excluded

    def preview(self, paths: list[str]) -> dict[str, Any]:
        info = self.git_info()
        _require(info.repository_root is not None, "GIT_NOT_CONFIGURED", "先执行 git-status 和 init-git")
        _require(paths and all(isinstance(value, str) and value for value in paths), "GIT_PATHS_REQUIRED", "至少给出一个 --path")
        selected: set[str] = set()
        excluded: dict[str, str] = {}
        for value in paths:
            relative = _relative(self.root, value)
            target = self.root / relative
            _require(target.exists() or target.is_symlink(), "GIT_PATH_MISSING", f"路径不存在：{value}")
            files, blocked = self._walk(target)
            selected.update(files)
            excluded.update(blocked)
        tracked = {
            os.fsdecode(value) for value in self._git("ls-files", "-z", "--", *paths).stdout.split(b"\0") if value
        }
        selected.update(tracked)
        rows: list[dict[str, Any]] = []
        for relative in sorted(selected):
            target = self.root / relative
            reason = self._reason(relative)
            if reason:
                excluded[relative] = reason
                continue
            if not target.exists() and relative in tracked:
                rows.append({"path": relative, "deleted": True, "sha256": None, "size": 0})
                continue
            if target.is_symlink() or not target.is_file():
                excluded[relative] = "not_regular_file"
                continue
            if self._git("check-ignore", "--quiet", "--", relative).returncode == 0:
                excluded[relative] = "gitignore"
                continue
            content = target.read_bytes()
            if SECRET_PATTERN.search(content):
                excluded[relative] = "possible_secret"
                continue
            rows.append({
                "path": relative, "deleted": False, "sha256": hashlib.sha256(content).hexdigest(),
                "size": target.stat().st_size, "executable": bool(target.stat().st_mode & 0o111),
            })
        payload = {
            "schema_version": 1, "task_root": str(self.root), "repository_root": str(info.repository_root),
            "scope": info.scope, "head": info.head, "requested_paths": paths, "files": rows,
            "excluded": [{"path": key, "reason": value} for key, value in sorted(excluded.items())],
        }
        return {"status": "preview", **payload, "plan_sha256": _digest(payload)}

    def checkpoint(self, plan: dict[str, Any], message: str, *, confirm: bool = False) -> dict[str, Any]:
        _require(confirm, "CONFIRMATION_REQUIRED", "审查预览清单后加入 --confirm-commit")
        _require(isinstance(message, str) and message.strip() and len(message) <= 500,
                 "GIT_MESSAGE_REQUIRED", "检查点说明不能为空且不超过 500 字符")
        _require(isinstance(plan, dict) and isinstance(plan.get("requested_paths"), list),
                 "INVALID_GIT_PLAN", "使用 git-preview 的 JSON 输出")
        current = self.preview(plan["requested_paths"])
        _require(plan.get("plan_sha256") == current["plan_sha256"], "STALE_GIT_PLAN", "预览后内容、HEAD 或范围变化；重新预览")
        paths = [row["path"] for row in current["files"]]
        _require(paths, "GIT_EMPTY_PLAN", "没有可安全提交的文件")
        info = self.git_info()
        _require(info.repository_root is not None, "GIT_NOT_CONFIGURED", "Git 尚未初始化")
        staged = self._git("diff", "--cached", "--name-only", "--", *paths).stdout
        _require(not staged, "GIT_STAGED_OVERLAP", "所选路径已有暂存内容；先人工处理，不覆盖部分暂存")
        for field in ("user.name", "user.email"):
            _require(bool(self._git("config", "--get", field).stdout.strip()),
                     "GIT_IDENTITY_REQUIRED", "请先为本仓库设置 user.name/user.email")
        markers = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer")
        _require(not any((info.repository_root / ".git" / marker).exists() for marker in markers),
                 "GIT_OPERATION_IN_PROGRESS", "仓库存在未结束的 Git 操作；先人工处理")
        self._git("add", "--", *paths, check=True)
        result = self._git("commit", "--only", "--no-verify", "-m", message, "--", *paths, check=True)
        commit = self._git("rev-parse", "HEAD", check=True).stdout.decode().strip()
        record = {
            "at": _utc_now(), "commit": commit, "message": message,
            "plan_sha256": current["plan_sha256"], "files": paths,
        }
        record_path = self.root / ".autoresearch" / "git-checkpoints.jsonl"
        record_path.parent.mkdir(exist_ok=True)
        with record_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return {"status": "committed", **record, "git_output": result.stdout.decode(errors="replace").strip()}

    def read_decisions(self) -> dict[str, Any]:
        path = self.root / ".autoresearch" / "decision-log.md"
        if not path.exists():
            return {"path": str(path), "exists": False, "entries": [], "latest": {}, "issues": []}
        _require(path.is_file() and not path.is_symlink() and not path.parent.is_symlink()
                 and path.resolve().is_relative_to(self.root),
                 "DECISION_LOG_UNSAFE", "decision-log.md 必须是题目根内的普通文件")
        entries: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        issues: list[str] = []
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            heading = re.match(r"^##\s+(\S+)\s+—\s+([a-z_]+)\s*$", line)
            if heading:
                if current:
                    entries.append(current)
                current = {"date": heading.group(1), "gate": heading.group(2), "line": line_number}
                continue
            field = re.match(r"^-\s+(status|scope|evidence|approver|limits|reason|rule_version|before|bindings):\s*(.*?)\s*$", line)
            if field and current is not None:
                if field.group(1) in current:
                    current.setdefault("parse_issues", []).append(f"第 {line_number} 行重复字段 {field.group(1)}")
                current[field.group(1)] = field.group(2)
        if current:
            entries.append(current)
        latest: dict[str, dict[str, Any]] = {}
        exceptions: list[dict[str, Any]] = []
        for entry in entries:
            issues.extend(entry.get("parse_issues", []))
            gate = entry.get("gate")
            if gate in CHECK_DECISIONS:
                exceptions.append(entry)
                continue
            if gate not in GATES:
                issues.append(f"第 {entry['line']} 行 gate 无效：{gate}")
                continue
            missing = [key for key in ("status", "scope", "evidence", "approver", "limits") if not entry.get(key)]
            if missing:
                issues.append(f"第 {entry['line']} 行缺字段：{','.join(missing)}")
            if entry.get("status") not in DECISION_STATUSES:
                issues.append(f"第 {entry['line']} 行 status 无效：{entry.get('status')}")
            latest[gate] = entry
        return {"path": str(path), "exists": True, "entries": entries, "latest": latest,
                "exceptions": exceptions, "issues": issues}


def main(argv: list[str] | None = None) -> int:
    """模块入口；作为运行包的一部分随 autoresearch_flow 一起分发。"""
    parser = argparse.ArgumentParser(description="检查题目 Git 范围、建立检查点和读取阶段门决定")
    parser.add_argument("--task-root", type=Path, required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("status")
    init = actions.add_parser("init-git")
    init.add_argument("--confirm-git", action="store_true")
    preview = actions.add_parser("preview")
    preview.add_argument("--path", action="append", required=True)
    checkpoint = actions.add_parser("checkpoint")
    checkpoint.add_argument("--plan", type=Path, required=True)
    checkpoint.add_argument("--message", required=True)
    checkpoint.add_argument("--confirm-commit", action="store_true")
    actions.add_parser("decisions")
    args = parser.parse_args(argv)
    try:
        workspace = TaskWorkspace(args.task_root)
        if args.action == "status":
            result = workspace.status()
        elif args.action == "init-git":
            result = workspace.init_git(confirm=args.confirm_git)
        elif args.action == "preview":
            result = workspace.preview(args.path)
        elif args.action == "checkpoint":
            result = workspace.checkpoint(
                json.loads(args.plan.read_text(encoding="utf-8")),
                args.message,
                confirm=args.confirm_commit,
            )
        else:
            result = workspace.read_decisions()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (FlowError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        error = {"status": "error", "code": getattr(exc, "code", "INPUT_ERROR"), "message": str(exc)}
        print(json.dumps(error, ensure_ascii=False, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
