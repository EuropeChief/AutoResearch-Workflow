"""Evidence-backed research gates; reads reviewer data, never submission code."""
from __future__ import annotations

import math
import statistics

IDS = ("G01", "G02", "G03")
TITLES = {"G01": "方法级优化空间", "G02": "Baseline 合理性", "G03": "Reference 提升充分性"}
STATUSES = {"pass", "fail", "manual"}


def text(value):
    return isinstance(value, str) and bool(value.strip())


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def empty():
    return {"schema_version": 1, "checks": [
        {"id": key, "title": TITLES[key], "status": "manual", "summary": "尚未完成证据复核。",
         "evidence": [], "reason_code": "NOT_REVIEWED", "remediation": "", "acceptance_evidence": ""}
        for key in IDS]}


def assess_improvement(comparison, assessment):
    """Recompute the formal comparison. Missing facts cannot imply a pass."""
    failures, missing, warnings, actions = [], [], [], []
    computed = {}

    def fail(message, action):
        failures.append(message)
        actions.append(action)

    def absent(message, action):
        missing.append(message)
        actions.append(action)

    if not isinstance(assessment, dict):
        assessment = {}
    direction = assessment.get("direction")
    mode = assessment.get("evaluation_mode")
    if direction not in ("minimize", "maximize"):
        absent("指标方向待确认", "注明正式主指标是越高越好还是越低越好，并与原始结果对齐")
    elif comparison.get("direction") != direction:
        fail("G03 与跑分概览的指标方向冲突", "统一 G03、逐轮结果和跑分概览的主指标方向")
    if mode not in ("stochastic", "deterministic"):
        absent("未确认随机或确定性评估模式", "说明评估中的随机性来源及正式重复运行协议")
    if not text(assessment.get("threshold_basis")):
        absent("缺少阈值口径来源", "注明采用的 3σ/归一化分数口径及任务另行约定阈值的来源")
    for field, label in (("same_protocol", "同协议比较"), ("quality_valid", "质量门有效性")):
        value = assessment.get(field)
        if value is False:
            fail(label + "未满足", "按相同数据、评测及预算协议提交两组通过质量门的正式结果")
        elif value is not True:
            absent(label + "待确认", "核对并记录两组正式结果的协议、预算和质量门是否一致有效")
    pairs = comparison.get("paired_runs", [])
    seeds = assessment.get("formal_seeds")
    declared = assessment.get("declared_run_count")
    if not isinstance(seeds, list) or not seeds:
        absent("未声明完整正式 seed 集", "提供正式 seed 清单，并按同一 seed 配对 Baseline 与 Reference")
        seeds = []
    elif any(not isinstance(seed, (str, int)) or isinstance(seed, bool) for seed in seeds):
        raise ValueError("G03.formal_seeds must contain string/integer seeds")
    elif len({str(seed) for seed in seeds}) != len(seeds):
        raise ValueError("G03.formal_seeds contains duplicate seeds")
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        absent("未声明正式运行总数", "声明完整正式运行数，保留全部成对运行而非筛选有利 seed")
    elif declared != len(seeds) or declared != len(pairs):
        absent("声明运行数、正式 seed 集与成对记录不完整一致", "补齐声明的全部正式 seed 成对原始结果并统一运行总数")
    if seeds and {str(seed) for seed in seeds} != {str(row.get("seed")) for row in pairs}:
        absent("正式 seed 集与实际跑分不一致", "补齐或纠正正式 seed 对应的 Baseline/Reference 原始结果")
    if mode == "stochastic" and isinstance(declared, int) and not isinstance(declared, bool) and declared < 3:
        fail("随机评估正式重复运行少于 3 次", "使用至少 3 个预声明 seed，成对重跑 Baseline 和 Reference")
    if not pairs:
        absent("缺少正式成对原始跑分", "提交每个正式 seed 的 Baseline/Reference 主指标与有效性记录")
    usable = bool(pairs)
    for row in pairs:
        if not finite(row.get("baseline")) or not finite(row.get("reference")):
            usable = False
            absent(f"seed {row.get('seed')} 的原始跑分不完整", "补齐该 seed 的有限数值主指标，不能用汇总声明代替")
        for key in ("baseline_valid", "reference_valid"):
            if row.get(key) is False:
                fail(f"seed {row.get('seed')} 的 {key} 为 false", "修复该轮质量门失败原因后按正式协议重新运行并保留原始失败记录")
            elif row.get(key) is not True:
                absent(f"seed {row.get('seed')} 的 {key} 未确认", "依据该轮原始评分记录补齐质量门有效性")
    if usable and direction in ("minimize", "maximize"):
        baseline = [row["baseline"] for row in pairs]
        reference = [row["reference"] for row in pairs]
        try:
            bmean, rmean = statistics.fmean(baseline), statistics.fmean(reference)
            sigma = statistics.stdev(baseline) if len(baseline) >= 2 else None
            rsigma = statistics.stdev(reference) if len(reference) >= 2 else None
        except (OverflowError, statistics.StatisticsError):
            return {"status": "fail" if failures else "manual", "computed": {}, "failures": failures,
                    "missing": missing + ["正式数值超出可稳定重算范围"], "warnings": warnings,
                    "actions": actions + ["核对主指标单位和异常数值，提供可稳定重算的原始记录"]}
        delta = bmean - rmean if direction == "minimize" else rmean - bmean
        if not all(finite(value) for value in (bmean, rmean, delta)) or any(value is not None and not finite(value) for value in (sigma, rsigma)):
            return {"status": "fail" if failures else "manual", "computed": {}, "failures": failures,
                    "missing": missing + ["统计计算出现非有限值"], "warnings": warnings,
                    "actions": actions + ["核对主指标单位和异常数量级，提交不会使统计计算溢出的原始记录"]}
        computed.update(baseline_mean=bmean, reference_mean=rmean,
                        baseline_sample_std=sigma, reference_sample_std=rsigma,
                        improvement=delta, run_count=len(pairs), sigma_multiplier=None)
        for key in ("baseline_mean", "reference_mean", "baseline_sample_std", "reference_sample_std"):
            claimed = comparison.get(key)
            actual = computed[key]
            if claimed is not None and actual is not None and not math.isclose(claimed, actual, rel_tol=1e-7, abs_tol=1e-12):
                fail(f"{key} 与逐 seed 重算不一致", "从同一完整 seed 集重算均值和样本标准差，并修正汇总中的不一致数值")
        if delta <= 0:
            fail("Reference 没有正向原始指标改善", "提供具有正向主指标改善的 Reference，并按同协议重新验证")
        if mode == "stochastic":
            if sigma is None or len(pairs) < 3:
                absent("正式随机运行不足以完成至少 3 次的样本标准差检查", "补齐至少 3 次正式成对运行后重算 Baseline 样本标准差")
            else:
                computed["three_sigma_baseline"] = 3 * sigma
                computed["sigma_multiplier"] = delta / sigma if sigma > 0 else None
                if delta < 3 * sigma and not math.isclose(delta, 3 * sigma, rel_tol=1e-10, abs_tol=0):
                    fail("改善未达到 3 倍 Baseline 样本标准差", "改进 Reference 或排查波动来源，提供满足 Δ≥3σ_B 的正式结果；σ_B 使用样本标准差")
                elif sigma > 0 and delta < 5 * sigma:
                    warnings.append("改善达到 3σ_B 但低于 5σ_B，建议复核稳定性；不单独判失败。")
        minimum = assessment.get("absolute_min_improvement")
        if minimum is not None:
            if not finite(minimum) or minimum < 0:
                raise ValueError("G03.absolute_min_improvement must be a nonnegative finite number or null")
            if not text(assessment.get("absolute_threshold_source")):
                absent("任务绝对改善阈值缺少预声明来源", "补充该任务事前约定的绝对改善阈值来源，不能事后新增门槛")
            elif delta < minimum and not math.isclose(delta, minimum, rel_tol=1e-10, abs_tol=0):
                fail("改善未达到任务预声明的绝对阈值", "使 Reference 达到任务预声明绝对改善阈值，并按原协议复验")
        upper = assessment.get("upper_bound")
        if not finite(upper):
            absent("缺少有限的 upper bound 锚点", "给出正式评分使用的 upper bound 及其校准来源")
        elif (direction == "minimize" and upper >= bmean) or (direction == "maximize" and upper <= bmean):
            fail("upper bound 的方向错误或与 Baseline 重合", "按指标方向校准优于 Baseline 的 upper bound，避免零分母并重新计算评分")
        else:
            score = (bmean - rmean) / (bmean - upper)
            computed["normalized_score"] = score
            if not (0.15 - 1e-12 <= score <= 0.8 + 1e-12):
                fail("Reference 归一化分数不在 [0.15, 0.8]", "核对 B/U 的合理性，并提交落在 [0.15, 0.8] 的有效 Reference 证据；不得仅为过门槛移动锚点")
    status = "fail" if failures else "manual" if missing else "pass"
    return {"status": status, "computed": computed, "failures": failures, "missing": missing,
            "warnings": warnings, "actions": list(dict.fromkeys(actions))}


