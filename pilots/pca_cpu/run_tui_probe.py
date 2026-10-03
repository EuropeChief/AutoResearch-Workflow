"""Opt-in bounded Seed CPU TUI probe; no default-mode switch or host changes."""
import argparse
import json
import os
from pathlib import Path
import pty
import select
import signal
import subprocess
import sys
import time
import tomllib
import uuid

FLOW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import _atomic_json, _read_json, _require, _sha256, _utc_now
from autoresearch_flow.harbor_runtime import compose_override, validate_launch
from autoresearch_flow.runtime import Runtime, public_evaluation
from autoresearch_flow.runtime_events import EventClock
from autoresearch_flow.runtime_tui import RolloutTail, TmuxTerminal, codex_command
from autoresearch_flow.trajectory import validate_round

PROMPT = '''这是 CPU 运行底座短联调，不是正式科研轨迹，不需等待十小时。
请只完成一轮：阅读 /workspace/instruction.md，使用 exec_command 单独原样执行 /workspace/evaluate
（不要与其他命令拼接，等它返回成功结果），
向 /expert_evidence/trajectory.jsonl 追加一条由你编写的八字段记录：
round（从1递增）、policy_name、method_summary（中文）、status、score（raw_metric.value）、
failure_reason、retained_best、time（YYYY-MM-DD HH:mm:ss）。成功 status=ok、failure_reason=null。
把当前候选备份为 /expert_evidence/best_method/，然后结束本次回答；收到继续指令后再做一轮。
只使用公开合法工具，不访问私有目录或凭据，不启动其他 Agent 或新会话。
'''
CONTINUE = '在当前原会话中继续上述短联调，再完成一轮相同范围的公开检查和真实记录，然后结束回答。'


def observer_cycle(terminal):
    """A real read-only PTY client attaches, draws, then detaches; server stays."""
    master, slave = pty.openpty()
    client = None
    try:
        client = subprocess.Popen(terminal.attach_command(), stdin=slave, stdout=slave, stderr=slave,
                                  env={**os.environ, 'TERM': 'xterm-256color'}, start_new_session=True)
        os.close(slave)
        slave = None
        ready, _, _ = select.select([master], [], [], 10)
        _require(ready and os.read(master, 65536), 'TUI_OBSERVER', '只读观察端未返回终端画面')
        os.write(master, b'\x02d')
        _require(client.wait(timeout=10) == 0 and terminal.status()['alive'],
                 'TUI_OBSERVER', '观察端脱离后终端未继续存活')
    finally:
        if client is not None and client.poll() is None:
            client.kill()
            client.wait(timeout=5)
        os.close(master)
        if slave is not None:
            os.close(slave)


