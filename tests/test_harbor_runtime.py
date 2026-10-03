"""Offline adapter contracts. No Docker, credentials, or model calls."""
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import test_w3_contract as w3
from autoresearch_flow.core import FlowError
from autoresearch_flow.harbor_runtime import HarborExecBackend, compose_override, final_snapshot, launch, validate_harness


class HarborRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fx = w3.RuntimeTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.runtime = self.fx.runtime
        self.task = self.fx.root/'harbor_task'
        files = {'instruction.md': 'public task', 'environment/Dockerfile': 'FROM scratch',
                 'environment/starter/method.py': '# starter', 'tests/Dockerfile': 'FROM scratch',
                 'tests/test.sh': '# synthetic', 'task.toml':
                 'artifacts=["/workspace/solution"]\n[environment]\ncpus=1\nmemory_mb=1024\n'
                 'docker_image="sha256:'+'a'*64+'"\n[agent]\n[verifier]\nenvironment_mode="separate"\n[verifier.environment]\n'}
        for name, value in files.items():
            path = self.task/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        self.fx.config['harness'] = {'version': '0.23.0', 'executable': '/synthetic/harbor', 'task': 'harbor_task'}
        self.fx.prepare()

    def test_resource_and_image_mismatch_rejected(self):
        validate_harness(self.fx.config, self.fx.root)
        self.fx.config['resources']['memory'] = '2g'
        with self.assertRaises(FlowError) as error:
            validate_harness(self.fx.config, self.fx.root)
        self.assertEqual(error.exception.code, 'HARBOR_RESOURCES')

    def test_overlay_contains_no_private_task_or_host_socket(self):
        override = compose_override(self.runtime, 'seed', 'formal')
        targets = [v['target'] for v in override['services']['main']['volumes']]
        self.assertNotIn('/tests', targets)
        self.assertNotIn('/var/run/docker.sock', targets)
        self.assertNotIn('/workspace', targets)
        self.assertIn('/workspace/solution', targets)
        self.assertTrue(override['services']['main']['init'])

    def final_fixture(self):
        state = self.runtime._state('seed')
        state['thread_id'] = 'synthetic-thread'
        state['segments'] = [{'phase': 'formal', 'status': 'completed', 'logs': [],
                              'intervals': [], 'unverified_seconds': 0}]
        self.runtime._save('seed', state)
        base = self.runtime.directory/'seed/formal/output'
        (base/'best_method').mkdir()
        (base/'best_method/method.py').write_text('# starter')
        row = {'round': 1, 'policy_name': 'synthetic', 'method_summary': '合成测试',
               'status': 'ok', 'score': 0, 'failure_reason': None,
               'retained_best': True, 'time': '2026-09-30 12:00:00'}
        (base/'trajectory.jsonl').write_text(json.dumps(row)+'\n')
        return state

    def test_duration_alone_does_not_allow_finalization(self):
        state = self.final_fixture()
        with patch.object(self.runtime, '_seconds', return_value=36000):
            self.assertIn('candidate_sha256', final_snapshot(self.runtime, 'seed'))
            state['segments'][-1]['status'] = 'budget_exhausted'
            self.runtime._save('seed', state)
            with self.assertRaises(FlowError):
                final_snapshot(self.runtime, 'seed')

    def test_best_candidate_must_be_restored(self):
        self.final_fixture()
        (self.runtime.directory/'seed/formal/solution/method.py').write_text('# different')
        with patch.object(self.runtime, '_seconds', return_value=36000), self.assertRaises(FlowError) as error:
            final_snapshot(self.runtime, 'seed')
        self.assertEqual(error.exception.code, 'BEST_NOT_RESTORED')

    def test_run_disables_verifier_and_repeated_final_is_blocked(self):
        jobs = []
        class Process:
            def __init__(self, command, **kwargs):
                job = json.loads(Path(command[-1]).read_text())
                jobs.append(job)
                result = Path(job['jobs_dir'])/'trial/synthetic/result.json'
                result.parent.mkdir(parents=True)
                result.write_text('{"exception_info":null}')
            def wait(self, **kwargs): return 0
        with patch('subprocess.check_output', return_value='harbor 0.23.0'), patch('subprocess.Popen', Process):
            launch(self.runtime, 'seed', 'run', 10)
            self.assertTrue(jobs[0]['verifier']['disable'])
            marker = self.runtime.directory/'seed/harbor/final_attempt.json'
            marker.write_text('{}')
            with self.assertRaises(FlowError) as error:
                launch(self.runtime, 'seed', 'run', 10)
            self.assertEqual(error.exception.code, 'FINAL_ALREADY_ATTEMPTED')

    def test_final_scoring_rejects_errors_missing_or_nonfinite_rewards(self):
        self.final_fixture()
        cases = [
            ({'exception_info': {'exception_type': 'VerifierError'}}, 'blocked'),
            ({'verifier_environment_mode': 'separate', 'verifier_result': {'rewards': {'reward': float('nan')}}}, 'blocked'),
            ({'verifier_environment_mode': 'separate', 'verifier_result': {'rewards': {}}}, 'blocked'),
            ({'verifier_environment_mode': 'shared', 'verifier_result': {'rewards': {'reward': 1}}}, 'blocked'),
            ({'verifier_environment_mode': 'separate', 'verifier_result': {'rewards': {'reward': 1}}}, 'final_scored'),
        ]
        for trial, expected in cases:
            class Process:
                def __init__(self, command, **kwargs):
                    job = json.loads(Path(command[-1]).read_text())
                    assert job['verifier']['disable'] is False
                    result = Path(job['jobs_dir'])/'trial/synthetic/result.json'
                    result.parent.mkdir(parents=True)
                    result.write_text(json.dumps(trial))
                def wait(self, **kwargs): return 0
            with self.subTest(expected=expected, trial=trial), patch.object(self.runtime, '_seconds', return_value=36000), \
                 patch('subprocess.check_output', return_value='harbor 0.23.0'), patch('subprocess.Popen', Process):
                self.assertEqual(launch(self.runtime, 'seed', 'finalize', 10)['status'], expected)
                with self.assertRaises(FlowError) as error:
                    launch(self.runtime, 'seed', 'finalize', 10)
                self.assertEqual(error.exception.code, 'FINAL_ALREADY_ATTEMPTED')
            # Reset only this synthetic unit-test fixture, never a real query ledger.
            (self.runtime.directory/'seed/harbor/final_attempt.json').unlink()

    def test_image_digest_resolves_to_image_id(self):
        backend = HarborExecBackend('a'*64)
        self.runtime.config['image'] = 'example/image@sha256:'+'b'*64
        with patch('subprocess.check_output', side_effect=['sha256:'+'c'*64, 'sha256:'+'c'*64]), \
             patch('subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='codex '+self.runtime.config['codex_version'])):
            self.assertEqual(backend.check(self.runtime, 'seed')['status'], 'ok')

    def test_cleanup_escalates_and_keeps_marker_if_still_alive(self):
        backend = HarborExecBackend('a'*64)
        scripts = []
        def run(command, **kwargs):
            if command[1] == 'inspect':
                return SimpleNamespace(returncode=0, stdout='true', stderr='')
            scripts.append(command[command.index('-c')+1])
            return SimpleNamespace(returncode=1, stdout='', stderr='process group still alive')
        with patch('subprocess.run', side_effect=run), self.assertRaises(FlowError) as error:
            backend.stop('ar-synthetic')
        self.assertEqual(error.exception.code, 'CLEANUP_UNCONFIRMED')
        script = scripts[0]
        self.assertLess(script.index('signal.SIGTERM'), script.index('signal.SIGKILL'))
        self.assertLess(script.index("raise RuntimeError('process group still alive')"), script.index('p.unlink'))


if __name__ == '__main__':
    unittest.main()
