"""QA15 evidence collection and conservative resource checks; no task execution."""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
import deployment_review

LIMITS = {"score_seconds": 7200, "gpu_count": 8, "gpu_types": ["H20"], "cpu_cores": 64}
FIELDS = ("score_seconds", "gpu_count", "gpu_type", "cpu_cores", "peak_memory_mb", "peak_storage_mb")


def collect(root, files, config=None, trajectory_paths=None):
    observations, errors, formal, agent_scores = [], [], [], []
    for relative in files:
        path = Path(relative)
        is_formal = path.name == "result.json" and len(path.parts) >= 3 and path.parts[-3] in ("baseline_runs", "reference_runs")
        is_trajectory = relative in (trajectory_paths or []) or ("expert_evidence" in path.parts and path.name.startswith("trajectory") and path.suffix == ".json")
        if not is_formal and not is_trajectory and path.name not in ("run_summary.json", "run.json"):
            continue
        if is_formal:
            formal.append(relative)
        try:
            target = root / relative
            if target.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("resource JSON exceeds 4 MiB; inspect raw log separately")
            data = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("resource JSON must be an object")
            if is_trajectory:
                rounds = data.get("rounds", [])
                if isinstance(rounds, list):
                    for row in rounds:
                        if isinstance(row, dict) and str(row.get("status", "")).lower() in ("ok", "success", "pass", "complete", "completed"):
                            if isinstance(row.get("score"), (int, float)) and not isinstance(row["score"], bool) and math.isfinite(row["score"]):
                                agent_scores.append({"source_path": relative, "round": row.get("round")})
            observations.append({"path": relative, "role": data.get("role"),
                                 "execution": data.get("execution"), "protocol": data.get("protocol")})
        except (OSError, ValueError, UnicodeError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    cfg = config if isinstance(config, dict) else {}
    verifier = cfg.get("verifier", {})
    env = cfg.get("environment", {})
    venv = verifier.get("environment", env) if isinstance(verifier, dict) else env
    return {"status": "manual", "summary": "QA15 已启用；等待结合日志、轨迹和B/R实现估算完整单轮耗时、GPU数量及CPU核数。",
            "limits": dict(LIMITS), "formal_run_paths": sorted(formal), "agent_scores": agent_scores, "observations": observations,
            "parse_errors": errors, "declared_environment": env, "declared_verifier_environment": venv,
            "declared_verifier_timeout": verifier.get("timeout_sec") if isinstance(verifier, dict) else None,
            "evidence": [], "runs": [], "enforcement_review": None}


def hardware_review(current, review, estimate, root, validate_evidence, deployment=None):
    """Reviewer metadata connects task intent and existing hardware evidence."""
    data = review.get("hardware_review", {})
    if not isinstance(data, dict):
        raise ValueError("hardware_review must be an object")
    refs = validate_evidence(root, data.get("evidence", []), "hardware_review")
    kind = data.get("task_type", "unknown")
    comparison = data.get("score_comparability", "unverified")
    if kind not in ("cpu", "gpu", "unknown") or comparison not in ("same_hardware", "revalidated", "unverified", "reused_without_validation"):
        raise ValueError("hardware_review has unsupported task_type or score_comparability")
    affected = data.get("affected_formal_runs", [])
    if not isinstance(affected, list):
        raise ValueError("affected_formal_runs must be an array")
    for ref in affected:
        parts = Path(ref).parts
        if len(parts) < 3 or parts[-3] not in ("baseline_runs", "reference_runs") or parts[-1] != "result.json":
            raise ValueError("affected_formal_runs must name formal B/R result.json files")
    refs += validate_evidence(root, affected, "hardware affected_formal_runs")
    formal_effect = data.get("affects_formal_scores", bool(affected))
    if not isinstance(formal_effect, bool):
        raise ValueError("affects_formal_scores must be boolean")
    if affected and not formal_effect:
        raise ValueError("affected formal runs cannot be declared unaffected")
    gaps, problems = [], []
    if kind == "unknown":
        gaps.append("CPU/GPU任务性质尚未据实判定")
    if not refs or not isinstance(data.get("summary"), str) or not data["summary"].strip():
        gaps.append("任务性质与换卡成绩可比性的现有依据")
    if comparison == "unverified":
        gaps.append("当前成绩的硬件归属/换卡影响尚未确认")
    if comparison == "reused_without_validation":
        problems.append("旧卡成绩未经复核直接作为新卡成绩，不能据此声称目标硬件结果")
    profile = (deployment or {}).get("profile", deployment_review.INNERFIELD)
    envs = (deployment or {}).get("effective_environments", {
        "agent": current.get("declared_environment", {}), "verifier": current.get("declared_verifier_environment", {})})
    if profile == deployment_review.INNERFIELD:
        actual = [(name, env.get("gpus", 0)) for name, env in envs.items() if isinstance(env, dict)]
        if kind == "cpu":
            if estimate.get("gpu_count", 0) not in (None, 0) or any(isinstance(n, (int, float)) and n > 0 for _, n in actual):
                problems.append("CPU题不得增加GPU；资源估算与Solver/Verifier实际申请均须为0")
        elif kind == "gpu":
            if estimate.get("gpu_count") == 0:
                gaps.append("GPU题的资源估算为0GPU，需核对与实际评分硬件的一致性")
            if not any(isinstance(n, (int, float)) and not isinstance(n, bool) and n > 0 for _, n in actual):
                gaps.append("GPU题的实际Solver/Verifier GPU申请尚未对应")
            if not estimate.get("gpu_type"):
                gaps.append("GPU资源估算须明确其实际或推断所依据的卡型；最终目标配置写H20")
        for role, env in envs.items():
            if not isinstance(env, dict):
                continue
            count = env.get("gpus", 0)
            types = env.get("gpu_types")
            if isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0:
                if not isinstance(types, list) or not types:
                    gaps.append(f"{role}有效gpu_types尚未明确")
                elif any(not isinstance(t, str) or t.strip().upper() not in deployment_review.GPU_TYPES for t in types):
                    problems.append(f"{role}最终gpu_types未按项目通知写为H20；实际研究卡型可自选")
    status = "fail" if problems else "manual" if gaps else "pass"
    score_status = "fail" if comparison == "reused_without_validation" else "manual" if comparison == "unverified" or not refs or not data.get("summary") else "pass"
    return {**data, "task_type": kind, "score_comparability": comparison, "status": status,
            "score_status": score_status if formal_effect else "pass", "affects_formal_scores": formal_effect,
            "affected_formal_runs": affected, "problems": problems, "gaps": gaps,
            "evidence": list(dict.fromkeys(refs + ([(deployment or {})["config_source"]] if (deployment or {}).get("config_source") else []))),
            "summary": "；".join(problems + gaps) or data.get("summary", ""),
            "remediation": "按任务性质核对当前Solver/Verifier资源。换卡只复核受影响的成绩或耗时，并引用已有配置、说明或运行记录；旧测量保留原硬件标签。",
            "acceptance_evidence": "CPU题不申请GPU；GPU题提交配置写H20，实际设备据实记录；H20适配由算法部门负责，不把专家原卡测量改写为H20实测。"}


def apply_review(current, review, root, validate_evidence, deployment=None):
    """Accept a supported whole-task estimate; detailed allocation proofs optional."""
    if review is None:
        return current
    if not isinstance(review, dict):
        raise ValueError("resource_review must be an object")
    refs = validate_evidence(root, review.get("evidence", []), "resource_review")
    rows = review.get("runs", [])
    if not isinstance(rows, list):
        raise ValueError("resource_review.runs must be an array")
    problems, checked = [], []
    def numbers(row, label):
        for field in FIELDS:
            value = row.get(field)
            if field == "gpu_type" or value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{label}.{field}: require a finite nonnegative value")
            if field in ("gpu_count", "cpu_cores") and int(value) != value:
                raise ValueError(f"{label}.{field}: require an integer")
    for index, row in enumerate(rows):
        label = f"resource_review.runs[{index}]"
        if not isinstance(row, dict) or not row.get("run_id"):
            raise ValueError(f"{label}: run_id is required")
        evidence = validate_evidence(root, row.get("evidence", []), label, required=True)
        if row.get("source_path"):
            validate_evidence(root, [row["source_path"]], label + ".source_path", required=True)
        if row.get("scope") not in ("score", "training", "verifier", "setup", "agent_run"):
            raise ValueError(f"{label}: specify score/training/verifier/setup/agent_run scope")
        rounds = row.get("covered_rounds", [])
        if not isinstance(rounds, list) or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in rounds):
            raise ValueError(f"{label}.covered_rounds: require positive round numbers")
        numbers(row, label)
        if row["scope"] == "score" and row.get("score_seconds") is not None and row["score_seconds"] > 7200:
            problems.append(f"{row['run_id']} 完整单次评分 {row['score_seconds']}s 超过7200s")
        checked.append({**row, "evidence": evidence})
    estimate = review.get("estimate")
    if estimate is not None and not isinstance(estimate, dict):
        raise ValueError("resource_review.estimate must be an object")
    # Existing full score records also work; the new estimate is only needed
    # when the reviewer combines logs, source complexity and configuration.
    if estimate is None:
        scores = [row for row in rows if row["scope"] == "score"]
        formal = set(current.get("formal_run_paths", []))
        if formal:
            scores = [row for row in scores if row.get("source_path") in formal]
        if scores:
            estimate = dict(scores[0])
            for field in ("score_seconds", "gpu_count", "cpu_cores"):
                values = [row.get(field) for row in scores]
                estimate[field] = max(values) if all(v is not None for v in values) else None
            estimate["basis"] = "已有完整评分记录的代表性资源观测。"
            estimate["evidence"] = list(dict.fromkeys(ref for row in scores for ref in row["evidence"]))
    estimate = estimate or {}
    numbers(estimate, "resource_review.estimate")
    er = validate_evidence(root, estimate.get("evidence", []), "resource estimate")
    missing = []
    # A supported target estimate may differ from old calibration measurements,
    # but already supplied score records cannot silently contradict it. This is
    # a reviewer explanation over existing evidence, not a new required artifact.
    conflicts = []
    for row in checked:
        if row["scope"] != "score":
            continue
        for field in ("score_seconds", "gpu_count", "cpu_cores"):
            observed, proposed = row.get(field), estimate.get(field)
            if observed is not None and proposed is not None and observed > proposed:
                conflicts.append(f"{row['run_id']}.{field} 已给观测为{observed}，高于目标估算{proposed}")
        hardware_data = review.get("hardware_review", {})
        same_hardware = isinstance(hardware_data, dict) and hardware_data.get("score_comparability") == "same_hardware"
        if same_hardware and row.get("gpu_count") and estimate.get("gpu_count") and row.get("gpu_type") and estimate.get("gpu_type"):
            observed_type = str(row["gpu_type"]).strip().upper()
            proposed_type = str(estimate["gpu_type"]).strip().upper()
            if observed_type != proposed_type:
                conflicts.append(f"{row['run_id']}.gpu_type={row['gpu_type']} 与估算{estimate['gpu_type']}不同，但声明same_hardware")
    reconciliation = estimate.get("observation_reconciliation")
    reconciliation_refs = []
    if reconciliation is not None:
        if not isinstance(reconciliation, dict) or not isinstance(reconciliation.get("summary"), str) or not reconciliation["summary"].strip():
            raise ValueError("resource estimate observation_reconciliation requires a concrete summary")
        reconciliation_refs = validate_evidence(root, reconciliation.get("evidence", []), "resource observation reconciliation", required=True)
    if conflicts and reconciliation is None:
        missing.append("已有完整评分观测与估算存在未解释差异：" + "；".join(conflicts)
                       + "；请引用已有材料说明历史校准、目标配置或方法变化")
    for field, label in (("score_seconds", "完整一轮评分耗时"), ("gpu_count", "GPU数量"), ("cpu_cores", "CPU核数")):
        value = estimate.get(field)
        if value is None:
            missing.append(label)
        elif value > LIMITS[field]:
            problems.append(f"估算{label} {value} 超过上限{LIMITS[field]}")
    if not estimate.get("time_accounting"):
        missing.append("计时包含的阶段")
    if not estimate.get("basis") or not er:
        missing.append("可引用的日志/实现估算依据")
    gpu_type = estimate.get("gpu_type")
    # Actual expert hardware is unrestricted by model; retain honest estimates
    # and comparability checks above. H20 adaptation belongs to the project.
    for name in ("declared_environment", "declared_verifier_environment"):
        env = current.get(name, {})
        if isinstance(env, dict):
            for key, maximum in (("cpus", 64), ("gpus", 8)):
                value = env.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and value > maximum:
                    problems.append(f"{name}.{key} 请求{value} 超过{maximum}")
    hardware = hardware_review(current, review, estimate, root, validate_evidence, deployment)
    problems.extend(hardware["problems"])
    missing.extend(hardware["gaps"])
    conclusion = review.get("status", "manual")
    if conclusion not in ("pass", "manual", "fail"):
        raise ValueError("QA15 cannot be skipped")
    if conclusion == "fail" and (not refs or not review.get("summary")):
        raise ValueError("resource_review fail needs evidence and explanation")
    status = "fail" if problems or conclusion == "fail" else "manual" if missing or conclusion != "pass" else "pass"
    summary = ("；".join(problems) if problems else "缺少：" + "、".join(missing) if missing else
               review.get("summary") or f"估算完整一轮{estimate['score_seconds']}秒、{estimate['gpu_count']}GPU、{estimate['cpu_cores']}CPU，符合资源上限。")
    covered = {r.get("source_path") for r in rows if r.get("scope") == "score"}
    covered_scores = {(r.get("source_path"), n) for r in rows for n in r.get("covered_rounds", [])}
    # Coverage and deployment details are observations, not new mandatory gates.
    return {**current, "status": status, "summary": summary, "estimate": estimate, "runs": checked,
            "observation_conflicts": conflicts, "observation_reconciliation": reconciliation,
            "hardware_review": hardware,
            "enforcement_review": review.get("enforcement_review"),
            "missing_run_paths": sorted(set(current.get("formal_run_paths", [])) - covered),
            "missing_agent_scores": [r for r in current.get("agent_scores", []) if (r["source_path"], r["round"]) not in covered_scores],
            "problems": problems, "gaps": missing,
            "evidence": list(dict.fromkeys(refs + er + reconciliation_refs + hardware["evidence"] + [ref for row in rows for ref in row["evidence"]])),
            "feasibility_summary": review.get("feasibility_summary", estimate.get("basis", "")),
            "remediation": "" if status == "pass" else review.get("remediation") or
                (hardware["remediation"] if hardware["status"] != "pass" else
                 "降低上述超限资源需求，或说明并验证目标硬件上的可行配置。" if problems else
                 "在专家说明中补充" + "、".join(missing or ["资源估算结论"]) + "；可引用现有B/R日志、轨迹和实现，无需逐轮补配额或cgroup证明。确实无法推断时补一轮代表性运行摘要。"),
            "acceptance_evidence": "" if status == "pass" else review.get("acceptance_evidence") or
                (hardware["acceptance_evidence"] if hardware["status"] != "pass" else
                 "一份有来源的完整单轮资源估算：耗时≤7200秒、GPU≤8张、CPU≤64核；提交目标H20，实际卡型自选，标明实测与推断及包含的运行阶段。")}
