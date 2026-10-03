"""Portable, package-only evidence for the tutorial's non-training 7h exception."""
from __future__ import annotations

import copy
import math
import shutil

from .core import _atomic_json, _read_json, _require, _sha256
from .duration import snapshot, validate_assessment, validate_roll
from .experiments import evidence
from .pca_contract import task_digest
from .policies import DURATION_SECONDS
from .runtime import TRACKS, Runtime
from .runtime_events import effective_seconds


def explanation(bundle):
    decision = bundle["assessment"]["decision"]
    lines = ["## 非训练 7h 例外证据", decision["rationale"],
             "不训练/不微调依据：" + decision["non_training_basis"],
             "短迭代依据：" + decision["short_iteration_basis"],
             "证据索引：[duration_evidence.json](duration_evidence.json)。时长按各自净有效时间，不相加。"]
    for track in TRACKS:
        row = bundle["tracks"][track]
        review = row["review"]
        lines.append(f"{track}：净有效 {row['effective_seconds'] / 3600:.6f} 小时；有效方法闭环 {row['effective_rounds']} 轮；典型单轮 {review['typical_round_minutes']:g} 分钟。")
        lines.extend(["连续演进：" + review["continuous_evolution"], "可继续验证方向：" + review["next_direction"]])
    lines.append("唯一 best_method 已在干净快照中重跑成功；结果/日志与方法指纹见证据索引。此为本地专家证据，不声明平台已验收。")
    return "\n\n".join(lines) + "\n"


