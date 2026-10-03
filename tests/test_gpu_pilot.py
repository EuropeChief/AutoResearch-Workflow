"""GPU pilot preparation contracts. No CUDA, Docker or model invocation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

FLOW = Path(__file__).resolve().parents[1]


class GpuPilotTests(unittest.TestCase):
    def test_adapter_accepts_observed_pytorch_uuid_without_nvidia_prefix(self):
        from pilots.gpu_queue.cuda_adapter import evaluate
        observed = 'e5719698-edfe-bbe4-ff2c-686aff90c7df'
        assigned = 'GPU-' + observed
        request = {'assigned_devices': [assigned], 'run': {'seed': 1}}

        class IdentityVerified(Exception):
            pass

        def before_workload(seed):
            raise IdentityVerified()

        for actual in (observed, assigned):
            cuda = SimpleNamespace(is_available=lambda: True, device_count=lambda: 1,
                                   get_device_properties=lambda index: SimpleNamespace(uuid=actual))
            fake = SimpleNamespace(cuda=cuda, manual_seed=before_workload)
            with self.subTest(actual=actual), patch.dict(os.environ, CUDA_VISIBLE_DEVICES=assigned), \
                 patch.dict(sys.modules, torch=fake):
                with self.assertRaises(IdentityVerified):
                    evaluate(request)

    def test_adapter_rejects_mismatched_or_extra_devices_before_workload(self):
        from pilots.gpu_queue.cuda_adapter import evaluate
        authorized = 'GPU-e5719698-edfe-bbe4-ff2c-686aff90c7df'
        other = '54fe0ffa-b4d2-d149-633e-e37e6e8e96c4'
        request = {'assigned_devices': [authorized]}
        for visible, count, actual, message in [
            ('GPU-other', 1, authorized, 'queue-assigned'),
            (authorized, 2, authorized, 'more than one'),
            (authorized, 1, other, 'differs from queue assignment'),
            (authorized, 1, 'GPU-other', 'valid GPU UUID'),
        ]:
            cuda = SimpleNamespace(is_available=lambda: True, device_count=lambda: count,
                                   get_device_properties=lambda index: SimpleNamespace(uuid=actual))
            # No real torch import or CUDA initialization is allowed in this test.
            with self.subTest(message=message), patch.dict(os.environ, CUDA_VISIBLE_DEVICES=visible), \
                 patch.dict(sys.modules, torch=SimpleNamespace(cuda=cuda)):
                with self.assertRaisesRegex((ValueError, RuntimeError), message):
                    evaluate(request)

    def test_prepare_is_offline_bounded_and_does_not_overwrite(self):
        from pilots.gpu_queue import probe
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            approval = base/'approval.md'
            approval.write_text('Synthetic test only: devices 4/6, no actual GPU permission.\n')
            with patch.object(probe, 'RUNS', base/'runs'):
                root = probe.prepare('fixture', ['4', '6'], Path(sys.executable), approval)
                data = json.loads((root/'probe.json').read_text())
                self.assertEqual(data['scope'], 'synthetic_gpu_queue_probe')
                self.assertEqual((root/'approval.md').read_bytes(), approval.read_bytes())
                self.assertFalse((root/'result.json').exists())
                self.assertFalse((root/'serial').exists())
                plans = [json.loads((root/x['path']).read_text()) for x in data['plans']]
                self.assertEqual([p['resources']['max_parallel'] for p in plans], [1, 2])
                self.assertEqual([p['timeout_seconds'] for p in plans], [30, 30])
                self.assertEqual([p['seeds'] for p in plans], [[1, 2, 3], [1, 2, 3]])
                before = (root/'probe.json').read_bytes()
                with self.assertRaises(FileExistsError):
                    probe.prepare('fixture', ['4', '6'], Path(sys.executable), approval)
                self.assertEqual((root/'probe.json').read_bytes(), before)

    def test_invalid_authorization_or_scope_cannot_create_a_pilot(self):
        from pilots.gpu_queue import probe
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            approval = base/'approval.md'
            approval.write_text(' ')
            with patch.object(probe, 'RUNS', base/'runs'):
                with self.assertRaises(ValueError):
                    probe.prepare('fixture', ['4'], Path(sys.executable), approval)
                approval.write_text('Synthetic only')
                for ids in ([], ['4', '4'], ['4', '6', '7'], ['all']):
                    with self.subTest(ids=ids), self.assertRaises(ValueError):
                        probe.prepare('fixture', ids, Path(sys.executable), approval)
                with self.assertRaises(ValueError):
                    probe.prepare('../outside', ['4'], Path(sys.executable), approval)
                self.assertFalse((base/'runs').exists())

    def test_run_requires_opt_in_before_any_device_query(self):
        result = subprocess.run([sys.executable, str(FLOW/'pilots/gpu_queue/probe.py'),
                                 'run', 'missing-fixture'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--allow-gpu', result.stderr)

    def test_summary_accepts_real_queue_receipts_from_cpu_processes(self):
        from pilots.gpu_queue import probe
        from autoresearch_flow.experiment_runner import ExperimentRunner
        adapter = '''import json, sys, time
from pathlib import Path
r = json.loads(Path(sys.argv[1]).read_text())
time.sleep(0.1)
run = r['run']
result = {k: run[k] for k in ('seed', 'role', 'method_sha256', 'seed_plan_sha256', 'protocol_sha256')}
result.update(status='succeeded', raw_metric=float(run['seed']), quality_passed=True,
              fixed=r['protocol']['fixed'], actual_budget={'matmuls': 1}, devices=r['assigned_devices'])
Path('adapter-result.json').write_text(json.dumps(result))
Path('cuda-result.json').write_text(json.dumps({'fixture_only': 'CPU simulation, NOT CUDA evidence',
    'cuda_available': True, 'matmul_finite': True, 'matmul_correct': True, 'visible_devices': r['assigned_devices']}))
'''
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            approval = base/'approval.md'
            approval.write_text('Synthetic fixture only, no GPU authorized.')
            with patch.object(probe, 'RUNS', base/'runs'):
                root = probe.prepare('cpu-contract', ['4', '6'], Path(sys.executable), approval)
            cpu = root/'cpu_simulation.py'
            cpu.write_text(adapter)
            devices = [{'id': i, 'uuid': f'GPU-test-{base.name}-{i}', 'name': 'synthetic',
                        'driver': 'synthetic', 'busy': False} for i in ('4', '6')]
            outputs = []
            for phase in ('serial', 'parallel'):
                plan = json.loads((root/(phase+'-plan.json')).read_text())
                plan['adapter_files'] = [probe.ref(root, cpu)]
                plan['command'][1] = '{adapter_root}/cpu_simulation.py'
                outputs.append(ExperimentRunner(root, device_probe=lambda: devices).execute(plan))
            self.assertEqual(set(outputs[0]['run_directories']), {'1', '2', '3'})
            result = probe.summarize(root, ['4', '6'], outputs)
            self.assertEqual(result['status'], 'passed')
            self.assertEqual(result['aggregate']['mean'], 2.0)
            self.assertEqual({x['run_id'] for x in result['runs']},
                             {f'{phase}-{seed}' for phase in ('serial', 'parallel') for seed in (1, 2, 3)})

    def test_execution_binds_outputs_and_rejects_overlap_or_drift(self):
        from pilots.gpu_queue import probe
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            approval = base/'approval.md'
            approval.write_text('Synthetic approval fixture, not permission to use hardware.')
            with patch.object(probe, 'RUNS', base/'runs'):
                root = probe.prepare('execution', ['4', '6'], Path(sys.executable), approval)
                calls = []

                class SyntheticQueue:
                    """Simulated external queue receipts; does not stand in for live acceptance."""
                    def __init__(self, task):
                        self.task = task

                    def execute(self, plan):
                        name = plan['id']
                        calls.append(name)
                        paths = {}
                        for index, seed in enumerate(plan['seeds']):
                            run_id = f'{name}-{seed}'
                            out = root/name/run_id
                            out.mkdir(parents=True, exist_ok=True)
                            paths[str(seed)] = out.relative_to(root).as_posix()
                            (out/'request.json').write_text(json.dumps({'run': {'run_id': run_id, 'seed': seed}}))
                            device = '4' if name == 'serial' or index != 1 else '6'
                            second = index*2 if name == 'serial' else (index//2)*2 + 10
                            execution = {'exit_code': 0, 'devices': ['GPU-'+device],
                                         'device_inventory': [{'id': device, 'uuid': 'GPU-'+device}],
                                         'started_at': f'2026-10-04T00:00:{second:02d}+00:00',
                                         'finished_at': f'2026-10-04T00:00:{second+1:02d}+00:00'}
                            (out/'execution.json').write_text(json.dumps(execution))
                            (out/'cuda-result.json').write_text(json.dumps({
                                'cuda_available': True, 'matmul_finite': True, 'matmul_correct': True,
                                'visible_devices': ['GPU-'+device]}))
                        return {'status': 'ok', 'launched': list(paths) if calls.count(name) == 1 else [],
                                'run_directories': paths,
                                'report': {'groups': {'best_method': {'mean': 2.0, 'sample_std': 1.0, 'count': 3}}}}

                with patch.object(probe, 'ExperimentRunner', SyntheticQueue):
                    result = probe.run('execution')
                self.assertEqual(result['status'], 'passed')
                self.assertEqual(len(result['runs']), 6)
                self.assertEqual(calls, ['serial', 'serial', 'parallel', 'parallel'])
                self.assertTrue(result['completed_reused_without_launch'])
                self.assertTrue(result['cross_device_overlap_observed'])
                from tools.release_evidence import _gpu_result
                _gpu_result(root, result)
                outputs = [json.loads((root/name).read_text())
                           for name in ('serial-queue.json', 'parallel-queue.json')]
                target = root/'parallel/parallel-2/execution.json'
                row = json.loads(target.read_text())
                row['devices'] = ['GPU-4']
                row['device_inventory'] = [{'id': '4', 'uuid': 'GPU-4'}]
                target.write_text(json.dumps(row))
                (target.parent/'cuda-result.json').write_text(json.dumps({
                    'cuda_available': True, 'matmul_finite': True, 'matmul_correct': True,
                    'visible_devices': ['GPU-4']}))
                with self.assertRaisesRegex(ValueError, 'overlap'):
                    probe.summarize(root, ['4', '6'], outputs)
                (root/'approval.md').write_text('changed')
                with patch.object(probe, 'ExperimentRunner') as runner:
                    with self.assertRaisesRegex(ValueError, 'drift'):
                        probe.run('execution')
                    runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
