"""Independent protocol, evidence and statistical operations; no task ledger."""
from __future__ import annotations

import copy
import json
import math
import statistics
from pathlib import Path

from .common import FlowError, _require, _sha256, _canonical_digest, _read_json, _atomic_json

def number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value), "INVALID_NUMBER", f"{label} 必须是有限数值（不能是布尔值）")
    return value


def normalize(raw, baseline, upper_bound, direction, *, hard_gate_passed=True):
    """Unclipped score; gate failures return -1, not a value-based validity test."""
    for label, value in (("B", baseline), ("U", upper_bound)):
        number(value, label)
    _require(direction in {"maximize", "minimize"}, "INVALID_SCORE", "指标方向无效")
    sign = 1 if direction == "maximize" else -1
    _require(sign * (upper_bound - baseline) > 0, "INVALID_SCORE", "U 必须严格位于 B 的改善方向")
    _require(type(hard_gate_passed) is bool, "INVALID_SCORE", "Hard Gate 必须是布尔值")
    if not hard_gate_passed:
        return -1.0
    number(raw, "raw_metric")
    score = (raw - baseline) / (upper_bound - baseline)
    return number(score, "score")


def protocol(value):
    """Accept a concrete protocol, without requiring an ID, stage or source lock."""
    p = copy.deepcopy(value)
    _require(isinstance(p, dict), "INVALID_PROTOCOL", "协议须为 JSON 对象")
    try:
        json.dumps(p, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise FlowError("INVALID_PROTOCOL", "协议含非 JSON 或非有限值") from exc
    m = p.get("metric", {})
    _require(isinstance(m, dict) and isinstance(m.get("name"), str) and m["name"].strip()
             and m.get("direction") in {"maximize", "minimize"} and isinstance(m.get("unit"), str),
             "INVALID_PROTOCOL", "metric 须有 name/direction/unit（无量纲可用空单位）")
    _require(isinstance(p.get("split"), str) and bool(p["split"].strip()), "INVALID_PROTOCOL", "须标明真实 split")
    fixed = p.get("fixed", {})
    _require(isinstance(fixed, dict), "INVALID_PROTOCOL", "fixed 须为对象")
    _require(bool(p.get("data") or fixed.get("data")), "INVALID_PROTOCOL", "须提供实际数据版本/指纹")
    _require(type(p.get("training")) is bool and p.get("evaluation_mode") in {"random", "deterministic"},
             "INVALID_PROTOCOL", "声明 training 与 evaluation_mode")
    if p["evaluation_mode"] == "deterministic":
        _require(isinstance(p.get("determinism_basis", p.get("rationale")), str)
                 and bool(p.get("determinism_basis", p.get("rationale")).strip()),
                 "INVALID_PROTOCOL", "确定性须说明依据，不能从固定 seed 或相同结果推断")
    seeds = p.get("seeds")
    _require(isinstance(seeds, list) and seeds and all(type(s) is int and s >= 0 for s in seeds)
             and len(set(seeds)) == len(seeds), "INVALID_SEEDS", "seed 须为不重复非负整数")
    _require(isinstance(p.get("budget"), dict) and bool(p["budget"]), "INVALID_PROTOCOL", "须声明实际共同预算")
    for key, bound in p["budget"].items():
        if isinstance(bound, dict) and "mode" in bound:
            _require(bound["mode"] in {"exact", "maximum"}
                     and number(bound.get("value"), key) > 0 and isinstance(bound.get("unit"), str),
                     "INVALID_PROTOCOL", "数值预算须有 exact/maximum、正数 value 与 unit")
    _require(type(p.get("high_variance", False)) is bool, "INVALID_PROTOCOL", "high_variance 须为布尔值")
    _require(p.get("purpose", "formal") in {"formal", "exploratory"}, "INVALID_PROTOCOL", "purpose 须为 formal/exploratory")
    _require(number(p.get("reload_tolerance", 0), "reload_tolerance") >= 0, "INVALID_PROTOCOL", "重载容差不得为负")
    # Exploration is allowed to use a small set; summarize labels insufficient formal sets.
    return p


def minimum_repeats(p):
    return 5 if p.get("high_variance") else 3 if p["training"] or p["evaluation_mode"] == "random" else 1


def raw_value(record, metric):
    """Never infer a normalized score as the raw metric."""
    m = record.get("metrics", {})
    _require(isinstance(m, dict), "INVALID_RESULT", "metrics 须为对象")
    primary = m.get("primary")
    _require(primary is None or isinstance(primary, dict), "INVALID_RESULT", "metrics.primary 须为对象")
    choices = [v for v in (record.get("raw_metric"), m.get("raw"), m.get("raw_metric"),
                           m.get("value"), primary)
               if v is not None]
    choices = [v.get("value") if isinstance(v, dict) else v for v in choices]
    _require(bool(choices), "MISSING_METRIC", "须提供 metrics.raw / metrics.raw_metric / raw_metric")
    values = [number(v, "raw_metric") for v in choices]
    _require(all(v == values[0] for v in values), "METRIC_CONFLICT", "多处原始指标矛盾")
    for key in ("name", "direction", "unit"):
        if key in m:
            _require(m[key] == metric[key], "METRIC_CONFLICT", f"metrics.{key} 与协议不同")
        if primary and key in primary:
            _require(primary[key] == metric[key], "METRIC_CONFLICT", f"metrics.primary.{key} 与协议不同")
    return values[0]


def quality_passed(record):
    q = record.get("quality_gate", {})
    if "quality_gate" in record:
        passed = q is True or isinstance(q, dict) and (
            q.get("passed") is True or "passed" not in q and q.get("valid") is True)
        if isinstance(q, dict) and (q.get("valid") is False or q.get("violations")):
            passed = False
        return passed and record.get("quality_passed", True) is True
    return record.get("quality_passed") is True


def artifact_file(root, ref, *, nonempty=True):
    _require(isinstance(ref, dict) and isinstance(ref.get("path"), str), "MISSING_EVIDENCE", "缺少证据路径")
    base = Path(root).resolve()
    path = (base / ref["path"]).resolve()
    _require(not Path(ref["path"]).is_absolute() and path.is_relative_to(base)
             and path.is_file(), "MISSING_EVIDENCE", f"证据不存在或越界：{ref['path']}")
    _require(not nonempty or path.stat().st_size > 0, "EMPTY_EVIDENCE", f"证据为空：{ref['path']}")
    if "sha256" in ref:
        _require(_sha256(path) == ref["sha256"], "EVIDENCE_DRIFT", f"证据哈希变化：{ref['path']}")
    return path


def record_evidence(record, root, p):
    """Structural evidence check, never loads a model or certifies scientific validity."""
    issues = []
    refs = record.get("artifacts", record.get("evidence", {}))
    try:
        _require(isinstance(refs, dict), "MISSING_EVIDENCE", "artifacts 须为对象")
        artifact_file(root, refs.get("log"))
        e = record.get("execution", {})
        _require(isinstance(e, dict), "INVALID_EXECUTION", "execution 须为对象")
        for key in ("command", "started_at", "finished_at", "exit_code"):
            _require(key in e and (e[key] is not None or bool(e.get("missing_reason"))),
                     "MISSING_EXECUTION", f"执行字段 {key} 缺失且无解释")
        _require(e["exit_code"] is None or type(e["exit_code"]) is int and e["exit_code"] == 0,
                 "EXECUTION_FAILED", "成功结果与实际退出码矛盾")
        method = record.get("method", {})
        _require(isinstance(method, dict) and bool(method.get("sha256") or record.get("method_sha256")),
                 "MISSING_METHOD", "缺少实际方法哈希")
        for ref in refs.values():
            if isinstance(ref, dict) and "path" in ref:
                artifact_file(root, ref)
        if record.get("schema_version") == "autoresearch-run.v1":
            _require(_canonical_digest(method["files"]) == method["sha256"], "METHOD_MISMATCH", "方法文件指纹不匹配")
            for path, digest in method["files"].items():
                artifact_file(root, {"path": str(Path(method["path"]) / path), "sha256": digest}, nonempty=False)
            raw = _read_json(artifact_file(root, refs.get("raw_result")))
            _require(raw_value(raw, p["metric"]) == raw_value(record, p["metric"])
                     and quality_passed(raw), "RESULT_MISMATCH", "汇总结果与原始测量矛盾")
            _require(e.get("actual_budget") == raw.get("actual_budget"), "BUDGET_MISMATCH", "实际预算与原始记录矛盾")
        for key, bound in p["budget"].items():
            if isinstance(bound, dict) and bound.get("mode") in {"exact", "maximum"}:
                used = number((e.get("actual_budget") or record.get("actual_budget") or {}).get(key), key)
                _require(used >= 0 and (used == bound["value"] if bound["mode"] == "exact" else used <= bound["value"]),
                         "BUDGET_MISMATCH", f"实际 {key} 与协议不符")
        if p["training"]:
            train = record.get("training", {})
            _require(isinstance(train, dict) and train.get("origin") in {"initialization", "declared_pretrained"},
                     "TRAINING_ORIGIN", "须说明独立训练起点；共享预训练须在协议声明")
            if train["origin"] == "declared_pretrained":
                _require(bool(p.get("pretrained")), "TRAINING_ORIGIN", "协议未声明共享预训练")
            model = artifact_file(root, refs.get("model"))
            artifact_file(root, refs.get("reload_log"))
            a = _read_json(artifact_file(root, refs.get("model_metadata")))
            expected = {"seed": record["seed"], "role": record["role"], "method_sha256": method["sha256"],
                        "sha256": _sha256(model), "size_bytes": model.stat().st_size}
            _require(all(a.get(k) == v for k, v in expected.items()), "MODEL_MISMATCH", "模型元信息与结果不对应")
            _require(a.get("reload_passed") is True and isinstance(a.get("format"), str) and bool(a["format"]),
                     "RELOAD_FAILED", "缺少有效重载结论或模型格式")
            _require(abs(number(a.get("reload_metric"), "reload_metric") - raw_value(record, p["metric"]))
                     <= p.get("reload_tolerance", 0), "RELOAD_FAILED", "重载原始指标超出容差")
    except (FlowError, KeyError, TypeError, ValueError) as exc:
        issues.append(str(exc))
    return issues


def result_paths(inputs):
    """Read explicit results or canonical seed results, not retry/history copies."""
    paths = []
    for item in inputs:
        path = Path(item).resolve()
        if path.is_file():
            paths.append(path)
        elif path.is_dir():
            paths.extend(sorted(path.glob("seed_*/result.json")))
        else:
            raise FlowError("MISSING_RESULT", f"结果路径不存在：{path}")
    _require(bool(paths), "MISSING_RESULT", "没有 result.json；目录须直接包含 seed_*/result.json")
    _require(len(paths) == len(set(paths)), "DUPLICATE_RESULT", "同一结果文件不能输入两次")
    return paths


def summarize(inputs, *, protocol_value=None, score_contract=None, evidence_root=None):
    paths = result_paths(inputs)
    records = [(path, _read_json(path)) for path in paths]
    p = protocol(protocol_value if protocol_value is not None else records[0][1].get("protocol"))
    digest = _canonical_digest(p)
    groups, issues, evidence_issues = {}, [], []
    source_results = []
    for path, record in records:
        role, seed = record.get("role"), record.get("seed")
        _require(isinstance(role, str) and role, "INVALID_ROLE", f"{path}: 缺少 role")
        group = groups.setdefault(role, {"values": {}, "seen_seeds": [], "methods": set()})
        source_results.append({"path": str(path), "sha256": _sha256(path), "role": role,
                               "seed": seed if type(seed) is int else repr(seed),
                               "status": record.get("status")})
        if type(seed) is not int or seed not in p["seeds"]:
            issues.append(f"{role}: 非声明 seed {seed}")
            continue
        if seed in group["seen_seeds"]:
            raise FlowError("DUPLICATE_SEED", f"{role}: seed {seed} 重复，不能自动挑选或取交集")
        group["seen_seeds"].append(seed)
        try:
            _require(str(record.get("status")).upper() in {"SUCCEEDED", "SUCCESS", "COMPLETE", "VALID", "OK"},
                     "RUN_INVALID", f"运行状态 {record.get('status')}")
            bound = record.get("protocol")
            if bound is None and record.get("protocol_sha256") is None:
                evidence_issues.append(f"{role}/{seed}: 仅按补充协议计算，原结果未绑定协议，不能据此宣称正式验证")
            elif (protocol_value is not None and isinstance(p.get("source_protocol"), dict)
                  and bound == p["source_protocol"] and record.get("schema_version") != "autoresearch-run.v1"):
                evidence_issues.append(f"{role}/{seed}: 旧协议字段映射仅用于只读复算，正式证据语义仍须核查")
            else:
                _require(bound == p if bound is not None else record.get("protocol_sha256") == digest,
                         "PROTOCOL_MISMATCH", "结果协议或数据/split/预算不同")
            _require(quality_passed(record), "QUALITY_FAILED", "质量门未通过或未知")
            value = raw_value(record, p["metric"])
            group["values"][str(seed)] = value
            method_hash = record.get("method", {}).get("sha256", record.get("method_sha256"))
            if method_hash:
                group["methods"].add(method_hash)
            # Runner roots are recognizable without an absolute path recorded in the data.
            root = Path(evidence_root) if evidence_root else path.parent.parent if path.parent.name == f"seed_{seed}" else path.parent
            for issue in record_evidence(record, root, p):
                evidence_issues.append(f"{role}/{seed}: {issue}")
        except (FlowError, TypeError, AttributeError) as exc:
            issues.append(f"{role}/{seed}: {exc}")
    for role, group in groups.items():
        values = [group["values"][str(s)] for s in p["seeds"] if str(s) in group["values"]]
        group.update(count=len(values), mean=statistics.mean(values) if values else None,
                     sample_std=statistics.stdev(values) if len(values) > 1 else None,
                     missing_seeds=[s for s in p["seeds"] if str(s) not in group["values"]])
        if group["missing_seeds"]:
            issues.append(f"{role}: 缺少有效正式 seed {group['missing_seeds']}")
        if len(group["methods"]) > 1:
            issues.append(f"{role}: 混用了不同方法源码")
        group["method_sha256"] = next(iter(group.pop("methods")), None)
    complete = not issues and not evidence_issues
    formal = complete and p.get("purpose", "formal") == "formal" and len(p["seeds"]) >= minimum_repeats(p)
    report = {"schema_version": "autoresearch-comparison-summary.v2", "status": "COMPLETE" if complete else "PARTIAL",
              "metric": p["metric"], "split": p["split"], "protocol": p, "protocol_sha256": digest,
              "seeds": p["seeds"], "groups": groups, "source_results": source_results, "issues": issues,
              "evidence_issues": evidence_issues, "formal_sample_complete": formal,
              "scientific_review": "NOT_PERFORMED", "paired_results": {}, "normalization": None}
    if not formal:
        report["notice"] = "临时统计，不能作为正式冻结或最终提交结论；缺证、探索或次数不足见协议/问题列表"
    if "baseline" in groups and "reference" in groups:
        b, r = groups["baseline"], groups["reference"]
        if not b["missing_seeds"] and not r["missing_seeds"] and not issues:
            sign = 1 if p["metric"]["direction"] == "maximize" else -1
            delta = number(sign * (r["mean"] - b["mean"]), "mean_paired_improvement")
            sigma = b["sample_std"]
            stochastic = p["evaluation_mode"] == "random"
            passed = delta > 0 and (not stochastic or sigma is not None and delta >= 3 * sigma)
            report["paired_results"] = {str(s): {"baseline": b["values"][str(s)], "reference": r["values"][str(s)],
                "paired_improvement": sign * (r["values"][str(s)] - b["values"][str(s)])} for s in p["seeds"]}
            report["statistics"] = {"paired_run_count": len(p["seeds"]), "baseline_mean": b["mean"],
                "reference_mean": r["mean"], "baseline_sample_std": sigma, "reference_sample_std": r["sample_std"],
                "mean_paired_improvement": delta, "relative_improvement": delta / abs(b["mean"]) if b["mean"] else None,
                "baseline_sigma_multiple": delta / sigma if sigma else None}
            report["significance_rule"] = {"required_baseline_sigma_multiple": 3.0 if stochastic else None,
                "numerical_passed": passed, "passed": passed if formal else None,
                "strength": ("insufficient" if not passed else "deterministic_positive" if not stochastic
                             else "strong" if delta >= 5 * sigma else "needs_more_runs_and_review")}
            if score_contract is not None:
                _require(isinstance(score_contract, dict) and bool(score_contract.get("rationale")),
                         "INVALID_SCORE", "U 须有独立依据 rationale")
                u = score_contract.get("upper_bound")
                score = normalize(r["mean"], b["mean"], u, p["metric"]["direction"])
                report["normalization"] = {"baseline": b["mean"], "upper_bound": u, "reference": score,
                    "reference_in_range": 0.15 <= score <= 0.8, "rationale": score_contract["rationale"],
                    "unclipped": True}
    report["validity"] = {"same_protocol": not any("协议" in x or "split" in x for x in issues),
                          "all_declared_pairs_complete": bool(report["paired_results"]) and complete,
                          "all_quality_gates_passed": not issues,
                          "evidence_complete": not evidence_issues}
    return report


def write_summary(report, output_dir):
    root = Path(output_dir).resolve()
    _require(not any((root / n).exists() for n in ("comparison_summary.json", "summary.md")),
             "OUTPUT_EXISTS", "汇总文件已存在；使用新的输出目录")
    root.mkdir(parents=True, exist_ok=True)
    _atomic_json(root / "comparison_summary.json", report)
    lines = ["# 实验统计", "", f"状态：{report['status']}；正式样本完整：{report['formal_sample_complete']}。",
             "数值及证据检查不等于 Baseline/优化面/U 科学审查通过。", "",
             "| 角色 | 有效数 | 原始指标均值 | 样本标准差 | 缺失 seed |", "| --- | --- | --- | --- | --- |"]
    for role, group in report["groups"].items():
        lines.append(f"| {role} | {group['count']} | {group['mean']} | {group['sample_std']} | {group['missing_seeds']} |")
    for issue in report["issues"] + report["evidence_issues"]:
        lines.append("- " + issue)
    if report.get("statistics"):
        lines += ["", "比较：" + json.dumps(report["statistics"], ensure_ascii=False),
                  "判据：" + json.dumps(report["significance_rule"], ensure_ascii=False)]
    if report["normalization"]:
        lines += ["", "归一化：" + json.dumps(report["normalization"], ensure_ascii=False)]
    (root / "summary.md").write_text("\n".join(lines) + "\n")
