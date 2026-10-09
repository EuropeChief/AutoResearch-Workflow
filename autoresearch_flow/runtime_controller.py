"""Per-track native Goal observer and optional fixed-entry coordinator.

No global task state, idle watchdog, wall-clock kill, automatic new Goal, or
other-track link. The TUI is an observer/client of the same native backend.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import subprocess
import time
import uuid

from .common import FlowError, _atomic_json, _read_json, _require
from .runtime_clock import ActivityClock
from .runtime_container import NativeContainer
from .runtime_jobs import FileJobs, IDENTIFIER
from .runtime_rpc import CodexRpc, GoalSession
from .track_runtime import TrackRuntime


def goal_objective(config):
    if config.get('purpose') == 'preflight':
        return '完成本轨 prompt 中有界合成预检；不训练，不用于正式轨迹时长证明。'
    seconds = config['duration']['minimum_seconds']
    return (f'独立合法完成本轨优化探索，净有效迭代至少 {seconds} 秒；只用公开合法入口，'
            '自行维护轨迹 JSON 和 best_method。不得因未提升而提前退出；真实满足时长、产物和合法性后自主收口。')


class Controller:
    def __init__(self, runtime):
        self.runtime, self.directory = runtime, runtime.directory
        self.config, self.state, self.snapshot = runtime._load()
        self.state['controller_pid'] = os.getpid()
        self.state['segment'] = uuid.uuid4().hex
        self.state['controller_started_at'] = time.time()
        self.clock = ActivityClock(self.directory / 'logs/activity.jsonl', self.state['segment'])
        self.container, self.rpc, self.session, self.jobs = None, None, None, None
        self.exit_requested = False
        self.job_activity = set()
        self.completed_jobs = set()
        self.unresolved_jobs = set()
        self.last_goal_check = 0
        self.stale_rpc = False

    def save(self):
        self.state['updated_at'] = time.time()
        _atomic_json(self.directory / 'state.json', self.state)
        progress = self.clock.summary(live=True)
        progress.update(minimum_seconds=self.config['duration']['minimum_seconds'],
                        formal=self.config.get('purpose','formal') == 'formal')
        _atomic_json(self.directory / 'logs/timing.json', progress)
        if (self.directory / 'jobs/responses').exists():
            path = self.directory / 'jobs/responses/progress.json'
            _atomic_json(path, {'status':self.state['status'], 'timing':progress})
            path.chmod(0o444)

    def connect(self):
        if self.rpc:
            self.rpc.close()
        self.rpc = CodexRpc(self.container.proxy_command(), env=os.environ.copy(),
                            log_path=self.directory / 'logs/rpc.jsonl', secrets=self.secrets)
        self.rpc.initialize()
        self.session = GoalSession(self.rpc, model=self.config['model']['model'], thread_id=self.state['thread_id'])
        self.stale_rpc = False

    def events(self):
        for record in self.rpc.drain_events():
            message = record['message']
            method, params = message.get('method'), message.get('params', {})
            if params.get('threadId') not in (None, self.state['thread_id']):
                continue
            evidence = 'logs/rpc.jsonl@' + str(record['at'])
            stamp = {'at':record['at'],'monotonic':record.get('monotonic',time.monotonic())}
            if method == 'turn/started':
                turn = params.get('turn',{}).get('id')
                if turn:
                    self.clock.record('start', activity='turn:' + turn, evidence=evidence, **stamp)
                    self.state['active_turn'] = turn
            elif method == 'turn/completed':
                turn = params.get('turn',{}).get('id')
                if turn:
                    self.clock.record('end', activity='turn:' + turn, evidence=evidence, **stamp)
                self.state['active_turn'] = None
            elif method in {'thread/goal/updated','thread/goal/changed'}:
                if params.get('goal'):
                    self.goal(params['goal'], evidence)
            elif method == 'error':
                error = params.get('error',{})
                self.clock.record('fact', evidence=evidence, detail=error,
                                  note='原生错误原件；是否为阻塞区间须结合实际恢复，不按静默强停')
                self.close_model_activity(evidence, **stamp)
            elif method and method.startswith('item/') and self.state.get('active_turn'):
                # Actual new native output/tool activity, not a timer or Goal poll.
                self.clock.record('start',activity='turn:' + self.state['active_turn'], evidence=evidence, **stamp)
            elif method == 'runtime/proxy_exit':
                self.stale_rpc = True
                self.state['status'] = 'observation_interrupted'
                self.clock.record('fact', evidence=evidence, detail=params)
                self.close_model_activity(evidence, **stamp)
                # A dead observer cannot prove backend stopped; no cancellation.

    def close_model_activity(self, evidence, **stamp):
        for activity in list(self.clock.active):
            if activity.startswith('turn:'):
                self.clock.record('end',activity=activity,evidence=evidence,**stamp)

    def goal(self, value, evidence):
        _require(value['threadId'] == self.state['thread_id'] and value['objective'] == self.state['objective'],
                 'GOAL_MISMATCH','本轨原 Goal 改变；不静默创建新目标')
        self.state['goal'] = value
        self.state['status'] = value['status']
        self.state.pop('error',None)
        if value['status'] != 'active':
            for activity in list(self.clock.active):
                if activity.startswith('turn:'):
                    self.clock.record('end', activity=activity, evidence=evidence)
        if value['status'] == 'complete':
            self.state['artifact_check'] = self.artifacts()

    def artifacts(self):
        # Model-owned trajectory is never synthesized from raw logs.
        output = self.directory / 'output'
        trajectory = [p.name for p in output.glob('*.json') if p.name.startswith('trajectory')]
        best = output / 'best_method'
        timing = self.clock.summary(live=True)
        return {'trajectory_json_present':bool(trajectory), 'best_method_present':best.exists(),
                'minimum_time_reached':timing['net_active_seconds'] >= self.config['duration']['minimum_seconds'],
                'unresolved_timing':timing['unresolved'],
                'note':'presence/progress only, not final trajectory schema review or QA'}

    async def job_events(self):
        if not self.jobs:
            return
        await self.jobs.poll()
        records = [_read_json(p) for p in (self.directory/'jobs/records').glob('*.json')
                   if not p.name.endswith('.completion.json')]
        active = {r['job_id'] for r in records if r['status']=='running'}
        by_id={r['job_id']:r for r in records}
        for job in active - self.job_activity:
            record=by_id[job]
            self.clock.record('start',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                              at=record['started_at'],monotonic=record['started_monotonic'])
        for job in self.job_activity - active:
            record=by_id[job]
            if 'finished_monotonic' in record:
                self.clock.record('end',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                                  at=record['finished_at'],monotonic=record['finished_monotonic'])
                self.completed_jobs.add(job)
            elif 'observation_ended_monotonic' in record:
                self.clock.record('end',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                                  at=record['observation_ended_at'],monotonic=record['observation_ended_monotonic'],
                                  verified_terminal=False)
                self.clock.record('fact',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                                  unresolved_job=True,note='worker 终态未知；不续计、不重复提交、不猜结果')
                self.unresolved_jobs.add(job)
        # Completed durable jobs may have finished while this observer was absent.
        for record in records:
            job=record['job_id']
            if record['status']!='running' and job not in self.completed_jobs and 'finished_monotonic' in record:
                self.clock.record('start',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                                  at=record['started_at'],monotonic=record['started_monotonic'])
                self.clock.record('end',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                                  at=record['finished_at'],monotonic=record['finished_monotonic'])
                self.completed_jobs.add(job)
            elif record['status']=='observation_pending' and job not in self.unresolved_jobs:
                # Recovery may first encounter an already-lost observer.
                self.clock.record('fact',activity='job:'+job,evidence='jobs/records/'+job+'.json',
                                  unresolved_job=True,note='待核作业保留资源占用边界；未证尾部不计时')
                self.unresolved_jobs.add(job)
        self.job_activity = active

    async def durable_job(self,job,work):
        root=self.directory/'implementation'
        with (self.directory/'logs'/('job-'+job+'.supervisor.log')).open('a') as log:
            proc=subprocess.Popen([sys.executable,'-m','autoresearch_flow.runtime_job_process',
                '--runtime-dir',str(self.directory),'--job-id',job],cwd=root,
                env={**os.environ,'PYTHONPATH':str(root)},stdin=subprocess.DEVNULL,
                stdout=log,stderr=log,start_new_session=True)
        completion=self.directory/'jobs/records'/(job+'.completion.json')
        while not completion.exists():
            if proc.poll() is not None:
                raise FlowError('JOB_SUPERVISOR_EXIT','公开监督进程退出，查本轨 supervisor log；不猜测训练结果')
            await asyncio.sleep(0.25)
        final=_read_json(completion)
        _require(final.get('status')!='observation_pending','JOB_SUPERVISOR_EXIT',
                 '公开作业的执行连接失去观测，worker 终态待核；不能重跑或猜测分数')
        stdout=self.directory/'jobs/records'/(job+'.stdout.log')
        stderr=self.directory/'jobs/records'/(job+'.stderr.log')
        return {'exit_code':final.get('exit_code',1),'stdout':stdout.read_text() if stdout.exists() else '',
                'stderr':stderr.read_text() if stderr.exists() else final.get('error',''),
                'finished_at':final['finished_at'],'finished_monotonic':final['finished_monotonic']}

    async def controls(self):
        for path in sorted((self.directory / 'control/requests').glob('*.json')):
            if (self.directory / 'control/responses' / path.name).exists():
                continue
            try:
                request = _read_json(path)
                action = request['action']
                _require(set(request) <= {'action','prompt'}, 'CONTROL_DENIED','控制输入不接受其他参数')
                if action == 'pause':
                    value = self.session.pause()
                    turn = self.state.get('active_turn')
                    if turn:
                        self.rpc.request('turn/interrupt', {'threadId':self.state['thread_id'],'turnId':turn})
                    self.goal(value, 'explicit user pause:' + path.name)
                elif action == 'resume':
                    if self.stale_rpc:
                        self.connect()
                    value = self.session.resume(self.state['objective'], request.get('prompt') or
                        '继续原 Goal 和原会话；先检查已有公开作业状态/结果，不重复提交。净有效时长以公开 progress.json 为据。')
                    self.goal(value,'same thread/Goal resume:' + path.name)
                elif action == 'shutdown':
                    healthy = self.jobs.busy() if self.jobs else []
                    _require(not healthy,'HEALTHY_JOBS_ACTIVE','先等本轨健康作业完成，不能自动杀训练')
                    if self.state.get('goal',{}).get('status') == 'active':
                        self.goal(self.session.pause(),'explicit scoped shutdown')
                    self.exit_requested = True
                else:
                    raise FlowError('CONTROL_DENIED','只接受原 Goal 暂停/恢复或本轨空闲收口')
                response = {'status':'applied','action':action,'thread_id':self.state['thread_id'],'goal':self.state['goal']}
            except Exception as exc:
                response = {'status':'failed','error':type(exc).__name__ + ': ' + str(exc)}
            _atomic_json(self.directory / 'control/responses' / path.name,response)

    async def run(self, *, preflight_only=False, allow_busy=False, recover=False):
        lock = (self.directory / 'controller.lock').open('a')
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as exc:
            lock.close()
            raise FlowError('CONTROLLER_RUNNING','本轨已有控制器；不重开或用预检干扰') from exc
        self.lock = lock
        # Reload under this track's lock; preflight can never overwrite an old account/thread.
        latest = _read_json(self.directory / 'state.json')
        if (preflight_only or not recover) and latest.get('thread_id'):
            lock.close()
            raise FlowError('THREAD_EXISTS','已有原会话不能再 run/preflight；使用原实例恢复')
        self.container = NativeContainer(self.runtime, allow_busy=allow_busy)
        self.secrets = []
        try:
            self.state['status'] = 'starting'
            self.save()
            if recover:
                await self.container.adopt()
            else:
                await self.container.start()
            if recover:
                value=_read_json(self.directory/'codex_home/auth.json')
                self.secrets=[x for x in value.values() if isinstance(x,str)]
                self.secrets += [x for x in value.get('tokens',{}).values() if isinstance(x,str)]
            elif not preflight_only:
                self.secrets = self.container.credential_material()
            else:
                path = self.directory / 'codex_home/auth.json'
                path.write_text('{"synthetic_auth_marker":true}')
                path.chmod(0o600)
            if not recover:
                await self.container.preflight()
            if preflight_only:
                self.state['status'] = 'preflight_passed'
                return
            if not recover or not await self.container.backend_alive():
                await self.container.backend()
                self.clock.record('fact',evidence='actual native backend start/restart',
                                  note='原 Codex home 与 thread/Goal 不重建；不杀其他进程')
            self.connect()
            if recover:
                value = self.session.attach(self.state['objective'])
            else:
                _require(self.state['thread_id'] is None,'THREAD_EXISTS','已有会话不能启动新线程；使用原会话恢复')
                self.state['objective'] = goal_objective(self.config)
                value = self.session.start(self.state['objective'],(self.directory / 'prompt.md').read_text())
            self.state['thread_id'] = self.session.thread_id
            self.goal(value, 'initial native Goal')
            self.jobs = FileJobs(self.directory / 'jobs', self.directory / 'solution', self.durable_job,
                max_candidate_bytes=self.config['evaluation'].get('max_candidate_bytes',64*1024*1024)) \
                if self.config['evaluation'].get('mode','direct') == 'worker' else None
            for name in ['requests','responses']:
                (self.directory / 'control' / name).mkdir(parents=True, exist_ok=True)
            while not self.exit_requested:
                await self.job_events()
                await self.controls()
                self.events()
                if not self.stale_rpc and time.monotonic() - self.last_goal_check > 5:
                    try:
                        self.goal(self.session.get(),'native thread/goal/get')
                    except FlowError as exc:
                        self.stale_rpc = True
                        self.state['status'] = 'observation_interrupted'
                        self.clock.record('fact',evidence='native Goal query',error=str(exc))
                        self.close_model_activity('native observation interrupted')
                    self.last_goal_check = time.monotonic()
                self.save()
                await asyncio.sleep(0.25)
        except BaseException as exc:
            if self.session and self.session.thread_id:
                self.state['thread_id'] = self.session.thread_id
            self.state['status'] = 'interrupted'
            self.state['error'] = type(exc).__name__ + ': ' + str(exc)
            self.clock.record('fact',evidence='controller lifecycle', error=self.state['error'])
            self.close_model_activity('actual observer exit; gap not guessed')
            raise
        finally:
            if self.rpc:
                self.rpc.close()
            # Only an explicit graceful shutdown or preflight closes this environment.
            # An exception must not cancel still-healthy model/training work.
            if self.exit_requested or preflight_only or self.state['thread_id'] is None:
                self.clock.close('actual controller scoped cleanup')
                await self.container.stop()
            try:
                self.save()
            finally:
                lock.close()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--preflight-only',action='store_true')
    parser.add_argument('--allow-busy',action='store_true')
    parser.add_argument('--recover',action='store_true')
    args = parser.parse_args(argv)
    runtime = TrackRuntime(args.runtime_dir)
    asyncio.run(Controller(runtime).run(preflight_only=args.preflight_only,allow_busy=args.allow_busy,recover=args.recover))


if __name__ == '__main__':
    main()
