"""Pinned Harbor launcher and streaming exec adapter; no mandatory Harbor import."""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tomllib
import uuid

from .core import FlowError, _atomic_json, _read_json, _require, _sha256
from .pca_contract import check_task, task_digest

SEGMENT_EXEC = '''import os, pathlib, sys
pidfile = pathlib.Path(sys.argv[1])
pidfile.parent.mkdir(exist_ok=True)
if os.getpgrp() != os.getpid():
    os.setsid()
pidfile.write_text(str(os.getpid()))
os.execvp(sys.argv[2], sys.argv[2:])
'''


def validate_harness(config, root):
    spec = config.get('harness')
    _require(isinstance(spec, dict) and set(spec) <= {'version', 'executable', 'task', 'docker_config'},
             'HARBOR_CONFIG', 'harness 只接受 version/executable/task/docker_config')
    _require(spec.get('version') == '0.23.0', 'HARBOR_VERSION', '当前有限适配只验证 Harbor 0.23.0')
    for name in ('executable', 'docker_config'):
        if name in spec:
            _require(isinstance(spec[name], str) and Path(spec[name]).is_absolute(),
                     'HARBOR_CONFIG', f'{name} 须指向本机明确绝对路径')
    _require('executable' in spec, 'HARBOR_CONFIG', '须指定 Harbor 可执行文件')
    task = spec.get('task')
    _require(isinstance(task, str) and task and not Path(task).is_absolute()
             and '..' not in Path(task).parts, 'HARBOR_CONFIG', 'task 须为题目根内相对路径')
    target = root / task
    _require(target.resolve().is_relative_to(root.resolve()), 'HARBOR_CONFIG', '任务路径越界')
    structural = check_task(target)
    card = tomllib.loads((target / 'task.toml').read_text())
    _require(card['environment'].get('docker_image') == config['image'],
             'HARBOR_IMAGE', 'Harbor Agent 与 runtime 必须绑定同一不可变镜像')
    memory = config['resources']['memory'].lower()
    memory_mb = int(memory[:-1]) * (1024 if memory[-1] == 'g' else 1)
    _require(card['environment'].get('cpus') == config['resources']['cpus']
             and card['environment'].get('memory_mb') == memory_mb,
             'HARBOR_RESOURCES', 'task.toml 是资源权威来源；runtime CPU/内存必须一致')
    return structural


def compose_override(runtime, track, phase):
    base = runtime.directory / track / phase
    mounts = [(p, '/workspace/' + p.name, True) for p in sorted((runtime.directory/'public').iterdir())]
    mounts += [(base/'solution', '/workspace/solution', False),
               (base/'output', '/expert_evidence', False),
               (base/'codex_home', '/codex', False),
               (runtime.directory/track/'config.toml', '/codex/config.toml', True)]
    main = {'user': f'{os.getuid()}:{os.getgid()}', 'read_only': True, 'init': True,
            'security_opt': ['no-new-privileges:true'], 'tmpfs': ['/tmp:rw,nosuid,size=1g'],
            'volumes': [{'type': 'bind', 'source': str(p.resolve()), 'target': dst, 'read_only': ro}
                        for p, dst, ro in mounts]}
    security = runtime.config.get('docker_security')
    if security:
        main['security_opt'] += ['apparmor='+security['apparmor'],
                                'seccomp='+str(runtime.directory/'security/seccomp.json')]
    gpu = runtime.config['resources']['gpus'][track]
    if gpu:
        main['deploy'] = {'resources': {'reservations': {'devices': [
            {'driver': 'nvidia', 'device_ids': gpu.split(','), 'capabilities': ['gpu']}]}}}
    return {'services': {'main': main}}


def final_snapshot(runtime, track):
    """Necessary final-candidate checks; expert review is still explicit."""
    state = runtime._state(track)
    segments = [s for s in state['segments'] if s['phase'] == 'formal']
    _require(state['active'] is None and runtime._seconds(state) >= runtime.minimum_seconds()
             and segments and segments[-1]['status'] == 'completed',
             'FINAL_NOT_READY', '须净有效时长达标且末段正常收尾；异常暂停不得评分')
    base = runtime.directory/track/'formal'
    best, candidate = base/'output/best_method', base/'solution'
    best_digest = task_digest(best)
    files = [p for p in best.rglob('*') if p.is_file()]
    _require(bool(files), 'FINAL_NOT_READY', '缺少最佳方法代码备份')
    for path in files:
        target = candidate/path.relative_to(best)
        _require(target.is_file() and not target.is_symlink() and _sha256(target) == _sha256(path),
                 'BEST_NOT_RESTORED', '最佳代码未恢复到候选提交面')
    from .trajectory import validate_round
    rows = (base/'output/trajectory.jsonl').read_text().splitlines()
    _require(bool(rows), 'FINAL_NOT_READY', '缺 Agent 自写轨迹')
    for number, row in enumerate(rows, 1):
        validate_round(json.loads(row), number)
    return {'candidate_sha256': task_digest(candidate), 'best_method_sha256': best_digest,
            'thread_id': state['thread_id'], 'trajectory_sha256': _sha256(base/'output/trajectory.jsonl')}


