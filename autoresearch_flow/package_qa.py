"""Read the final official report and existing scope/version evidence."""

from __future__ import annotations

import datetime as dt
import zipfile
from pathlib import Path

from .archive_io import _verify_zip, package_snapshot
from .common import FlowError, _canonical_digest, _require, _sha256
from .materials_io import read_object
from .qa_contract import validate_qa_report

TREE_ALGORITHM = "sha256-canonical-package-snapshot-v1"


def resolve_reference(value, report_file):
    _require(
        isinstance(value, str) and value.strip(),
        "QA_SCOPE_MISSING",
        "报告缺实际取证路径",
    )
    p = Path(value).expanduser()
    return p if p.is_absolute() else report_file.parent / p


def _directory_version(scan, report, report_path, rows):
    """Reuse the QA inventory and ordinary filesystem change evidence.

    This is not forensic authentication: do not claim an original digest when
    the official directory report did not record one.
    """
    inventory_path = report_path.parent / "inventory.json"
    _require(
        inventory_path.is_file(),
        "QA_VERSION_UNVERIFIED",
        "缺现有 QA inventory 或明确版本摘要；无法确认 QA 后是否改动",
    )
    inventory = read_object(inventory_path)
    _require(
        resolve_reference(inventory.get("root"), report_path).resolve()
        == scan.resolve(),
        "QA_SCOPE_MISMATCH",
        "QA inventory 的范围不是报告取证目录",
    )
    expected = sorted(r["path"] for r in rows if r["type"] == "file")
    _require(
        inventory.get("files") == expected,
        "QA_VERSION_UNVERIFIED",
        "当前文件清单与 QA inventory 不同；请核对实际通过版本",
    )
    try:
        stamp = dt.datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00"))
        _require(
            stamp.tzinfo is not None,
            "QA_VERSION_UNVERIFIED",
            "报告时间缺时区，不能核改动",
        )
        timestamp = stamp.timestamp()
        _require(
            timestamp <= dt.datetime.now(dt.timezone.utc).timestamp() + 1,
            "QA_VERSION_UNVERIFIED",
            "报告时间在未来，不能作为改动依据",
        )
    except (KeyError, AttributeError, TypeError, ValueError, OverflowError) as exc:
        raise FlowError(
            "QA_VERSION_UNVERIFIED", "报告缺可解析的实际生成时间；请核现有版本依据"
        ) from exc
    changed = [
        r["path"]
        for r in rows
        if max((scan / r["path"]).stat().st_mtime, (scan / r["path"]).stat().st_ctime)
        > timestamp
    ]
    _require(
        not changed,
        "QA_VERSION_UNVERIFIED",
        "取证目录在 QA 报告生成后有内容/权限改动，不能直接复用 PASS："
        + ", ".join(changed[:5]),
    )


def accepted(package_root, report_file, snapshot, *, legacy_review=None,
             legacy_worksheet=None, legacy_result=None):
    path = Path(report_file).expanduser().absolute()
    _require(not path.is_symlink(), "QA_SCOPE_MISMATCH", "报告原件不能是链接")
    path = path.resolve()
    _require(
        not path.is_relative_to(package_root),
        "QA_SCOPE_MISMATCH",
        "独立 QA 报告必须在提交包外",
    )
    report = read_object(path)
    legacy = (legacy_review, legacy_worksheet, legacy_result)
    if any(value is not None for value in legacy):
        _require(all(value is not None for value in legacy), "QA_LEGACY_INPUTS",
                 "旧题路径须同时提供官方 review、审核底稿和豁免结果")
        from .legacy_qa import validate_legacy_qa
        checked = validate_legacy_qa(
            package_root, path, legacy_review, legacy_worksheet, legacy_result,
            require_pass=True,
        )
        _require(package_snapshot(package_root) == snapshot, "SOURCE_DRIFT",
                 "官方旧题复核期间源包发生变化")
        return report, {
            **checked, "report": str(path), "report_sha256": _sha256(path),
            "correspondence": "official_standard_review_with_waivers",
        }
    try:
        validate_qa_report(report, require_pass=True)
    except (TypeError, KeyError, AttributeError) as exc:
        raise FlowError("QA_REPORT_SCHEMA", "报告嵌套类型不符合当前终稿合同") from exc
    _require(
        not report.get("inspection_error"),
        "QA_UNRESOLVED",
        "报告包含取证错误，不能打包",
    )
    source = report.get("source")
    _require(isinstance(source, dict), "QA_SCOPE_MISSING", "报告缺 source 取证范围")
    digest = source.get("package_digest")
    current = _canonical_digest(snapshot)
    if digest is not None:
        _require(
            isinstance(digest, dict) and digest.get("algorithm") == TREE_ALGORITHM,
            "QA_VERSION_UNVERIFIED",
            "现有摘要算法未知；不能将不同算法的 SHA-256 互换",
        )
        _require(
            digest.get("value") == current,
            "QA_SCOPE_MISMATCH",
            "报告已有包摘要与当前内容/权限不符",
        )
        correspondence = "reported_tree_digest"
    elif source.get("kind") == "zip":
        scan = resolve_reference(source.get("path"), path)
        _require(
            scan.is_file()
            and not scan.is_symlink()
            and source.get("sha256") == _sha256(scan),
            "QA_VERSION_UNVERIFIED",
            "QA 所检 ZIP 缺失或与报告原始 SHA-256 不符",
        )
        try:
            with zipfile.ZipFile(scan) as z:
                names = z.namelist()
            prefix = (
                ""
                if any(n.startswith("workspace/") for n in names)
                else names[0].split("/")[0]
                if names
                else ""
            )
            rows = [r for r in snapshot if r["path"] != "."] if not prefix else snapshot
            _verify_zip(
                package_root, scan, prefix, snapshot=rows, allow_implicit_dirs=True
            )
        except (zipfile.BadZipFile, RuntimeError) as exc:
            raise FlowError(
                "QA_VERSION_UNVERIFIED", "报告所检 ZIP 损坏或无法读回内容"
            ) from exc
        correspondence = "scanned_zip"
    else:
        _require(
            source.get("kind") == "directory",
            "QA_SCOPE_MISSING",
            "报告 source.kind 未识别",
        )
        scan = resolve_reference(source.get("path"), path)
        _require(
            scan.is_dir() and not scan.is_symlink(),
            "QA_VERSION_UNVERIFIED",
            "QA 原取证目录已不可读，且报告没有可核版本摘要",
        )
        if report.get("workspace_root") is not None:
            _require(
                resolve_reference(report["workspace_root"], path).resolve()
                == scan.resolve(),
                "QA_SCOPE_MISMATCH",
                "报告 workspace_root 与 source.path 不一致",
            )
        scanned = snapshot if scan.resolve() == package_root else package_snapshot(scan)
        _directory_version(scan, report, path, scanned)
        _require(
            scanned == snapshot,
            "QA_SCOPE_MISMATCH",
            "通过的取证副本与待交包的路径/内容/权限不同",
        )
        correspondence = (
            "scanned_directory"
            if scan.resolve() == package_root
            else "identical_scanned_copy"
        )
    return report, {
        "decision": "PASS",
        "report": str(path.resolve()),
        "report_sha256": _sha256(path),
        "correspondence": correspondence,
    }
