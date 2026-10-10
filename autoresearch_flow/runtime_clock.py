"""Recomputable actual-activity intervals, not Goal counters or wall-clock caps."""
from __future__ import annotations

import json
import math
from pathlib import Path
import time

from .common import _require


def union_seconds(intervals):
    result, end = 0.0, None
    for start, stop in sorted(intervals):
        _require(math.isfinite(start) and math.isfinite(stop) and stop >= start,
                 'TIMING_INVALID', '区间时标无效')
        result += max(0.0, stop - max(start, end if end is not None else start))
        end = max(stop, end if end is not None else stop)
    return result


def activity_summary(records, *, now=None):
    opened, intervals, unresolved, adjustments, closed_jobs, pending_jobs = {}, [], [], [], set(), {}
    for record in records:
        key = (record['segment'], record.get('activity'))
        action, stamp = record['action'], record['monotonic']
        if action == 'start':
            _require(key not in opened, 'TIMING_INVALID', '同一活动重复开始')
            opened[key] = record
        elif action == 'end':
            _require(key in opened, 'TIMING_INVALID', '活动结束缺少开始证据')
            begin = opened.pop(key)
            _require(stamp >= begin['monotonic'], 'TIMING_INVALID', '单段单调时钟倒退')
            intervals.append((begin['at'], begin['at'] + stamp - begin['monotonic']))
            if str(record.get('activity','')).startswith('job:') and record.get('verified_terminal',True):
                closed_jobs.add(record['activity'])
        elif action == 'fact' and record.get('unresolved_job'):
            pending_jobs[record['activity']] = {'activity':record['activity'], 'segment':record['segment'],
                                              'evidence':record['evidence'], 'reason':'worker terminal state unknown'}
        elif action == 'exclude':
            start, stop = record['start_at'], record['stop_at']
            _require(type(start) in (int, float) and type(stop) in (int, float)
                     and math.isfinite(start) and math.isfinite(stop) and stop >= start
                     and record.get('reason') and record.get('evidence'),
                     'TIMING_INVALID', '扣除须含有界时间、原因和原件依据')
            adjustments.append((start, stop))
    for key, record in opened.items():
        if key[1] in closed_jobs:
            continue  # Same durable job has complete original start/finish evidence.
        if now is not None and key[0] == now['segment'] and now['monotonic'] >= record['monotonic']:
            intervals.append((record['at'], record['at'] + now['monotonic'] - record['monotonic']))
        else:
            unresolved.append({'segment': key[0], 'activity': key[1], 'started_at': record['at']})
    unresolved.extend(value for job,value in pending_jobs.items() if job not in closed_jobs)
    # Subtract only the intersection with recorded actual activity, never negative time.
    combined = sorted(intervals)
    intersections = [(max(a, c), min(b, d)) for a, b in combined for c, d in adjustments
                     if max(a, c) < min(b, d)]
    return {'gross_active_seconds': union_seconds(combined),
            'excluded_seconds': union_seconds(intersections),
            'net_active_seconds': union_seconds(combined) - union_seconds(intersections),
            'unresolved': unresolved, 'intervals': combined,
            'note': 'union of actual turns/jobs; unknown/crashed open segments not guessed; Goal counter is not used'}


class ActivityClock:
    def __init__(self, path, segment):
        self.path, self.segment, self.active = Path(path), segment, set()

    def record(self, action, *, activity=None, evidence, **fields):
        _require(action in {'start', 'end', 'fact', 'exclude'}, 'TIMING_INVALID', '计时动作无效')
        if action == 'start':
            if activity in self.active:
                return
            self.active.add(activity)
        if action == 'end':
            if activity not in self.active:
                return
            self.active.remove(activity)
        record = {'action': action, 'activity': activity, 'segment': self.segment,
                  'at': time.time(), 'monotonic': time.monotonic(), 'evidence': evidence, **fields}
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(record, ensure_ascii=False) + '\n')

    def summary(self, *, live=False):
        records = [json.loads(line) for line in self.path.read_text(encoding='utf-8').splitlines()] if self.path.exists() else []
        now = {'segment': self.segment, 'monotonic': time.monotonic()} if live else None
        return dict(activity_summary(records, now=now),observed_clock=now)

    def close(self, evidence):
        for activity in list(self.active):
            self.record('end', activity=activity, evidence=evidence)
