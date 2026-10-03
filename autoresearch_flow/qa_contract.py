"""Small v0.3.1 handoff contracts; no task execution or QA judgments."""
from pathlib import Path
import re

from .core import _read_json, _require

QA_IDS = {f"QA{i:02d}" for i in range(1, 22)}
G_IDS = {f"G{i:02d}" for i in range(1, 4)}
H_IDS = {f"H{i:02d}" for i in range(1, 7)}
NA_IDS = {"QA04", "QA15", "QA19", "H05", "H06"}


def validate_qa_report(report, *, require_pass=False):
    """Accept current reports, including failures for repair; close only a PASS."""
    _require(report.get("schema_version") == 4
             and report.get("policy", {}).get("name") == "implementation"
             and report["policy"].get("revision") == "research-quality-v3",
             "QA_REPORT_SCHEMA", "需 v0.3.1 schema 4 / research-quality-v3 报告")
    for name in ("overview", "runtime_review", "format_alignment", "harbor",
                 "content_gates", "review", "summary"):
        _require(isinstance(report.get(name), dict), "QA_REPORT_SCHEMA", f"缺少报告对象 {name}")
    harbor = report["harbor"]
    groups = [(report.get("checks"), QA_IDS),
              (report["content_gates"].get("checks"), G_IDS),
              (harbor.get("checks"), H_IDS)]
    rows = {}
    for values, expected in groups:
        _require(isinstance(values, list) and len(values) == len(expected)
                 and all(isinstance(v, dict) for v in values)
                 and {v.get("id") for v in values} == expected,
                 "QA_REPORT_SCHEMA", "QA01–21、G01–03、H01–06 各须恰好出现一次")
        for row in values:
            key, status = row["id"], row.get("status")
            _require(status in {"pass", "fail", "manual", "not_applicable"}
                     and (status != "not_applicable" or key in NA_IDS),
                     "QA_REPORT_SCHEMA", f"{key} 状态不符合当前 Skill；不得沿用旧豁免")
            _require(isinstance(row.get("summary"), str) and row["summary"].strip()
                     and isinstance(row.get("evidence"), list),
                     "QA_REPORT_SCHEMA", f"{key} 缺结论或证据列表")
            _require(status != "pass" or bool(row["evidence"]),
                     "QA_REPORT_SCHEMA", f"{key} 通过项须有证据")
            if status in {"fail", "manual"} and key not in H_IDS:
                _require(all(isinstance(row.get(k), str) and row[k].strip()
                             for k in ("remediation", "acceptance_evidence")),
                         "QA_REPORT_SCHEMA", f"{key} 缺返修与验收建议")
            rows[key] = row
    _require(rows["QA15"]["status"] == "not_applicable",
             "QA_REPORT_SCHEMA", "QA15 按当前 Skill 固定跳过")
    expected_runtime = {"pass": "evidence_consistent", "fail": "failed",
                        "manual": "unverified", "not_applicable": "not_run"}
    _require(harbor.get("runtime_status") == expected_runtime[rows["H06"]["status"]],
             "QA_REPORT_SCHEMA", "H06 与 Harbor runtime_status 不一致")
    _require(rows["H06"]["status"] != "not_applicable" or not rows["H06"]["evidence"],
             "QA_REPORT_SCHEMA", "已有 Trial 证据不能标记不适用")
    decision = report["summary"].get("decision")
    _require(decision in {"PASS", "FAIL", "INCOMPLETE"}, "QA_REPORT_SCHEMA", "报告总评非法")
    if require_pass or decision == "PASS":
        _require(decision == "PASS" and report["review"].get("completed") is True
                 and all(r["status"] in {"pass", "not_applicable"} for r in rows.values()),
                 "QA_UNRESOLVED", "独立质检须完成且全部适用项通过，不能用例外关闭失败")
        _require(report["runtime_review"].get("status") == "pass"
                 and harbor.get("static_status") == "pass" and harbor.get("qa17_status") == "pass"
                 and harbor.get("hidden_review", {}).get("status") == "pass"
                 and harbor.get("artifact_contract", {}).get("status") == "pass",
                 "QA_UNRESOLVED", "PASS 缺时长、Harbor、Hidden 或 artifacts 的通过结论")
        path = harbor.get("path_contract", {})
        _require(path.get("status") == "pass" or
                 (path.get("status") == "manual" and bool(path.get("manual_resolution"))),
                 "QA_UNRESOLVED", "Docker 路径合同未完成复核")
        _require(not any(x.get("status") == "fail" for x in path.get("findings", [])),
                 "QA_UNRESOLVED", "Docker 路径失败不能被 PASS 遮蔽")
        _require(report["format_alignment"].get("review", {}).get("status") in
                 {"aligned", "aligned_with_extras", "deviations"},
                 "QA_UNRESOLVED", "缺少已完成的格式审阅")
    return {"schema_version": 4, "decision": decision,
            "runtime_status": harbor["runtime_status"]}


