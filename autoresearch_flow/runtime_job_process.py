"""One durable expert-side public job; survives model/controller interruption."""
import argparse
import asyncio
import fcntl
from pathlib import Path
import time

from .common import _atomic_json, _read_json, _require
from .runtime_container import NativeContainer
from .runtime_jobs import IDENTIFIER, public_result
from .track_runtime import TrackRuntime


async def run(runtime, job):
    records = runtime.directory / 'jobs/records'
    record = records / (job + '.completion.json')
    _require(not record.exists(), 'JOB_EXISTS', '不重复执行已完成作业')
    work = runtime.directory / 'jobs/worker' / job
    original = _read_json(records / (job + '.json'))
    container = NativeContainer(runtime)
    try:
        await container.adopt()
        outcome = await container.run_job(job, work)
        result = public_result(outcome['stdout'],outcome['exit_code'])
        (records / (job + '.stdout.log')).write_text(outcome['stdout'])
        (records / (job + '.stderr.log')).write_text(outcome['stderr'])
    except Exception as exc:
        # A lost Docker/exec connection doesn't prove the worker exited.
        result = {'status':'observation_pending','error':type(exc).__name__ + ': ' + str(exc)}
    times = ({'observation_ended_at':time.time(),'observation_ended_monotonic':time.monotonic()}
             if result['status']=='observation_pending'
             else {'finished_at':time.time(),'finished_monotonic':time.monotonic()})
    result.update(started_at=original['started_at'],started_monotonic=original['started_monotonic'],
                  candidate_sha256=original['candidate_sha256'], **times)
    _atomic_json(record,result)
    # Never stop the shared track environment on one job's completion/failure.


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir',type=Path,required=True)
    parser.add_argument('--job-id',required=True)
    args=parser.parse_args()
    _require(IDENTIFIER.fullmatch(args.job_id),'JOB_INVALID','作业 ID 无效')
    runtime=TrackRuntime(args.runtime_dir)
    lock=(runtime.directory/'jobs/records'/(args.job_id+'.lock')).open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    asyncio.run(run(runtime,args.job_id))


if __name__=='__main__':
    main()
