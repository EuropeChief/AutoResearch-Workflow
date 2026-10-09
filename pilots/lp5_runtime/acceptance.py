"""Bounded LP-5 integration; preserves actual originals, not a formal trajectory."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import time

FLOW=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(FLOW))
from autoresearch_flow.common import _atomic_json, _read_json
from autoresearch_flow.track_runtime import TrackRuntime
from autoresearch_flow.runtime_container import NativeContainer
from autoresearch_flow.runtime_jobs import FileJobs
from autoresearch_flow.runtime_clock import ActivityClock


async def run(args):
    start=time.monotonic()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    starter=out/'starter'
    starter.mkdir()
    (starter/'method.py').write_text('VALUE=1\n')
    (out/'prompt.md').write_text('仅合成预检，不训练。使用公开入口提交并查询。')
    config={'schema_version':3,'track':'seed','image':args.image,'codex_version':'0.160.0',
      'model_profile':str(args.profile.resolve()),'codex_vendor':str(args.codex_vendor.resolve()),
      'candidate':str(starter),'prompt':str(out/'prompt.md'),'purpose':'preflight',
      'public_files':[{'source':str(Path(__file__).with_name('runner.py')),'destination':'public_eval/runner.py'}],
      'evaluation':{'mode':'worker','command':['python','/workspace/public_eval/runner.py','--candidate','{candidate}',
         '--output','{output}']+(['--gpu'] if args.gpu_id else []),'timeout_seconds':30},
      'resources':{'cpus':1,'memory':'2g','gpu_ids':[args.gpu_id] if args.gpu_id else []},
      'security':{'mode':'codex_nested','authorization':args.authorization}}
    if args.security_mode=='default':
        config['security']={'mode':'default'}
    # Fixed absolute interpreter in this existing PyTorch image.
    config['evaluation']['command'][0]='/opt/conda/bin/python'
    runtime=TrackRuntime.prepare(config,out/'runtime',base_dir=out)
    container=NativeContainer(runtime,allow_busy=args.allow_busy)
    report={'status':'failed','model_calls':0,'training_runs':0,'gpu_ids':config['resources']['gpu_ids'],'calls':[]}
    try:
        await container.start()
        auth=runtime.directory/'codex_home/auth.json'
        auth.write_text('{"synthetic_auth_marker":true}')
        auth.chmod(0o600)
        report['sandbox']=await container.preflight()
        jobs=FileJobs(runtime.directory/'jobs',runtime.directory/'solution',container.run_job)
        import shlex
        async def client(operation,job=None,expected_exit=0):
            command=shlex.join([container.codex,'sandbox','-C','/workspace/solution','-P','autoresearch','--',
                'python','/workspace/evaluate.py',operation]+(['--job-id',job] if job else []))
            task=asyncio.create_task(container.exec_agent(command,timeout=35))
            while not task.done():
                await jobs.poll()
                await asyncio.sleep(0.05)
            value=await task
            report['calls'].append({'operation':operation,'exit_code':value.return_code,
                'stdout':value.stdout,'stderr':value.stderr})
            assert value.return_code==expected_exit,(value.stdout,value.stderr)
            return json.loads(value.stdout.splitlines()[-1])
        launched=await client('submit')
        job=launched['job_id']
        assert launched['status']=='running'
        current=await client('status',job)
        live=await client('logs',job)
        if jobs.pending:
            await asyncio.gather(*jobs.pending.values())
        result=await client('result',job)
        assert result['status']=='succeeded' and result['exit_code']==0
        assert result['raw_metric']['value']==(32768.0 if args.gpu_id else 1.0)
        report['candidate_sha256']=result['candidate_sha256']
        report['result']=result
        assert (runtime.directory/'jobs/worker'/job/'output/artifact.json').is_file()
        report['artifact_written']=True
        if args.boundary_checks:
            # Actual worker permission checks use only synthetic local markers.
            method=runtime.directory/'solution/method.py'
            method.write_text("from pathlib import Path\n"
                "for name,path,read in [('auth','/codex/auth.json',True),('client','/workspace/evaluate.py',False),"
                "('snapshot',__file__,False),('response','/run/autoresearch/responses/.probe',False)]:\n"
                " try:\n  p=Path(path)\n  p.read_text() if read else p.write_text('probe')\n"
                " except OSError: print('BOUNDARY_DENIED:'+name,flush=True)\n"
                " else: raise RuntimeError('boundary unexpectedly writable/readable:'+name)\nVALUE=2\n")
            second=await client('submit')
            if jobs.pending:
                await asyncio.gather(*jobs.pending.values())
            final=await client('result',second['job_id'])
            assert final['raw_metric']['value']==(131072.0 if args.gpu_id else 4.0)
            live=await client('logs',second['job_id'])
            assert all('BOUNDARY_DENIED:'+name in live['log'] for name in ['auth','client','snapshot','response'])
            report['worker_boundaries_verified']=True
            report['second_result']=final
            method.write_text("raise RuntimeError('synthetic expected public failure')\n")
            failed=await client('submit')
            if jobs.pending:
                await asyncio.gather(*jobs.pending.values())
            result=await client('result',failed['job_id'],expected_exit=1)
            assert result['status']=='failed' and result['exit_code']!=0 and 'score' not in result
            report['actual_failure_result']=result
            # Inject a forbidden command into the real untrusted request channel.
            forbidden='f'*32
            path=runtime.directory/'jobs/requests'/(forbidden+'.json')
            path.write_text(json.dumps({'request_id':forbidden,'operation':'submit','command':'/tests'}))
            await jobs.poll()
            response=_read_json(runtime.directory/'jobs/responses'/(forbidden+'.json'))
            assert response['status']=='failed'
            report['forbidden_request_rejected']=True
        report['status']='passed'
    except BaseException as exc:
        report['error']=str(exc)
        raise
    finally:
        await container.stop()
        report['elapsed_seconds']=time.monotonic()-start
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
    parser.add_argument('--gpu-id')
    parser.add_argument('--allow-busy',action='store_true')
    parser.add_argument('--boundary-checks',action='store_true')
    parser.add_argument('--security-mode',choices=['default','codex_nested'],default='codex_nested')
    args=parser.parse_args()
    asyncio.run(run(args))


if __name__=='__main__':
    main()
