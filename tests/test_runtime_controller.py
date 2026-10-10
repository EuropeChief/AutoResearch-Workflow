import asyncio
import fcntl
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from autoresearch_flow.common import FlowError
from autoresearch_flow.runtime_controller import Controller
from autoresearch_flow.runtime_jobs import FileJobs
from autoresearch_flow.runtime_cli import dispatch
from test_independent_runtime import TrackPreparationTests


class ControllerTests(TrackPreparationTests, unittest.IsolatedAsyncioTestCase):
    def test_authorized_shared_gpu_acceptance_reaches_background_controller(self):
        import cli
        runtime = self.prepare('shared-acceptance', dict(self.config, purpose='acceptance'))
        args = cli._parser().parse_args(['runtime', 'run', '--runtime-dir', str(runtime.directory),
                                       '--confirm-cost', '--allow-busy-gpu'])
        with patch('autoresearch_flow.runtime_cli.subprocess.Popen') as launch:
            launch.return_value.pid = 1234
            result = dispatch(args)
        self.assertEqual(result['controller_pid'], 1234)
        self.assertIn('--allow-busy', launch.call_args.args[0])

    def test_shared_gpu_exception_cannot_start_formal_training(self):
        runtime = self.prepare('formal-shared')
        args = SimpleNamespace(runtime_action='run', runtime_dir=runtime.directory,
                               task_root=None, confirm_cost=True, allow_busy_gpu=True)
        with patch('autoresearch_flow.runtime_cli.subprocess.Popen') as launch:
            with self.assertRaisesRegex(FlowError, '仅.*验收'):
                dispatch(args)
        launch.assert_not_called()

    def test_acceptance_cannot_be_finalized_as_formal_even_with_long_timing(self):
        cfg = dict(self.config, purpose='acceptance')
        runtime = self.prepare('acceptance', cfg)
        path = runtime.directory / 'state.json'
        state = json.loads(path.read_text())
        state.update(thread_id='acceptance-thread', goal={'status': 'complete'})
        path.write_text(json.dumps(state))
        args = SimpleNamespace(runtime_action='finalize', runtime_dir=runtime.directory, task_root=None)
        with patch('autoresearch_flow.runtime_cli.activity_summary', return_value={'net_active_seconds': 40000, 'unresolved': []}):
            with self.assertRaisesRegex(FlowError, '不能作为正式轨迹'):
                dispatch(args)

    async def test_running_track_lock_prevents_preflight_or_second_controller(self):
        runtime=self.prepare()
        lock=(runtime.directory/'controller.lock').open('a')
        self.addCleanup(lock.close)
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with self.assertRaisesRegex(FlowError,'已有控制器'):
            await Controller(runtime).run(preflight_only=True)

    async def test_preflight_cannot_overwrite_existing_thread_auth(self):
        runtime=self.prepare()
        path=runtime.directory/'state.json'
        state=json.loads(path.read_text())
        state['thread_id']='original'
        path.write_text(json.dumps(state))
        auth=runtime.directory/'codex_home/auth.json'
        auth.write_text('synthetic-original-auth')
        with self.assertRaisesRegex(FlowError,'已有原会话'):
            await Controller(runtime).run(preflight_only=True)
        self.assertEqual(auth.read_text(),'synthetic-original-auth')

    def test_native_event_timestamps_and_proxy_disconnect_end_verified_model_activity(self):
        runtime=self.prepare()
        controller=Controller(runtime)
        controller.state['thread_id']='original'
        class Rpc:
            def drain_events(self):
                return [{'at':1000,'monotonic':0,'message':{'method':'turn/started',
                   'params':{'threadId':'original','turn':{'id':'turn'}}}},
                  {'at':1010,'monotonic':10,'message':{'method':'runtime/proxy_exit','params':{}}}]
        controller.rpc=Rpc()
        controller.events()
        self.assertEqual(controller.clock.summary(live=True)['net_active_seconds'],10)
        self.assertEqual(controller.state['status'],'observation_interrupted')
        rows=[json.loads(x) for x in controller.clock.path.read_text().splitlines()]
        starts=[r for r in rows if r['action']=='start']
        self.assertEqual(starts[0]['monotonic'],0)

    async def test_failed_and_unknown_job_end_verified_clock_not_cleanup_guess(self):
        for code in ['RUNNER_FAILED','JOB_SUPERVISOR_EXIT']:
            runtime=self.prepare(name='run-'+code)
            controller=Controller(runtime)
            async def runner(job,work):
                raise FlowError(code,'synthetic failure')
            controller.jobs=FileJobs(runtime.directory/'jobs',runtime.directory/'solution',runner)
            job='a'*32
            await controller.jobs.handle({'request_id':job,'operation':'submit'})
            await controller.job_events()
            await asyncio.gather(*controller.jobs.pending.values())
            await controller.job_events()
            self.assertNotIn('job:'+job,controller.clock.active)
            summary=controller.clock.summary(live=True)
            self.assertEqual(bool(summary['unresolved']),code=='JOB_SUPERVISOR_EXIT')
            before=summary['net_active_seconds']
            await asyncio.sleep(.01)
            self.assertEqual(controller.clock.summary(live=True)['net_active_seconds'],before)

    def test_timing_recomputes_exclusions_at_saved_observation_not_current_wallclock(self):
        runtime=self.prepare()
        ledger=runtime.directory/'logs/activity.jsonl'
        ledger.write_text(json.dumps({'action':'start','activity':'turn:one','segment':'a',
                                     'at':1010,'monotonic':10,'evidence':'native log'})+'\n')
        (runtime.directory/'logs/timing.json').write_text(json.dumps({
            'observed_clock':{'segment':'a','monotonic':20},'net_active_seconds':10}))
        exclusion=runtime.directory/'exclusion.json'
        exclusion.write_text(json.dumps({'start_at':1015,'stop_at':1017,'reason':'synthetic outage','evidence':'original:4'}))
        args=SimpleNamespace(runtime_action='exclude',runtime_dir=runtime.directory,task_root=None,file=exclusion)
        dispatch(args)
        args.runtime_action='timing'
        timing=dispatch(args)
        self.assertEqual(timing['net_active_seconds'],8)
        self.assertEqual(timing['excluded_seconds'],2)
