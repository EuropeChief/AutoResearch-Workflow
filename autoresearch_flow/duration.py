"""One frozen duration policy, with pre-run eligibility and post-run Roll evidence.

No timing is inferred from wall clock or trajectory summaries. Expert judgments
have located evidence; final method rerun remains a stage-5 responsibility.
"""
from __future__ import annotations

import math
from pathlib import Path

from .core import TaskStore, _atomic_json, _canonical_digest, _require, _utc_now
from .experiments import ExperimentBook, evidence
from .policies import DURATION_SECONDS, effective_policy


def text(value, label):
    _require(isinstance(value, str) and value.strip(), "DURATION_EVIDENCE", f"缺 {label}")


def positive(value, label):
    _require(type(value) in (int, float) and math.isfinite(value) and value > 0,
             "DURATION_EVIDENCE", f"{label} 须为有限正数")


def check_refs(root, refs):
    _require(isinstance(refs, list) and refs, "DURATION_EVIDENCE", "缺真实证据引用")
    for ref in refs:
        evidence(root, ref)


def validate_assessment(root, decision):
    _require(isinstance(decision, dict) and isinstance(decision.get("mode"), str)
             and decision["mode"] in DURATION_SECONDS,
             "DURATION_EVIDENCE", "未知时长模式")
    for key in ("reviewer", "approved_by", "rationale"):
        text(decision.get(key), key)
    check_refs(root, decision.get("evidence"))
    if decision["mode"] == "non_training_7h":
        _require(all(decision.get(k) is True for k in ("non_training", "no_finetuning", "short_iterations")),
                 "DURATION_INELIGIBLE", "7h 仅用于完全不训练/不微调且单轮很短的任务")
        for key in ("protocol_id", "public_dev_protocol", "non_training_basis", "short_iteration_basis"):
            text(decision.get(key), key)
        samples = decision.get("iteration_samples")
        _require(isinstance(samples, list) and samples, "DURATION_EVIDENCE", "缺实际迭代耗时样本")
        for sample in samples:
            _require(isinstance(sample, dict), "DURATION_EVIDENCE", "耗时样本须为对象")
            positive(sample.get("seconds"), "样本秒数")
            evidence(root, sample.get("evidence"))


def snapshot(root):
    store = TaskStore(Path(root))
    state = store._load()
    policy = effective_policy(state)["duration_policy"]
    assessment = state.get("duration_assessment")
    if assessment is not None:
        _require(isinstance(assessment, dict) and isinstance(assessment.get("decision"), dict),
                 "DURATION_EVIDENCE", "时长决策记录无效")
        body = {k: v for k, v in assessment.items() if k != "sha256"}
        _require(assessment.get("sha256") == _canonical_digest(body)
                 and body["decision"].get("mode") == policy["mode"],
                 "DURATION_DRIFT", "时长决策指纹或模式不匹配")
        validate_assessment(store.task_root, body["decision"])
        if policy["mode"] == "non_training_7h":
            protocol = ExperimentBook(store.task_root)._load()["protocols"].get(body["decision"]["protocol_id"])
            _require(protocol is not None and protocol["sha256"] == body.get("protocol_sha256")
                     and protocol["protocol"]["training"] is False,
                     "DURATION_INELIGIBLE", "非训练资格与冻结实验协议不符")
    payload = {"policy": policy, "assessment": assessment}
    return {**payload, "sha256": _canonical_digest(payload)}


