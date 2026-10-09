import asyncio
import json
from pathlib import Path
import tempfile
import unittest

from autoresearch_flow.common import FlowError
from autoresearch_flow.runtime_jobs import FileJobs, freeze_candidate, public_result


class JobsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'solution'
        self.source.mkdir()
        (self.source / 'method.py').write_text('value=1')
        self.done = asyncio.Event()
        self.calls = 0
        async def runner(job, work):
            self.calls += 1
            (work / 'output/runner.log').write_text('epoch 1\n')
            await self.done.wait()
            return {'exit_code': 0, 'stdout': json.dumps({'status': 'succeeded', 'score': 0.5,
                'raw_metric': {'name': 'error', 'direction': 'minimize', 'value': 4.0}})}
        self.jobs = FileJobs(self.root / 'jobs', self.source, runner)

    async def test_long_job_disconnect_query_and_frozen_source(self):
        job = 'a' * 32
        running = await self.jobs.handle({'request_id': job, 'operation': 'submit'})
        await asyncio.sleep(0)
        self.assertEqual(running['status'], 'running')
        (self.source / 'method.py').write_text('value=2')
        self.assertEqual((self.jobs.root / 'worker' / job / 'solution/method.py').read_text(), 'value=1')
        same = await self.jobs.handle({'request_id': job, 'operation': 'submit'})
        self.assertEqual(same['candidate_sha256'], running['candidate_sha256'])
        log = await self.jobs.handle({'request_id': 'b'*32, 'operation': 'logs', 'job_id': job})
        self.assertIn('epoch 1', log['log'])
        self.done.set()
        await asyncio.gather(*self.jobs.pending.values())
        result = await self.jobs.handle({'request_id': 'c'*32, 'operation': 'result', 'job_id': job})
        self.assertEqual(result['score'], 0.5)
        self.assertEqual(result['candidate_sha256'], running['candidate_sha256'])
        self.assertEqual(self.calls, 1)

    async def test_unknown_command_resource_or_path_rejected(self):
        for key in ['command', 'source', 'gpu_ids']:
            with self.assertRaises(FlowError):
                await self.jobs.handle({'request_id': 'a'*32, 'operation': 'submit', key: '/tests'})
        with self.assertRaises(FlowError):
            await self.jobs.handle({'request_id': '../bad', 'operation': 'submit'})

    async def test_recovery_preserves_single_job_limit_and_merges_completion(self):
        old = 'a' * 32
        await self.jobs.handle({'request_id': old, 'operation': 'submit'})
        recovered = FileJobs(self.jobs.root, self.source, self.jobs.runner)
        with self.assertRaisesRegex(FlowError, '已有公开作业'):
            await recovered.handle({'request_id': 'b'*32, 'operation': 'submit'})
        self.assertEqual((await recovered.handle({'request_id': old, 'operation': 'submit'}))['status'], 'running')
        (self.jobs.root/'records'/(old+'.completion.json')).write_text(json.dumps({
            'status':'succeeded','finished_at':2,'finished_monotonic':2,'score':0.5}))
        # A direct submit, not only poll(), must reconcile durable completion.
        next_job=await recovered.handle({'request_id':'b'*32,'operation':'submit'})
        self.assertEqual(next_job['status'],'running')
        self.done.set()
        await asyncio.gather(*self.jobs.pending.values(),*recovered.pending.values())

    async def test_runner_exception_has_real_end_and_supervisor_loss_is_pending(self):
        async def failed(job,work):
            raise RuntimeError('synthetic runner exited')
        jobs=FileJobs(self.root/'failed',self.source,failed)
        job='a'*32
        await jobs.handle({'request_id':job,'operation':'submit'})
        await asyncio.gather(*jobs.pending.values())
        result=await jobs.handle({'request_id':'b'*32,'operation':'result','job_id':job})
        self.assertEqual(result['status'],'failed')
        self.assertGreaterEqual(result['finished_monotonic'],result['started_monotonic'])
        async def unknown(job,work):
            raise FlowError('JOB_SUPERVISOR_EXIT','synthetic observation lost')
        jobs=FileJobs(self.root/'unknown',self.source,unknown)
        await jobs.handle({'request_id':job,'operation':'submit'})
        await asyncio.gather(*jobs.pending.values())
        result=await jobs.handle({'request_id':'b'*32,'operation':'result','job_id':job})
        self.assertEqual(result['status'],'observation_pending')
        self.assertNotIn('score',result)
        self.assertIn('observation_ended_monotonic',result)
        with self.assertRaises(FlowError):
            await jobs.handle({'request_id':'c'*32,'operation':'submit'})
        (jobs.root/'records'/(job+'.completion.json')).write_text(json.dumps({
            'status':'failed','finished_at':result['observation_ended_at'],
            'finished_monotonic':result['observation_ended_monotonic']}))
        await jobs.poll()
        self.assertEqual((await jobs.handle({'request_id':'b'*32,'operation':'result','job_id':job}))['status'],'failed')

    async def test_malformed_operation_cannot_exit_coordinator(self):
        for number,operation in enumerate([[],{},None,1]):
            identifier=f'{number:032x}'
            path=self.jobs.root/'requests'/(identifier+'.json')
            path.write_text(json.dumps({'request_id':identifier,'operation':operation,'job_id':'a'*32}))
        await self.jobs.poll()
        for path in (self.jobs.root/'responses').glob('*.json'):
            self.assertEqual(json.loads(path.read_text())['status'],'failed')

    async def test_worker_log_symlink_never_reads_host_private_file(self):
        job='a'*32
        await self.jobs.handle({'request_id':job,'operation':'submit'})
        await asyncio.sleep(0)
        secret=self.root/'synthetic_private_marker'
        secret.write_text('DO_NOT_EXPOSE_SYNTHETIC')
        log=self.jobs.root/'worker'/job/'output/runner.log'
        log.unlink()
        log.symlink_to(secret)
        with self.assertRaises(OSError):
            await self.jobs.handle({'request_id':'b'*32,'operation':'logs','job_id':job})
        self.done.set()
        await asyncio.gather(*self.jobs.pending.values())

    async def test_failure_and_result_missing_metric_are_not_success(self):
        self.assertEqual(public_result('bad', 5)['exit_code'], 5)
        self.assertEqual(public_result('{"status":"succeeded","score":0.5}', 0)['status'], 'failed')
        self.assertEqual(public_result('{"status":"succeeded","score":NaN}', 0)['status'], 'failed')

    async def test_candidate_links_and_volume_rejected(self):
        (self.source / 'link').symlink_to('/etc/passwd')
        with self.assertRaises(FlowError):
            freeze_candidate(self.source, self.root / 'snapshot')
        self.assertFalse((self.root / 'snapshot').exists())
        (self.source / 'link').unlink()
        with self.assertRaises(FlowError):
            freeze_candidate(self.source, self.root / 'snapshot', limit=1)

    async def test_file_response_readonly_and_request_validation(self):
        path = self.jobs.root / 'requests' / ('a'*32 + '.json')
        path.write_text(json.dumps({'request_id': 'a'*32, 'operation': 'submit', 'source': '/tests'}))
        await self.jobs.poll()
        response = self.jobs.root / 'responses' / path.name
        self.assertEqual(json.loads(response.read_text())['status'], 'failed')
        self.assertEqual(response.stat().st_mode & 0o777, 0o444)