def validate_launch(runtime):
    """Recheck the prepared task and pinned Harness before any launch path."""
    spec = runtime.config['harness']
    current = validate_harness(runtime.config, runtime.root)
    manifest = _read_json(runtime.directory/'manifest.json')
    _require(current['task_sha256'] == manifest.get('harbor_task_sha256'),
             'HARBOR_TASK_DRIFT', '任务配置或双镜像源码改变，不能拼接旧轨迹')
    try:
        version = subprocess.check_output([spec['executable'], '--version'], text=True, timeout=30).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise FlowError('HOST_DEPENDENCY_UNAVAILABLE',
                        '无法调用 Harbor；请由用户核对 harness.executable 路径、执行权限及 --version 输出；流程不自动安装或改权限') from exc
    _require(version.split() and version.split()[-1] == spec['version'], 'HARBOR_VERSION', 'Harbor 实际版本与锁定版本不同')
    return current


def launch(runtime, track, action, budget, resume=False):
    """Host only. Private task context/metadata never goes into Agent mounts."""
    _require(track in ('codex', 'seed'), 'INVALID_TRACK', '仅接受 codex/seed')
    spec = runtime.config['harness']
    current = validate_launch(runtime)
    phase = 'preflight' if action == 'preflight' else 'formal'
    directory = runtime.directory/track/'harbor'
    directory.mkdir(exist_ok=True)
    with (directory/'launch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _require(False, 'ALREADY_RUNNING', '该轨迹已有 Harbor 作业')
        state = runtime._state(track)
        _require(state['active'] is None, 'UNCLOSED_SEGMENT', '先 recover 未收口分段')
        _require(not (directory/'final_attempt.json').exists(), 'FINAL_ALREADY_ATTEMPTED',
                 '最终评分已申请过；不能静默重评或继续使用已看过最终结果的轨迹')
        _require(action in ('preflight', 'finalize') or bool(state['thread_id']) == resume,
                 'RESUME_REQUIRED', '已有轨迹须显式 resume 原 thread')
        snapshot = final_snapshot(runtime, track) if action == 'finalize' else None
        run = directory/uuid.uuid4().hex
        run.mkdir()
        overlay = run/'agent-compose.json'
        _atomic_json(overlay, compose_override(runtime, track, phase))
        job = {'job_name': 'trial', 'jobs_dir': str(run/'jobs'), 'n_attempts': 1,
               'tasks': [{'path': str((runtime.root/spec['task']).resolve())}],
               'agents': [{'import_path': 'autoresearch_flow.harbor_agent:FlowCodexAgent',
                           'override_timeout_sec': budget+60,
                           'kwargs': {'task_root': str(runtime.root), 'track': track,
                                      'action': action, 'budget': budget, 'resume_original': resume}}],
               'environment': {'type': 'docker', 'extra_docker_compose': [str(overlay)]},
               'verifier': {'disable': action != 'finalize'},
               'n_concurrent_trials': 1, 'retry': {'max_retries': 0}}
        _atomic_json(run/'job.json', job)
        if snapshot:
            _atomic_json(directory/'final_attempt.json', {'run': str(run), **snapshot})
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        if spec.get('docker_config'):
            env['DOCKER_CONFIG'] = spec['docker_config']
        command = [spec['executable'], 'run', '-c', str(run/'job.json')]
        with (run/'console.log').open('x') as output:
            process = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                exit_code = process.wait(timeout=budget+360)
            except (KeyboardInterrupt, subprocess.TimeoutExpired):
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                exit_code = process.returncode
        results = list((run/'jobs/trial').glob('*/result.json'))
        trial = _read_json(results[0]) if len(results) == 1 else {}
        report = {'exit_code': exit_code, 'trial_result': str(results[0]) if len(results) == 1 else None,
                  'exception': (trial.get('exception_info') or {}).get('exception_type'),
                  'verifier_result': trial.get('verifier_result'), 'task_sha256': current['task_sha256']}
        _atomic_json(run/'launch_result.json', report)
        _require(len(results) == 1, 'HARBOR_FAILED', f'Harbor 未生成完整 trial，查看 {run}/console.log')
        outcome = runtime.status(track)
        outcome['harbor'] = {**report, 'run': str(run)}
        if action == 'preflight':
            ready = not report['exception'] and bool((runtime._state(track)['preflight'] or {}).get('ready', False))
            outcome['status'] = 'ready' if ready else 'blocked'
        elif action == 'finalize':
            rewards = (trial.get('verifier_result') or {}).get('rewards')
            passed = (exit_code == 0 and not report['exception']
                      and trial.get('verifier_environment_mode') == 'separate'
                      and isinstance(rewards, dict) and bool(rewards)
                      and all(type(v) in (int, float) and math.isfinite(v) for v in rewards.values()))
            outcome['status'] = 'final_scored' if passed else 'blocked'
        else:
            outcome['status'] = ('blocked' if report['exception'] or exit_code != 0 else
                                 'awaiting_finalization' if outcome['status'] == 'duration_reached'
                                 else outcome['status'])
        return outcome


class HarborExecBackend:
    """Stream Codex from a container already started/owned by Harbor."""
    def __init__(self, container):
        _require(bool(re.fullmatch('[0-9a-f]{64}', container)), 'HARBOR_CONTAINER', '须绑定真实容器 ID')
        self.container = container

    def command(self, runtime, track, phase, name, command, use_auth=False, tty=False):
        _require(os.getuid() != 0, 'NONROOT_REQUIRED', '专家宿主须为非 root 用户')
        args = ['docker', 'exec', '-i', '-u', f'{os.getuid()}:{os.getgid()}',
                '-w', '/workspace/solution', '-e', 'CODEX_HOME=/codex']
        if tty:
            args.insert(3, '-t')
        if use_auth and runtime.config['tracks'][track]['auth_ref']['kind'] == 'api_key_json':
            args += ['-e', 'AUTORESEARCH_MODEL_KEY']
        return args + [self.container, 'python3', '/workspace/_segment_exec.py',
                       '/codex/.supervisor/'+name, *command]

    def check(self, runtime, track):
        actual = subprocess.check_output(['docker', 'inspect', '--format', '{{.Image}}', self.container], text=True).strip()
        expected = subprocess.check_output(
            ['docker', 'image', 'inspect', '--format', '{{.Id}}', runtime.config['image']],
            text=True).strip()
        _require(actual == expected, 'HARBOR_IMAGE', '实际容器镜像漂移')
        result = subprocess.run(['docker', 'exec', self.container, 'codex', '--version'], capture_output=True, text=True)
        _require(result.returncode == 0 and runtime.config['codex_version'] in result.stdout,
                 'CODEX_VERSION', 'Codex 版本不匹配')
        return {'status': 'ok', 'image_id': actual}

    def boundary(self, runtime, track):
        from .runtime import DockerBackend
        return DockerBackend.boundary(self, runtime, track)

    def spawn(self, command, env):
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, start_new_session=True)

    def stop(self, name):
        _require(bool(re.fullmatch('[a-zA-Z0-9-]+', name)), 'INVALID_PROCESS', '无效监督进程标识')
        inspect = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', self.container], capture_output=True, text=True)
        if inspect.returncode == 0 and inspect.stdout.strip() == 'false':
            return
        if inspect.returncode != 0:
            _require('No such' in inspect.stderr or 'no such' in inspect.stderr, 'CLEANUP_UNCONFIRMED', '无法确认 Harbor 容器状态')
            return
        script = ("import os,pathlib,signal,sys,time; p=pathlib.Path(sys.argv[1]); "
                  "pid=int(p.read_text()) if p.exists() else None\n"
                  "def alive():\n"
                  " try: os.killpg(pid,0); return True\n"
                  " except ProcessLookupError: return False\n"
                  "if pid is not None:\n"
                  " try: os.killpg(pid,signal.SIGTERM)\n"
                  " except ProcessLookupError: pass\n"
                  " end=time.monotonic()+5\n"
                  " while alive() and time.monotonic()<end: time.sleep(.05)\n"
                  " if alive(): os.killpg(pid,signal.SIGKILL)\n"
                  " end=time.monotonic()+2\n"
                  " while alive() and time.monotonic()<end: time.sleep(.05)\n"
                  " if alive(): raise RuntimeError('process group still alive')\n"
                  " p.unlink(missing_ok=True)\n")
        result = subprocess.run(['docker','exec','-u',f'{os.getuid()}:{os.getgid()}',self.container,
                                 'python3','-c',script,'/codex/.supervisor/'+name], capture_output=True, text=True, timeout=15)
        _require(result.returncode == 0, 'CLEANUP_UNCONFIRMED', 'Codex 分段清理失败')
