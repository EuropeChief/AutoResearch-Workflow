"""Direct QA-accepted package -> three ZIPs and seven-field Markdown."""

from __future__ import annotations

import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .archive_io import (
    _archive_support,
    _split_zip,
    _verify_upload,
    _verify_zip,
    _write_zip,
    package_snapshot,
)
from .common import _require, _sha256
from .package_form import render
from .package_qa import accepted
from .package_precheck import check as format_precheck


def _name(root, explicit):
    value = explicit if explicit is not None else root.name
    if explicit is None and (
        value in {"submission_root", "submission", "final", "package"}
        or re.search(r"(?:tob|auto|task|question|problem)[_-]?\d", value, re.IGNORECASE)
    ):
        value = "research-submission"
    _require(
        isinstance(value, str)
        and re.fullmatch(r"[\w][\w .()-]{0,100}", value)
        and not value.endswith((" ", "."))
        and value.casefold() not in {"harbor_task", "optimization_evidence"},
        "INVALID_ARCHIVE_NAME",
        "附件名称须为安全单层语义名称，不能与子仓名相同",
    )
    return value


def _scope_snapshot(rows, relative):
    prefix = relative + "/"
    return [
        {**r, "path": "." if r["path"] == relative else r["path"][len(prefix) :]}
        for r in rows
        if r["path"] == relative or r["path"].startswith(prefix)
    ]


def package(
    package_root,
    qa_report,
    output_dir,
    *,
    name=None,
    upload_limit_bytes=300_000_000,
    part_bytes=None,
    form_notes=None,
    legacy_review=None,
    legacy_worksheet=None,
    legacy_result=None,
):
    """No QA workflow, runtime state, model loading, compression receipt or upload."""
    unresolved = Path(package_root).expanduser().absolute()
    _require(not unresolved.is_symlink(), "PACKAGE_SYMLINK", "源包根不能是链接")
    root = unresolved.resolve()
    requested = Path(output_dir).expanduser().absolute()
    _require(not requested.is_symlink(), "OUTPUT_BOUNDARY", "输出不能是链接")
    output = requested.resolve()
    _require(not output.is_relative_to(root), "OUTPUT_BOUNDARY", "输出目录必须在源包外")
    _require(
        not output.exists() or output.is_dir(),
        "OUTPUT_EXISTS",
        "输出位置已是文件，禁止覆盖",
    )
    _require(
        type(upload_limit_bytes) is int and upload_limit_bytes > 0,
        "INVALID_UPLOAD_LIMIT",
        "上传上限须为正整数字节，不固定限制为 300 MB",
    )
    if part_bytes is None:
        part_bytes = min(290_000_000, upload_limit_bytes)
    _require(
        type(part_bytes) is int and 0 < part_bytes <= upload_limit_bytes,
        "INVALID_PART_SIZE",
        "分卷须为正整数字节，且不超过上传上限",
    )
    for relative in (
        "workspace/harbor_task",
        "workspace/reference",
        "expert_evidence",
        "optimization_evidence",
    ):
        _require(
            (root / relative).is_dir(), "PACKAGE_MISSING", "指定最终包缺 " + relative
        )
    prefix = _name(root, name)
    if output.is_dir():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = output / f"{prefix}-{stamp}-{uuid.uuid4().hex[:8]}"
    snapshot = package_snapshot(root)
    report, qa = accepted(root, qa_report, snapshot,
                          legacy_review=legacy_review,
                          legacy_worksheet=legacy_worksheet,
                          legacy_result=legacy_result)
    text, form = render(root, report, form_notes)
    scopes = {
        "submission": (root, prefix, snapshot),
        "harbor_task": (
            root / "workspace/harbor_task",
            "harbor_task",
            _scope_snapshot(snapshot, "workspace/harbor_task"),
        ),
        "optimization_evidence": (
            root / "optimization_evidence",
            "optimization_evidence",
            _scope_snapshot(snapshot, "optimization_evidence"),
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".ar-package-", dir=output.parent
    ) as temporary:
        staging = Path(temporary) / "attachments"
        staging.mkdir()
        archives = {}
        for role, (source, archive_prefix, rows) in scopes.items():
            target = staging / (archive_prefix + ".zip")
            _write_zip(source, target, archive_prefix, snapshot=rows)
            entry = _verify_zip(source, target, archive_prefix, snapshot=rows)
            if role == "submission":
                checked = format_precheck(target, staging / "format-precheck")
                if checked['status'] != 'format_checked_not_qa':
                    failure = output.parent / (prefix + '-format-precheck-failed-' + uuid.uuid4().hex[:8])
                    shutil.copytree(staging / 'format-precheck', failure)
                    _require(False, "PACKAGE_FORMAT",
                             "最终完整归档格式检查未完成或存在ERROR；原判定="
                             + str(checked['original_decision']) + "；报告保留于 " + str(failure))
            _split_zip(target, part_bytes, upload_limit_bytes)
            archives[role] = _verify_upload(
                target, entry, part_bytes, upload_limit_bytes
            )
        for filename, body in _archive_support(archives, legacy_receipt=False).items():
            (staging / filename).write_text(body, encoding="utf-8")
        (staging / "填表信息.md").write_text(text, encoding="utf-8")
        _require(
            package_snapshot(root) == snapshot,
            "SOURCE_DRIFT",
            "压缩期间源包变化，请稳定最终包后再运行",
        )
        _require(
            _sha256(Path(qa["report"])) == qa["report_sha256"],
            "QA_REPORT_DRIFT",
            "压缩期间独立报告变化",
        )
        _require(all(_sha256(Path(ref["path"])) == ref["sha256"]
                     for ref in qa.get("inputs", {}).values()),
                 "QA_REPORT_DRIFT", "压缩期间旧题复核输入发生变化")
        source_archive = qa.get("source_archive")
        _require(not source_archive or _sha256(Path(source_archive["path"])) == source_archive["sha256"],
                 "QA_REPORT_DRIFT", "压缩期间原质检 ZIP 发生变化")
        _require(
            not output.exists(), "OUTPUT_EXISTS", "生成期间输出目录已出现，禁止覆盖"
        )
        staging.rename(output)
    return {
        "status": "packaged",
        "output_directory": str(output),
        "archives": archives,
        "format_precheck": {**checked, "source": str(output / Path(checked['source']).name),
                            "original_report": str(output / 'format-precheck/report.json'),
                            "note": "原报告保留检查时临时路径；输入身份按source_identity核对，报告随附件迁移"},
        "qa": qa,
        "form": {**form, "path": str(output / "填表信息.md")},
        "upload_limit_bytes": upload_limit_bytes,
        "part_bytes": part_bytes,
    }
