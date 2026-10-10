"""Authorized Seed CPU start/pause/same-Goal-resume acceptance, at most 8 min.

Production controllers have no track wall-clock cap. This cap is only the
explicitly bounded synthetic test harness; no GPT, GPU or training.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

FLOW=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(FLOW))
from autoresearch_flow.common import _atomic_json, _read_json
from autoresearch_flow.common import FlowError
from autoresearch_flow.track_runtime import TrackRuntime
from autoresearch_flow.runtime_controller import Controller


async def run(args):
    begin=time.monotonic()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    starter=out/'starter'
    starter.mkdir()
    (starter/'method.py').write_text('VALUE=1\n')
    prompt=('这是有界 CPU 合成预检，不训练、不调用 GPU、不接触私有目录。公开文件在 /workspace，候选在 /workspace/solution，产物在 /expert_evidence。'
      '现在只做第一段：用 python /workspace/evaluate.py submit 启动一次公开作业，立刻把含 job_id 的返回对象写 /expert_evidence/first_started.json。再用 status/logs/result 查询直到完成，'
      '保留真实 raw_metric 与 score 到 /expert_evidence/first_done.json。用实际结果自行写一轮八字段 trajectory.jsonl'
      '（round,policy_name,method_summary,status,score,failure_reason,retained_best,time；score 是 raw_metric.value；中文摘要）。'
      '完成 first_done 后暂时等候后续提示，不能把原 Goal 标为 complete：原 Goal 还需第二段恢复检查。不要重复提交，不做多余操作。')
    (out/'prompt.md').write_text(prompt)
    config={'schema_version':3,'track':'seed','image':args.image,'codex_version':'0.160.0',
      'model_profile':str(args.profile.resolve()),'codex_vendor':str(args.codex_vendor.resolve()),
      'candidate':str(starter),'prompt':str(out/'prompt.md'),'purpose':'preflight',
      'public_files':[{'source':str(Path(__file__).with_name('runner.py')),'destination':'public_eval/runner.py'}],
      'evaluation':{'mode':'worker','command':['/opt/conda/bin/python','/workspace/public_eval/runner.py',
         '--candidate','{candidate}','--output','{output}','--delay','30'],'timeout_seconds':50},
      'resources':{'cpus':1,'memory':'2g','gpu_ids':[]},
      'security':{'mode':'codex_nested','authorization':args.authorization}}
    runtime=TrackRuntime.prepare(config,out/'runtime',base_dir=out)
    controller=Controller(runtime)
    task=asyncio.create_task(controller.run())
    report={'status':'failed','model':'doubao-seed-2.1-turbo','gpu_calls':0,'training_runs':0}

    async def until(predicate,timeout=180):
        deadline=min(begin+480,time.monotonic()+timeout)
        while not predicate():
            if task.done():
                await task
                raise RuntimeError('controller exited before acceptance finished')
            if time.monotonic()>deadline:
                raise TimeoutError('bounded CPU acceptance deadline; not a production watchdog')
            await asyncio.sleep(0.2)

    def finished_file(name):
        try:
            return _read_json(runtime.directory/'output'/name).get('status')=='succeeded'
        except (FlowError,OSError):
            return False  # Agent may be in the middle of writing its own JSON.

    async def control(action,prompt=None):
        identifier=uuid.uuid4().hex
        request={'action':action}
        if prompt:
            request['prompt']=prompt
        _atomic_json(runtime.directory/'control/requests'/(identifier+'.json'),request)
        path=runtime.directory/'control/responses'/(identifier+'.json')
        await until(path.exists,45)
        value=_read_json(path)
        assert value['status']=='applied',value
        return value

    try:
        await until(lambda:(runtime.directory/'output/first_started.json').is_file())
        await until(lambda:(runtime.directory/'control/requests').exists())
        first=runtime.status()
        report['initial_thread_id']=first['thread_id']
        report['initial_goal']=first['goal']
        assert first['goal']['status']=='active'
        paused=await control('pause')
        report['paused_goal']=paused['goal']
        assert paused['goal']['status']=='paused'
        job=_read_json(runtime.directory/'output/first_started.json')['job_id']
        report['paused_job_id']=job
        report['job_state_at_pause']=_read_json(runtime.directory/'jobs/records'/(job+'.json'))['status']
        # Real observer/control process loss: do not stop backend or the durable job.
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        controller=Controller(runtime)
        task=asyncio.create_task(controller.run(recover=True))
        await until(lambda:runtime.status()['status']=='paused',30)
        report['controller_recovered_original_thread']=runtime.status()['thread_id']==first['thread_id']
        await until(lambda:_read_json(runtime.directory/'jobs/records'/(job+'.json'))['status']!='running',60)
        report['job_result_while_paused']=_read_json(runtime.directory/'jobs/records'/(job+'.json'))
        assert report['job_result_while_paused']['status']=='succeeded'
        # Observation client opening/closing must not change original paused Goal.
        from autoresearch_flow.runtime_rpc import CodexRpc
        observer=CodexRpc(controller.container.proxy_command(),env=os.environ.copy(),
           log_path=runtime.directory/'logs/observer-rpc.jsonl',secrets=controller.secrets)
        observer.initialize()
        observed=observer.request('thread/goal/get',{'threadId':first['thread_id']})['goal']
        observer.close()
        report['observer_closed_goal']=observed
        assert observed['status']=='paused'
        resumed=await control('resume',
            '继续原 Goal 和原会话的第二段合成验收。先检查第一段已有作业，不能重复跑原作业。'
            '确认 first_done.json 后，将候选 VALUE 改为2，合法提交一次新公开作业并查结果；'
            '将完整真实结果写 second_done.json，追加第二轮中文八字段轨迹，并复制完整候选到 /expert_evidence/best_method。'
            '完成后可以自主将原 Goal 标为 complete，说明真实结果。仅此 CPU 合成步骤，不训练、不用 GPU。')
        assert resumed['thread_id']==first['thread_id']
        assert resumed['goal']['objective']==first['goal']['objective']
        assert resumed['goal']['status']=='active'
        report['resumed_goal']=resumed['goal']
        await until(lambda:finished_file('second_done.json'))
        await until(lambda:(runtime.directory/'output/best_method/method.py').is_file(),30)
        await until(lambda:not controller.jobs.pending,30)
        report['first_result']=_read_json(runtime.directory/'output/first_done.json') if (runtime.directory/'output/first_done.json').exists() else report['job_result_while_paused']
        report['second_result']=_read_json(runtime.directory/'output/second_done.json')
        records=[_read_json(p) for p in (runtime.directory/'jobs/records').glob('*.json')
                 if not p.name.endswith('.completion.json')]
        assert sorted(r['raw_metric']['value'] for r in records if r['status']=='succeeded')==[1.0,4.0]
        report['original_thread_preserved']=runtime.status()['thread_id']==first['thread_id']
        report['timing']=controller.clock.summary(live=True)
        report['status']='passed'
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        if controller.session:
            try:
                value=controller.session.get()
                if value and value['status']=='active':
                    controller.session.pause()
            except Exception:
                pass
        if controller.jobs and controller.jobs.pending:
            await asyncio.gather(*controller.jobs.pending.values())
        controller.exit_requested=True
        try:
            await asyncio.wait_for(task,timeout=20)
        except Exception:
            if controller.container:
                await controller.container.stop()
        report['elapsed_seconds']=time.monotonic()-begin
        _atomic_json(out/'report.json',report)
        print(json.dumps({'status':report['status'],'elapsed_seconds':report['elapsed_seconds'],
           'report':str(out/'report.json')}),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--image',required=True)
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--codex-vendor',type=Path,required=True)
    parser.add_argument('--authorization',required=True)
    args=parser.parse_args()
    asyncio.run(run(args))


if __name__=='__main__':
    main()