def probe(runtime, directory, budget):
    _require(0 < budget <= 1200, 'LIVE_BUDGET', '本短测总预算不得超过 20 分钟')
    phase, track = 'preflight', 'seed'
    home = runtime.directory/track/phase/'codex_home'
    _require(not list((home/'sessions').rglob('*.jsonl')), 'PILOT_EXISTS', '短测须用新准备的合成目录，不覆盖旧会话')
    env, redact = runtime._auth(track, phase)
    env['TERM'] = 'xterm-256color'
    deadline = time.monotonic() + budget
    thread = None
    report = {'status': 'running', 'gpu_used': False, 'hidden_queries': 0,
              'formal_evidence': False, 'native_turns': 0, 'segments': [], 'public_results': [],
              'real_compaction_observed': False}
    _atomic_json(directory/'report.json', report)
    try:
        for index in range(2):
            tail = RolloutTail(home, runtime.config['codex_version'], thread)
            clock = EventClock(thread)
            name = 'ar-tui-probe-'+uuid.uuid4().hex[:12]
            prompt = PROMPT if index == 0 else CONTINUE
            command = runtime.backend.command(runtime, track, phase, name,
                                               codex_command(prompt, thread), use_auth=True, tty=True)
            started = time.time()
            segment = directory/f'segment-{index+1}'
            segment.mkdir()
            with TmuxTerminal() as terminal, (segment/'native.jsonl').open('x') as native, \
                    (segment/'events.jsonl').open('x') as events:
                try:
                    terminal.start(command, env)
                    _atomic_json(segment/'terminal.json', {'attach': terminal.attach_command()})
                    observer_done = continued = False
                    turn_results = []
                    while True:
                        _require(time.monotonic() < deadline, 'BUDGET_EXHAUSTED', '本次 CPU 短测总预算耗尽')
                        for observation in tail.poll():
                            received = time.time()
                            value = redact.value(observation['native'])
                            native.write(json.dumps(value, ensure_ascii=False)+'\n')
                            stamp = observation['native_at']
                            if value['type'] == 'session_meta':
                                stamp = max(started, stamp)  # Resume metadata is historical, not work.
                            else:
                                _require(started <= stamp <= received + 2, 'CLOCK_ORDER', '新增原生事件超出本分段时间范围')
                            for event in observation['events']:
                                safe = redact.value(event)
                                clock.event(safe, stamp)
                                events.write(json.dumps({'received_at': received, 'at': stamp,
                                                         'source': 'native_rollout', 'event': safe}, ensure_ascii=False)+'\n')
                                _require(safe['type'] != 'turn.failed', 'TUI_FAILED',
                                         '观察到原生错误；立即停止，不沿用失败回合的评测结果')
                                if safe.get('item', {}).get('type') == 'compaction':
                                    report['real_compaction_observed'] = True
                                if safe['type'] == 'item.completed':
                                    result = public_evaluation(safe['item'], ['/workspace/evaluate'])
                                    if result is not None:
                                        turn_results.append(result)
                                if safe['type'] == 'turn.completed':
                                    _require(turn_results, 'PILOT_EVIDENCE', '本回合未观察到成功的真实公开评测调用')
                                    report['public_results'].append(turn_results[-1])
                                    turn_results = []
                            native.flush()
                            events.flush()
                        _require(terminal.status()['alive'], 'TUI_EXITED', 'TUI 提前退出，不能判联调通过')
                        _require(tail.adapter.state != 'failed', 'TUI_FAILED', '原生记录报告外部异常，停止短测')
                        if tail.adapter.idle:
                            thread = tail.adapter.thread_id
                            if not observer_done:
                                observer_cycle(terminal)
                                observer_done = True
                            if index == 0 and not continued:
                                terminal.send(CONTINUE)
                                continued = True
                            elif clock.completed_turns >= (2 if index == 0 else 1):
                                # Deliberate external interruption at idle; original
                                # persisted session must resume on the next launch.
                                break
                        time.sleep(.2)
                finally:
                    try:
                        (segment/'screen.txt').write_text(redact.text(terminal.capture()) if terminal.started else '')
                    finally:
                        try:
                            runtime.backend.stop(name)
                        finally:
                            clock.stop(time.time())
                            _atomic_json(segment/'timing.json', clock.summary())
            report['native_turns'] += clock.completed_turns
            report['segments'].append({'thread_id': thread, 'observer_detached': observer_done,
                                       'turns': clock.completed_turns, 'observed_seconds': clock.summary()['observed_active_seconds']})
        trajectory = runtime.directory/track/phase/'output/trajectory.jsonl'
        records = [json.loads(line) for line in trajectory.read_text().splitlines()]
        _require(len(records) == report['native_turns'] == len(report['public_results']) == 3,
                 'PILOT_EVIDENCE', 'Agent 记录、原生回合和真实公开评测数量不一致')
        for number, record in enumerate(records, 1):
            validate_round(record, number)
            _require(record['status'] == 'ok' and record['score'] == report['public_results'][number-1]['raw_metric']['value'],
                     'PILOT_EVIDENCE', 'Agent 自写分数没有绑定该回合实际公开结果')
        report.update(status='tui_probe_passed', thread_id=thread, trajectory_sha256=_sha256(trajectory),
                      same_thread_resume=True, continued_without_observer=True,
                      limits=['未验证十小时运行；不是科研轨迹', '压缩只按实际是否发生记录，未发生不算覆盖'])
    except Exception as error:
        report.update(status='blocked', error=redact.text(str(error)))
        raise
    finally:
        report['evidence'] = [{'path': str(p.relative_to(directory)), 'sha256': _sha256(p)}
                              for p in sorted(directory.rglob('*')) if p.is_file() and p.name != 'report.json']
        _atomic_json(directory/'report.json', report)
    return report


