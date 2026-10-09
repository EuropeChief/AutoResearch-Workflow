"""State-free I/O primitives shared by old and lightweight tools."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


class FlowError(Exception):
    """A user-actionable contract failure, never a task-science judgment."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise FlowError(code, message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), "MISSING_OR_UNSAFE_FILE", f"缺少普通文件或文件是符号链接：{path}")
    _require(path.stat().st_size <= 8 * 1024 * 1024, "FILE_TOO_LARGE", f"状态/规则文件超过 8 MiB：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError("INVALID_JSON", f"无法读取 JSON {path}: {exc}") from exc
    _require(isinstance(value, dict), "INVALID_SCHEMA", f"JSON 根必须是对象：{path}")
    return value


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
