"""Optional fixed-entry jobs for a task needing execution outside Codex's sandbox.

Only the expert-side coordinator imports this module. Requests cannot specify
host commands, source directories, GPU IDs or credentials. No socket or daemon
credential is exposed to the model. A disconnected client does not cancel jobs.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import time

from .common import FlowError, _atomic_json, _canonical_digest, _read_json, _require
from .runtime_files import read_tail

IDENTIFIER = re.compile(r'[a-f0-9]{32}')
BUSY_STATUSES = {'running', 'observation_pending'}
CODEX_PROTECTION_DIRS = frozenset({'.git', '.agents', '.codex', '.aws'})


def public_result(stdout, exit_code):
    if exit_code != 0:
        return {'status': 'failed', 'exit_code': exit_code, 'error': 'fixed public runner failed'}
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(value, dict) or value.get('status') != 'succeeded':
            continue
        score, raw = value.get('score'), value.get('raw_metric')
        if (type(score) in (int, float) and math.isfinite(score) and isinstance(raw, dict)
                and isinstance(raw.get('name'), str) and raw['name']
                and raw.get('direction') in {'maximize', 'minimize'}
                and type(raw.get('value')) in (int, float) and math.isfinite(raw['value'])):
            return {'status': 'succeeded', 'exit_code': 0, 'score': score, 'raw_metric': raw}
    return {'status': 'failed', 'exit_code': 0, 'error': 'public runner omitted finite score/raw_metric'}


def freeze_candidate(source, target, limit=64 * 1024 * 1024):
    source, target = Path(source), Path(target)
    _require(source.is_dir() and not source.is_symlink(), 'CANDIDATE_INVALID', '候选须为普通目录')
    _require(not target.exists(), 'JOB_EXISTS', '不覆盖候选快照')
    files, total, ignored = {}, 0, []
    target.mkdir(parents=True)
    try:
        for path in sorted(source.rglob('*')):
            relative = path.relative_to(source)
            info = path.lstat()
            _require(not stat.S_ISLNK(info.st_mode) and (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)),
                     'CANDIDATE_INVALID', '候选快照不接受符号链接或特殊文件')
            # Native Codex temporarily creates empty mount targets while
            # evaluate.py runs. The tool sees read-only mounts, but the host
            # sees mode-0755 directories. Only empty reserved root directories
            # are infrastructure; preserve actual content and nested directories.
            if (len(relative.parts) == 1 and relative.name in CODEX_PROTECTION_DIRS
                    and stat.S_ISDIR(info.st_mode)
                    and next(path.iterdir(), None) is None):
                ignored.append(str(relative))
                continue
            if path.is_dir():
                (target / relative).mkdir(exist_ok=True)
                continue
            # O_NOFOLLOW plus metadata verification prevents normal symlink swaps.
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as stream:
                current = os.fstat(stream.fileno())
                _require(stat.S_ISREG(current.st_mode) and current.st_size <= limit - total,
                         'CANDIDATE_LIMIT', '候选快照超过体积限制')
                raw = stream.read(limit - total + 1)
                after = os.fstat(stream.fileno())
                _require(len(raw) <= limit - total and current.st_mtime_ns == after.st_mtime_ns
                         and current.st_size == after.st_size,
                         'CANDIDATE_CHANGED', '复制过程中候选变化，请稳定保存后重试')
            total += len(raw)
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            destination.chmod(0o555 if info.st_mode & 0o111 else 0o444)
            files[str(relative)] = hashlib.sha256(raw).hexdigest()
        for directory in sorted((p for p in target.rglob('*') if p.is_dir()), reverse=True):
            directory.chmod(0o555)
        target.chmod(0o555)
    except BaseException:
        for directory in [target, *(p for p in target.rglob('*') if p.is_dir())]:
            directory.chmod(0o755)
        shutil.rmtree(target)
        raise
    result = {'files': files, 'sha256': _canonical_digest(files), 'bytes': total}
    if ignored:
        result['ignored_sandbox_protection_dirs'] = ignored
    return result


class FileJobs:
    """Single-track bounded job coordinator, with durable public status/results."""
    def __init__(self, root, candidate, runner, *, max_candidate_bytes=64 * 1024 * 1024):
        self.root, self.candidate, self.runner = Path(root), Path(candidate), runner
        self.limit, self.pending = max_candidate_bytes, {}
        for name in ('requests', 'responses', 'worker', 'records'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / 'requests').chmod(0o700)
        (self.root / 'responses').chmod(0o755)
        (self.root / 'worker').chmod(0o755)

    def _write_response(self, identifier, result):
        path = self.root / 'responses' / (identifier + '.json')
        _atomic_json(path, result)
        path.chmod(0o444)

    def _record(self, job, value):
        value = dict(value, job_id=job, updated_at=time.time())
        _atomic_json(self.root / 'records' / (job + '.json'), value)
        return value

    def reconcile(self):
        # In-memory tasks disappear on recovery; trusted persistent records do not.
        for path in (self.root / 'records').glob('*.completion.json'):
            job = path.name.removesuffix('.completion.json')
            record = self.root / 'records' / (job + '.json')
            if IDENTIFIER.fullmatch(job) and record.exists():
                state = _read_json(record)
                if state.get('status') in BUSY_STATUSES:
                    self._record(job, dict(state, **_read_json(path)))

    def busy(self):
        self.reconcile()
        return [p.stem for p in (self.root / 'records').glob('*.json')
                if IDENTIFIER.fullmatch(p.stem) and _read_json(p).get('status') in BUSY_STATUSES]

    async def _run(self, job, snapshot):
        try:
            outcome = await self.runner(job, self.root / 'worker' / job)
            result = public_result(outcome['stdout'], outcome['exit_code'])
            (self.root / 'records' / (job + '.stdout.log')).write_text(outcome['stdout'], encoding='utf-8')
            (self.root / 'records' / (job + '.stderr.log')).write_text(outcome.get('stderr', ''), encoding='utf-8')
            result.update(started_at=snapshot['started_at'], finished_at=outcome.get('finished_at',time.time()),
                          started_monotonic=snapshot['started_monotonic'],
                          finished_monotonic=outcome.get('finished_monotonic',time.monotonic()),
                          candidate_sha256=snapshot['candidate_sha256'])
            self._record(job, result)
        except Exception as exc:
            unknown = isinstance(exc, FlowError) and exc.code == 'JOB_SUPERVISOR_EXIT'
            times = ({'observation_ended_at':time.time(), 'observation_ended_monotonic':time.monotonic()}
                     if unknown else {'finished_at':time.time(), 'finished_monotonic':time.monotonic()})
            self._record(job, dict(snapshot, status='observation_pending' if unknown else 'failed',
                                   error=type(exc).__name__ + ': ' + str(exc), **times))
        finally:
            self.pending.pop(job, None)

    async def handle(self, request):
        _require(isinstance(request, dict), 'REQUEST_INVALID', '请求须为 JSON 对象')
        identifier = request.get('request_id', '')
        _require(isinstance(identifier, str) and IDENTIFIER.fullmatch(identifier), 'REQUEST_INVALID', '请求 ID 无效')
        operation = request.get('operation')
        _require(isinstance(operation, str), 'REQUEST_INVALID', 'operation 须为固定操作字符串')
        expected = {'request_id', 'operation'} | ({'job_id'} if operation != 'submit' else set())
        _require(set(request) == expected and operation in {'submit', 'status', 'logs', 'result'},
                 'REQUEST_DENIED', '只接受固定公开提交/状态/日志/结果，不能指定路径、命令或资源')
        if operation == 'submit':
            job = identifier
            self.reconcile()
            record = self.root / 'records' / (job + '.json')
            if record.exists():
                return _read_json(record)
            _require(not self.busy(), 'JOB_BUSY', '本轨已有公开作业或待核状态，先查询结果，不能重复占用资源')
            work = self.root / 'worker' / job
            work.mkdir()
            snapshot = freeze_candidate(self.candidate, work / 'solution', self.limit)
            output = work / 'output'
            output.mkdir(mode=0o777)
            output.chmod(0o777)
            metadata = {'status': 'running', 'started_at': time.time(), 'started_monotonic':time.monotonic(),
                        'candidate_sha256': snapshot['sha256']}
            _atomic_json(work / 'candidate.json', snapshot)
            state = self._record(job, metadata)
            self.pending[job] = asyncio.create_task(self._run(job, metadata))
            return state
        job = request.get('job_id', '')
        _require(isinstance(job, str) and IDENTIFIER.fullmatch(job), 'REQUEST_INVALID', '作业 ID 无效')
        record = self.root / 'records' / (job + '.json')
        _require(record.is_file(), 'JOB_MISSING', '不存在本轨公开作业')
        state = _read_json(record)
        if operation == 'logs':
            log = self.root / 'worker' / job / 'output' / 'runner.log'
            try:
                state['log'] = read_tail(log, root=self.root / 'worker')
            except FileNotFoundError:
                state['log'] = ''
            state['log_note'] = 'live worker stdout; not independent final scoring evidence'
        return state

    async def poll(self):
        # Supervisor results survive controller/API interruptions. No job rerun.
        self.reconcile()
        for path in sorted((self.root / 'requests').glob('*.json')):
            identifier = path.stem
            if not IDENTIFIER.fullmatch(identifier) or (self.root / 'responses' / path.name).exists():
                continue
            try:
                _require(not path.is_symlink() and path.stat().st_size <= 4096, 'REQUEST_INVALID', '请求不是有界普通文件')
                request = _read_json(path)
                _require(request.get('request_id') == identifier, 'REQUEST_INVALID', '请求 ID 与文件不一致')
                result = await self.handle(request)
            except (FlowError, ValueError, OSError) as exc:
                result = {'status': 'failed', 'error': str(exc)}
            self._write_response(identifier, result)