def select(root, decision, *, confirm=False):
    store = TaskStore(Path(root))
    _require(confirm, "DURATION_CONFIRMATION_REQUIRED", "审查资格与证据后显式 --confirm-duration")
    _require(not store.check()["issues"], "SOURCE_DRIFT", "先处理来源漂移")
    state = store._load()
    runtime = store.state_dir / "runtime"
    _require(not runtime.exists() and not runtime.is_symlink(), "DURATION_FROZEN", "runtime 已准备，不得事后降低门槛或拼接轨迹")
    _require(state["current_stage"] == "4" and state["stages"]["4"]["substeps"]["4.1"]["status"] != "passed",
             "DURATION_STAGE", "在阶段 4.1、runtime prepare 之前确认时长")
    _require("duration_assessment" not in state, "DURATION_FROZEN", "时长决策已冻结，不覆盖原决定")
    validate_assessment(store.task_root, decision)
    protocol_hash = None
    if decision["mode"] == "non_training_7h":
        protocol = ExperimentBook(store.task_root)._load()["protocols"].get(decision["protocol_id"])
        _require(protocol is not None and protocol["protocol"]["training"] is False,
                 "DURATION_INELIGIBLE", "正式协议须明确为非训练任务")
        protocol_hash = protocol["sha256"]
    body = {"decision": decision, "protocol_sha256": protocol_hash, "confirmed_at": _utc_now()}
    state["duration_assessment"] = {**body, "sha256": _canonical_digest(body)}
    state["workflow_policy"]["duration_policy"] = {"mode": decision["mode"],
        "minimum_effective_seconds": DURATION_SECONDS[decision["mode"]]}
    state["history"].append({"action": "duration_selected", "at": body["confirmed_at"], "assessment_sha256": _canonical_digest(body)})
    store._validate_state(state)
    _atomic_json(store.state_path, state)
    return {"status": "frozen_before_runtime", **snapshot(root)}


def prompt_text(value):
    hours = value["policy"]["minimum_effective_seconds"] // 3600
    note = f"本组冻结目标为至少 {hours} 小时净有效独立迭代，两组分别计算。排队、安装、构建失败、长时间阻塞不计时；只在同一原会话恢复，不靠等待补时。"
    if value["policy"]["mode"] == "non_training_7h":
        note += "本题采用非训练短迭代例外：至少完成3轮有效方法闭环（改动、同一 Public/Dev 评分结论、下一轮决策）；真实方法失败可计，纯排障/机械重复不可计。中文方法摘要须体现连续演进，结束时说明至少一个可继续验证方向。仍只写原八个轨迹字段。"
    return note


def validate_roll(root, rows, review, public_protocol):
    """Semantic truth is the expert's responsibility; require located evidence."""
    _require(isinstance(review, dict), "ROLL_EVIDENCE", "缺持续迭代审阅")
    text(review.get("reviewer"), "闭环审阅人")
    for name in ("continuous_evolution", "next_direction"):
        text(review.get(name), name)
    positive(review.get("typical_round_minutes"), "典型单轮分钟数")
    items = review.get("rounds")
    _require(isinstance(items, list) and len(items) == len(rows), "ROLL_EVIDENCE", "逐轮闭环审阅缺失")
    effective = []
    for number, (row, item) in enumerate(zip(rows, items), 1):
        _require(isinstance(item, dict) and item.get("round") == number
                 and item.get("consistent") is True and type(item.get("method_iteration")) is bool,
                 "ROLL_EVIDENCE", "须逐轮区分真实方法迭代与排障/重复")
        refs = item.get("evidence")
        _require(isinstance(refs, list) and refs, "ROLL_EVIDENCE", "闭环缺操作/评分证据")
        for located in refs:
            _require(isinstance(located, dict), "ROLL_EVIDENCE", "证据定位须为对象")
            text(located.get("locator"), "行号/事件定位")
            evidence(root, located.get("ref"))
        if item["method_iteration"]:
            _require(row.get("round") == number, "ROLL_EVIDENCE", "审阅轮次与轨迹不一致")
            for name in ("method_change", "score_conclusion", "next_decision"):
                text(item.get(name), name)
            _require(item.get("public_dev_protocol") == public_protocol,
                     "ROLL_PROTOCOL", "有效闭环必须使用同一 Public/Dev 口径")
            effective.append(item["method_change"].strip())
    _require(len(effective) >= 3 and len(set(effective)) == len(effective),
             "ROLL_INCOMPLETE", "每条至少3轮非机械重复的有效方法闭环；排障不计入")
    return len(effective)
