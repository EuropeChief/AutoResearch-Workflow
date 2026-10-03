"""Task-scoped Git setup and reviewed checkpoints; never pushes or resets user work."""
import fcntl
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .core import (
    PACKAGE_ROOT,
    FlowError,
    TaskStore,
    _atomic_json,
    _canonical_digest,
    _read_json,
    _require,
    _sha256,
    _utc_now,
)

MAX_FILE_BYTES = 10 * 1024 * 1024  # Local Git hygiene, not a project submission limit.
PRIVATE_DIRS = {".git", ".codex", ".ssh", "auth", "credentials", "secrets",
                "data", "datasets", "checkpoints", "weights", "logs", "runtime",
                "deliverables", "archives", "__pycache__", ".venv", "venv", ".cache"}
ARTIFACT_SUFFIXES = {".pt", ".pth", ".ckpt", ".safetensors", ".bin", ".npz", ".npy",
                     ".zip", ".7z", ".rar", ".tar", ".gz", ".log", ".pyc", ".pem", ".key"}
SECRET = re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bAKIA[A-Z0-9]{16}\b")
IGNORE_BLOCK = """# AutoResearch task hygiene (OP-1); evidence remains on disk.
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
data/
datasets/
checkpoints/
weights/
logs/
runtime/
deliverables/
archives/
__pycache__/
.venv/
venv/
.cache/
*.pyc
*.pt
*.pth
*.ckpt
*.safetensors
*.bin
*.npz
*.npy
*.zip
*.zip.*
*.7z
*.rar
*.tar
*.gz
*.log
!/.autoresearch-flow/
/.autoresearch-flow/*
!/.autoresearch-flow/state.json
# End AutoResearch task hygiene
"""


