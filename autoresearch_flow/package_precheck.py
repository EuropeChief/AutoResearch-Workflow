"""Thin invocation of the project format checker; preserve its original result."""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

from .archive_io import package_snapshot
from .common import _atomic_json, _canonical_digest, _read_json, _require, _sha256

FLOW = Path(__file__).resolve().parents[1]


def check(source, output, *, phase="final", task_kind="auto"):
    source = Path(source).expanduser().absolute()
    output = Path(output).expanduser().absolute()
    _require(phase in {"before_research", "final"}, "PRECHECK_PHASE", "前检时点不合法")
    _require(task_kind in {"auto", "cpu", "gpu"}, "PRECHECK_KIND", "题目类型不合法")
    _require(not source.is_symlink() and source.exists(), "PRECHECK_SOURCE", "输入须为真实目录或归档")
    source = source.resolve()
    _require(not output.exists() and not output.is_symlink()
             and not output.resolve().is_relative_to(source),
             "OUTPUT_BOUNDARY", "报告须在输入包外的新目录，不覆盖旧报告")
    def identity():
        return ({"algorithm": "sha256-canonical-package-snapshot-v1",
                 "value": _canonical_digest(package_snapshot(source))} if source.is_dir()
                else {"algorithm": "sha256", "value": _sha256(source)})
    before = identity()
    script = FLOW / "sources/format-precheck/check_package.py"
    proc = subprocess.run([sys.executable, str(script), str(source), "--out", str(output),
                           "--task-kind", task_kind], capture_output=True, text=True)
    report_path = output / "report.json"
    _require(report_path.is_file(), "PRECHECK_INCOMPLETE",
             "格式脚本未生成报告，退出码=" + str(proc.returncode) + "；" + proc.stderr[-1000:])
    report = _read_json(report_path)
    _require(before == identity(), "SOURCE_DRIFT", "前检期间输入改变，原结果不能代表当前包")
    deferred, blocking = [], []
    for row in report.get("findings", []):
        if row.get("level") != "ERROR":
            continue
        # Only absent final-evidence directories are not yet due at launch.
        # Do not ignore arbitrary messages or any workspace/config/path errors.
        if (phase == "before_research" and row.get("code") == "MISSING_DELIVERY_DIRECTORY"
                and row.get("path") in {"expert_evidence", "optimization_evidence"}):
            deferred.append(row)
        else:
            blocking.append(row)
    incomplete = proc.returncode not in {0, 1} or report.get("decision") == "INSPECTION_ERROR"
    status = "incomplete" if incomplete else "blocked" if blocking else "format_checked_not_qa"
    result = {"status": status, "phase": phase, "source": str(source), "source_identity": before,
              "checker_sha256": _sha256(script), "original_decision": report.get("decision"),
              "original_exit_code": proc.returncode, "original_report": str(report_path),
              "original_report_sha256": _sha256(report_path), "blocking": blocking,
              "deferred_until_final": deferred, "final_acceptance": False}
    _atomic_json(output / "scope.json", result)
    return result