def check_exposure_manifest(workspace):
    """Validate authored declarations and references, without inventing image evidence."""
    workspace = Path(workspace).resolve()
    manifest = workspace / "qa_exposure_manifest.json"
    _require(manifest.is_file(), "EXPOSURE_MISSING",
             "PCA 作者包的 Agent 可见面较窄，须提供 workspace/qa_exposure_manifest.json")
    data = _read_json(manifest)
    _require(data.get("schema_version") == 1, "EXPOSURE_SCHEMA", "可见性清单 schema_version 须为 1")

    def local(value):
        _require(isinstance(value, str) and value and "\\" not in value,
                 "EXPOSURE_PATH", "可见性清单路径须为有效字符串")
        path = Path(value)
        _require(not path.is_absolute() and ".." not in path.parts
                 and path.as_posix() == value and value != ".",
                 "EXPOSURE_PATH", "源码引用须相对 workspace，不能越界")
        target = workspace / path
        _require(target.exists() and target.resolve().is_relative_to(workspace)
                 and not target.is_symlink(), "EXPOSURE_PATH", f"可见性引用不存在或越界：{value}")
        return path

    groups = {}
    for field in ("agent_visible_paths", "trusted_only_paths"):
        values = data.get(field)
        _require(isinstance(values, list) and values
                 and all(isinstance(v, str) for v in values)
                 and len(set(values)) == len(values),
                 "EXPOSURE_SCHEMA", f"{field} 须为非空且不重复的路径列表")
        groups[field] = [local(v) for v in values]
    for visible in groups["agent_visible_paths"]:
        _require(not any(visible.is_relative_to(private) or private.is_relative_to(visible)
                         for private in groups["trusted_only_paths"]),
                 "EXPOSURE_OVERLAP", "Agent 可见路径与私有路径重叠")
        _require(not any(visible.is_relative_to(private) or private.is_relative_to(visible)
                         for private in (Path("harbor_task/tests"), Path("reference"))),
                 "EXPOSURE_OVERLAP", "Agent 可见清单包含私有 tests 或 Reference")
    writable = data.get("agent_writable_paths")
    _require(isinstance(writable, list) and writable
             and all(isinstance(v, str) and Path(v).is_absolute() and ".." not in Path(v).parts
                     for v in writable), "EXPOSURE_SCHEMA", "可写清单须用运行时绝对路径")
    for name in ("final_image_digest", "verifier_image_digest"):
        _require(isinstance(data.get(name), str)
                 and re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", data[name]),
                 "EXPOSURE_SCHEMA", f"{name} 须为真实不可变镜像摘要")
    view = workspace / local(data.get("generated_agent_view_manifest"))
    _require(view.is_file() and view.stat().st_size > 0,
             "EXPOSURE_SCHEMA", "缺少从真实最终镜像及挂载采集的非空视图清单")
    _require(type(data.get("verified_as_uid")) is int and data["verified_as_uid"] >= 0,
             "EXPOSURE_SCHEMA", "须填写实际核验 UID")
    return {"status": "declarations_checked_not_isolation_certification",
            "path": "workspace/qa_exposure_manifest.json"}
