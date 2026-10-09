"""Codex observable event timing. All timestamps come from the supervising process."""
from __future__ import annotations

import math
import re

from .common import _require


class Redactor:
    def __init__(self, secrets=()):
        self.secrets = sorted({value for value in secrets if isinstance(value, str) and value}, key=len, reverse=True)

    def text(self, value):
        for secret in self.secrets:
            value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s\"']+", r"\1[REDACTED]", value)

    def value(self, value):
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {key: ("[REDACTED]" if key.lower() in {"api_key", "access_token", "refresh_token", "id_token", "authorization"} else self.value(item)) for key, item in value.items()}
        return value


def interval_seconds(intervals):
    return sum(end - start for start, end in intervals)


def union(intervals):
    merged = []
    for start, end in sorted(intervals):
        _require(all(type(v) in (float, int) and math.isfinite(v) for v in (start, end)) and end >= start, "INVALID_INTERVAL", "时间区间不合法")
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def effective_seconds(intervals, exclusions=()):
    total = 0.0
    for start, end in union(intervals):
        total += end - start
        for left, right in union(exclusions):
            total -= max(0, min(end, right) - max(start, left))
    return max(0, total)


class EventClock:
    def __init__(self, expected_thread=None, silence_seconds=300):
        self.thread_id = expected_thread
        self.saw_thread = False
        self.silence_seconds = silence_seconds
        self.last = None
        self.active = False
        self.turn_open = False
        self.pending = set()
        self.intervals = []
        self.unverified = []
        self.errors = []
        self.counts = {}
        self.completed_turns = 0

    def advance(self, at):
        _require(type(at) in (float, int) and math.isfinite(at) and (self.last is None or at >= self.last), "CLOCK_ORDER", "事件时间不应倒退")
        if self.last is not None and self.active and at > self.last:
            target = self.intervals if self.pending or at - self.last <= self.silence_seconds else self.unverified
            target.append([self.last, at])
        self.last = at

    def event(self, event, at):
        self.advance(at)
        kind = event.get("type")
        self.counts[kind] = self.counts.get(kind, 0) + 1
        if kind == "thread.started":
            thread = event.get("thread_id")
            _require(isinstance(thread, str) and bool(re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", thread)), "THREAD_MISSING", "Codex 未提供合法 thread_id")
            _require(self.thread_id is None or self.thread_id == thread, "THREAD_MISMATCH", "恢复返回了新会话，不能拼接轨迹")
            self.thread_id = thread
            self.saw_thread = True
        elif kind == "turn.started":
            _require(self.saw_thread, "THREAD_MISSING", "turn 之前缺 thread.started")
            self.turn_open = self.active = True
        elif kind in {"error", "turn.failed"}:
            self.errors.append({"at": at, "type": kind})
            self.active = False
            self.pending.clear()
            if kind == "turn.failed":
                self.turn_open = False
        elif kind == "turn.completed":
            self.active = self.turn_open = False
            self.pending.clear()
            self.completed_turns += 1
        elif isinstance(kind, str) and kind.startswith("item."):
            item = event.get("item", {})
            if self.turn_open:
                self.active = True
            if item.get("type") in {"command_execution", "mcp_tool_call"}:
                item_id = item.get("id")
                if kind == "item.started":
                    self.pending.add(item_id)
                elif kind == "item.completed":
                    self.pending.discard(item_id)

    def stop(self, at):
        self.advance(at)
        self.active = self.turn_open = False
        self.pending.clear()

    def summary(self):
        return {"thread_id": self.thread_id, "saw_thread": self.saw_thread,
                "intervals": union(self.intervals), "unverified_intervals": union(self.unverified),
                "observed_active_seconds": effective_seconds(self.intervals),
                "unverified_seconds": interval_seconds(union(self.unverified)),
                "errors": self.errors, "event_counts": self.counts, "completed_turns": self.completed_turns}
