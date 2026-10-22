"""Validate paired legacy reports by recomputing the bundled official assessment.

The official implementation runs in a separate interpreter so ordinary QA's
same-named modules cannot change its strict reconstruction or waiver policy.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from .common import FlowError, _require, _sha256
from .materials_io import read_object

_SCRIPTS = Path(__file__).resolve().parents[1] / "skills/autoresearch-task-qa-legacy-waiver/scripts"
_ASSESS = """
import json, pathlib, sys
sys.path.insert(0, sys.argv[1])
import legacy_migration_waiver as waiver
import task_fingerprint
p = json.load(sys.stdin)
report = waiver.load_json(pathlib.Path(p['report']))
review = waiver.load_json(pathlib.Path(p['review']))
worksheet = waiver.load_json(pathlib.Path(p['worksheet']))
result = waiver.assess(
    report, review, worksheet, pathlib.Path(p['root']),
    task_fingerprint.sha256_file(pathlib.Path(p['report'])),
    task_fingerprint.sha256_file(pathlib.Path(p['review'])),
    worksheet_outside_artifact=True,
)
print(json.dumps(result, ensure_ascii=False, allow_nan=False))
"""


def validate_legacy_qa(root, report, review, worksheet, result, *, require_pass=False):
    """Recheck existing official artifacts; never execute a task or write reports.

    Passing explicit worksheet/review references selects the designated-legacy
    path. Scope assertions still require the reviewer's factual assessment;
    neither a file outside the submission nor this function authenticates a user.
    """
    root = Path(root).resolve()
    _require(root.is_dir(), "QA_SCOPE_MISMATCH", "旧题质检范围须为实际目录")
    paths = {}
    snapshots = {}
    for name, value in (("report", report), ("review", review),
                        ("worksheet", worksheet), ("result", result)):
        raw = Path(value)
        _require(not raw.is_symlink(), "QA_REPORT_BOUNDARY", "质检输入不得为符号链接")
        path = raw.resolve()
        _require(path.is_file(), "QA_REPORT_MISSING", "成对质检输入不存在或不是文件：" + str(path))
        _require(not path.is_relative_to(root), "QA_REPORT_BOUNDARY",
                 "严格报告、review、审核底稿及豁免结果须在题包外")
        read_object(path)
        paths[name] = path
        snapshots[name] = _sha256(path)
    _require(len(set(paths.values())) == 4, "QA_REPORT_BOUNDARY", "成对质检输入须为独立文件")
    saved = read_object(paths["result"])
    _require(saved.get("strict_report_path") == str(paths["report"]),
             "QA_SCOPE_MISMATCH", "豁免结果未绑定所给严格报告路径")
    payload = {name: str(path) for name, path in paths.items()}
    payload["root"] = str(root)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-B", "-c", _ASSESS, str(_SCRIPTS)],
            input=json.dumps(payload), text=True, capture_output=True,
            cwd=_SCRIPTS, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FlowError("QA_LEGACY_VALIDATION", "官方旧题复核工具未完成") from exc
    _require(proc.returncode == 0, "QA_LEGACY_VALIDATION",
             "官方旧题复核失败：" + proc.stderr[-1500:])
    try:
        computed = json.loads(proc.stdout)
    except ValueError as exc:
        raise FlowError("QA_LEGACY_VALIDATION", "官方复核未返回有效 JSON") from exc
    _require(isinstance(computed, dict) and not computed.get("integrity_issues"),
             "QA_LEGACY_VALIDATION", "严格报告与当前题包／review 不一致或未完成复核")
    # The CLI adds the report path and every assessment gets a fresh timestamp.
    ignored = {"generated_at", "strict_report_path"}
    _require({k: v for k, v in saved.items() if k not in ignored}
             == {k: v for k, v in computed.items() if k not in ignored},
             "QA_REPORT_DRIFT", "豁免结果与官方重新评估不一致")
    _require(all(_sha256(path) == snapshots[name] for name, path in paths.items()),
             "QA_REPORT_DRIFT", "质检输入在复核过程中发生变化")
    decision = computed.get("decision")
    _require(decision in {"PASS", "PASS_WITH_WAIVERS", "FAIL", "INCOMPLETE"},
             "QA_REPORT_SCHEMA", "官方豁免结论非法")
    if require_pass:
        _require(decision in {"PASS", "PASS_WITH_WAIVERS"},
                 "QA_UNRESOLVED", "旧题仍有未豁免失败或待核事项")
    return {
        "schema_version": 2, "profile": computed["profile"], "decision": decision,
        "strict_decision": computed["strict_decision"],
        "platform_followup_pending": computed.get("platform_followup_pending", []),
        "inputs": {name: {"path": str(path), "sha256": snapshots[name]}
                   for name, path in paths.items()},
    }
