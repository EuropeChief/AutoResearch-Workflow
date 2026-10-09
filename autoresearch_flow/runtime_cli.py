"""Direct one-track commands, dispatched before importing legacy state tools."""
from pathlib import Path
import asyncio
import json
import os
import subprocess
import shlex
import shutil
import sys
import time
import uuid

from .common import FlowError, _atomic_json, _read_json, _require
from .track_runtime import TrackRuntime
from .runtime_clock import activity_summary
from .runtime_files import read_tail


def independent(args):
    return args.command == 'runtime' and bool(getattr(args, 'runtime_dir', None)
                                               or getattr(args, 'config', None)
                                               or getattr(args, 'output_dir', None))


def dispatch(args):
    if args.runtime_action == 'prepare':
        _require(args.config is not None and args.output_dir is not None,
                 'RUNTIME_INPUT', '独立 prepare 须指定 --config 和 --output-dir')
        _require(args.task_root is None and args.file is None, 'RUNTIME_INPUT', '不能混用新接口与旧任务状态接口')
        runtime = TrackRuntime.prepare(_read_json(args.config), args.output_dir, base_dir=args.config.resolve().parent)
        return runtime.status()
    _require(args.runtime_dir is not None and args.task_root is None,
             'RUNTIME_INPUT', '独立运行动作须使用 --runtime-dir，不混入 task-root')
    runtime = TrackRuntime(args.runtime_dir)
    _require(not getattr(args, 'budget_seconds', None) and not getattr(args,'track',None),
             'RUNTIME_INPUT','新本轨运行没有整轨墙钟/外部轨迹选择')
    if args.runtime_action == 'status':
        return runtime.status()
    if args.runtime_action == 'check':
        return runtime.status()
    if args.runtime_action == 'preflight':
        _require(args.allow_live,'LIVE_PERMISSION','实际容器预检须明确 --allow-live')
        from .runtime_controller import Controller
        asyncio.run(Controller(runtime).run(preflight_only=True,allow_busy=args.allow_busy_gpu))
        return _read_json(runtime.directory / 'preflight.json')
    if args.runtime_action in {'run','recover'}:
        _require(args.confirm_cost,'MODEL_PERMISSION','首次真实模型调用须明确 --confirm-cost')
        _, state, _ = runtime._load()
        recovering=args.runtime_action=='recover'
        _require(bool(state['thread_id']) if recovering else state['thread_id'] is None,
                 'THREAD_EXISTS','首次 run 不允许已有会话；recover 必须有原 threadId')
        root = runtime.directory / 'implementation'
        with (runtime.directory / 'logs/controller.log').open('a') as stream:
            proc = subprocess.Popen([sys.executable,'-m','autoresearch_flow.runtime_controller',
                '--runtime-dir',str(runtime.directory)]+(['--recover'] if recovering else []), cwd=root,
                env={**os.environ,'PYTHONPATH':str(root)},stdin=subprocess.DEVNULL,stdout=stream,stderr=stream,start_new_session=True)
        return {'status':'starting','controller_pid':proc.pid,'runtime_dir':str(runtime.directory),
                'next_action':'runtime status，然后 attach 原生可视化界面；关闭观察端不停止本轨'}
    if args.runtime_action in {'pause','resume','stop'}:
        if args.runtime_action == 'resume':
            _require(args.confirm_cost,'MODEL_PERMISSION','原会话续跑可能调用模型，须 --confirm-cost')
        identifier = uuid.uuid4().hex
        control = runtime.directory / 'control'
        _require((control/'requests').is_dir(),'CONTROLLER_NOT_READY','本轨控制器尚未就绪；不猜测状态或新建会话')
        action = 'shutdown' if args.runtime_action == 'stop' else args.runtime_action
        value = {'action':action}
        if action == 'resume' and getattr(args,'prompt',None):
            value['prompt'] = args.prompt
        _atomic_json(control/'requests'/(identifier+'.json'),value)
        response = control/'responses'/(identifier+'.json')
        deadline = time.monotonic()+40
        while not response.exists():
            if time.monotonic() >= deadline:
                return {'status':'pending','request_id':identifier,'note':'控制请求待核；不会杀会话或健康训练'}
            time.sleep(0.1)
        return _read_json(response)
    if args.runtime_action == 'attach':
        _, state, _ = runtime._load()
        info = _read_json(runtime.directory/'container.json')
        _require(state['thread_id'],'THREAD_MISSING','尚未取得实际原 threadId')
        command = ['docker','exec','-it','-u',f'{info["uid"]}:{os.getgid()}','-e','CODEX_HOME=/codex',
            info['container_id'],info['codex'],'--remote','unix:///codex/control.sock','resume',state['thread_id'],'--no-alt-screen']
        _require(sys.stdin.isatty() and sys.stdout.isatty(),'TUI_REQUIRED','attach 须在 tmux/交互终端运行；后台状态和日志另有只读入口')
        _require(shutil.which('tmux'),'TUI_REQUIRED','原生只读观察使用已有 tmux；不自动安装宿主工具')
        name='ar-ui-' + runtime.status()['instance_id'][:20]
        tmux=['tmux','-L',name]  # Independent server inherits this host user's current groups.
        existing=subprocess.run([*tmux,'has-session','-t',name],capture_output=True)
        if existing.returncode:
            subprocess.run([*tmux,'new-session','-d','-s',name,shlex.join(command)],check=True)
        # Readonly tmux observer cannot inject prompts or Ctrl-C into the model.
        code = subprocess.call([*tmux,'attach-session','-r','-t',name])
        return {'status':'observer_closed','exit_code':code,'note':'只退出可视化客户端，不终止后端/Goal/作业'}
    if args.runtime_action == 'timing':
        path = runtime.directory / 'logs/timing.json'
        if not path.exists():
            return {'status':'not_started','net_active_seconds':0}
        progress=_read_json(path)
        ledger=runtime.directory/'logs/activity.jsonl'
        rows=[json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
        # Recompute exclusions without inventing time since the last saved observation.
        progress.update(activity_summary(rows,now=progress.get('observed_clock')))
        return progress
    if args.runtime_action == 'exclude':
        _require(args.file,'TIMING_INPUT','扣时须提供 --file 原件引用')
        value=_read_json(args.file)
        _require(set(value)=={'start_at','stop_at','reason','evidence'},'TIMING_INPUT','扣时须含时间、原因、原件依据')
        from .runtime_clock import ActivityClock
        clock=ActivityClock(runtime.directory/'logs/activity.jsonl','expert-adjustment')
        clock.record('exclude',**value)
        return {'status':'recorded','note':'原始日志不改写；下次 timing/finalize 重算'}
    if args.runtime_action == 'finalize':
        config,state,_=runtime._load()
        path=runtime.directory/'logs/activity.jsonl'
        rows=[json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        timing=activity_summary(rows)
        _require(config.get('purpose','formal')=='formal','PREFLIGHT_NOT_FORMAL','合成预检不能作为正式轨迹证据')
        _require(state.get('goal',{}).get('status')=='complete','GOAL_NOT_COMPLETE','由 Agent 自主完成原 Goal 后再收口')
        _require(timing['net_active_seconds']>=config['duration']['minimum_seconds'] and not timing['unresolved'],
                 'TIMING_NOT_READY','净时长不足或还有待核区间，不能称为正式完成')
        return {'status':'content_review_required','thread_id':state['thread_id'],'timing':timing,
                'note':'只核本轨时间/Goal，不执行 Hidden；轨迹内容、候选与原生 Trial 由后续材料/Harbor 接口审查'}
    if args.runtime_action in {'logs','jobs'}:
        job = getattr(args,'job_id',None)
        if job:
            from .runtime_jobs import IDENTIFIER
            _require(IDENTIFIER.fullmatch(job),'JOB_INVALID','作业 ID 无效')
            if args.runtime_action == 'jobs':
                return _read_json(runtime.directory / 'jobs/records' / (job+'.json'))
            path = runtime.directory / 'jobs/worker' / job / 'output/runner.log'
        else:
            if args.runtime_action == 'jobs':
                return {'jobs':[_read_json(p) for p in sorted((runtime.directory/'jobs/records').glob('*.json'))
                                if not p.name.endswith('.completion.json')]}
            path = runtime.directory/'logs/rpc.jsonl'
        try:
            tail=read_tail(path,root=runtime.directory)
        except FileNotFoundError:
            tail=''
        return {'path':str(path),'tail':tail}
    _require(False, 'RUNTIME_ACTION_NOT_READY', '该独立运行动作尚未实现；不能静默调用旧底座')