def apply_review(review, overview, root, validate_evidence):
    if not isinstance(review, dict) or review.get("schema_version") != 1:
        raise ValueError("review.content_gates requires schema_version=1 and G01–G03")
    rows = review.get("checks")
    if not isinstance(rows, list) or len(rows) != 3 or not all(isinstance(row, dict) for row in rows) or {row.get("id") for row in rows} != set(IDS):
        raise ValueError("review.content_gates.checks must contain G01–G03 exactly once")
    final = []
    for original in sorted(rows, key=lambda row: row["id"]):
        row = dict(original)
        key, status = row["id"], row.get("status")
        if status not in STATUSES or not text(row.get("summary")) or not text(row.get("reason_code")):
            raise ValueError(f"{key}: status, summary and reason_code are required")
        validate_evidence(root, row.get("evidence"), key, required=status == "pass")
        for field in ("remediation", "acceptance_evidence"):
            if field not in row or not isinstance(row[field], str) or (status in ("fail", "manual") and not text(row[field])):
                raise ValueError(f"{key}: {field} must describe a concrete correction/verification for fail/manual")
        row["title"] = TITLES[key]
        if key == "G03":
            result = assess_improvement(overview["baseline_reference"], row.get("assessment"))
            row.update({key: result[key] for key in ("computed", "warnings")})
            row["automatic_status"] = result["status"]
            if result["status"] != "pass":
                row["status"] = "fail" if status == "fail" or result["status"] == "fail" else "manual"
                row["summary"] += "；重算核验：" + "；".join(result["failures"] + result["missing"])
                row["reason_code"] = "REFERENCE_THRESHOLD_FAILED" if row["status"] == "fail" else "REFERENCE_EVIDENCE_INCOMPLETE"
                row["remediation"] = "；".join(filter(None, [row["remediation"], *result["actions"]]))
                row["acceptance_evidence"] = row["acceptance_evidence"] or "重新提交完整正式 seed 的逐轮原始结果、质量门、同协议说明与可重算 comparison_summary.json。"
        final.append(row)
    return {"schema_version": 1, "checks": final}


