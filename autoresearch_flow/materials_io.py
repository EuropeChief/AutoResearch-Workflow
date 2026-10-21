"""Small package-boundary helpers. Never import code from a submission."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

from .common import FlowError, _require, _sha256

WORK_NAMES = {".git", ".autoresearch", ".autoresearch-flow", "__pycache__", ".pytest_cache", ".run.lock"}
SECRET_NAMES = {"auth.json", ".env", "credentials.json", "id_rsa", "id_ed25519"}
_PARSERS = {}


def bundled(name):
    """Reuse pinned official read-only parsers, not the QA CLI or its review workflow."""
    if name in _PARSERS:
        return _PARSERS[name]
    base = Path(__file__).resolve().parents[1] / "skills/autoresearch-task-qa/scripts"
    dependencies = {
        "harbor_review": ("docker_paths", "evidence_refs", "task_fingerprint", "deployment_review"),
        "deployment_review": ("docker_paths",),
    }.get(name, ())
    loaded = {key: bundled(key) for key in dependencies}
    previous = {key: sys.modules.get(key) for key in dependencies}
    sys.modules.update(loaded)
    spec = importlib.util.spec_from_file_location("_materials_" + name, base / (name + ".py"))
    _require(spec is not None and spec.loader is not None, "PARSER_MISSING", f"缺随包解析器：{name}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        for key, value in previous.items():
            if value is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = value
    _PARSERS[name] = module
    return module


def read_object(path):
    path = Path(path)
    _require(path.is_file() and not path.is_symlink(), "MISSING_FILE", f"缺少普通文件：{path}")
    _require(path.stat().st_size <= 8 * 1024 * 1024, "FILE_TOO_LARGE", f"JSON 超过检查上限：{path}")
    def reject(value):
        raise ValueError("非有限 JSON 值：" + value)
    try:
        obj = json.loads(path.read_text(encoding="utf-8"), parse_constant=reject)
    except (ValueError, UnicodeError) as exc:
        raise FlowError("INVALID_JSON", f"{path.name}: {exc}") from exc
    _require(isinstance(obj, dict), "JSON_ROOT", f"{path.name} 根须为对象")
    return obj


def inside(root, name, *, directory=False, nonempty=True):
    _require(isinstance(name, str) and name and not Path(name).is_absolute(),
             "PACKAGE_PATH", f"证据须用包内相对路径：{name!r}")
    base = Path(root).resolve()
    path = (base / name).resolve()
    _require(path.is_relative_to(base), "PACKAGE_ESCAPE", f"证据越过提交包：{name}")
    valid = path.is_dir() or path.is_file() if directory is None else path.is_dir() if directory else path.is_file()
    _require(valid, "MISSING_EVIDENCE", f"包内缺少：{name}")
    _require(not nonempty or directory or path.stat().st_size > 0, "EMPTY_EVIDENCE", f"证据为空：{name}")
    return path


def reference(root, value, *, nonempty=True):
    ref = {"path": value} if isinstance(value, str) else value
    _require(isinstance(ref, dict), "PACKAGE_PATH", "证据引用须为路径或 path 对象")
    path = inside(root, ref.get("path"), nonempty=nonempty)
    if ref.get("sha256") is not None:
        _require(_sha256(path) == ref["sha256"], "EVIDENCE_HASH", f"证据哈希不符：{ref['path']}")
    return path


def files(root):
    """Do not follow symlinks, including directories and special files."""
    root = Path(root)
    _require(root.is_dir() and not root.is_symlink(), "PACKAGE_ROOT", "范围根须为普通目录")
    found = []
    for base, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            path = Path(base) / name
            mode = path.lstat().st_mode
            _require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), "UNSAFE_FILE", f"不读取链接/特殊文件：{path.relative_to(root)}")
            if stat.S_ISREG(mode):
                found.append(path)
    return sorted(found)


def issue(items, code, path, message, *, level="error"):
    items.append({"code": code, "path": str(path), "message": message, "level": level})
