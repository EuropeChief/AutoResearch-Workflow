"""No-model CPU test of native readonly TUI attach/detach and frozen Codex bundle."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

FLOW=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(FLOW))
from autoresearch_flow.common import _atomic_json
from autoresearch_flow.track_runtime import TrackRuntime
from autoresearch_flow.runtime_container import NativeContainer
from autoresearch_flow.runtime_rpc import CodexRpc


async def run(args):
    began=time.monotonic()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    (out/'starter').mkdir()
    (out/'starter/method.py').write_text('VALUE=1')
    (out/'prompt.md').write_text('无模型 CPU 界面预检。')
    config={'schema_version':3,'track':'seed','image':args.image,'codex_version':'0.160.0',
      'model_profile':str(args.profile.resolve()),'codex_vendor':str(args.codex_vendor.resolve()),
      'candidate':str(out/'starter'),'prompt':str(out/'prompt.md'),'purpose':'preflight',
      'public_files':[], 'evaluation':{'mode':'direct','command':['/bin/true']},
      'resources':{'cpus':1,'memory':'2g','gpu_ids':[]},
      'security':{'mode':'codex_nested','authorization':args.authorization}}
    runtime=TrackRuntime.prepare(config,out/'runtime',base_dir=out)
    container=NativeContainer(runtime)
    rpc=None
    name='ar-ui-' + runtime.status()['instance_id'][:20]
    tmux=['tmux','-L',name]
    report={'status':'failed','model_calls':0,'gpu_calls':0,'training_runs':0}
    try:
        await container.start()
        secrets=container.credential_material()  # Authentication only; no turn/Goal is started.
        await container.preflight()
        await container.backend()
        rpc=CodexRpc(container.proxy_command(),env=os.environ.copy(),log_path=runtime.directory/'logs/rpc.jsonl',secrets=secrets)
        rpc.initialize()
        thread=rpc.request('thread/start',{'model':config.get('model','doubao-seed-2.1-turbo'),
           'cwd':'/workspace/solution','approvalPolicy':'never','ephemeral':False})['thread']['id']
        # Never goal/set or turn/start: there is no generation or autonomous Goal.
        state=json.loads((runtime.directory/'state.json').read_text())
        state['thread_id']=thread
        _atomic_json(runtime.directory/'state.json',state)
        subprocess.run([*tmux,'new-session','-d','-s',name],check=True)
        subprocess.run([*tmux,'set-window-option','-t',name,'remain-on-exit','on'],check=True)
        subprocess.run([*tmux,'respawn-pane','-k','-t',name,shlex.join(container.tui_command(thread))],check=True)
        await asyncio.sleep(2)
        pane=subprocess.run([*tmux,'capture-pane','-p','-t',name],capture_output=True,text=True,check=True).stdout
        (out/'native-screen.txt').write_text(pane)
        assert 'Codex' in pane or 'doubao-seed' in pane,pane
        # A genuine tty client is attached readonly, then only that client is detached.
        import pty
        master,slave=pty.openpty()
        proc=subprocess.Popen([*tmux,'attach-session','-r','-t',name],stdin=slave,stdout=slave,stderr=slave,
                              env={**os.environ,'TERM':'xterm-256color'},start_new_session=True)
        os.close(slave)
        await asyncio.sleep(0.5)
        clients=subprocess.run([*tmux,'list-clients','-t',name,'-F','#{client_readonly}'],
                               capture_output=True,text=True,check=True).stdout
        assert clients.strip()=='1',clients  # Works with tmux 3.0 and later.
        subprocess.run([*tmux,'detach-client','-s',name],check=True)
        proc.wait(timeout=5)
        os.close(master)
        result=rpc.request('thread/goal/get',{'threadId':thread})
        assert result['goal'] is None
        report.update(status='passed',thread_id=thread,readonly_client=True,
          backend_alive_after_detach=True,code_bundle_frozen=(runtime.directory/'codex_runtime/bin/codex').is_file())
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        subprocess.run([*tmux,'kill-session','-t',name],capture_output=True)
        if rpc:
            rpc.close()
        await container.stop()
        report['elapsed_seconds']=time.monotonic()-began
        _atomic_json(out/'report.json',report)
        print(json.dumps({'status':report['status'],'elapsed_seconds':report['elapsed_seconds'],
            'report':str(out/'report.json')}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['output','profile','codex-vendor']:
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--authorization',required=True)
    args=parser.parse_args()
    asyncio.run(run(args))


if __name__=='__main__':
    main()
