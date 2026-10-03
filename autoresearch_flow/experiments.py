"""W2: preregistered experiments, evidence integrity, statistics and score contracts.

The ledger records expert-run experiments; it never runs candidate code or certifies
scientific validity. Local bookkeeping is not the final submission result schema.
"""
from __future__ import annotations

import copy
import fcntl
import math
import statistics
from contextlib import contextmanager
from pathlib import Path

from .core import (FlowError, TaskStore, SHA256_RE, TASK_ID_RE, _atomic_json,
                   _canonical_digest, _read_json, _require, _safe_repository_file,
                   _sha256, _utc_now)


def number(value, label):
    _require(type(value) in (int, float) and math.isfinite(value), "INVALID_NUMBER", f"{label} 必须是有限数值（不能是布尔值）")
    return value


def _finite_json(value):
    """Keep invalid raw evidence on disk, but make ledger/output strict JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite_json(item) for item in value]
    return value


def evidence(root, ref):
    _require(isinstance(ref, dict) and set(ref) == {"path", "sha256"}, "INVALID_EVIDENCE", "证据须含 path 与 sha256")
    _require(isinstance(ref["sha256"], str) and bool(SHA256_RE.fullmatch(ref["sha256"])), "INVALID_EVIDENCE", "证据 SHA-256 无效")
    path = _safe_repository_file(root, ref["path"])
    _require(_sha256(path) == ref["sha256"], "EVIDENCE_DRIFT", f"证据哈希改变：{ref['path']}")
    return path


def validate_protocol(p):
    _require(isinstance(p, dict) and p.get("schema_version") == 1, "INVALID_PROTOCOL", "实验协议 schema_version 必须为 1")
    _require(isinstance(p.get("id"), str) and bool(TASK_ID_RE.fullmatch(p["id"])), "INVALID_PROTOCOL", "协议 ID 不合法")
    metric = p.get("metric", {})
    _require(isinstance(metric, dict) and isinstance(metric.get("name"), str) and metric["name"] and metric.get("direction") in {"maximize", "minimize"}, "INVALID_PROTOCOL", "指标须有名称和方向")
    _require(type(p.get("training")) is bool and p.get("evaluation_mode") in {"random", "deterministic"}, "INVALID_PROTOCOL", "声明 training 和 evaluation_mode")
    seeds = p.get("seeds")
    _require(isinstance(seeds, list) and seeds and all(type(s) is int and s >= 0 for s in seeds) and len(seeds) == len(set(seeds)), "INVALID_SEEDS", "seed 须为非负整数且不重复")
    _require(type(p.get("high_variance", False)) is bool, "INVALID_PROTOCOL", "high_variance 必须为布尔值")
    minimum = 5 if p.get("high_variance", False) else 3 if p["training"] or p["evaluation_mode"] == "random" else 1
    _require(len(seeds) >= minimum, "INVALID_SEEDS", f"该协议至少需要 {minimum} 个 seed")
    fixed = p.get("fixed")
    _require(isinstance(fixed, dict) and {"data", "preprocessing", "evaluator"} <= set(fixed) and all(isinstance(v, str) and SHA256_RE.fullmatch(v) for v in fixed.values()), "INVALID_PROTOCOL", "fixed 须至少锁定 data/preprocessing/evaluator 的 SHA-256")
    budget = p.get("budget")
    _require(isinstance(budget, dict) and budget, "INVALID_PROTOCOL", "须声明可核验的共同资源预算")
    for key, bound in budget.items():
        _require(isinstance(bound, dict) and bound.get("mode") in {"exact", "maximum"}, "INVALID_PROTOCOL", f"预算 {key} 须声明 exact 或 maximum")
        _require(number(bound.get("value"), key) > 0, "INVALID_PROTOCOL", "预算必须为正数")
        _require(isinstance(bound.get("unit"), str) and bound["unit"], "INVALID_PROTOCOL", "预算须有单位")
    _require(isinstance(p.get("rationale"), str) and p["rationale"].strip(), "INVALID_PROTOCOL", "须说明预算口径与确定性/随机性依据")
    _require(number(p.get("reload_tolerance", 0), "reload_tolerance") >= 0, "INVALID_PROTOCOL", "重载容差不得为负")


def normalize(raw, baseline, upper_bound, direction, *, hard_gate_passed=True):
    """Linear, continuous, directional, unclipped score; hard gate is separate."""
    for label, value in (("B", baseline), ("U", upper_bound)):
        number(value, label)
    _require(direction in {"maximize", "minimize"}, "INVALID_SCORE", "指标方向无效")
    sign = 1 if direction == "maximize" else -1
    _require(sign * (upper_bound - baseline) > 0, "INVALID_SCORE", "U 必须严格位于 B 的改善方向")
    _require(type(hard_gate_passed) is bool, "INVALID_SCORE", "Hard Gate 必须是布尔值")
    if not hard_gate_passed:
        return 0.0
    number(raw, "raw_metric")
    score = (raw - baseline) / (upper_bound - baseline)
    return number(score, "score")


class ExperimentBook:
    def __init__(self, task_root):
        self.store = TaskStore(Path(task_root))
        self.root = self.store.task_root
        self.path = self.store.state_dir / "experiments.json"

    def _load(self):
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "先核对任务规则来源漂移")
        if not self.path.exists():
            return {"schema_version": 1, "protocols": {}, "runs": {}}
        data = _read_json(self.path)
        _require(data.get("schema_version") == 1 and isinstance(data.get("protocols"), dict) and isinstance(data.get("runs"), dict), "INVALID_LEDGER", "实验账本结构错误")
        for record in data["protocols"].values():
            validate_protocol(record["protocol"])
            _require(_canonical_digest(record["protocol"]) == record["sha256"], "PROTOCOL_DRIFT", "已锁定协议内容被改动")
        return data

    @contextmanager
    def _edit(self):
        self.store._load()
        with (self.store.state_dir / "experiments.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = self._load()
            yield data
            _atomic_json(self.path, data)

    def _invalidate(self, action, protocol_id, reason):
        state = self.store._load()
        for key, stage in state["stages"].items():
            if int(key) >= 2 and stage["status"] == "passed":
                stage["status"] = "needs_recheck"
                for substep in stage["substeps"].values():
                    if substep["status"] == "passed":
                        substep["status"] = "needs_recheck"
        if state["current_stage"] is None or int(state["current_stage"]) > 2:
            state["current_stage"] = "2"
        state["history"].append({"action": action, "at": _utc_now(), "protocol_id": protocol_id, "reason": reason})
        _atomic_json(self.store.state_path, state)

    @staticmethod
    def _effective(record):
        p = copy.deepcopy(record["protocol"])
        for extension in record.get("seed_extensions", []):
            p["seeds"].extend(extension["seeds"])
        validate_protocol(p)
        return p

    def extend(self, protocol_id, extension):
        _require(isinstance(extension, dict) and isinstance(extension.get("reason"), str) and extension["reason"].strip(), "INVALID_EXTENSION", "补充 seed 须记录理由")
        with self._edit() as data:
            _require(protocol_id in data["protocols"], "PROTOCOL_MISSING", "协议不存在")
            record = data["protocols"][protocol_id]
            p = self._effective(record)
            seeds = extension.get("seeds")
            _require(isinstance(seeds, list) and seeds and all(type(s) is int and s >= 0 for s in seeds) and len(seeds) == len(set(seeds)) and not set(seeds).intersection(p["seeds"]), "INVALID_EXTENSION", "只能追加未运行过的新 seed，不能删除或重复")
            self._invalidate("seed_extension", protocol_id, extension["reason"])
            record.setdefault("seed_extensions", []).append({"seeds": list(seeds), "reason": extension["reason"], "registered_at": _utc_now()})
            p = self._effective(record)
        return {"status": "extended", "protocol_id": protocol_id, "seeds": p["seeds"]}

    def lock(self, protocol):
        validate_protocol(protocol)
        with self._edit() as data:
            _require(protocol["id"] not in data["protocols"], "PROTOCOL_EXISTS", "已锁定协议不覆盖；变更用新 ID，并说明原因")
            # A revised scientific protocol invalidates prior stage conclusions.
            if data["protocols"]:
                self._invalidate("protocol_revision", protocol["id"], protocol["rationale"])
            record = {"protocol": copy.deepcopy(protocol), "sha256": _canonical_digest(protocol), "locked_at": _utc_now(), "rules_lock_sha256": _canonical_digest(self.store._load()["rules_lock"])}
            data["protocols"][protocol["id"]] = record
        return record

    def start(self, spec):
        _require(isinstance(spec, dict), "INVALID_RUN", "运行登记必须为对象")
        with self._edit() as data:
            run_id = spec.get("run_id")
            _require(isinstance(run_id, str) and bool(TASK_ID_RE.fullmatch(run_id)) and run_id not in data["runs"], "INVALID_RUN", "run_id 非法或已存在")
            _require(spec.get("protocol_id") in data["protocols"], "PROTOCOL_MISSING", "正式运行前必须先锁协议")
            p = data["protocols"][spec["protocol_id"]]
            _require(p["rules_lock_sha256"] == _canonical_digest(self.store._load()["rules_lock"]), "STALE_PROTOCOL", "规则锁已升级；复核后以新协议登记")
            effective = self._effective(p)
            _require(spec.get("role") in {"baseline", "reference", "best_method"} and type(spec.get("seed")) is int and spec["seed"] in effective["seeds"], "INVALID_RUN", "角色或 seed 不在正式协议中")
            files = spec.get("method_files")
            _require(isinstance(files, list) and files, "INVALID_RUN", "须提供完整方法文件索引")
            for ref in files:
                evidence(self.root, ref)
            _require(len({ref["path"] for ref in files}) == len(files), "INVALID_RUN", "方法文件不能重复")
            method_hash = _canonical_digest(sorted(files, key=lambda x: x["path"]))
            related = [r for r in data["runs"].values() if r["protocol_id"] == spec["protocol_id"] and r["role"] == spec["role"]]
            _require(all(r["method_sha256"] == method_hash for r in related), "METHOD_MISMATCH", "同角色正式重复须使用同一方法版本；方法变化需新协议 ID")
            same_seed = [r for r in related if r["seed"] == spec["seed"]]
            retry = spec.get("retry_of")
            if same_seed:
                previous = data["runs"].get(retry)
                _require(previous in same_seed and previous["status"] == "infra_error" and not any(r.get("retry_of") == retry for r in same_seed), "DUPLICATE_SEED", "只允许显式重试已登记的基础设施失败，禁止挑选重复结果")
            else:
                _require(retry is None, "INVALID_RETRY", "首次运行不能指定 retry_of")
            run = {"run_id": run_id, "protocol_id": spec["protocol_id"], "protocol_sha256": p["sha256"], "role": spec["role"], "seed": spec["seed"], "method_files": copy.deepcopy(files), "method_sha256": method_hash, "retry_of": retry, "status": "running", "started_at": _utc_now(), "result": None}
            run["seed_plan_sha256"] = _canonical_digest(effective["seeds"])
            data["runs"][run_id] = run
        return run

    def finish(self, run_id, result):
        _require(isinstance(result, dict), "INVALID_RESULT", "结果须为对象")
        with self._edit() as data:
            _require(run_id in data["runs"], "RUN_MISSING", "运行必须先登记 start")
            run = data["runs"][run_id]
            _require(run["status"] == "running", "RUN_FINISHED", "已完成结果不允许覆盖")
            _require(result.get("status") in {"succeeded", "failed", "infra_error", "hard_gate_failure"}, "INVALID_RESULT", "运行状态不合法")
            refs = result.get("evidence")
            _require(isinstance(refs, dict) and "log" in refs, "INVALID_EVIDENCE", "所有运行包括失败均须保留原始日志")
            for ref in refs.values():
                evidence(self.root, ref)
            if result["status"] != "succeeded":
                _require(isinstance(result.get("error"), str) and result["error"].strip(), "INVALID_RESULT", "失败须有清晰 error")
            # Record invalid successful claims too: report blocks them without losing evidence.
            run["result"] = _finite_json(copy.deepcopy(result))
            run["status"] = result["status"]
            run["finished_at"] = _utc_now()
            validation_issues = []
            if run["status"] == "succeeded":
                try:
                    self._validate_result(data["protocols"][run["protocol_id"]]["protocol"], run["protocol_sha256"], run)
                except (FlowError, KeyError, TypeError) as exc:
                    validation_issues.append(str(exc))
        return {**run, "status": "recorded_invalid" if validation_issues else run["status"], "validation_issues": validation_issues}

    def report(self, protocol_id, roles=("baseline", "reference")):
        data = self._load()
        _require(protocol_id in data["protocols"], "PROTOCOL_MISSING", "协议不存在")
        record = data["protocols"][protocol_id]
        p = self._effective(record)
        issues, groups = [], {}
        if record["rules_lock_sha256"] != _canonical_digest(self.store._load()["rules_lock"]):
            issues.append("规则版本已变化，旧协议待重验")
        attempts = [r for r in data["runs"].values() if r["protocol_id"] == protocol_id]
        replaced = {r["retry_of"] for r in attempts if r.get("retry_of")}
        for attempt in attempts:
            for ref in (attempt.get("result") or {}).get("evidence", {}).values():
                try:
                    evidence(self.root, ref)
                except FlowError as exc:
                    issues.append(f"{attempt['run_id']}: {exc}")
        for role in roles:
            selected = [r for r in attempts if r["role"] == role and r["run_id"] not in replaced]
            if sorted(r["seed"] for r in selected) != sorted(p["seeds"]):
                issues.append(f"{role}: 正式 seed 集不完整或有重复")
            values = {}
            for run in selected:
                try:
                    self._validate_result(p, record["sha256"], run)
                    values[str(run["seed"])] = run["result"]["raw_metric"]
                except (FlowError, KeyError, TypeError) as exc:
                    issues.append(f"{run['run_id']}: {exc}")
            ordered = [values[str(s)] for s in p["seeds"] if str(s) in values]
            groups[role] = {"values": values, "count": len(ordered), "mean": statistics.mean(ordered) if ordered else None, "sample_std": statistics.stdev(ordered) if len(ordered) > 1 else None, "method_sha256": selected[0]["method_sha256"] if selected else None}
        report = {"status": "blocked" if issues else "ok", "protocol_id": protocol_id, "protocol_sha256": record["sha256"], "metric": p["metric"], "seeds": p["seeds"], "groups": groups, "issues": issues, "attempts": [{"run_id": r["run_id"], "role": r["role"], "seed": r["seed"], "status": r["status"], "retry_of": r["retry_of"]} for r in attempts]}
        report["experiment_sha256"] = _canonical_digest({"protocol": record, "runs": attempts})
        report["evaluation_protocol"] = {"training": p["training"], "evaluation_mode": p["evaluation_mode"],
                                         "high_variance": p.get("high_variance", False), "seeds": p["seeds"]}
        report["source_results"] = {r["run_id"]: (r.get("result") or {}).get("evidence", {}).get("result") for r in attempts}
        report["seed_extensions"] = record.get("seed_extensions", [])
        if not issues and "baseline" in groups and "reference" in groups:
            b, r = groups["baseline"], groups["reference"]
            sign = 1 if p["metric"]["direction"] == "maximize" else -1
            delta = sign * (r["mean"] - b["mean"])
            sigma = b["sample_std"]
            strength = "strong" if delta > 0 and (sigma is None or delta >= 5 * sigma) else "needs_more_runs" if delta > 0 and delta >= 3 * sigma else "insufficient"
            report.update(improvement=delta, baseline_sigma_multiple=delta / sigma if sigma else None, evidence_strength=strength, paired_results={str(s): {"baseline": b["values"][str(s)], "reference": r["values"][str(s)], "paired_improvement": sign * (r["values"][str(s)] - b["values"][str(s)])} for s in p["seeds"]})
            if strength != "strong":
                report["status"] = "blocked" if strength == "insufficient" else "needs_review"
                report["issues"].append("提升不足 3σ 或非正" if strength == "insufficient" else "教程要求增加重复次数并标记平台复核（3σ–5σ）")
        return report

    def _validate_result(self, p, protocol_hash, run):
        _require(run["status"] == "succeeded", "RUN_INVALID", f"运行状态为 {run['status']}")
        r = run["result"]
        for key in ("seed", "role", "method_sha256", "seed_plan_sha256"):
            _require(r.get(key) == run[key], "RESULT_MISMATCH", f"结果 {key} 与登记不符")
        _require(r.get("protocol_sha256") == protocol_hash and r.get("fixed") == p["fixed"], "PROTOCOL_MISMATCH", "结果协议/数据/预处理/评分指纹不符")
        number(r.get("raw_metric"), "raw_metric")
        _require(r.get("quality_passed") is True, "QUALITY_FAILED", "质量门未通过")
        execution = r.get("execution")
        _require(isinstance(execution, dict) and {"command", "started_at", "finished_at", "exit_code"} <= set(execution), "EXECUTION_MISSING", "须记录实际命令、起止时间、退出码；缺失值写 null 并解释")
        if any(execution[key] is None for key in ("command", "started_at", "finished_at", "exit_code")):
            _require(isinstance(execution.get("missing_reason"), str) and execution["missing_reason"].strip(), "EXECUTION_MISSING", "缺失执行信息必须说明，不可反推")
        _require(execution["exit_code"] is None or type(execution["exit_code"]) is int and execution["exit_code"] == 0, "EXECUTION_FAILED", "成功运行的实际退出码必须为 0 或解释缺失")
        actual = r.get("actual_budget", {})
        _require(isinstance(actual, dict), "INVALID_BUDGET", "actual_budget 必须为对象")
        for key, bound in p["budget"].items():
            used = number(actual.get(key), key)
            _require(used >= 0 and (used == bound["value"] if bound["mode"] == "exact" else used <= bound["value"]), "BUDGET_MISMATCH", f"实际预算 {key} 不满足 {bound}")
        for ref in run["method_files"]:
            evidence(self.root, ref)
        refs = r["evidence"]
        _require({"log", "result"} <= set(refs), "MISSING_EVIDENCE", "须有原始 result 和 log")
        for ref in refs.values():
            evidence(self.root, ref)
        raw = _read_json(evidence(self.root, refs["result"]))
        for key, value in r.items():
            if key != "evidence":
                _require(raw.get(key) == value, "RAW_RESULT_MISMATCH", f"原始 result 的 {key} 与入账记录不符")
        if p["training"]:
            _require(r.get("training_origin") == "initialization", "NOT_INDEPENDENT", "正式训练须从初始化开始")
            _require({"model", "artifact", "reload_log"} <= set(refs), "MODEL_MISSING", "训练型每个 seed 须有模型、artifact、reload_log")
            artifact = _read_json(evidence(self.root, refs["artifact"]))
            model_path = evidence(self.root, refs["model"])
            expected = {"seed": run["seed"], "role": run["role"], "method_sha256": run["method_sha256"],
                        "sha256": refs["model"]["sha256"], "size_bytes": model_path.stat().st_size,
                        "reload_metric": r.get("reload_metric")}
            _require(all(artifact.get(k) == v for k, v in expected.items()) and isinstance(artifact.get("format"), str) and artifact["format"], "ARTIFACT_MISMATCH", "artifact 与模型文件/角色/seed/方法/重载指标不符")
            _require(r.get("reload_passed") is True, "RELOAD_FAILED", "重载复评未通过")
            _require(abs(number(r.get("reload_metric"), "reload_metric") - r["raw_metric"]) <= p.get("reload_tolerance", 0), "RELOAD_MISMATCH", "重载指标超出事前容差")


def score_check(book, protocol_id, contract):
    report = book.report(protocol_id)
    if report["status"] == "blocked":
        return report
    _require(isinstance(contract, dict) and isinstance(contract.get("rationale"), str) and contract["rationale"].strip() and isinstance(contract.get("evidence"), list) and contract["evidence"], "U_EVIDENCE_MISSING", "U 必须有独立论证及证据；不能按目标分数反推")
    for ref in contract["evidence"]:
        evidence(book.root, ref)
    _require(contract.get("protocol_sha256") == report["protocol_sha256"], "STALE_SCORE_CONTRACT", "U 论证未绑定当前协议")
    b, r = report["groups"]["baseline"]["mean"], report["groups"]["reference"]["mean"]
    u, ceiling = number(contract.get("upper_bound"), "U"), number(contract.get("metric_ceiling"), "metric_ceiling")
    direction = report["metric"]["direction"]
    score = normalize(r, b, u, direction)
    sign = 1 if direction == "maximize" else -1
    _require(sign * (ceiling - u) >= 0, "INVALID_SCORE", "U 不能超过指标理论 ceiling")
    issues = list(report["issues"])
    if not 0.15 <= score <= 0.8:
        issues.append("Reference 分数不在 [0.15,0.8]；不得反推 U 修正")
    sigma = report["groups"]["baseline"]["sample_std"]
    warnings = ["剩余 headroom 小于 3σ_B，需专家说明改进空间"] if sigma and sign * (u - r) < 3 * sigma else []
    return {**report, "status": "blocked" if not 0.15 <= score <= 0.8 else report["status"], "issues": issues, "warnings": warnings, "anchors": {"baseline": b, "reference": r, "upper_bound": u, "metric_ceiling": ceiling}, "reference_score": score, "formula": "(raw-B)/(U-B), unclipped; hard gate failure = 0", "upper_bound_review": "requires_expert_review"}


def baseline_check(book, protocol_id, review, phase):
    _require(phase in (2, 3), "INVALID_PHASE", "Baseline 审查阶段只接受 2 或 3")
    report = book.report(protocol_id, ("baseline",) if phase == 2 else ("baseline", "reference"))
    if report["status"] == "blocked":
        return report
    _require(review.get("protocol_sha256") == report["protocol_sha256"] and review.get("baseline_method_sha256") == report["groups"]["baseline"]["method_sha256"], "STALE_REVIEW", "审查未绑定当前协议/Baseline 方法")
    if phase == 3:
        _require(review.get("reference_method_sha256") == report["groups"]["reference"]["method_sha256"], "STALE_REVIEW", "阶段 3 审查须绑定 Reference 方法")
    _require(review.get("experiment_sha256") == report["experiment_sha256"], "STALE_REVIEW", "运行结果或 seed 计划变化后须重新审查")
    checks = review.get("checks", {})
    _require(isinstance(checks, dict) and set(checks) == {f"B{i:02d}" for i in range(1, 9)}, "REVIEW_INCOMPLETE", "必须覆盖 B01–B08")
    issues, deferred = list(report["issues"]), []
    for key, item in checks.items():
        _require(isinstance(item, dict) and item.get("status") in {"pass", "fail", "manual", "deferred"} and all(isinstance(item.get(field), str) and item[field].strip() for field in ("reviewer", "rationale")), "INVALID_REVIEW", f"{key} 须有明确专家、结论与理由")
        _require(isinstance(item.get("evidence"), list) and item["evidence"], "MISSING_EVIDENCE", f"{key} 须引用证据")
        for ref in item["evidence"]:
            evidence(book.root, ref)
        if item["status"] == "deferred":
            _require(phase == 2 and key in {"B03", "B07"} and item.get("due_stage") == 3 and item.get("current_part_passed") is True and isinstance(item.get("pending_requirement"), str) and item["pending_requirement"].strip(), "INVALID_DEFERRAL", f"{key} 只能暂缓跨方法部分，且阶段 3 到期")
            deferred.append(key)
        elif item["status"] != "pass":
            issues.append(f"{key}: {item['status']}")
    return {"status": "blocked" if issues else "ready_for_expert_confirmation", "issues": issues, "deferred": deferred, "phase": phase, "protocol_sha256": report["protocol_sha256"], "review_sha256": _canonical_digest(review), "note": "程序只验证结论绑定与证据完整性；专家及用户冻结确认仍必需"}
