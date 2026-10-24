"""Recompute the official complete review, preserving submitted QA artifacts."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import zipfile

from .archive_io import package_snapshot, _verify_zip
from .common import FlowError, _canonical_digest, _require, _sha256
from .materials_io import read_object

_SCRIPTS = Path(__file__).resolve().parents[1] / "skills/autoresearch-task-qa-legacy-waiver/scripts"
_VERSION = "0.3.10-standard-waiver.5"
_STAGE = "standard_review_with_waivers"
_ASSESS = """
import contextlib, io, json, pathlib, sys, tempfile
sys.path.insert(0, sys.argv[1])
import audit_standard_with_waivers as waiver
p = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix='autoresearch-standard-qa-') as temporary:
    out = pathlib.Path(temporary)
    with contextlib.redirect_stdout(io.StringIO()):
        waiver.main([p['source'], '--standard-review', p['review'],
                     '--review', p['worksheet'], '--out-dir', str(out)])
    result = json.loads((out / 'report.json').read_text(encoding='utf-8'))
    native = out / 'standard/report.json'
    print(json.dumps({'result': result, 'report': json.loads(native.read_text(encoding='utf-8'))
                     if native.is_file() else None}, ensure_ascii=False, allow_nan=False))
"""


def _stable_report(value, *, standard=False, zip_input=False):
    """Normalize only official timestamps and ZIP extraction-root metadata.

    Never rewrite paths in evidence, findings, worksheets, or component results.
    """
    result = copy.deepcopy(value)
    if not isinstance(result, dict):
        return result
    result.pop("generated_at", None)
    if not standard:
        if isinstance(result.get("format_precheck"), dict):
            result["format_precheck"].pop("generated_at", None)
        for key in ("standard_report", "standard_evaluation_report", "standard_first_attempt"):
            if isinstance(result.get(key), dict):
                result[key] = _stable_report(result[key], standard=True, zip_input=zip_input)
    elif zip_input:
        source = result.get("source", {})
        scan = source.get("path")
        _require(source.get("kind") == "directory" and isinstance(scan, str)
                 and Path(scan).name.startswith("standard-waiver-"),
                 "QA_SCOPE_MISMATCH", "ZIP 原标准报告缺官方临时解包目录")
        source["path"] = "<official-zip-extraction>"
        for parent, key in ((result, "workspace_root"),
                            (result.get("format_alignment", {}), "inspected_root"),
                            (result.get("format_alignment", {}), "submission_root")):
            if key in parent:
                path = parent[key]
                _require(isinstance(path, str) and (path == scan or path.startswith(scan + "/")),
                         "QA_SCOPE_MISMATCH", "原标准报告的解包范围不一致")
                parent[key] = "<official-zip-extraction>" + path[len(scan):]
    return result


def _source(root, saved, native, report, snapshot):
    """Use existing directory inventory or exact ZIP bytes for current binding."""
    source = saved.get("source")
    _require(isinstance(source, str) and Path(source).is_absolute(),
             "QA_SCOPE_MISMATCH", "完整总报告缺明确来源")
    path = Path(source)
    _require(not path.is_symlink(), "QA_SCOPE_MISMATCH", "质检来源不能是链接")
    if path.is_dir():
        _require(path.resolve() == root and isinstance(native.get("source"), dict)
                 and native["source"].get("kind") == "directory"
                 and native["source"].get("path") == str(root),
                 "QA_SCOPE_MISMATCH", "原标准报告与总报告未绑定当前题包目录")
        from .package_qa import _directory_version
        _directory_version(root, native, report, snapshot)
        return path, False, None
    _require(path.is_file() and zipfile.is_zipfile(path), "QA_SCOPE_MISMATCH",
             "原取证 ZIP 不可读；请对当前待交目录重新静态质检")
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
    # Try only the existing two layouts: bare package or a single enclosing folder.
    prefix = "" if any(name.startswith(("workspace/", "expert_evidence/", "task.toml"))
                       for name in names) else names[0].split("/")[0] if names else ""
    rows = snapshot if prefix else [row for row in snapshot if row["path"] != "."]
    _verify_zip(root, path, prefix, snapshot=rows, allow_implicit_dirs=True)
    return path, True, _sha256(path)


def validate_legacy_qa(root, report, review, worksheet, result, *, require_pass=False):
    """Recheck external reports with official logic in an isolated interpreter.

    Scratch outputs are removed; saved reports and task code remain untouched.
    Explicit inputs select the legacy path, not proof of historical eligibility.
    """
    candidate = Path(root).expanduser()
    _require(not candidate.is_symlink(), "QA_SCOPE_MISMATCH", "旧题质检目录不能是链接")
    root = candidate.resolve()
    _require(root.is_dir(), "QA_SCOPE_MISMATCH", "旧题质检范围须为实际目录")
    before = package_snapshot(root)
    paths, snapshots = {}, {}
    for name, value in (("report", report), ("review", review),
                        ("worksheet", worksheet), ("result", result)):
        raw = Path(value).expanduser()
        _require(not raw.is_symlink(), "QA_REPORT_BOUNDARY", "质检输入不得为符号链接")
        path = raw.resolve()
        _require(path.is_file(), "QA_REPORT_MISSING", "完整质检输入不存在或不是文件：" + str(path))
        _require(not path.is_relative_to(root), "QA_REPORT_BOUNDARY",
                 "原标准报告、review、完整审核底稿及总报告须在题包外")
        read_object(path)
        paths[name] = path
        snapshots[name] = _sha256(path)
    _require(len(set(paths.values())) == 4, "QA_REPORT_BOUNDARY", "四份质检输入须为独立文件")
    saved = read_object(paths["result"])
    _require(saved.get("version") == _VERSION and saved.get("stage") == _STAGE
             and saved.get("schema_version") == 1, "QA_REPORT_VERSION",
             "须提供 standard-waiver.5 完整总报告；旧 .2 报告使用 2.1.3 复核，格式子报告不能替代完整审查")
    native = read_object(paths["report"])
    _require(_stable_report(native, standard=True)
             == _stable_report(saved.get("standard_report"), standard=True),
             "QA_REPORT_DRIFT", "所给原标准报告与完整总报告保留的原判不一致")
    source, zipped, archive_sha = _source(root, saved, native, paths["report"], before)
    payload = {name: str(path) for name, path in paths.items()}
    payload["source"] = str(source)
    try:
        proc = subprocess.run([sys.executable, "-I", "-B", "-c", _ASSESS, str(_SCRIPTS)],
            input=json.dumps(payload), text=True, capture_output=True, cwd=_SCRIPTS, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FlowError("QA_REVIEW_INCOMPLETE", "官方复核工具未完成，交质检处理；不是专家题目失败") from exc
    _require(proc.returncode == 0, "QA_REVIEW_INCOMPLETE",
             "官方复核工具未完成，交质检处理：" + proc.stderr[-1500:])
    try:
        computed = json.loads(proc.stdout)
    except ValueError as exc:
        raise FlowError("QA_REVIEW_INCOMPLETE", "官方复核未返回有效 JSON，交质检处理") from exc
    _require(isinstance(computed, dict) and isinstance(computed.get("result"), dict),
             "QA_REVIEW_INCOMPLETE", "官方完整复核未产生报告")
    _require(_stable_report(native, standard=True, zip_input=zipped)
             == _stable_report(computed.get("report"), standard=True, zip_input=zipped)
             and _stable_report(saved, zip_input=zipped) == _stable_report(computed["result"], zip_input=zipped),
             "QA_REPORT_DRIFT", "原判、完整结论、组件或逐原因明细与官方复算不一致")
    _require(all(_sha256(path) == snapshots[name] for name, path in paths.items())
             and (not zipped or _sha256(source) == archive_sha),
             "QA_REPORT_DRIFT", "质检输入或原 ZIP 在复核过程中发生变化")
    _require(package_snapshot(root) == before, "QA_PACKAGE_DRIFT", "题包在复核过程中发生变化")
    final = computed["result"]
    decision = final.get("decision")
    _require(decision in {"PASS_WITH_WAIVERS", "FAIL", "ERROR"},
             "QA_REPORT_SCHEMA", "官方完整质检结论非法")
    if require_pass:
        _require(decision != "FAIL", "QA_UNRESOLVED", "旧题仍有具体未豁免失败；未完成审查另见总报告")
        _require(decision == "PASS_WITH_WAIVERS" and final.get("review_completed") is True
                 and final.get("standard_auditor_executed") is True
                 and not final.get("input_and_review_errors") and not final.get("is_task_rejection"),
                 "QA_REVIEW_INCOMPLETE", "审核底稿、输入或读取尚未完成，交质检处理；不是专家题目失败")
    rows = (final.get("content_gates", {}).get("checks", []) + final.get("items21", [])
            + final.get("harbor6", []) + final.get("trajectory_content_review", {}).get("trajectories", []))
    return {
        "schema_version": 3, "profile": _STAGE, "version": _VERSION, "decision": decision,
        "review_completed": final.get("review_completed", False),
        "is_task_rejection": final.get("is_task_rejection", False),
        "strict_decision": native.get("summary", {}).get("decision"),
        "waived_findings": [{"owner": row["id"], **finding} for row in rows
                            for finding in row.get("findings", []) if finding.get("final_effect") == "waived"],
        "platform_followup_pending": final.get("format_precheck", {}).get("platform_followup_pending", []),
        "platform_observations": final.get("format_precheck", {}).get("platform_observations", []),
        "platform_runtime_status": final.get("platform_runtime_status"),
        "nop_runtime_status": final.get("nop_review", {}).get("runtime_status"),
        "package_sha256": _canonical_digest(before),
        "inputs": {name: {"path": str(path), "sha256": snapshots[name]}
                   for name, path in paths.items()},
        **({"source_archive": {"path": str(source), "sha256": archive_sha}} if zipped else {}),
    }