def validate_scope(config, allow_security_exception):
    _require(all(gpu is None for gpu in config['resources']['gpus'].values()),
             'LIVE_SCOPE', '本次仍仅授权 CPU，不允许 GPU')
    _require(bool(config.get('docker_security')) == allow_security_exception,
             'LIVE_SCOPE', '安全例外必须显式启用并绑定 Runtime 已核验的本次授权/限定 seccomp')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-root', type=Path, required=True)
    parser.add_argument('--budget-seconds', type=int, default=1200)
    parser.add_argument('--allow-live', action='store_true', required=True)
    parser.add_argument('--allow-security-exception', action='store_true',
                        help='仅在已明确授权并冻结 docker_security 时使用')
    args = parser.parse_args()
    root = args.task_root.resolve()
    _require(root.is_relative_to(Path(__file__).resolve().parent/'runs'),
             'LIVE_SCOPE', '仅接受本 CPU pilot 的 runs 下合成目录，不运行真实题目')
    _require(0 < args.budget_seconds <= 1200, 'LIVE_BUDGET', '短测累计预算须为 1–1200 秒')
    runtime = Runtime(root)
    runtime._load()
    validate_scope(runtime.config, args.allow_security_exception)
    spec = runtime.config['harness']
    validate_launch(runtime)
    card = tomllib.loads((root/spec['task']/'task.toml').read_text())
    _require(card['environment'].get('gpus', 0) == 0 and
             card['verifier']['environment'].get('gpus', 0) == 0,
             'LIVE_SCOPE', 'Harbor 原始资源声明也必须为 CPU-only')
    runtime.check('seed')  # Host/image checks before reading any auth or calling model.
    run = root/'tui_probe'
    _require(not run.exists(), 'PILOT_EXISTS', '短测目录已存在；保留原记录，不静默重试重置预算')
    run.mkdir(mode=0o700)
    overlay = run/'agent-compose.json'
    _atomic_json(overlay, compose_override(runtime, 'seed', 'preflight'))
    job = {'job_name': 'tui', 'jobs_dir': str(run/'jobs'), 'n_attempts': 1,
           'tasks': [{'path': str(root/spec['task'])}],
           'agents': [{'import_path': 'pilots.pca_cpu.tui_probe_agent:TuiProbeAgent',
                       'override_timeout_sec': args.budget_seconds + 30,
                       'kwargs': {'task_root': str(root), 'track': 'seed', 'action': 'preflight',
                                  'budget': args.budget_seconds}}],
           'environment': {'type': 'docker', 'extra_docker_compose': [str(overlay)]},
           'verifier': {'disable': True}, 'n_concurrent_trials': 1, 'retry': {'max_retries': 0}}
    _atomic_json(run/'job.json', job)
    _atomic_json(run/'invocation.json', {'started_at': _utc_now(), 'budget_seconds': args.budget_seconds,
                 'runtime_manifest_sha256': _sha256(runtime.directory/'manifest.json'),
                 'source': [{'path': str(p.relative_to(FLOW)), 'sha256': _sha256(p)} for p in
                            [Path(__file__), Path(__file__).with_name('tui_probe_agent.py'),
                             *sorted((FLOW/'autoresearch_flow').glob('*.py'))]],
                 'scope': 'Seed CPU only; no GPU or Hidden scoring',
                 'security_exception': runtime.config.get('docker_security')})
    env = {**os.environ, 'PYTHONPATH': str(FLOW)}
    if spec.get('docker_config'):
        env['DOCKER_CONFIG'] = spec['docker_config']
    with (run/'console.log').open('x') as output:
        process = subprocess.Popen([spec['executable'], 'run', '-c', str(run/'job.json')], env=env,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            exit_code = process.wait(timeout=args.budget_seconds + 60)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=10)
            raise
    results = list((run/'jobs/tui').glob('*/result.json'))
    _require(exit_code == 0 and len(results) == 1 and not _read_json(results[0]).get('exception_info'),
             'PILOT_FAILED', f'Harbor 短测未通过；查看 {run}/console.log 和 trial 结果，不自动重跑')
    _require(_read_json(run/'evidence/report.json')['status'] == 'tui_probe_passed',
             'PILOT_FAILED', '缺少完整 TUI 短测证据')
    print(run/'evidence/report.json')


if __name__ == '__main__':
    main()
