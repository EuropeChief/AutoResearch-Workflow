"""Agent-authored trajectory conversion only; no synthesis from runtime logs."""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

from .common import FlowError, _require, _atomic_json
from .materials_io import bundled, issue, read_object
from .trajectory import ROUND_FIELDS


def check_rounds(value, path="trajectory", *, metric=None, observations=None):
    findings = []
    if metric is not None and (not isinstance(metric,dict) or metric.get("direction") not in {"minimize","maximize"}):
        issue(findings,"TRAJECTORY_METRIC",path,"可选 metric 须声明实际 maximize/minimize 方向")
        return findings
    if observations is not None and not isinstance(observations,dict):
        issue(findings,"TRAJECTORY_OBSERVATION",path,"逐轮核对须为轮次到实际评测对象的映射")
        return findings
    if not isinstance(value, dict) or not isinstance(value.get("rounds"), list) or not value["rounds"]:
        issue(findings, "TRAJECTORY_ROUNDS", path, "根对象须含非空 rounds 数组")
        return findings
    known = bundled("submission_format")
    previous, best, last_time = 0, None, None
    for i, row in enumerate(value["rounds"]):
        loc = f"{path}:rounds[{i}]"
        if not isinstance(row, dict):
            issue(findings, "TRAJECTORY_FIELD", loc, "轮次须为对象"); continue
        missing = ROUND_FIELDS - row.keys()
        if missing:
            issue(findings, "TRAJECTORY_FIELD", loc, "缺字段：" + ", ".join(sorted(missing))); continue
        extra = row.keys() - ROUND_FIELDS
        if extra:
            issue(findings, "TRAJECTORY_EXTRA", loc, "最终每轮仅保留八字段：" + ", ".join(sorted(extra)))
        number = row["round"]
        if type(number) is not int or number <= previous:
            issue(findings, "TRAJECTORY_ORDER", loc + ".round", "轮次须为正整数且严格递增")
        else:
            if previous == 0 and number != 1:
                issue(findings, "TRAJECTORY_START", loc + ".round", "轨迹须从第 1 轮开始")
            previous = number
        for key in ("policy_name", "method_summary", "status"):
            if not isinstance(row[key], str) or not row[key].strip():
                issue(findings, "TRAJECTORY_FIELD", loc + "." + key, "须为非空字符串")
        status = row["status"].strip().casefold() if isinstance(row["status"], str) else ""
        success, failed = status in known.SUCCESS_STATUSES, status in known.FAILURE_STATUSES
        score = row["score"]
        finite = type(score) in (int, float) and math.isfinite(score)
        if not finite and (success or score is not None):
            issue(findings, "TRAJECTORY_SCORE", loc + ".score", "成功须有有限原始指标，失败未知才可 null")
        if type(row["retained_best"]) is not bool:
            issue(findings, "TRAJECTORY_FIELD", loc + ".retained_best", "须为布尔值")
        if success and row["failure_reason"] is not None:
            issue(findings, "TRAJECTORY_STATUS", loc + ".failure_reason", "成功时为 null")
        if failed and (not isinstance(row["failure_reason"], str) or not row["failure_reason"].strip()):
            issue(findings, "TRAJECTORY_STATUS", loc + ".failure_reason", "失败须有真实原因")
        if failed and row["retained_best"] is True:
            issue(findings, "TRAJECTORY_BEST", loc + ".retained_best", "失败不得标最佳")
        if status and not success and not failed:
            issue(findings, "TRAJECTORY_STATUS_REVIEW", loc + ".status", "自定义状态需核实际含义，不自动判失败/成功", level="review")
            if row["failure_reason"] is not None and not isinstance(row["failure_reason"],str):
                issue(findings,"TRAJECTORY_STATUS",loc+".failure_reason","原因须为字符串或 null")
        try:
            stamp = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
            if last_time is not None and stamp < last_time:
                issue(findings, "TRAJECTORY_TIME", loc + ".time", "完成时间倒退")
            last_time = stamp
        except (TypeError, ValueError):
            issue(findings, "TRAJECTORY_TIME", loc + ".time", "按教程使用有效 YYYY-MM-DD HH:mm:ss 完成时间")
        if success and finite and metric and metric.get("direction") in {"minimize", "maximize"}:
            better = best is None or (score < best if metric["direction"] == "minimize" else score > best)
            if row["retained_best"] is True and not better and score != best:
                issue(findings, "TRAJECTORY_BEST", loc + ".retained_best", "比历史最佳更差却标为最佳")
            if better: best = score
        if observations is not None:
            record = observations.get(str(number))
            if not isinstance(record,dict):
                issue(findings, "TRAJECTORY_OBSERVATION", loc, "给定评测记录缺少该轮", level="review")
            elif record.get("split") not in {"dev", "public_dev", metric.get("split") if metric else None} or record.get("direction") != (metric or {}).get("direction"):
                issue(findings, "TRAJECTORY_METRIC", loc, "评测 split/指标方向不一致")
            elif success and record.get("raw_value") != score:
                issue(findings, "TRAJECTORY_RAW_SCORE", loc + ".score", "与该轮 Public/Dev 原始值不一致；不可填归一化分数")
    return findings


def prepare(source, output, *, metric=None, observations=None):
    source, output = Path(source), Path(output)
    _require(source.resolve() != output.resolve() and not output.exists(), "OUTPUT_EXISTS", "输出须为新文件，不能覆盖原轨迹")
    if source.suffix == ".jsonl":
        _require(source.is_file() and not source.is_symlink() and source.stat().st_size <= 8*1024*1024,
                 "TRAJECTORY_SOURCE", "须提供普通、可读取的 Agent 自写 JSONL")
        try:
            rows = [json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
                    for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (ValueError, UnicodeError) as exc:
            raise FlowError("TRAJECTORY_JSONL", f"原轨迹有无法解析的行：{exc}") from exc
        value = {"rounds": rows}
    else:
        value = read_object(source)
    findings = check_rounds(value, source.name, metric=metric, observations=observations)
    if any(x["level"] == "error" for x in findings):
        return {"status": "issues_found", "issues": findings}
    output.parent.mkdir(parents=True, exist_ok=True)
    _atomic_json(output, {"rounds": value["rounds"]})
    return {"status": "prepared", "output": str(output), "rounds": len(value["rounds"]), "issues": findings,
            "pending": ["原会话/模型/净时长与方法真实性按运行证据核查；整理不生成这些事实"]}
