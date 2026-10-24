#!/usr/bin/env python3
"""Aggregate full evidence-backed legacy-task review without rerunning tasks.

The reviewer reads the supplied material. This tool validates review coverage,
references, the finite waiver policy and formal arithmetic; it does not infer
scientific or trajectory conclusions from keywords or execute submitted code.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import zipfile

import audit_format_repair as format_review
import content_gates

VERSION = "0.3.10-legacy-review.4.1"
STAGE = "legacy_task_review"
QA_TITLES = ["八章节与题面信息泄露", "评分公式与 0/1 锚点", "参考解分数与复现材料",
    "波动指标的 3σ 可分辨性", "约束执行实现", "Verifier 入口、分数与错误处理",
    "instruction 中的 Hidden 信息泄露", "instruction 中的参考解信息泄露",
    "结果清理与原子写入", "冻结面保护或恢复实现", "instruction 八项内容", "Git 清理",
    "Baseline 与参考解提升", "合法改进空间", "评分资源需求估算", "轨迹实际迭代时长",
    "Harbor Harness 兼容性", "轨迹、日志与分析", "seed 与有效提升阈值",
    "修改范围、网络与工具策略", "三个 JSON 的填写内容"]
QA = {f"QA{i:02d}": title for i, title in enumerate(QA_TITLES, 1)}
H = dict(zip((f"H{i:02d}" for i in range(1, 7)),
             ("任务目录", "版本与配置", "环境与运行路径", "测试入口与 reward", "Job/Trial 调用配置", "NOP 自检记录")))
T = {"T01": "第一条轨迹已有内容", "T02": "第二条轨迹已有内容"}
COMPARISON_DIMENSIONS = {"prompt", "task", "dev", "feedback", "constraints", "resources"}
COMPARISON_ASSESSMENTS = {"same_conditions", "editorial_only", "legacy_resource_difference", "substantive_difference", "historical_evidence_gap"}
COMPARISON_IMPACTS = {"editorial_only", "substantive", "legacy_format_or_resource"}
G02_DIMENSIONS = {
    "training_sufficiency": "训练充分性", "method_representativeness": "方法代表性",
    "budget_comparability": "原协议预算可比性", "implementation_correctness": "实现正确性",
    "selection_integrity": "选择与对照完整性",
}
OBSERVED = {"pass", "fail", "manual", "not_applicable"}
NA_ALLOWED = {"QA04", "QA19", "H05"}
# Scope is per finding, never a permission to waive an entire check.
WAIVERS = {
    "legacy_nop_or_current_trial_gap": {"H06"},
    "legacy_trajectory_schema_gap": {"QA18", "QA21", "T01", "T02"},
    "legacy_task_binding_migration": {"QA21"},
    "legacy_runtime_proof_gap": {"QA18", "T01", "T02"},
    "legacy_research_duration_gap": {"QA16", "T01", "T02"},
    "legacy_hardware_record_difference": {"QA15", "QA18", "T01", "T02"},
    "legacy_target_resource_evidence_gap": {"QA15"},
    "legacy_new_validation_dependency": {"G03", "QA03", "QA13"},
    "platform_image_preparation_pending": {"H03", "H05"},
    "platform_execution_verification_pending": {"H03", "H05", "H06"},
    "unsupported_network_policy_transition": {"QA05", "H02"},
    "historical_agent_runtime_finding": {"QA18", "H03", "T01", "T02"},
}
F_H = {"F01": {"H01", "H02"}, "F02": {"H03"}, "F03": {"H04"},
       "F04": {"H04"}, "F05": {"H03"}, "F06": {"H02"}, "F07": {"H04"}}


def harbor_format_owners(finding):
    """Attribute known format faults to the relevant Harbor check."""
    owner, code = finding["owner"], finding["code"]
    if owner == "F01":
        if code == "TASK_DIRECTORY_MISSING":
            return {"H01"}
        if code == "CORE_FILE_MISSING":
            return {"H02"} if any(Path(ref).name == "task.toml" for ref in finding.get("evidence", [])) else {"H01"}
        if code != "SEMANTIC_REVIEW_FAILURE":
            return {"H02"}
        # The generic F01 manual summary may concern a document, directory or
        # interface. Keep its real FAIL at the source instead of scattering it
        # across multiple Harbor rows without a known causal mapping.
        return set()
    if owner == "F06" and code == "COMPOSE_UNSUPPORTED":
        return {"H03"}
    return F_H.get(owner, set())


def require(condition, code, message):
    if not condition:
        raise format_review.ReviewError(code, message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def string_values(value):
    return [row for row in value if isinstance(row, str)] if isinstance(value, list) else []


def references(root, values, label, *, content=False):
    require(isinstance(values, list) and bool(values), "REVIEW_EVIDENCE", label + " 必须引用已审材料；不是专家新增交付要求。")
    files = []
    for ref in values:
        if ref == "@legacy_inventory":
            continue
        files.append(format_review.safe_reference(root, ref))
    require(not content or files, "REVIEW_NOT_FINISHED", label + " 需要实际内容证据，目录清单不能代替研究或轨迹审阅。")
    return values


def reviewed_item(root, original, check_id, title, *, content=False):
    require(isinstance(original, dict), "REVIEW_ITEM", check_id + " 必须为审核项对象。")
    require(original.get("review_complete") is True, "REVIEW_NOT_FINISHED", check_id + " 尚未完成实际内容审阅。")
    require(original.get("observed_status") in OBSERVED and nonempty(original.get("summary")),
            "REVIEW_ITEM", check_id + " 需保留原始观察状态及具体内容结论。")
    references(root, original.get("evidence"), check_id, content=content)
    findings = original.get("findings")
    require(isinstance(findings, list), "REVIEW_ITEM", check_id + " findings 应逐原因列明，已审无问题时使用空数组。")
    derived_qa17 = check_id == "QA17" and original.get("derived_from") == list(H)
    require(original["observed_status"] not in {"fail", "manual"} or bool(findings) or derived_qa17,
            "REVIEW_NOT_FINISHED", check_id + " 的 fail/manual 必须逐原因审明，不可整项免掉。")
    require(check_id not in {*content_gates.IDS, *T} or original["observed_status"] != "not_applicable",
            "REVIEW_NOT_FINISHED", check_id + " 为本轮必审内容，不能设为不适用。")
    if original["observed_status"] == "not_applicable":
        require(check_id in NA_ALLOWED, "REVIEW_NOT_FINISHED", check_id + " 必须审阅已有内容，不能以不适用跳过；历史缺口须逐原因说明。")
        require(nonempty(original.get("not_applicable_basis")), "REVIEW_NOT_FINISHED", check_id + " 需说明不适用依据。")
    output = copy.deepcopy(original)
    output.update(id=check_id, title=title, status="pass", original_observed_status=original["observed_status"])
    seen = set()
    for finding in output["findings"]:
        require(isinstance(finding, dict) and nonempty(finding.get("id")) and finding["id"] not in seen,
                "REVIEW_FINDING", check_id + " 的每个原因需唯一 id。")
        seen.add(finding["id"])
        require(finding.get("kind") in {"substantive", "legacy_gap"} and nonempty(finding.get("summary"))
                and finding.get("effect") in {"unwaived", "waived"}, "REVIEW_FINDING", check_id + " 需区分实质问题/旧题具体缺口及豁免效果。")
        references(root, finding.get("evidence"), check_id + "/" + finding["id"])
        if finding["effect"] == "waived":
            reason = finding.get("waiver_reason")
            require(finding["kind"] == "legacy_gap" and reason in WAIVERS and check_id in WAIVERS[reason],
                    "WAIVER_OUT_OF_SCOPE", check_id + " 的该原因不属于允许豁免范围；实质问题不能豁免。")
            require(nonempty(finding.get("waiver_basis")), "WAIVER_BASIS", check_id + " 需写明此具体原因的已有材料和适用依据。")
            if reason == "historical_agent_runtime_finding":
                require(finding.get("classification") in {"leakage", "cheating", "policy_only", "suspicious"}
                        and finding.get("certainty") in {"confirmed", "suspected"}
                        and finding.get("score_effect") in {"invalid", "unverified", "none"}
                        and nonempty(finding.get("score_effect_basis")), "WAIVER_SCORE_SCOPE", check_id + " 需据已读历史事实区分污染/仅部署规则差异，保留具体分数影响及依据，不得因普通关键词先定性违规。")
                require(finding.get("formal_br_affected") is False,
                        "WAIVER_FORMAL_SCORE_PROTECTION", check_id + " 需说明本次已读作者正式 B/R 未把受污染Agent分数作为正证；不要求新增污染排除证明。正式 B/R 自身无效不可豁免。")
                if finding["classification"] in {"leakage", "cheating"} and finding["certainty"] == "confirmed":
                    require(finding["score_effect"] == "invalid" and finding.get("affected_score_status", "invalid") == "invalid",
                            "WAIVER_SCORE_SCOPE", check_id + " 已确认泄漏/作弊须保留受影响分数无效，不能改成有效或无影响。")
                if finding.get("affected_score_status") is not None:
                    require(finding["affected_score_status"] in {"valid", "invalid", "unverified"}, "WAIVER_SCORE_SCOPE", check_id + " 的原分数状态无效。")
            finding["final_effect"] = "waived"
        elif finding["kind"] == "substantive":
            require(nonempty(finding.get("remediation")) and nonempty(finding.get("acceptance_evidence")),
                    "REVIEW_ACTION", check_id + " 的真实问题需要具体修改方向和验收依据。")
            finding["final_effect"] = "blocking"
        else:
            finding["final_effect"] = "review_not_finished"
    if any(row["final_effect"] == "blocking" for row in output["findings"]):
        output["status"] = "fail"
    elif any(row["final_effect"] == "review_not_finished" for row in output["findings"]):
        output["status"] = "review_not_finished"
    elif output["findings"]:
        output["status"] = "pass_with_waivers"
    elif original["observed_status"] == "not_applicable":
        output["status"] = "not_applicable"
    return output


def section(root, raw, titles, errors, *, content=False):
    result = []
    if (not isinstance(raw, list) or len(raw) != len(titles) or any(not isinstance(row, dict) for row in raw)
            or {row.get("id") for row in raw} != set(titles)):
        errors.append({"code": "REVIEW_NOT_FINISHED", "summary": "必须逐项完成 " + "、".join(titles) + "；不能以格式通过代替整题审阅。"})
        raw = raw if isinstance(raw, list) else []
    for check_id, title in titles.items():
        matched = [row for row in raw if isinstance(row, dict) and row.get("id") == check_id]
        if len(matched) != 1:
            result.append({"id": check_id, "title": title, "status": "review_not_finished", "review_complete": False,
                "observed_status": None, "summary": "质检员尚未完成该项内容审阅；未据缺失底稿推断通过或作者失败。", "evidence": [], "findings": []})
            continue
        try:
            result.append(reviewed_item(root, matched[0], check_id, title, content=content))
        except (format_review.ReviewError, OSError, ValueError, TypeError) as exc:
            errors.append({"code": getattr(exc, "code", "REVIEW_ITEM_ERROR"), "owner": check_id, "summary": str(exc)})
            failed = [f for f in matched[0].get("findings", []) if isinstance(f, dict) and f.get("kind") == "substantive"]
            result.append({"id": check_id, "title": title, "status": "fail" if failed else "review_not_finished",
                           "observed_status": matched[0].get("observed_status"), "summary": matched[0].get("summary", ""),
                           "evidence": matched[0].get("evidence", []), "findings": copy.deepcopy(matched[0].get("findings", [])),
                           "review_complete": False})
    return result


def validate_overview(root, raw):
    require(isinstance(raw, dict), "REVIEW_NOT_FINISHED", "缺少实际任务方法与 Baseline/Reference 概览。")
    surface, comparison = raw.get("optimization_surface"), raw.get("baseline_reference")
    require(isinstance(surface, dict) and isinstance(comparison, dict), "REVIEW_NOT_FINISHED", "overview 需有优化面及正式 B/R 对照。")
    for field in ("summary", "metric_and_gate"):
        require(nonempty(surface.get(field)), "REVIEW_NOT_FINISHED", "优化面需说明 " + field)
    for field in ("modifiable", "fixed"):
        require(isinstance(surface.get(field), list) and surface[field] and all(nonempty(v) for v in surface[field]),
                "REVIEW_NOT_FINISHED", "优化面需实际列明 " + field)
    references(root, surface.get("evidence"), "优化面", content=True)
    for field in ("baseline_method", "reference_method", "metric", "improvement_summary", "quality_gate_summary"):
        require(nonempty(comparison.get(field)), "REVIEW_NOT_FINISHED", "正式 B/R 概览需说明 " + field)
    require(comparison.get("direction") in {"minimize", "maximize"} and isinstance(comparison.get("paired_runs"), list),
            "REVIEW_NOT_FINISHED", "正式 B/R 需主指标方向及已有逐 run 原值。")
    seeds = []
    for pair in comparison["paired_runs"]:
        require(isinstance(pair, dict) and isinstance(pair.get("seed"), (str, int)) and not isinstance(pair.get("seed"), bool),
                "REVIEW_SCIENTIFIC_DATA", "paired_runs 的 seed/run 标识无效。")
        seeds.append(str(pair["seed"]))
        for key in ("baseline", "reference"):
            require(pair.get(key) is None or content_gates.finite(pair[key]), "REVIEW_SCIENTIFIC_DATA", key + " 应为原始有限数值或 null。")
        for key in ("baseline_valid", "reference_valid"):
            require(pair.get(key) is None or isinstance(pair[key], bool), "REVIEW_SCIENTIFIC_DATA", key + " 应据已有材料填写 boolean/null。")
    require(len(seeds) == len(set(seeds)), "REVIEW_SCIENTIFIC_DATA", "正式 paired_runs 不得重复 seed/run 标识。")
    for field in ("baseline_mean", "reference_mean", "baseline_sample_std", "reference_sample_std"):
        require(comparison.get(field) is None or content_gates.finite(comparison[field]), "REVIEW_SCIENTIFIC_DATA", field + " 应为有限数值或 null。")
    references(root, comparison.get("evidence"), "正式 B/R", content=True)
    return copy.deepcopy(raw)


def existing_prompt_difference_signals(root, evidence, legacy_comparison=None):
    """Read exact structured legacy flags, never infer semantics from keywords.

    False only means a comparison needs an explanation. It does not by itself
    distinguish a typo, a missing historical binding or a changed task contract.
    All supplied JSON carriers, including arrays and large files, remain valid.
    """
    signals = []
    if isinstance(legacy_comparison, dict) and legacy_comparison.get("identical_prompt") is False:
        signals.append("review.task_version_comparison.identical_prompt=false")
    for ref in dict.fromkeys(evidence):
        suffix = Path(ref).suffix.lower()
        if ref == "@legacy_inventory" or suffix not in {".json", ".jsonl", ".ndjson"}:
            continue
        path = format_review.safe_reference(root, ref)
        try:
            with path.open(encoding="utf-8-sig") as source:
                if suffix == ".json":
                    payloads = [json.load(source)]
                else:
                    payloads = []
                    for line in source:
                        if line.strip():
                            try:
                                payloads.append(json.loads(line))
                            except json.JSONDecodeError:
                                continue
        except (UnicodeError, json.JSONDecodeError):
            # A source may be a nonstandard old log carrier. Its actual content
            # is still the reviewer's responsibility, not an automatic rejection.
            continue
        stack = payloads
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                flag = node.get("task_version_comparison")
                if isinstance(flag, dict) and flag.get("identical_prompt") is False:
                    signals.append(ref + ":task_version_comparison.identical_prompt=false")
                    break
                stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
            elif isinstance(node, list):
                stack.extend(value for value in node if isinstance(value, (dict, list)))
    return signals


def assess_comparability(root, raw, trajectories, qa18, errors, legacy_comparison=None, additional_sources=None):
    """Validate the reviewer's actual two-run comparison, not an author schema.

    The model/reviewer must read the original prompts, task snapshots, Dev,
    feedback and restrictions. This validator cannot establish their semantic
    equivalence. It prevents an omitted comparison or a known substantive
    difference from disappearing behind a handwritten QA18 pass or waiver.
    """
    value = copy.deepcopy(raw) if isinstance(raw, dict) else {
        "review_complete": False, "assessment": None, "summary": "尚未实际对比两轨条件。",
        "evidence": [], "compared_dimensions": [], "differences": []}
    differences = value.get("differences")
    differences = differences if isinstance(differences, list) else []
    substantive = value.get("assessment") == "substantive_difference" or any(
        isinstance(row, dict) and row.get("impact") == "substantive" for row in differences)
    value["comparison_validity"] = "not_comparable" if substantive else "review_not_finished"
    value["individual_trajectory_validity_changed"] = False
    value["reviewer_scope"] = "质检员内部对比底稿；不要求专家新增字段、Prompt快照、hash或重跑。语义判断须实际阅读原材料，脚本只核验审阅覆盖及判定一致性。"
    # Retain a known substantive fact even when another part of the worksheet
    # still needs work. An incomplete worksheet must never erase a true FAIL.
    if substantive and qa18 is not None:
        relevant = [row for row in differences if isinstance(row, dict) and row.get("impact") == "substantive"]
        evidence = [ref for row in relevant for ref in string_values(row.get("evidence"))]
        evidence += string_values(value.get("evidence"))
        details = "；".join(row.get("summary", "") for row in relevant if nonempty(row.get("summary")))
        qa18.setdefault("findings", []).append({"id": "automatic_two_trajectory_comparability", "kind": "substantive",
            "effect": "unwaived", "final_effect": "blocking", "summary": "两轨存在实质条件差异，不能作为同Prompt/任务/Dev/反馈/约束/资源条件的成对研究对照。" + details,
            "evidence": list(dict.fromkeys(evidence)), "remediation": "保留并说明两轨各自条件和结果，纠正同条件对照的声明；修改当前instruction.md不能追溯统一原两轨。若要主张同条件成对对照，需有真实同条件的既有有效记录；不能用格式迁移或旧字段缺口豁免实质差异。",
            "acceptance_evidence": "可定位的两轨原始任务条件、逐项差异和相应结论；单轨可各自有效，但不得据条件不一致的记录声称同条件优劣。"})
        qa18["status"] = "fail"
    try:
        require(isinstance(raw, dict) and value.get("review_complete") is True,
                "REVIEW_COMPARISON_NOT_FINISHED", "QA18尚未完成两轨实际条件对比；不能只看轨迹存在、独立或run_summary一致。这是质检员未完成工作，不是专家新交付要求。")
        assessment = value.get("assessment")
        require(assessment in COMPARISON_ASSESSMENTS and nonempty(value.get("summary")),
                "REVIEW_COMPARISON_NOT_FINISHED", "两轨对比需说明same_conditions/editorial_only/legacy_resource_difference/substantive_difference/historical_evidence_gap及实际内容结论。")
        dimensions = value.get("compared_dimensions")
        require(isinstance(dimensions, list) and all(isinstance(v, str) for v in dimensions)
                and len(dimensions) == len(COMPARISON_DIMENSIONS) and set(dimensions) == COMPARISON_DIMENSIONS,
                "REVIEW_COMPARISON_NOT_FINISHED", "两轨需逐维看过prompt、task、dev、feedback、constraints、resources，不能把不同任务条件误当普通旧字段缺口。")
        references(root, value.get("evidence"), "两轨条件对比", content=True)
        paths = {row.get("source_path") for row in trajectories if nonempty(row.get("source_path"))}
        require(len(trajectories) == 2 and paths.issubset(set(value["evidence"])),
                "REVIEW_COMPARISON_NOT_FINISHED", "两轨对比依据必须定位两条实际主轨迹；原Prompt/配置/Dev等已提供材料也应实际读取并引用。合并日志可使用原run定位。")
        require(isinstance(value.get("differences"), list), "REVIEW_COMPARISON_NOT_FINISHED", "两轨differences需逐处记录差异；确实相同时为空数组。")
        for row in differences:
            require(isinstance(row, dict) and row.get("dimension") in COMPARISON_DIMENSIONS
                    and row.get("impact") in COMPARISON_IMPACTS and nonempty(row.get("summary")),
                    "REVIEW_COMPARISON_NOT_FINISHED", "两轨每处差异需维度、影响与实际内容说明；不能仅凭不同hash判断实质变化。")
            references(root, row.get("evidence"), "两轨具体条件差异", content=True)
        impacts = {row["impact"] for row in differences}
        legacy_resources = [row for row in differences if row["impact"] == "legacy_format_or_resource" and row["dimension"] == "resources"]
        only_editorial_or_legacy_resources = all(row["impact"] == "editorial_only" or row in legacy_resources for row in differences)
        consistent = ((assessment == "same_conditions" and not differences)
            or (assessment == "editorial_only" and "editorial_only" in impacts and only_editorial_or_legacy_resources)
            or (assessment == "legacy_resource_difference" and bool(differences) and len(legacy_resources) == len(differences))
            or (assessment == "substantive_difference" and "substantive" in impacts)
            or (assessment == "historical_evidence_gap" and "substantive" not in impacts))
        require(consistent, "REVIEW_COMPARISON_INCONSISTENT", "两轨总体assessment与具体差异影响不一致；已知实质差异仍保留QA18失败，不能用总栏pass或历史豁免覆盖。")
        signal_sources = value["evidence"] + [ref for row in trajectories for ref in string_values(row.get("reviewed_sources"))]
        signal_sources += string_values(qa18.get("evidence")) if qa18 is not None else []
        signal_sources += string_values(additional_sources)
        signals = existing_prompt_difference_signals(root, signal_sources, legacy_comparison)
        value["existing_prompt_difference_signals"] = signals
        value["existing_flag_scan_scope"] = "对比底稿依据、QA18/QA21依据及两轨已读来源中的结构化JSON/JSONL；不宣称自动理解Prompt或会话语义。"
        require(not signals or (assessment != "same_conditions" and any(row["dimension"] == "prompt" for row in differences)),
                "REVIEW_COMPARISON_INCONSISTENT", "既有task_version_comparison.identical_prompt=false必须逐处说明Prompt差异及语义影响，不能直接声称同条件；false本身不自动等于实质差异。")
        value["comparison_validity"] = ("not_comparable" if substantive else "unverified" if assessment == "historical_evidence_gap"
            else "comparable_with_legacy_waivers" if legacy_resources else "comparable")
        if assessment == "historical_evidence_gap" and qa18 is not None and qa18.get("review_complete"):
            qa18["findings"].append({"id": "automatic_historical_comparison_gap", "kind": "legacy_gap", "effect": "waived", "final_effect": "waived",
                "summary": "已实际对比现有两轨材料，旧版材料仍不足以证明所有历史条件一致；仅此记录缺口豁免，不声称已证实同条件。" + value["summary"],
                "evidence": value["evidence"], "waiver_reason": "legacy_runtime_proof_gap",
                "waiver_basis": "本轮旧题迁移不要求新增Prompt快照、hash或重跑；已读资料中没有已确认的实质条件差异。"})
            if qa18["status"] == "pass":
                qa18["status"] = "pass_with_waivers"
        elif legacy_resources and qa18 is not None and qa18.get("review_complete"):
            qa18["findings"].append({"id": "automatic_legacy_comparison_resource_difference", "kind": "legacy_gap", "effect": "waived", "final_effect": "waived",
                "summary": "已核实的历史资源差异按迁移政策保留并豁免，不改写成完全相同，也不归为无证据。" + "；".join(row["summary"] for row in legacy_resources),
                "evidence": list(dict.fromkeys(ref for row in legacy_resources for ref in row["evidence"])), "waiver_reason": "legacy_hardware_record_difference",
                "waiver_basis": "本轮允许已有历史资源记录差异；原条件、最终统一条件验证及可比范围按已读材料说明，不新增换卡重跑义务。正式B/R实质预算不公平仍由G02独立审查。"})
            if qa18["status"] == "pass":
                qa18["status"] = "pass_with_waivers"
    except (format_review.ReviewError, OSError, ValueError, TypeError) as exc:
        errors.append({"code": getattr(exc, "code", "REVIEW_COMPARISON_ERROR"), "owner": "QA18", "summary": str(exc)})
        value["review_complete"] = False
        if qa18 is not None:
            qa18["review_complete"] = False
            if qa18["status"] != "fail":
                qa18["status"] = "review_not_finished"
    return value


def template(scan):
    base = format_review.review_template(scan)
    base["stage"] = STAGE
    def blank(check_id):
        return {"id": check_id, "review_complete": False, "observed_status": None,
                "summary": "", "evidence": [], "findings": []}
    base.update(overview={"optimization_surface": {"summary": "", "modifiable": [], "fixed": [], "metric_and_gate": "", "evidence": []},
                         "baseline_reference": {"baseline_method": "", "reference_method": "", "metric": "", "direction": None,
                             "paired_runs": [], "improvement_summary": "", "quality_gate_summary": "", "evidence": []}},
                content_gates={"schema_version": 1, "checks": [blank(key) for key in content_gates.IDS]},
                items21=[blank(key) for key in QA], harbor6=[blank(key) for key in H],
                trajectory_content_review={"trajectories": [{**blank(key), "name": "", "source_path": None,
                    "reviewed_sources": [], "method_summary": "", "iteration_summary": "", "final_result": "", "score_use_conclusion": ""} for key in T],
                    "comparability": {"review_complete": False, "assessment": None, "summary": "", "evidence": [],
                        "compared_dimensions": [], "differences": [],
                        "assessment_help": "same_conditions完全相同；editorial_only仅文字语义等价（可同时保留已授权旧资源差异）；legacy_resource_difference仅已核实且可豁免的历史资源差异；substantive_difference真实语义差异；historical_evidence_gap已审但旧证明不足。"}},
                reviewer_note="质检员实际阅读原有材料后填写全部三门、21项、6项Harbor、两轨及两轨六维条件对比；comparability为质检员内部底稿，不要求专家新增schema、Prompt快照、NOP/哈希/换卡重跑。语义差异由实际内容审阅判断，脚本不替代模型内容判断。")
    base["content_gates"]["checks"][1]["dimensions"] = {key: {"summary": "", "evidence": []} for key in G02_DIMENSIONS}
    base["content_gates"]["checks"][2]["assessment"] = {
        "direction": None, "evaluation_mode": None, "formal_seeds": [], "declared_run_count": None,
        "same_protocol": None, "quality_valid": None, "upper_bound": None, "threshold_basis": "",
        "absolute_min_improvement": None, "absolute_threshold_source": ""}
    return base


def assess(root, review=None):
    root = Path(root).resolve()
    result = {"schema_version": 1, "version": VERSION, "stage": STAGE, "decision": "ERROR", "code": "REVIEW_NOT_FINISHED",
        "generated_at": datetime.now(timezone.utc).isoformat(), "review_completed": False, "is_task_rejection": False,
        "platform_runtime_status": "not_executed", "task_code_executed": False, "overview": None,
        "content_gates": {"schema_version": 1, "checks": []}, "items21": [], "harbor6": [],
        "trajectory_content_review": {"trajectories": [], "comparability": None}, "input_and_review_errors": [],
        "scope_note": "逐项审阅已有研究与实现材料后按具体历史原因豁免；不补跑、不以格式前检代替完整质检。"}
    errors = result["input_and_review_errors"]
    try:
        scan = format_review.inventory(root, review)
        result["review_template"] = template(scan)
        result["task_root"] = scan["task_root"]
        result["legacy_inventory"] = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size}
            for p in sorted(root.rglob("*")) if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root)]
        require(review is not None, "REVIEW_NOT_PROVIDED", "已生成完整审核模板；质检员须审完所有内容，不能只检查格式。")
        require(review.get("schema_version") == 1 and review.get("stage") == STAGE, "REVIEW_SCHEMA", "完整审核使用schema_version=1、stage=legacy_task_review。")
        precheck = copy.deepcopy(review)
        precheck["stage"] = "format_repair"
        result["format_precheck"] = format_review.assess(root, precheck)
        if result["format_precheck"]["decision"] == "ERROR":
            errors.extend({"code": "FORMAT_REVIEW_NOT_FINISHED", "summary": message} for message in result["format_precheck"].get("input_and_review_errors", []))
        try:
            result["overview"] = validate_overview(root, review.get("overview"))
        except (format_review.ReviewError, OSError, ValueError, TypeError) as exc:
            errors.append({"code": getattr(exc, "code", "REVIEW_OVERVIEW"), "summary": str(exc)})
        gates = review.get("content_gates", {})
        result["content_gates"]["checks"] = section(root, gates.get("checks") if isinstance(gates, dict) else None, content_gates.TITLES, errors, content=True)
        g02 = next(row for row in result["content_gates"]["checks"] if row["id"] == "G02")
        if g02.get("review_complete"):
            try:
                dims = g02.get("dimensions")
                require(isinstance(dims, dict) and set(dims) == set(G02_DIMENSIONS), "REVIEW_NOT_FINISHED", "G02需逐维审阅已有Baseline训练、方法、预算、实现和选择依据。")
                for key, label in G02_DIMENSIONS.items():
                    value = dims[key]
                    if isinstance(value, str):
                        require(nonempty(value), "REVIEW_NOT_FINISHED", "G02 " + label + " 内容未审完。")
                    else:
                        require(isinstance(value, dict) and nonempty(value.get("summary")), "REVIEW_NOT_FINISHED", "G02 " + label + " 需实际事实说明。")
                        references(root, value.get("evidence"), "G02 " + label, content=True)
            except (format_review.ReviewError, OSError, ValueError, TypeError) as exc:
                errors.append({"code": getattr(exc, "code", "REVIEW_BASELINE"), "owner": "G02", "summary": str(exc)})
                g02["review_complete"] = False
                if g02["status"] != "fail":
                    g02["status"] = "review_not_finished"
        result["items21"] = section(root, review.get("items21"), QA, errors)
        result["harbor6"] = section(root, review.get("harbor6"), H, errors)
        evaluation_mode = next((row.get("assessment", {}).get("evaluation_mode") for row in result["content_gates"]["checks"] if row["id"] == "G03" and isinstance(row.get("assessment"), dict)), None)
        for row in result["items21"]:
            if row["id"] in {"QA04", "QA19"} and row.get("observed_status") == "not_applicable" and evaluation_mode != "deterministic":
                errors.append({"code": "REVIEW_NOT_FINISHED", "owner": row["id"], "summary": "QA04/QA19仅在已据原材料核实为确定性评估并与G03一致时不适用，不能跳过随机波动与seed审阅。"})
                row["review_complete"] = False
                if row["status"] != "fail":
                    row["status"] = "review_not_finished"
        tr = review.get("trajectory_content_review", {})
        trajectories = section(root, tr.get("trajectories") if isinstance(tr, dict) else None, T, errors, content=True)
        result["trajectory_content_review"]["trajectories"] = trajectories
        for row in trajectories:
            if not row.get("review_complete"):
                continue
            try:
                for field in ("name", "source_path", "method_summary", "iteration_summary", "final_result", "score_use_conclusion"):
                    require(nonempty(row.get(field)), "REVIEW_NOT_FINISHED", row["id"] + " 需实际审阅并说明 " + field)
                format_review.safe_reference(root, row["source_path"])
                references(root, row.get("reviewed_sources"), row["id"] + " 已读轨迹/分析", content=True)
                require(row["source_path"] in row["reviewed_sources"], "REVIEW_NOT_FINISHED", row["id"] + " 主轨迹必须在已读来源内，不得仅看摘要或清单。")
            except (format_review.ReviewError, OSError, ValueError, TypeError) as exc:
                errors.append({"code": getattr(exc, "code", "REVIEW_TRAJECTORY"), "owner": row["id"], "summary": str(exc)})
                row["review_complete"] = False
                if row["status"] != "fail":
                    row["status"] = "review_not_finished"
        if len(trajectories) == 2 and all(row.get("review_complete") for row in trajectories):
            if trajectories[0]["name"] == trajectories[1]["name"]:
                errors.append({"code": "REVIEW_NOT_FINISHED", "summary": "两轨需分别定位真实运行，不能同名复制。"})
            if trajectories[0]["source_path"] == trajectories[1]["source_path"] and not (
                    all(nonempty(row.get("run_locator")) for row in trajectories) and trajectories[0]["run_locator"] != trajectories[1]["run_locator"]):
                errors.append({"code": "REVIEW_NOT_FINISHED", "summary": "合并日志可以保留，但质检员需据现材料分别定位两个run；不要求专家拆文件或补跑。"})
        qa18 = next((row for row in result["items21"] if row["id"] == "QA18"), None)
        qa21 = next((row for row in result["items21"] if row["id"] == "QA21"), {})
        result["trajectory_content_review"]["comparability"] = assess_comparability(
            root, tr.get("comparability") if isinstance(tr, dict) else None, trajectories, qa18, errors,
            review.get("task_version_comparison"), qa21.get("evidence"))
        g03 = next((row for row in result["content_gates"]["checks"] if row["id"] == "G03"), None)
        if g03 and result["overview"]:
            try:
                numerical = content_gates.assess_improvement(result["overview"]["baseline_reference"], g03.get("assessment"))
                g03["numerical_assessment"] = numerical
                g03["computed"] = numerical["computed"]
                if numerical["failures"]:
                    g03["status"] = "fail"
                    g03["findings"].append({"id": "automatic_formal_comparison", "kind": "substantive", "effect": "unwaived", "final_effect": "blocking",
                        "summary": "；".join(numerical["failures"]), "evidence": result["overview"]["baseline_reference"]["evidence"],
                        "remediation": "核对已有正式 B/R 与评分定义，纠正实质数值、协议或质量有效性问题；迁移记录豁免不能证明科学门达标。",
                        "acceptance_evidence": "可信已有原始对照结果、相同协议与质量门依据及可重算的阈值计算。"})
                if numerical["missing"]:
                    errors.append({"code": "REVIEW_SCIENTIFIC_EVIDENCE_NOT_FINISHED", "owner": "G03", "summary": "需质检员从原材料核清正式数值与原协议，不能自动通过，也不要求因新环境补跑：" + "；".join(numerical["missing"])})
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                errors.append({"code": "REVIEW_SCIENTIFIC_DATA", "owner": "G03", "summary": str(exc)})
        # Repeated Harbor findings still appear under H; links identify their
        # deterministic format root cause rather than hiding them as waivers.
        format_faults = copy.deepcopy(result["format_precheck"].get("current_findings", []))
        for frow in result["format_precheck"].get("checks", []):
            if frow["status"] == "fail" and frow.get("review_status") == "fail":
                format_faults.append({"owner": frow["id"], "code": "SEMANTIC_REVIEW_FAILURE", "summary": frow["summary"],
                    "evidence": frow["evidence"], "remediation": frow.get("remediation", ""), "acceptance_evidence": frow.get("acceptance_evidence", "")})
        for row in result["harbor6"]:
            linked = [f for f in format_faults if row["id"] in harbor_format_owners(f)]
            if linked:
                row["format_root_causes"] = copy.deepcopy(linked)
                row["status"] = "fail"
        qa17 = next((row for row in result["items21"] if row["id"] == "QA17"), None)
        if qa17:
            qa17["harbor_derived_from"] = [{"id": row["id"], "status": row["status"]} for row in result["harbor6"]]
            if any(row["status"] == "fail" for row in result["harbor6"]):
                qa17["status"] = "fail"
            elif len(result["harbor6"]) != 6 or any(not row.get("review_complete") or row["status"] == "review_not_finished" for row in result["harbor6"]):
                if qa17["status"] != "fail":
                    qa17["status"] = "review_not_finished"
            elif qa17["status"] == "pass" and any(row["status"] == "pass_with_waivers" for row in result["harbor6"]):
                qa17["status"] = "pass_with_waivers"
        all_items = result["content_gates"]["checks"] + result["items21"] + result["harbor6"] + trajectories
        if any(row["status"] == "review_not_finished" for row in all_items):
            errors.append({"code": "REVIEW_NOT_FINISHED", "summary": "仍有未审明具体原因的项目，应由质检员继续读已有材料，不能转成专家新增补跑要求。"})
        true_fail = result["format_precheck"]["decision"] == "FAIL" or bool(result["format_precheck"].get("current_findings")) or any(row["status"] == "fail" for row in all_items)
        result["review_completed"] = not errors and len(all_items) == 32
        result["decision"] = "FAIL" if true_fail else "ERROR" if errors else "PASS_WITH_WAIVERS"
        result["code"] = "SUBSTANTIVE_FINDINGS" if true_fail else "REVIEW_NOT_FINISHED" if errors else "FULL_LEGACY_REVIEW_COMPLETED"
        result["is_task_rejection"] = true_fail
        result["reviewed_counts"] = {"gates": len(result["content_gates"]["checks"]), "qa": len(result["items21"]), "harbor": len(result["harbor6"]), "trajectories": len(trajectories)}
    except (format_review.ReviewError, OSError, ValueError, TypeError, KeyError) as exc:
        errors.append({"code": getattr(exc, "code", "INPUT_OR_REVIEW_ERROR"), "summary": str(exc)})
        fail = any(row.get("status") == "fail" for row in result["content_gates"]["checks"] + result["items21"] + result["harbor6"] + result["trajectory_content_review"]["trajectories"])
        fail |= result.get("format_precheck", {}).get("decision") == "FAIL" or bool(result.get("format_precheck", {}).get("current_findings"))
        result["decision"], result["is_task_rejection"] = ("FAIL", True) if fail else ("ERROR", False)
        result["code"] = "SUBSTANTIVE_FINDINGS" if fail else getattr(exc, "code", "INPUT_OR_REVIEW_ERROR")
    return result


def render(result, *, expert=False):
    lines = ["# 旧题完整质检与逐原因豁免", "", "本轮结论：" + result["decision"], "阶段：" + STAGE,
        "已完成全部内容审阅：" + ("是" if result.get("review_completed") else "否"), "",
        result.get("scope_note", ""), "平台实跑：not_executed；未执行模型、题目程序、Docker 或 Harbor。", ""]
    overview = result.get("overview")
    if overview:
        surface, comp = overview["optimization_surface"], overview["baseline_reference"]
        lines += ["## 方法与正式对照", "", surface["summary"], "可修改：" + "；".join(surface["modifiable"]),
            "冻结面：" + "；".join(surface["fixed"]), "指标与质量门：" + surface["metric_and_gate"],
            "Baseline：" + comp["baseline_method"], "Reference：" + comp["reference_method"],
            "正式改善：" + comp["improvement_summary"], "质量有效性：" + comp["quality_gate_summary"],
            "已有原始对照：" + json.dumps(comp["paired_runs"], ensure_ascii=False), "依据：" + "；".join(comp["evidence"]), ""]
    sections = [("研究三门", result.get("content_gates", {}).get("checks", [])), ("21 项内容与实现", result.get("items21", [])),
                ("Harbor 六项", result.get("harbor6", [])), ("两轨已有内容", result.get("trajectory_content_review", {}).get("trajectories", []))]
    for title, rows in sections:
        lines += ["## " + title, ""]
        for row in rows:
            lines += [f"### {row['id']} {row['title']}", "", f"观察判定：{row.get('observed_status')}；本轮判定：{row['status']}",
                row.get("summary", ""), "审阅依据：" + "；".join(row.get("evidence", []))]
            if row.get("not_applicable_basis"):
                lines += ["不适用依据：" + row["not_applicable_basis"]]
            for field, label in (("method_summary", "方法"), ("iteration_summary", "迭代内容"), ("final_result", "最终结果"), ("score_use_conclusion", "分数采用范围")):
                if field in row:
                    lines += [label + "：" + row[field]]
            if "reviewed_sources" in row:
                lines += ["已读来源：" + "；".join(row["reviewed_sources"])]
            if row.get("computed") is not None:
                lines += ["正式复算：" + json.dumps(row["computed"], ensure_ascii=False)]
            if row.get("dimensions"):
                for key, label in G02_DIMENSIONS.items():
                    value = row["dimensions"].get(key)
                    if isinstance(value, dict):
                        lines += [label + "：" + value.get("summary", ""), "  依据：" + "；".join(value.get("evidence", []))]
                    elif isinstance(value, str):
                        lines += [label + "：" + value]
            for finding in row.get("findings", []):
                lines += ["- " + finding.get("summary", "") + "；处理：" + finding.get("effect", "未核清"), "  依据：" + "；".join(finding.get("evidence", []))]
                if finding.get("effect") == "waived":
                    lines += ["  豁免原因：" + str(finding.get("waiver_reason")) + "；" + finding.get("waiver_basis", "")]
                    if finding.get("affected_score_status"):
                        lines += ["  原分数状态：" + finding["affected_score_status"]]
                    if finding.get("classification"):
                        lines += ["  历史事实：" + finding["classification"] + "/" + finding["certainty"] + "；分数影响：" + finding["score_effect"],
                                  "  影响依据：" + finding["score_effect_basis"], "  受污染或未证实的Agent分数不作为作者正式 B/R 正证；仅部署规则差异不自动改写分数。"]
                elif finding.get("kind") == "substantive":
                    lines += ["  修改方向：" + finding.get("remediation", ""), "  验收：" + finding.get("acceptance_evidence", "")]
            for finding in row.get("format_root_causes", []):
                lines += ["- 当前格式实质问题（来自 " + finding["owner"] + "）：" + finding["summary"], "  定位：" + "；".join(finding.get("evidence", []))]
            if row.get("harbor_derived_from"):
                lines += ["Harbor逐项派生：" + "；".join(item["id"] + "=" + item["status"] for item in row["harbor_derived_from"])]
            lines += [""]
    comparison = result.get("trajectory_content_review", {}).get("comparability")
    if comparison:
        lines += ["## 两轨实际条件对比", "", "对比已完成：" + ("是" if comparison.get("review_complete") else "否"),
            "条件判断：" + str(comparison.get("assessment")) + "；成对对照有效性：" + str(comparison.get("comparison_validity")),
            str(comparison.get("summary", "")), "已对比维度：" + "、".join(string_values(comparison.get("compared_dimensions"))),
            "对比依据：" + "；".join(string_values(comparison.get("evidence"))), comparison.get("reviewer_scope", "")]
        for difference in comparison.get("differences", []) if isinstance(comparison.get("differences"), list) else []:
            if isinstance(difference, dict):
                lines += ["- " + str(difference.get("dimension")) + " / " + str(difference.get("impact")) + "：" + str(difference.get("summary", "")),
                    "  依据：" + "；".join(string_values(difference.get("evidence")))]
        if comparison.get("existing_prompt_difference_signals"):
            lines += ["既有版本差异标记已核对：" + "；".join(comparison["existing_prompt_difference_signals"])]
        if comparison.get("comparison_validity") == "not_comparable":
            lines += ["两条轨迹可分别保留其自身有效结果，但不能作为同条件成对比较；修改当前instruction.md不会追溯统一历史Prompt、反馈及约束，历史字段豁免不能消除已确认的实质差异。"]
        lines += [""]
    precheck = result.get("format_precheck")
    if precheck:
        lines += ["## 当前格式前检 F01–F07（子检查）", "", "format_decision：" + precheck["decision"],
                  "以下仅为当前格式子检查；整题结论以本报告顶部完整质检结果为准。", ""]
        for row in precheck.get("checks", []):
            lines += [f"- {row['id']} [{row['status']}] {row['title']}：{row['summary']}",
                      "  格式审阅依据：" + "；".join(row.get("evidence", []))]
            for finding in row.get("automatic_findings", []):
                lines += ["  已确认当前格式问题：" + finding["summary"], "  定位：" + "；".join(finding.get("evidence", []))]
            if row["status"] == "fail" and row.get("remediation"):
                lines += ["  修改方向：" + row["remediation"], "  验收：" + row.get("acceptance_evidence", "")]
        lines += ["", "## 平台后续事项（不阻断本轮已有材料审阅）", ""]
        for row in precheck.get("platform_followup_pending", []):
            summary = ("已有原硬件结果本轮复核；不把旧值改称新硬件实测，不要求新环境补跑；平台核对实际当前提交物移交及目标硬件运行。"
                       if row.get("id") == "RUNTIME_TRANSFER" else row["summary"])
            lines += ["- " + summary]
        if precheck.get("platform_observations"):
            lines += ["- " + row["summary"] for row in precheck["platform_observations"]]
    if result.get("input_and_review_errors"):
        lines += ["## 质检流程需继续完成的部分", "", "以下由质检员继续审阅已有材料，不是专家新增文件或补跑要求。"]
        lines += ["- " + row["code"] + "：" + row["summary"] for row in result["input_and_review_errors"]]
    return "\n".join(lines) + "\n"


def write_report(result, out):
    output = copy.deepcopy(result)
    review_template = output.pop("review_template", None)
    serialized = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    for filename in ("legacy_review_report.json", "report.json"):
        format_review.atomic_write(out / filename, serialized)
    for filename in ("legacy_review_report.md", "legacy_review_report.txt", "report.md", "report.txt"):
        format_review.atomic_write(out / filename, render(output))
    format_review.atomic_write(out / "return_to_expert.txt", render(output, expert=True))
    if output.get("format_precheck"):
        format_review.atomic_write(out / "format_precheck.json", json.dumps(output["format_precheck"], ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        child = copy.deepcopy(output["format_precheck"])
        child.pop("review_template", None)
        child["report_scope"] = "仅格式子报告，不代表整题质检结论；总审见 report.json / report.md / report.txt。"
        format_review.atomic_write(out / "format_report.json", json.dumps(child, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        child_text = "# 仅格式前检子报告\n\n不代表整题质检结论；完整三门、21项、Harbor六项、两轨与豁免结论请看 report.*。\n\n" + format_review.render(child)
        for filename in ("format_report.md", "format_report.txt"):
            format_review.atomic_write(out / filename, child_text)
    if review_template is not None:
        format_review.atomic_write(out / "review_template.json", json.dumps(review_template, ensure_ascii=False, indent=2) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--review", type=Path, help="reviewer's complete G01–G03, QA01–QA21, H01–H06, two-trajectory and F01–F07 worksheet")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    source, out = args.source.expanduser().resolve(), args.out_dir.expanduser().resolve()
    names = {"legacy_review_report.json", "legacy_review_report.md", "legacy_review_report.txt", "report.json", "report.md", "report.txt", "return_to_expert.txt", "format_precheck.json", "format_report.json", "format_report.md", "format_report.txt", "review_template.json"}
    if out == source or (source.is_dir() and out.is_relative_to(source)) or any(source == out / name for name in names):
        parser.error("outputs must be outside and must not overwrite the submitted artifact")
    if args.review and (args.review.expanduser().resolve() == out or any(args.review.expanduser().resolve() == out / name for name in names)):
        parser.error("outputs must not overwrite the review; use e.g. legacy_review.json")
    try:
        review = format_review.json_object(args.review) if args.review else None
        if source.is_dir():
            result = assess(source, review)
        elif source.is_file() and zipfile.is_zipfile(source):
            with tempfile.TemporaryDirectory(prefix="legacy-task-review-") as temporary:
                root = Path(temporary).resolve()
                format_review.unpack(source, root)
                result = assess(root, review)
        else:
            raise format_review.ReviewError("INPUT_UNREADABLE", "输入应为完整包目录或ZIP；工具未判退题目。")
    except (OSError, ValueError, TypeError, UnicodeError, zipfile.BadZipFile) as exc:
        result = {"schema_version": 1, "version": VERSION, "stage": STAGE, "decision": "ERROR", "code": getattr(exc, "code", "INPUT_OR_REVIEW_ERROR"),
            "review_completed": False, "is_task_rejection": False, "platform_runtime_status": "not_executed", "task_code_executed": False,
            "input_and_review_errors": [{"code": getattr(exc, "code", "INPUT_OR_REVIEW_ERROR"), "summary": str(exc)}]}
    result["source"] = str(source)
    write_report(result, out)
    print(json.dumps({"decision": result["decision"], "code": result["code"], "report": str(out / "legacy_review_report.json")}, ensure_ascii=False))
    return 0 if result["decision"] == "PASS_WITH_WAIVERS" else 1 if result["decision"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
