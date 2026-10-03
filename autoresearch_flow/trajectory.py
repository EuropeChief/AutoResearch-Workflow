"""PCA Agent-authored round schema, shared by import and package validation.

This module validates records, never synthesizes an Agent trajectory from logs.
"""
from __future__ import annotations

from datetime import datetime
import math
import re

from .core import FlowError, _require

ROUND_FIELDS = frozenset({"round", "policy_name", "method_summary", "status", "score",
                          "failure_reason", "retained_best", "time"})


def validate_round(row: dict, number: int) -> dict:
    _require(isinstance(row, dict) and set(row) == ROUND_FIELDS, "TRAJECTORY_SCHEMA",
             f"第 {number} 行须含 PCA 八字段；旧轨迹不能无证据补造")
    _require(type(row["round"]) is int and row["round"] == number,
             "TRAJECTORY_ORDER", f"第 {number} 行轮次不连续")
    for key in ("policy_name", "method_summary", "status"):
        _require(isinstance(row[key], str) and row[key].strip(), "TRAJECTORY_SCHEMA",
                 f"第 {number} 轮 {key} 不能为空")
    score = row["score"]
    _require(score is None or type(score) in (int, float) and math.isfinite(score),
             "TRAJECTORY_SCORE", "score 须为真实 Public/Dev 原始指标或 null")
    _require(type(row["retained_best"]) is bool, "TRAJECTORY_SCHEMA", "retained_best 须为布尔值")
    if row["status"] == "ok":
        _require(score is not None and row["failure_reason"] is None,
                 "TRAJECTORY_STATUS", "成功须有原始分数，failure_reason 为 null")
    else:
        _require(isinstance(row["failure_reason"], str) and row["failure_reason"].strip()
                 and not row["retained_best"], "TRAJECTORY_STATUS", "失败须说明原因且不能保留为最佳")
    stamp = row["time"]
    _require(isinstance(stamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", stamp),
             "TRAJECTORY_TIME", "完成时间须为 YYYY-MM-DD HH:mm:ss")
    try:
        datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
    except ValueError as exc:
        raise FlowError("TRAJECTORY_TIME", "完成时间不是有效日期") from exc
    return dict(row)


def raw_public_metric(result: dict) -> float | None:
    """Explicit adapter for W3's normalized score vs. PCA raw trajectory score."""
    _require(isinstance(result, dict), "PUBLIC_RESULT", "公开结果须为对象")
    if result.get("status") != "succeeded":
        return None
    metric = result.get("raw_metric")
    _require(isinstance(metric, dict) and metric.get("direction") in {"minimize", "maximize"}
             and isinstance(metric.get("name"), str) and metric["name"]
             and type(metric.get("value")) in (int, float) and math.isfinite(metric["value"]),
             "PUBLIC_RESULT", "成功公开结果缺原始指标，不能以归一化 score 替代")
    return metric["value"]