def export(root, package, delivery, verification):
    value = snapshot(root)
    _require(value["policy"]["mode"] == "non_training_7h", "DURATION_EVIDENCE", "仅例外任务导出此证据")

    def copy_ref(ref, source_root=root):
        source = evidence(source_root, ref)
        relative = f"expert_evidence/duration_sources/{ref['sha256']}{source.suffix}"
        dest = package / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        _require(_sha256(dest) == ref["sha256"], "DURATION_DRIFT", "例外证据复制时变化")
        return {"path": relative, "sha256": ref["sha256"]}

    def relocate(value):
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                return copy_ref(value)
            return {k: relocate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [relocate(v) for v in value]
        return value

    assessment = relocate(copy.deepcopy(value["assessment"]))
    # Path relocation changes the portable representation; keep both fingerprints.
    assessment["source_sha256"] = assessment.pop("sha256")
    tracks = {}
    runtime = Runtime(root)
    for track in TRACKS:
        status = runtime.status(track)
        state = runtime._state(track)
        final, _ = delivery.current_trajectory(track)
        review = delivery.current_review(track)["review"]
        count = validate_roll(root, _read_json(final)["rounds"], review, value["assessment"]["decision"]["public_dev_protocol"])
        intervals = [i for s in state["segments"] if s["phase"] == "formal" for i in s["intervals"]]
        exclusions = relocate(state.get("exclusions", []))
        logs = [copy_ref(ref, runtime.directory) for s in state["segments"] if s["phase"] == "formal" for ref in s["logs"]]
        tracks[track] = {"thread_id": status["thread_id"], "active": status["active"],
            "effective_seconds": status["effective_seconds_before_content_review"],
            "intervals": intervals, "exclusions": exclusions, "timing_logs": logs,
            "trajectory_sha256": _sha256(final), "review": relocate(review), "effective_rounds": count}
    bundle = {"schema_version": 1, "policy": value["policy"], "source_policy_sha256": value["sha256"],
        "assessment": assessment, "tracks": tracks, "clean_verification": {
            "method_sha256": verification["method_sha256"],
            "protocol_id": verification["protocol_id"], "protocol_sha256": verification["protocol_sha256"],
            "result": copy_ref(verification["clean_result"]), "log": copy_ref(verification["clean_log"]),
            "best_tree_sha256": task_digest(package / "expert_evidence/best_method")}}
    _atomic_json(package / "expert_evidence/duration_evidence.json", bundle)
    doc = package / "expert_evidence/专家作业说明文档.md"
    doc.write_text(doc.read_text(encoding="utf-8") + "\n\n" + explanation(bundle), encoding="utf-8")
    summary_path = package / "expert_evidence/run_summary.json"
    summary = _read_json(summary_path)
    summary["fast_iteration_exception"]["evidence"] += "\n\n" + explanation(bundle)
    _atomic_json(summary_path, summary)


def check(package, summary, protocol, protocol_id):
    bundle = _read_json(package / "expert_evidence/duration_evidence.json")
    _require(bundle.get("schema_version") == 1 and bundle.get("policy") == {
        "mode": "non_training_7h", "minimum_effective_seconds": DURATION_SECONDS["non_training_7h"]}, "DURATION_EVIDENCE", "缺7h冻结政策")
    assessment = bundle.get("assessment", {})
    decision = assessment.get("decision")
    validate_assessment(package, decision)
    _require(isinstance(protocol, dict) and protocol.get("training") is False
             and decision["mode"] == "non_training_7h" and decision["protocol_id"] == protocol_id,
             "DURATION_INELIGIBLE", "训练型或不匹配协议不可交7h例外")
    tracks = bundle.get("tracks")
    _require(isinstance(tracks, dict) and set(tracks) == set(TRACKS), "ROLL_EVIDENCE", "两条例外记录缺失")
    thread_ids = []
    for track, declared in zip(TRACKS, summary["agent_execution"]):
        row = tracks[track]
        _require(isinstance(row, dict) and {"thread_id", "active", "review", "effective_rounds", "trajectory_sha256"} <= row.keys()
                 and isinstance(row.get("thread_id"), str) and row["thread_id"]
                 and row.get("active") is None, "ROLL_EVIDENCE", "轨迹尚未收口或缺会话标识")
        thread_ids.append(row["thread_id"])
        for ref in row.get("timing_logs", []):
            evidence(package, ref)
        _require(row.get("timing_logs"), "ROLL_EVIDENCE", "缺可核运行日志")
        exclusions = row.get("exclusions", [])
        _require(isinstance(exclusions, list) and isinstance(row.get("intervals"), list)
                 and all(isinstance(i, list) and len(i) == 2 for i in row["intervals"])
                 and all(isinstance(e, dict) and {"start", "end", "evidence"} <= e.keys() for e in exclusions)
                 and type(row.get("effective_seconds")) in (int, float),
                 "DURATION_EVIDENCE", "缺可重算净时长的活动/扣除区间")
        for entry in exclusions:
            _require(isinstance(entry["evidence"], list) and entry["evidence"], "DURATION_EVIDENCE", "时间扣除缺证据")
            for ref in entry.get("evidence", []):
                evidence(package, ref)
        seconds = effective_seconds(row["intervals"], [[e["start"], e["end"]] for e in exclusions])
        _require(seconds >= DURATION_SECONDS["non_training_7h"] and abs(seconds - row["effective_seconds"]) < 0.001
                 and abs(declared["duration_hours"] * 3600 - seconds) <= 1,
                 "DURATION_SHORT", "7h逐轨净时长不足或摘要与可核计时不一致（不能凑整/相加）")
        path = package / f"expert_evidence/trajectory_{track}.json"
        _require(_sha256(path) == row.get("trajectory_sha256"), "ROLL_EVIDENCE", "例外审阅与当前轨迹不符")
        count = validate_roll(package, _read_json(path)["rounds"], row["review"], decision["public_dev_protocol"])
        _require(count == row["effective_rounds"] == declared["effective_rounds"]
                 and declared["typical_round_minutes"] == row["review"]["typical_round_minutes"],
                 "ROLL_EVIDENCE", "闭环数量或典型耗时与摘要不符")
    _require(len(set(thread_ids)) == 2, "ROLL_EVIDENCE", "两组必须使用独立会话，不可合并时长")
    clean = bundle.get("clean_verification")
    _require(isinstance(clean, dict) and {"result", "log", "protocol_id", "protocol_sha256", "method_sha256", "best_tree_sha256"} <= clean.keys(),
             "CLEAN_RERUN_INVALID", "缺干净快照重跑证据")
    result = _read_json(evidence(package, clean["result"]))
    evidence(package, clean["log"])
    _require(clean["protocol_id"] == protocol_id and clean["protocol_sha256"] == assessment["protocol_sha256"]
             and clean["best_tree_sha256"] == task_digest(package / "expert_evidence/best_method")
             and result.get("method_sha256") == clean["method_sha256"] and result.get("status") == "succeeded"
             and type(result.get("score")) in (int, float) and math.isfinite(result["score"])
             and isinstance(result.get("execution"), dict) and result["execution"].get("exit_code") == 0
             and isinstance(result["execution"].get("command"), list) and result["execution"]["command"]
             and all(isinstance(result["execution"].get(k), str) and result["execution"][k] for k in ("started_at", "finished_at")),
             "CLEAN_RERUN_INVALID", "例外缺绑定当前方法/协议的干净快照成功出分")
    _require(explanation(bundle) in (package / "expert_evidence/专家作业说明文档.md").read_text(encoding="utf-8")
             and explanation(bundle) in summary["fast_iteration_exception"]["evidence"],
             "DURATION_EVIDENCE", "专家说明/摘要缺与本包一致的7h例外事实和证据引用")
    return bundle