def assess_runtime(review, trajectories, root, validate_evidence, duration_observations=None):
    if not isinstance(review, dict):
        raise ValueError("review.runtime_review is required for two effective-duration reviews")
    rows = review.get("trajectories")
    if not isinstance(rows, list) or len(rows) != 2 or not all(isinstance(row, dict) for row in rows):
        raise ValueError("runtime_review.trajectories must contain exactly two entries")
    expected = {row["name"]: row for row in trajectories}
    if len(expected) != 2 or {row.get("name") for row in rows} != set(expected):
        raise ValueError("runtime_review trajectory names must match the two overview trajectories")
    failures, missing, refs, normalized = [], [], [], []
    sources = [row.get("source_path") for row in rows if row.get("source_path") is not None]
    if len(sources) == 2 and sources[0] == sources[1]:
        missing.append("两条轨迹指向同一记录，未区分独立运行；合并日志需分别定位到独立 run_id/记录段")
    for original in rows:
        row = dict(original)
        name = row["name"]
        overview = expected[name]
        if row.get("source_path") != overview.get("source_path"):
            raise ValueError(f"runtime_review {name}: source_path differs from overview")
        seconds = row.get("effective_seconds")
        if seconds is not None and (not finite(seconds) or seconds < 0):
            raise ValueError(f"runtime_review {name}: effective_seconds must be nonnegative finite or null")
        validate_evidence(root, row.get("evidence", []), f"runtime_review {name}")
        refs.extend(row.get("evidence", []))
        if seconds is None or not row.get("evidence") or not text(row.get("time_accounting")) or row.get("source_path") is None:
            missing.append(name + "缺少有效时长或排除排队/安装/故障的核算证据")
        if seconds is not None:
            effective_hours = overview.get("duration_hours")
            # Both review fields describe effective time. Allow display rounding
            # to a minute, but never quietly treat overview as wall-clock time.
            if finite(effective_hours) and abs(seconds - effective_hours * 3600) > 60:
                missing.append(name + "概览与时长核验的有效时长不一致，须按同一扣除口径核对")
            for observation in duration_observations or []:
                prefix = str(row.get("source_path")) + "#"
                evidence = observation.get("evidence", "")
                field = evidence[len(prefix):] if evidence.startswith(prefix) else None
                # Only unambiguous top-level timings from this exact trajectory;
                # never infer whole-run bounds from nested trials or budgets.
                if field not in (".run_duration_seconds", ".wall_time_seconds", ".duration_seconds",
                                 ".elapsed_seconds", ".duration_hours", ":start/end"):
                    continue
                observed = observation.get("seconds")
                if finite(observed) and seconds > observed + 60:
                    refs.append(evidence)
                    message = name + "声明有效时长超过原轨迹记录的时长，需核对记录范围与扣除口径"
                    if field in (".run_duration_seconds", ".wall_time_seconds", ":start/end"):
                        failures.append(message)
                    else:
                        missing.append(message)
            if seconds < 7 * 3600:
                failures.append(name + f"有效时长 {seconds / 3600:.2f}h，低于例外最低 7h")
        cycles = row.get("effective_method_cycles")
        if cycles is not None and (not isinstance(cycles, int) or isinstance(cycles, bool) or cycles < 0):
            raise ValueError(f"runtime_review {name}: effective_method_cycles must be a nonnegative integer or null")
        best_refs = row.get("best_method_evidence", [])
        validate_evidence(root, best_refs, f"runtime_review {name} best_method")
        normalized.append(row)
    known = all(finite(row.get("effective_seconds")) for row in rows)
    standard = known and all(row["effective_seconds"] >= 10 * 3600 for row in rows)
    needs_exception = any(finite(row.get("effective_seconds")) and row["effective_seconds"] < 10 * 3600 for row in rows)
    eligibility = review.get("exception_eligibility")
    ineligible = False
    if needs_exception:
        if not isinstance(eligibility, dict):
            missing.append("存在不足 10h 的轨迹，缺少非训练且单轮迭代很短的例外资格核验")
        else:
            for field, label, rejected in (
                ("non_training", "任务完全不涉及训练或微调", "任务涉及训练或微调，不适用 7h 例外；两条轨迹各须达到 10h"),
                ("short_iterations", "单轮迭代很短", "单轮迭代不满足很短的条件，不适用 7h 例外；两条轨迹各须达到 10h"),
            ):
                if eligibility.get(field) is False:
                    failures.append(rejected)
                    ineligible = True
                elif eligibility.get(field) is not True:
                    missing.append("尚未确认" + label)
            eligibility_refs = eligibility.get("evidence", [])
            validate_evidence(root, eligibility_refs, "runtime_review.exception_eligibility")
            refs.extend(eligibility_refs)
            if not text(eligibility.get("basis")) or not eligibility_refs:
                missing.append("缺少非训练和典型单轮耗时的具体依据及实际日志引用；不能仅凭资格声明采用 7h 例外")
    if known and not standard and not failures:
        if not text(review.get("exception_reason")):
            missing.append("两条轨迹未均达到 10h，缺少 7–10h 例外的具体理由")
        for row in rows:
            if row.get("effective_method_cycles") is None:
                missing.append(row["name"] + "未证明至少 3 个有效方法闭环")
            elif row["effective_method_cycles"] < 3:
                failures.append(row["name"] + "有效方法闭环少于 3 个，未满足时长例外条件")
            if not text(row.get("next_direction")):
                missing.append(row["name"] + "缺少可继续探索的具体方向")
            if row.get("best_method_revalidated") is False:
                failures.append(row["name"] + "最优方法尚未复验，未满足时长例外条件")
            elif row.get("best_method_revalidated") is not True or not row.get("best_method_evidence"):
                missing.append(row["name"] + "缺少最优方法复验证据")
            refs.extend(row.get("best_method_evidence", []))
    status = "fail" if failures else "manual" if missing else "pass"
    summary = "；".join(failures + missing) if status != "pass" else (
        "、".join(f"{row['name']} {row['effective_seconds'] / 3600:.2f}h" for row in rows) + "，均达到每轨至少 10h；已核对起止、扣除区间及健康训练重叠。" if standard else
        "已确认任务完全不涉及训练或微调且单轮迭代很短；两条轨迹均至少 7h，资格依据、例外理由、各 3 个方法闭环、继续方向和最优方法复验证据齐全。")
    unknown_names = [row["name"] for row in rows if row.get("effective_seconds") is None]
    remediation = ("该任务涉及训练/微调或迭代不短，不适用7h例外；不足10h的轨迹需继续研究，使两轨分别达到至少 10h，保留旧记录。" if ineligible else
                   "为" + "、".join(unknown_names) + "补一张时长表：研究起止、排队/安装/API失联/故障区间、仍正常运行的训练重叠及有效秒数。可引用已交轨迹和日志片段；不强制提交完整timer或sessions。" if unknown_names else
                   "针对上述不足或矛盾修正时长表；实际不足10h需继续研究。仅无训练且迭代很短时补7h例外依据、3个方法闭环和最优方法复验。")
    return {"exception_reason": review.get("exception_reason", ""), "exception_eligibility": eligibility, "trajectories": normalized,
            "status": status, "summary": summary, "evidence": list(dict.fromkeys(refs)),
            "remediation": "" if status == "pass" else review.get("remediation") or remediation,
            "acceptance_evidence": "" if status == "pass" else review.get("acceptance_evidence") or "可复算的两轨起止/扣除表，与轨迹时间相符；默认每轨≥36000有效秒。最终复验、收集和明确故障不计，健康训练并发只计一次。"}
