"""LP-8 deployment and release-only contracts; no model/Docker invocation."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import os
from unittest.mock import patch

from autoresearch_flow import FLOW_VERSION
from tools import release_check as release
from tools.release_evidence import CLAIMS, validate_evidence
from tools.release_evidence_current import _version_only

FLOW = Path(__file__).resolve().parents[1]


class RuntimeDistributionTests(unittest.TestCase):
    def test_runtime_payload_is_smaller_and_retains_authoritative_originals(self):
        paths = {p.relative_to(FLOW).as_posix() for p in release.payload_files()}
        development = {p.relative_to(FLOW).as_posix() for p in release.development_files()}
        self.assertLess(len(paths), len(development))
        self.assertFalse(any(p.split('/')[0] in {'tests', 'tools', 'pilots', 'local'} for p in paths))
        self.assertFalse(any(p.startswith(('docs/maintenance/', 'docs/interfaces/')) for p in paths))
        self.assertNotIn('templates/stage-finish.example.json', paths)
        self.assertNotIn('templates/confirmation.example.json', paths)
        self.assertTrue(release.RUNTIME_DOCUMENTS <= paths)
        registry = release.Registry(FLOW)
        self.assertTrue({r['path'] for r in registry.manifest['bundled_files']} <= paths)
        self.assertIn('autoresearch_flow/assets/docker-codex-nested.json', paths)
        self.assertFalse(any(p.startswith('rules/history/') for p in paths))
        self.assertFalse(any(p.startswith('rules/provenance/') for p in paths))

    def test_clean_runtime_works_without_tests_design_credentials_or_ledger(self):
        with tempfile.TemporaryDirectory(prefix='ar-lightweight-release-') as tmp:
            root = Path(tmp)
            files = release.payload_files()
            for source in files:
                dest = root / source.relative_to(FLOW)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, dest)
            release.check_documents([root / p.relative_to(FLOW) for p in files], root)
            checks = release.runtime_smoke(root)
            self.assertTrue(any("preflight" in c["command"] and "--stage" in c["command"] for c in checks))
            self.assertTrue(any("autoresearch_flow.task_workspace" in c["command"] for c in checks))
            self.assertTrue(all(c['exit_code'] == 0 for c in checks))
            self.assertFalse((root / '.autoresearch-flow').exists())
            self.assertFalse((root / 'tests').exists())
            self.assertFalse((root / 'tools').exists())

    def test_only_version_literal_is_exempt_from_execution_source_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a, b = root / 'old.py', root / 'new.py'
            a.write_text('FLOW_VERSION="old"\nMODE=1\n')
            b.write_text('FLOW_VERSION="new"\nMODE=1\n')
            self.assertTrue(_version_only(a, b))
            b.write_text('FLOW_VERSION="new"\nMODE=2\n')
            self.assertFalse(_version_only(a, b))
            b.write_text('FLOW_VERSION=compute()\nMODE=1\n')
            self.assertFalse(_version_only(a, b))


class CurrentReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.flow = self.root / 'flow'
        self.flow.mkdir()
        self.evidence = self.root / 'evidence'
        self.evidence.mkdir()
        from tools.release_evidence_current import ENTRYPOINTS
        names = set(n for ns in ENTRYPOINTS.values() for n in ns)
        names.add('autoresearch_flow/__init__.py')
        for n in names:
            p = self.flow / n
            p.parent.mkdir(exist_ok=True)
            p.write_text('FLOW_VERSION="old"\n' if p.name == '__init__.py' else 'from . import __init__\n')
        self.files = sorted(self.flow.rglob('*.py'))
        originals = self.evidence / 'runtime/implementation'
        for p in self.files:
            q = originals / p.relative_to(self.flow)
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, q)
            q.chmod(q.stat().st_mode & ~0o222)
        self.write('runtime/snapshot.json', {'files': {
            'implementation/' + p.relative_to(self.flow).as_posix(): self.digest(p) for p in self.files}})
        self.write('raw.json', {'explicitly_synthetic': True})
        self.write('review.md', 'Synthetic unit fixture, not actual release acceptance.')
        self.write('result.json', {'status': 'passed'})
        self.write('approval.json', {'kind': 'release_exception', 'scope': 'independent_trial',
                    'approved_by': 'user', 'approved_at': '2026-10-10', 'release_version': FLOW_VERSION,
                    'reason': 'Synthetic explicit exception fixture.', 'user_reply': 'Synthetic explicit authorization.'})
        self.data = {'schema_version': 2, 'release_version': FLOW_VERSION,
                     'limitations': ['Independent trial waived; synthetic unit fixture only.'], 'checks': []}
        for gate in CLAIMS:
            if gate == 'independent_trial':
                check = {'id': gate, 'status': 'waived', 'mode': 'explicit_user_authorization',
                         'approval': self.ref('approval.json')}
            else:
                check = {'id': gate, 'status': 'passed', 'mode': 'reused', 'origin_version': 'synthetic-old',
                         'origin_at': '2026-10-09T00:00:00+00:00',
                         'sources': {'kind': 'runtime_snapshot', 'record': self.ref('runtime/snapshot.json')},
                         'reviewer': 'synthetic reviewer', 'review': self.ref('review.md'),
                         'result': self.ref('result.json'), 'evidence': [self.ref('raw.json')],
                         'claims': {c: True for c in CLAIMS[gate]}}
            self.data['checks'].append(check)
        self.manifest = self.evidence / 'manifest.json'

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write(self, name, data):
        p = self.evidence / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))

    def ref(self, name):
        return {'path': name, 'sha256': self.digest(self.evidence / name)}

    def validate(self):
        from tools.release_evidence import validate_bindings
        self.write('manifest.json', self.data)
        return validate_bindings(self.manifest, self.flow, self.files)

    def test_original_sources_and_explicit_version_specific_exception(self):
        result = self.validate()
        self.assertEqual(result['schema_version'], 2)
        self.assertEqual(result['checks'][-1]['mechanical_result'], 'waived_by_user')
        (self.flow / 'autoresearch_flow/__init__.py').write_text('FLOW_VERSION="new"\n')
        result = self.validate()
        self.assertEqual(result['checks'][0]['metadata_only_changes'], ['autoresearch_flow/__init__.py:FLOW_VERSION'])
        (self.flow / 'autoresearch_flow/runtime_controller.py').write_text('# behavior changed\n')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.validate()

    def test_raw_original_tampering_is_not_overridden_by_claims(self):
        self.write('raw.json', {'tampered': True})
        with self.assertRaisesRegex(ValueError, 'evidence drift'):
            self.validate()

    def test_removed_imported_source_cannot_disappear_from_dependency_scope(self):
        source = self.flow / 'autoresearch_flow/__init__.py'
        source.unlink()
        self.files.remove(source)
        with self.assertRaisesRegex(ValueError, 'missing current source'):
            self.validate()

    def test_relative_manifest_has_the_same_source_and_original_bindings(self):
        expected = self.validate()
        from tools.release_evidence import validate_bindings
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            actual = validate_bindings(Path('evidence/manifest.json'), self.flow, self.files)
        finally:
            os.chdir(previous)
        self.assertEqual(expected, actual)

    def test_new_version_cannot_inherit_an_old_exception(self):
        self.write('approval.json', {'kind': 'release_exception', 'scope': 'independent_trial',
            'approved_by': 'user', 'approved_at': '2026-10-04', 'release_version': 'unrelated-old', 'reason': 'old'})
        self.data['checks'][-1]['approval'] = self.ref('approval.json')
        with self.assertRaisesRegex(ValueError, 'not authorized'):
            self.validate()

    def test_other_gates_cannot_be_waived_and_duplicate_gates_are_rejected(self):
        self.data['checks'][0].update(status='waived', mode='explicit_user_authorization')
        with self.assertRaisesRegex(ValueError, 'only independent_trial'):
            self.validate()
        self.data['checks'][0] = copy.deepcopy(self.data['checks'][-1])
        with self.assertRaisesRegex(ValueError, 'missing or duplicated'):
            self.validate()

    def test_mechanical_results_are_required_even_when_review_and_binding_pass(self):
        self.write('result.json', {'status': 'failed'})
        for check in self.data['checks'][:-1]:
            check['result'] = self.ref('result.json')
        self.validate()
        with self.assertRaisesRegex(ValueError, 'actual result failed'):
            validate_evidence(self.manifest, self.flow, self.files)

    def native_fixture(self):
        from autoresearch_flow.runtime_clock import activity_summary
        thread, goal = 'synthetic-original-thread', {'status': 'complete', 'threadId': 'synthetic-original-thread',
                                                   'createdAt': 1, 'objective': 'synthetic-only'}
        state = {'status': 'complete', 'thread_id': thread, 'goal': goal, 'objective': goal['objective']}
        config = {'purpose': 'acceptance', 'duration': {'minimum_seconds': 36000}}
        self.write('runtime/state.json', state)
        activity = [{'action': action, 'activity': 'turn:' + str(i), 'segment': 'fixture',
                     'at': t, 'monotonic': t, 'evidence': 'synthetic only'}
                    for i, a, b in [(1, 1, 2), (2, 3, 4)] for action, t in [('start', a), ('end', b)]]
        self.write('runtime/logs/activity.jsonl', '\n'.join(json.dumps(x) for x in activity) + '\n')
        self.write('runtime/logs/timing.json', {**activity_summary(activity), 'formal': False})
        rpc = [{'at': t, 'direction': 'sent', 'message': {'method': m, 'params': {'threadId': thread, **p}}}
               for t, m, p in [(1, 'thread/goal/set', {'status': 'active'}), (1, 'turn/start', {}),
                              (2, 'thread/goal/set', {'status': 'paused'}),
                              (3, 'thread/goal/set', {'status': 'active'}), (3, 'turn/start', {})]]
        rpc.append({'at': 4, 'direction': 'received', 'message': {'method': 'thread/goal/updated',
                                                               'params': {'threadId': thread, 'goal': goal}}})
        self.write('runtime/logs/rpc.jsonl', '\n'.join(json.dumps(x) for x in rpc) + '\n')
        for i in [1, 2]:
            self.write(f'runtime/jobs/records/job{i}.json', {'job_id': f'job{i}', 'status': 'succeeded',
                'exit_code': 0, 'started_at': i * 2 - 0.5, 'score': -i})
        self.write('runtime/output/trajectory_codex.json', {'rounds': [
            {'round': i, 'policy_name': 'synthetic', 'method_summary': '仅测试夹具', 'status': 'ok',
             'score': i, 'failure_reason': None, 'retained_best': i == 1, 'time': '2026-10-10 00:00:00'}
            for i in [1, 2]]})
        report = {k: self.ref('runtime/' + n) for k, n in {'state': 'state.json', 'activity': 'logs/activity.jsonl',
            'rpc': 'logs/rpc.jsonl', 'timing': 'logs/timing.json', 'trajectory': 'output/trajectory_codex.json'}.items()}
        report['observation_review'] = self.ref('review.md')
        return config, state, report

    def test_current_native_results_and_replacement_goal_detection(self):
        from tools.release_evidence_current import _native
        config, state, report = self.native_fixture()
        with patch('autoresearch_flow.track_runtime.TrackRuntime._load', return_value=(config, state, {})):
            _native(self.evidence, report)
            name = 'runtime/logs/rpc.jsonl'
            rows = [json.loads(l) for l in (self.evidence / name).read_text().splitlines()]
            rows[-1]['message']['params']['goal']['createdAt'] = 99
            self.write(name, '\n'.join(json.dumps(x) for x in rows) + '\n')
            report['rpc'] = self.ref(name)
            with self.assertRaisesRegex(ValueError, 'Goal was replaced'):
                _native(self.evidence, report)

    def test_current_native_rejects_wrong_timing_first_result_reuse_and_invalid_round(self):
        from tools.release_evidence_current import _native
        from autoresearch_flow.common import FlowError
        for defect in ['timing', 'job', 'trajectory']:
            with self.subTest(defect=defect):
                config, state, report = self.native_fixture()
                if defect == 'timing':
                    self.write('runtime/logs/timing.json', {'formal': False, 'net_active_seconds': 99})
                    report['timing'] = self.ref('runtime/logs/timing.json')
                elif defect == 'job':
                    self.write('runtime/jobs/records/job2.json', {'status': 'succeeded', 'exit_code': 0,
                                                               'started_at': 1.6})
                else:
                    self.write('runtime/output/trajectory_codex.json', {'rounds': [{}, {}]})
                    report['trajectory'] = self.ref('runtime/output/trajectory_codex.json')
                with patch('autoresearch_flow.track_runtime.TrackRuntime._load', return_value=(config, state, {})):
                    with self.assertRaises((ValueError, FlowError)):
                        _native(self.evidence, report)

    def test_current_gpu_requires_same_instance_device_compute_and_unique_jobs(self):
        from tools.release_evidence_current import _gpu
        self.write('runtime/config.json', {'resources': {'gpu_ids': ['4']}})
        self.write('runtime/container.json', {'container_id': 'fixture-container'})
        admission = {'gpu_ids': ['4'], 'container_id': 'fixture-container',
            'gpu_uuids': ['GPU-00000000-0000-0000-0000-000000000004'],
            'device_requests': [{'Driver': 'nvidia', 'Count': 0, 'DeviceIDs': ['4'], 'Capabilities': [['gpu']]}],
            'cuda_matmul': True, 'privileged': False, 'docker_socket_absent': True,
            'provider_sha256': self.digest(self.flow / 'autoresearch_flow/harbor_gpu.py'),
            'gpu_helpers_sha256': self.digest(self.flow / 'autoresearch_flow/runtime_gpu.py')}
        self.write('runtime/trial/admission.json', admission)
        for i in [1, 2]:
            self.write(f'runtime/jobs/records/job{i}.json', {'job_id': f'job{i}', 'status': 'succeeded',
                                                         'exit_code': 0, 'score': -i})
        report = {'authorized_devices': ['4'], 'admission': self.ref('runtime/trial/admission.json'),
                  'jobs': [self.ref(f'runtime/jobs/records/job{i}.json') for i in [1, 2]]}
        _gpu(self.evidence, report, self.flow)
        for field, value in [('cuda_matmul', False), ('gpu_ids', ['5']), ('container_id', 'other')]:
            with self.subTest(field=field):
                changed = {**admission, field: value}
                self.write('runtime/trial/admission.json', changed)
                with self.assertRaises(ValueError):
                    _gpu(self.evidence, {**report, 'admission': self.ref('runtime/trial/admission.json')}, self.flow)
        self.write('runtime/trial/admission.json', admission)
        report['jobs'] = [report['jobs'][0], report['jobs'][0]]
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            _gpu(self.evidence, report, self.flow)


if __name__ == '__main__':
    unittest.main()
