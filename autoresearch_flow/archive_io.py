"""Portable ZIP primitives shared by legacy and independent delivery."""

from __future__ import annotations

import hashlib
import shlex
import shutil
import stat
import zipfile
from pathlib import Path

from .common import _canonical_digest, _require, _sha256


def package_snapshot(root: Path) -> list[dict]:
    """Content, relative path and Unix mode; never follow links/special files."""
    _require(
        root.is_dir() and not root.is_symlink(),
        "PACKAGE_MISSING",
        "提交包目录不存在或为链接",
    )
    entries = []
    for path in [root, *sorted(root.rglob("*"))]:
        _require(
            not path.is_symlink() and (path.is_file() or path.is_dir()),
            "PACKAGE_SYMLINK",
            "提交包只允许普通文件/目录，不含链接或特殊文件",
        )
        item = {
            "path": path.relative_to(root).as_posix(),
            "mode": stat.S_IMODE(path.stat().st_mode),
            "type": "directory" if path.is_dir() else "file",
        }
        if path.is_file():
            item.update(sha256=_sha256(path), bytes=path.stat().st_size)
        entries.append(item)
    return entries


def _tree_digest(root: Path) -> str:
    return _canonical_digest(package_snapshot(root))


def _zip_name(prefix, row):
    name = (
        prefix
        if row["path"] == "."
        else "/".join(x for x in (prefix, row["path"]) if x)
    )
    return name + "/" if row["type"] == "directory" else name


def _write_zip(root, path, prefix, *, snapshot=None):
    with zipfile.ZipFile(
        path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True
    ) as out:
        for row in snapshot if snapshot is not None else package_snapshot(root):
            info = zipfile.ZipInfo(
                _zip_name(prefix, row), date_time=(1980, 1, 1, 0, 0, 0)
            )
            info.create_system = 3
            kind = stat.S_IFDIR if row["type"] == "directory" else stat.S_IFREG
            info.external_attr = (kind | row["mode"]) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if row["type"] == "directory":
                info.external_attr |= 0x10
                out.writestr(info, b"")
            else:
                with (
                    (root / row["path"]).open("rb") as source,
                    out.open(info, "w", force_zip64=True) as target,
                ):
                    shutil.copyfileobj(source, target, length=1024 * 1024)


def _verify_zip(root, path, prefix, *, snapshot=None, allow_implicit_dirs=False):
    """Stream every member: CRC, bytes, paths, Unicode and Unix permissions."""
    _require(
        path.is_file() and not path.is_symlink(), "ARCHIVE_INVALID", "ZIP 缺失或为链接"
    )
    rows = snapshot if snapshot is not None else package_snapshot(root)
    expected = {_zip_name(prefix, row): row for row in rows}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = {m.filename for m in members}
        required = {
            name
            for name, row in expected.items()
            if not allow_implicit_dirs or row["type"] == "file"
        }
        _require(
            len(members) == len(names) and required <= names <= set(expected),
            "ARCHIVE_INVALID",
            "ZIP 文件/目录集合与源包不符",
        )
        for member in members:
            row = expected[member.filename]
            kind = stat.S_IFDIR if row["type"] == "directory" else stat.S_IFREG
            _require(
                stat.S_IMODE(member.external_attr >> 16) == row["mode"]
                and stat.S_IFMT(member.external_attr >> 16)
                in ({kind, 0} if allow_implicit_dirs else {kind})
                and member.is_dir() is (row["type"] == "directory")
                and member.create_system == 3,
                "ARCHIVE_INVALID",
                "ZIP 文件类型或 Unix 权限不符",
            )
            _require(
                row["type"] != "directory" or member.file_size == 0,
                "ARCHIVE_INVALID",
                "ZIP 目录含异常数据",
            )
            _require(
                member.filename.isascii() or member.flag_bits & 0x800,
                "ARCHIVE_INVALID",
                "非 ASCII 文件名未使用 UTF-8 标志",
            )
            digest = hashlib.sha256()
            with archive.open(member) as data:
                while block := data.read(1024 * 1024):
                    digest.update(block)
            if row["type"] == "file":
                _require(
                    digest.hexdigest() == row["sha256"]
                    and member.file_size == row["bytes"],
                    "ARCHIVE_INVALID",
                    "ZIP 解包内容与源文件不同",
                )
    return {
        "path": path.name,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "prefix": prefix,
        "parts": [],
        "upload": "single_zip",
    }


def _split_zip(path, maximum, limit):
    if path.stat().st_size <= limit:
        return
    with path.open("rb") as source:
        number = 1
        while source.tell() < path.stat().st_size:
            with path.with_name(f"{path.name}.part{number:03d}").open("xb") as part:
                remaining = maximum
                while remaining and (block := source.read(min(remaining, 1024 * 1024))):
                    part.write(block)
                    remaining -= len(block)
            number += 1


def _verify_upload(path, entry, maximum, limit):
    if entry["bytes"] <= limit:
        return entry
    combined, parts = hashlib.sha256(), []
    for number in range(1, (entry["bytes"] + maximum - 1) // maximum + 1):
        part = path.with_name(f"{path.name}.part{number:03d}")
        expected = min(maximum, entry["bytes"] - (number - 1) * maximum)
        _require(
            part.is_file()
            and not part.is_symlink()
            and part.stat().st_size == expected,
            "ARCHIVE_INVALID",
            "分卷缺失、大小不符或为链接",
        )
        digest = hashlib.sha256()
        with part.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                combined.update(block)
        parts.append(
            {"path": part.name, "sha256": digest.hexdigest(), "bytes": expected}
        )
    _require(
        combined.hexdigest() == entry["sha256"],
        "ARCHIVE_INVALID",
        "分卷拼接哈希不等于完整 ZIP",
    )
    return {**entry, "parts": parts, "upload": "byte_parts"}


def _archive_support(archives, *, legacy_receipt=True):
    checksums = []
    instructions = [
        "# 上传说明",
        "",
        "完整 ZIP 保留本地。未超限时上传该 ZIP；超限时只上传全部分卷，不重复上传两套。",
        "分卷为字节拼接格式，单卷不能独立解压；不是原生多卷 ZIP。收齐后按下面明确顺序合并。",
        "",
    ]
    for role in ("submission", "harbor_task", "optimization_evidence"):
        entry = archives[role]
        for item in [entry, *entry["parts"]]:
            checksums.append(f"{item['sha256']}  {item['path']}")
        instructions.extend([f"## {entry['path']}", ""])
        if entry["parts"]:
            names = " ".join(shlex.quote(p["path"]) for p in entry["parts"])
            instructions.extend(
                ["```sh", f"cat {names} > {shlex.quote(entry['path'])}", "```", ""]
            )
        else:
            instructions.extend(["直接上传此 ZIP，无需拼接。", ""])
        instructions.extend([f"完整文件 SHA-256：`{entry['sha256']}`。", ""])
    instructions.extend(
        [
            "保留全部文件时可运行 `sha256sum -c SHA256SUMS.txt`。",
            "中文文件名使用 UTF-8；Linux 可用 `unzip`读取 Unix 权限字段，保留脚本执行位。",
        ]
    )
    if legacy_receipt:
        instructions.append(
            "`archives.json`绑定独立 QA、源包快照及三份压缩包；这些材料均在提交包之外。"
        )
    return {
        "SHA256SUMS.txt": "\n".join(checksums) + "\n",
        "上传说明.md": "\n".join(instructions) + "\n",
    }