class TaskGit:
    def __init__(self, task_root):
        self.store = TaskStore(Path(task_root))
        self.store._load()
        self.root = self.store.task_root
        self.record_path = self.store.state_dir / "git_repository.json"

    def _git(self, *args, check=True, index=None, cwd=None, input_bytes=None):
        # Do not let inherited Git worktree/index/author variables redirect writes.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")
               or k in {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}}
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_OPTIONAL_LOCKS"] = "0"
        env["LC_ALL"] = "C"
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        try:
            result = subprocess.run(["git", "--literal-pathspecs", "-c", "core.hooksPath=/dev/null",
                                     "-c", "commit.gpgSign=false", "-C", str(cwd or self.root), *args],
                                    env=env, capture_output=True, input=input_bytes, timeout=60, check=False)
        except FileNotFoundError as exc:
            raise FlowError("GIT_MISSING", "宿主缺少 git；安装后重试，不需要模型调用") from exc
        except subprocess.TimeoutExpired as exc:
            raise FlowError("GIT_TIMEOUT", "Git 命令超时；先检查仓库，不标记检查点成功") from exc
        _require(not check or result.returncode == 0, "GIT_COMMAND_FAILED",
                 f"Git {args[0]} 失败（exit={result.returncode}）；请在指定仓库检查，不自动清理暂存或工作区")
        return result

    def _repository(self):
        result = self._git("rev-parse", "--show-toplevel", check=False)
        if result.returncode:
            # A corrupt/unreadable .git is not permission to initialize over it.
            marker = self.root / ".git"
            _require(not marker.exists() and not marker.is_symlink()
                     and b"not a git repository" in result.stderr,
                     "GIT_REPOSITORY_UNREADABLE", "存在不可读取的 Git 元数据；先人工修复，不覆盖")
            return None
        repository = Path(os.fsdecode(result.stdout).strip()).resolve()
        _require(self.root.is_relative_to(repository), "GIT_SCOPE", "Git 根未包含题目目录")
        _require(not (repository / ".git").is_symlink(), "GIT_SCOPE", "Git 元数据目录不能是符号链接")
        return repository

    def _head(self):
        result = self._git("rev-parse", "--verify", "HEAD", check=False)
        return result.stdout.decode().strip() if result.returncode == 0 else None

    def _git_path(self, name):
        path = Path(os.fsdecode(self._git("rev-parse", "--git-path", name).stdout).strip())
        return path if path.is_absolute() else self.root / path

    def _pending_operation(self):
        for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_START"):
            path = self._git_path(name)
            if path.exists() or path.is_symlink():
                return name
        return None

    def _binding(self, repository):
        if not self.record_path.exists():
            return None
        value = _read_json(self.record_path)
        _require(value.get("schema_version") == 1 and isinstance(value.get("repository_relative"), str)
                 and not Path(value["repository_relative"]).is_absolute()
                 and isinstance(value.get("scope"), str) and isinstance(value.get("checkpoints"), list)
                 and all(isinstance(c, dict) and isinstance(c.get("commit"), str)
                         and re.fullmatch(r"[0-9a-f]{40,64}", c["commit"]) for c in value["checkpoints"]),
                 "INVALID_GIT_RECORD", "Git 范围/检查点记录损坏；不据此宣布已就绪")
        _require(repository is not None
                 and (self.root / value["repository_relative"]).resolve() == repository
                 and value["scope"] == self.root.relative_to(repository).as_posix(),
                 "GIT_SCOPE_DRIFT", "Git 根/任务范围已变化，不能沿用旧检查点绑定")
        return value

    def status(self):
        repository = self._repository()
        binding = self._binding(repository)
        checkpoint = binding.get("checkpoints", [])[-1] if binding and binding.get("checkpoints") else None
        head = self._head() if repository else None
        pending = self._pending_operation() if repository else None
        ready = bool(not pending and checkpoint and head and self._git(
            "merge-base", "--is-ancestor", checkpoint["commit"], head, check=False).returncode == 0)
        dirty = bool(self._git("status", "--porcelain=v1", "--untracked-files=no").stdout) if repository else False
        return {"status": "ok", "mode": "new" if repository is None else "reuse_task" if repository == self.root else "reuse_parent",
                "repository_root": str(repository or self.root), "scope": self.root.relative_to(repository).as_posix() if repository else ".",
                "configured": binding is not None, "ready": ready, "head": head,
                "operation_in_progress": pending,
                "tracked_dirty": dirty, "checkpoint": checkpoint,
                "next_action": "先由用户处理未结束的 Git 操作，不代为 abort 或清理" if pending else
                    "审查 git-preview 并建立检查点" if binding and not ready else
                    "先确认仓库范围并执行 git-setup --confirm-git" if not binding else "按关键节点建立检查点；不自动回退研究证据"}

    @contextmanager
    def _edit(self):
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "先核对规则来源并显式升级")
        path = self.store.state_dir / "git.lock"
        _require(not path.is_symlink(), "GIT_SCOPE", "Git 流程锁不能是符号链接")
        with path.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def setup(self, repository_root, *, confirm=False):
        _require(confirm, "CONFIRMATION_REQUIRED", "审查 git-status 的范围后显式加入 --confirm-git")
        with self._edit():
            _require(self.root not in {Path("/"), Path.home().resolve(), PACKAGE_ROOT, self.store.repository_root},
                     "GIT_SCOPE", "不能把主目录、中央工作区或流程包当作新题仓库")
            repository = self._repository()
            expected = repository or self.root
            _require(Path(repository_root).resolve() == expected, "GIT_SCOPE",
                     "--repository-root 必须与 git-status 检出的根一致；不静默新建嵌套仓")
            ignore = self.root / ".gitignore"
            _require(not ignore.is_symlink() and (not ignore.exists() or ignore.is_file()),
                     "GIT_SCOPE", ".gitignore 必须是题目内普通文件")
            _require(not ignore.exists() or ignore.stat().st_size <= MAX_FILE_BYTES,
                     "GIT_SCOPE", ".gitignore 异常过大，先人工检查")
            try:
                before = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
            except UnicodeError as exc:
                raise FlowError("GIT_IGNORE_ENCODING", ".gitignore 不是 UTF-8；保留原件，先人工处理编码") from exc
            binding = self._binding(repository)
            if repository is None:
                self._git("init", "--quiet", "--template=", ".")
                repository = self._repository()
            if IGNORE_BLOCK not in before:
                ignore.write_text(before + ("\n" if before and not before.endswith("\n") else "") + IGNORE_BLOCK,
                                  encoding="utf-8")
            if binding is None:
                binding = {"schema_version": 1, "repository_relative": os.path.relpath(repository, self.root),
                           "scope": self.root.relative_to(repository).as_posix(), "configured_at": _utc_now(),
                           "initial_head": self._head(), "checkpoints": []}
            _atomic_json(self.record_path, binding)
        return self.status()

    def _excluded(self, relative):
        path = Path(relative)
        if any((self.root / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)):
            return "symlink"
        if any(p.lower() in PRIVATE_DIRS for p in path.parts):
            return "private_or_large_artifact_directory"
        if path.parts and path.parts[0] == ".autoresearch-flow" and relative != ".autoresearch-flow/state.json":
            return "private_workflow_record"
        if path.name.lower() in {"auth.json", "credentials.json"} or path.name.lower().endswith(".auth.json"):
            return "credential_filename"
        if path.name.startswith(".env") and path.name not in {".env.example", ".env.template"}:
            return "credential_filename"
        if path.suffix.lower() in ARTIFACT_SUFFIXES or ".zip." in path.name:
            return "large_artifact_or_private_file"
        if any((self.root / Path(*path.parts[:i]) / ".git").exists()
               or (self.root / Path(*path.parts[:i]) / ".git").is_symlink()
               for i in range(1, len(path.parts) + 1)):
            return "nested_repository"
        return None

    def preview(self, paths):
        repository = self._repository()
        _require(repository is not None and self._binding(repository) is not None,
                 "GIT_NOT_CONFIGURED", "先执行 git-status 和 git-setup，确认版本管理范围")
        _require(isinstance(paths, list) and paths and all(isinstance(p, str) and p for p in paths),
                 "GIT_PATHS_REQUIRED", "显式给出 --path；可用 . 预览过滤后的整个题目，不能默认提交全部")
        candidates: set[str] = set()
        excluded: dict[str, str] = {}
        for value in paths:
            path = Path(value)
            _require(not path.is_absolute() and ".." not in path.parts and "\\" not in value,
                     "GIT_SCOPE", "仅接受题目内相对路径，不接受路径上跳")
            relative = path.as_posix()
            actual = self.root / path
            _require(actual.resolve().is_relative_to(self.root), "GIT_SCOPE", "候选路径越出题目目录")
            reason = self._excluded(relative)
            if reason:
                excluded[relative] = reason
            elif actual.is_dir() and not actual.is_symlink():
                for directory, dirs, files in os.walk(actual, followlinks=False):
                    for name in list(dirs):
                        sub = Path(directory) / name
                        rel = sub.relative_to(self.root).as_posix()
                        reason = "symlink" if sub.is_symlink() else self._excluded(rel)
                        if rel == ".autoresearch-flow":
                            reason = None  # Only state.json may be selected below.
                        if reason:
                            excluded[rel] = reason
                            dirs.remove(name)
                    candidates.update((Path(directory) / n).relative_to(self.root).as_posix() for n in files)
            else:
                candidates.add(relative)
        # Include tracked deletions as well as files discovered in the worktree.
        tracked = {os.fsdecode(p) for p in self._git("ls-files", "-z", "--", *paths).stdout.split(b"\0") if p}
        candidates.update(tracked)
        files = []
        for rel in sorted(candidates):
            actual = self.root / rel
            reason = self._excluded(rel)
            if reason is None and not actual.exists() and rel in tracked:
                files.append({"path": rel, "sha256": None, "size": 0, "executable": False, "deleted": True})
                continue
            if reason is None and (actual.is_symlink() or not actual.is_file()):
                reason = "not_regular_file"
            if reason is None and self._git("check-ignore", "--quiet", "--", rel, check=False).returncode == 0:
                reason = "gitignore"
            if reason is None and actual.stat().st_size > MAX_FILE_BYTES:
                reason = "exceeds_local_git_size_limit"
            if reason is None and SECRET.search(actual.read_bytes()):
                reason = "possible_secret"
            if reason:
                excluded[rel] = reason
                continue
            files.append({"path": rel, "sha256": _sha256(actual), "size": actual.stat().st_size,
                          "executable": bool(actual.stat().st_mode & 0o111)})
        plan = {"schema_version": 1, "task_id": self.store._load()["task_id"],
                "repository_root": str(repository), "scope": self.root.relative_to(repository).as_posix(),
                "head": self._head(), "requested_paths": paths, "files": files,
                "excluded": [{"path": p, "reason": why} for p, why in sorted(excluded.items())]}
        return {"status": "preview", **plan, "plan_sha256": _canonical_digest(plan)}

    def checkpoint(self, plan, message, *, confirm=False):
        _require(confirm, "CONFIRMATION_REQUIRED", "审查预览文件清单后显式加入 --confirm-commit")
        _require(isinstance(message, str) and message.strip() and len(message) <= 500,
                 "GIT_MESSAGE_REQUIRED", "填写不含凭据的简短检查点说明")
        _require(isinstance(plan, dict) and isinstance(plan.get("requested_paths"), list),
                 "INVALID_GIT_PLAN", "使用 git-preview 的原始 JSON 输出作为 --file")
        with self._edit():
            actual = self.preview(plan["requested_paths"])
            _require(plan.get("plan_sha256") == actual["plan_sha256"]
                     and all(plan.get(k) == v for k, v in actual.items() if k != "status"),
                     "STALE_GIT_PLAN", "预览后内容、HEAD 或范围发生变化；重新预览，不提交未审查内容")
            paths = [f["path"] for f in actual["files"]]
            _require(paths, "GIT_EMPTY_PLAN", "没有可安全提交的文件；检查排除原因")
            for field in ("user.name", "user.email"):
                identity = self._git("config", "--get", field, check=False)
                _require(identity.returncode == 0 and identity.stdout.strip(), "GIT_IDENTITY_REQUIRED",
                         "缺少 Git user.name/user.email；请用 git -C <仓库根> config 设置本仓库身份，不修改全局或伪造作者")
            repository = self._repository()
            binding = self._binding(repository)
            commit, changed = self._commit_snapshot(actual, message, repository)
            checkpoint = {"at": _utc_now(), "commit": commit, "message": message,
                          "plan_sha256": actual["plan_sha256"], "files": actual["files"],
                          "tracked_dirty_after": bool(self._git("status", "--porcelain=v1", "--untracked-files=no").stdout)}
            binding["checkpoints"].append(checkpoint)
            _atomic_json(self.record_path, binding)
        return {"status": "committed" if changed else "unchanged", **checkpoint}

    def _commit_snapshot(self, plan, message, repository):
        """Build exact reviewed blobs/modes, preserving all unrelated index entries.

        An isolated index avoids `commit --only` rereading a changing worktree.
        Git's index.lock excludes competing staging; update-ref uses a HEAD CAS.
        No hooks/clean filters run and no worktree file is rewritten.
        """
        index = self._git_path("index")
        _require(not index.is_symlink(), "GIT_SCOPE", "Git index 不能是符号链接")
        lock = index.with_name(index.name + ".lock")
        try:
            descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError as exc:
            raise FlowError("GIT_INDEX_BUSY", "仓库正有其他 Git 写操作；稍后重试，不删除他人的 index.lock") from exc
        replaced = False
        try:
            with os.fdopen(descriptor, "wb") as output, tempfile.TemporaryDirectory(
                    prefix=".git-checkpoint-", dir=self.store.state_dir) as temporary:
                _require(self._pending_operation() is None, "GIT_OPERATION_IN_PROGRESS",
                         "仓库存在未结束的 merge/rebase/cherry-pick/revert/bisect；先由用户处理，不推进 HEAD 或清理标记")
                selected = [f["path"] for f in plan["files"]]
                _require(not self._git("diff", "--cached", "--name-only", "-z", "--", *selected).stdout,
                         "GIT_STAGED_OVERLAP", "所选路径已有暂存内容；先人工处理，程序不覆盖部分暂存")
                snapshot, preserved = Path(temporary) / "snapshot", Path(temporary) / "preserved"
                head = plan["head"]
                self._git("read-tree", head or "--empty", index=snapshot, cwd=repository)
                if index.exists():
                    shutil.copyfile(index, preserved)
                else:
                    self._git("read-tree", "--empty", index=preserved, cwd=repository)
                entries = bytearray()
                for item in plan["files"]:
                    path = self.root / item["path"]
                    repo_path = path.relative_to(repository).as_posix()
                    if item.get("deleted"):
                        _require(not path.exists() and not path.is_symlink(), "STALE_GIT_PLAN", "已删除文件重新出现；重新预览")
                        mode, oid = "0", "0" * (len(head) if head else 40)
                    else:
                        _require(self._excluded(item["path"]) is None and path.is_file(),
                                 "STALE_GIT_PLAN", "所选路径类型在提交前变化；重新预览")
                        content = path.read_bytes()
                        _require(hashlib.sha256(content).hexdigest() == item["sha256"]
                                 and bool(path.stat().st_mode & 0o111) == item["executable"],
                                 "STALE_GIT_PLAN", "提交前内容或权限发生变化；重新预览")
                        oid = self._git("hash-object", "-w", "--stdin", input_bytes=content).stdout.decode().strip()
                        mode = "100755" if item["executable"] else "100644"
                    entries += (mode + " " + oid + "\t").encode() + os.fsencode(repo_path) + b"\0"
                for target in (snapshot, preserved):
                    self._git("update-index", "-z", "--index-info", index=target, cwd=repository,
                              input_bytes=bytes(entries))
                tree = self._git("write-tree", index=snapshot, cwd=repository).stdout.decode().strip()
                old_tree = self._git("rev-parse", head + "^{tree}").stdout.decode().strip() if head else None
                changed = tree != old_tree
                commit = self._git("commit-tree", tree, *(["-p", head] if head else []), "-m", message).stdout.decode().strip() if changed else head
                _require(self._git("rev-parse", commit + "^{tree}").stdout.decode().strip() == tree,
                         "GIT_TREE_MISMATCH", "最终 commit tree 与审查快照不同，不登记成功")
                with preserved.open("rb") as source:
                    shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
                # CAS also checks concurrent branch changes for unchanged snapshots.
                self._git("update-ref", "-m", message, "HEAD", commit, head or "0" * len(commit))
                os.replace(lock, index)
                replaced = True
            return commit, changed
        except OSError as exc:
            raise FlowError("GIT_CHECKPOINT_IO", "Git 检查点写入失败；检查 HEAD/index 后再恢复，不自动重置用户数据") from exc
        finally:
            if not replaced:
                lock.unlink(missing_ok=True)
