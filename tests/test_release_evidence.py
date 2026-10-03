"""Synthetic release evidence; never a real live-run or independent-trial claim."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import shutil

from autoresearch_flow import FLOW_VERSION
from tools.release_evidence import validate_bindings, validate_evidence


class ReleaseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.flow = self.root/'flow'
        self.flow.mkdir()
        self.evidence = self.root/'evidence'
        self.evidence.mkdir()
        for name in ('runtime', 'harbor_agent', 'experiment_runner'):
            path = self.flow/f'autoresearch_flow/{name}.py'
            path.parent.mkdir(exist_ok=True)
            path.write_text('from . import core\n')
        (self.flow/'autoresearch_flow/core.py').write_text('# frozen dependency\n')
        (self.flow/'README.md').write_text('synthetic user entry')
        self.files = sorted(self.flow.rglob('*'))
        self.files = [p for p in self.files if p.is_file()]
        snapshot = {'version': 'synthetic-old', 'files': [
            {'path': p.relative_to(self.flow).as_posix(), 'sha256': self.digest(p),
             'mode': p.stat().st_mode & 0o777} for p in self.files]}
        self.write('origin.json', snapshot)
        self.write('raw.json', {'explicitly_synthetic': True, 'observation': 'fixture'})
        self.write('review.md', 'Synthetic reviewer: inspected fixture observations, not actual live evidence.\n')
        self.data = {'schema_version': 1, 'release_version': FLOW_VERSION,
                     'limitations': ['Synthetic unit fixture only'], 'checks': []}
        for gate, claims in {
            'native_runtime': ['native_tui', 'same_thread_resume', 'observer_detach', 'logs_and_timing', 'short_run_not_final'],
            'harbor_transfer': ['candidate_transfer', 'independent_verifier', 'reward_retrieval'],
            'gpu_dispatch': ['authorized_devices', 'actual_gpu_execution', 'no_duplicate_jobs'],
            'independent_trial': ['fresh_session', 'entry_sufficient', 'legal_pause_resume', 'no_unresolved_defects'],
        }.items():
            self.data['checks'].append({'id': gate, 'status': 'passed', 'mode': 'reused',
                'origin_version': 'synthetic-old', 'origin_at': '2026-10-03T00:00:00+00:00',
                'origin_sources': self.ref('origin.json'), 'evidence': [self.ref('raw.json')],
                'review': self.ref('review.md'), 'reviewer': 'synthetic reviewer',
                'claims': {claim: True for claim in claims}})
        self.manifest = self.evidence/'manifest.json'

    @staticmethod
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def write(self, name, value):
        path = self.evidence/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if not isinstance(value, str) else value)
        return path

    def ref(self, name):
        return {'path': name, 'sha256': self.digest(self.evidence/name)}

    def validate(self):
        self.manifest.write_text(json.dumps(self.data))
        return validate_bindings(self.manifest, self.flow, self.files)

    def waive_independent_trial(self, *, gate='independent_trial'):
        reason = 'Independent new-session trial skipped for the first formal release by explicit user instruction.'
        authorization = {'kind': 'first_release_exception', 'release_version': '1.0.0',
                         'scope': 'independent_trial', 'approved_by': 'user',
                         'approved_at': '2026-10-04', 'reason': reason}
        self.write('authorization.json', authorization)
        check = next(c for c in self.data['checks'] if c['id'] == gate)
        check.clear()
        check.update({'id': gate, 'status': 'waived', 'mode': 'explicit_user_authorization',
                      'waiver': {'approved_by': 'user', 'approved_at': '2026-10-04',
                                 'reason': reason, 'approval': self.ref('authorization.json')}})
        self.data['limitations'].append('Independent new-session trial waived for first release 1.0.0.')

    def test_explicit_reused_evidence_keeps_origin_and_rejects_dependency_or_raw_drift(self):
        result = self.validate()
        self.assertEqual(len(result['checks']), 4)
        self.assertEqual(result['checks'][0]['origin_version'], 'synthetic-old')
        self.assertEqual(result['checks'][0]['mode'], 'reused')
        dependency = self.flow/'autoresearch_flow/core.py'
        dependency.write_text('# changed dependency\n')
        with self.assertRaisesRegex(ValueError, 'source.*(changed|drift)'):
            self.validate()
        dependency.write_text('# frozen dependency\n')
        (self.evidence/'raw.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'evidence.*(changed|drift)'):
            self.validate()

    def test_missing_gate_failed_claim_and_empty_raw_evidence_do_not_release(self):
        original = copy.deepcopy(self.data)
        for change in ('missing', 'duplicate', 'failed', 'claim', 'raw'):
            with self.subTest(change=change):
                self.data = copy.deepcopy(original)
                check = self.data['checks'][0]
                if change == 'missing': self.data['checks'].pop()
                if change == 'duplicate': self.data['checks'][-1] = copy.deepcopy(check)
                if change == 'failed': check['status'] = 'pending'
                if change == 'claim': check['claims']['same_thread_resume'] = False
                if change == 'raw': check['evidence'] = []
                with self.assertRaises(ValueError): self.validate()

    def test_only_first_release_independent_trial_can_be_explicitly_waived(self):
        self.install_synthetic_results()
        self.waive_independent_trial()
        self.validate()
        bound = validate_evidence(self.manifest, self.flow, self.files)
        waiver = next(item for item in bound['checks'] if item['id'] == 'independent_trial')
        self.assertEqual(waiver['status'], 'waived')
        self.assertEqual(waiver['mechanical_result'], 'waived_by_user')
        self.assertTrue(all(item['mechanical_result'] == 'passed'
                            for item in bound['checks'] if item['id'] != 'independent_trial'))

        self.data['release_version'] = '1.0.1'
        with self.assertRaisesRegex(ValueError, 'version mismatch'):
            self.validate()

    def test_first_release_waiver_cannot_be_used_for_another_gate(self):
        self.waive_independent_trial(gate='gpu_dispatch')
        with self.assertRaisesRegex(ValueError, 'only independent_trial'):
            self.validate()

    def test_deleted_imported_module_and_executable_mode_drift_reject_reuse(self):
        dependency = self.flow/'autoresearch_flow/core.py'
        dependency.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'source changed'):
            self.validate()
        dependency.unlink()
        self.files.remove(dependency)
        with self.assertRaisesRegex(ValueError, 'source.*drift: removed dependency'):
            self.validate()

    def test_symlink_and_parent_traversal_are_not_evidence(self):
        ref = self.data['checks'][0]['evidence'][0]
        ref['path'] = '../evidence/raw.json'
        with self.assertRaisesRegex(ValueError, 'unsafe evidence path'):
            self.validate()
        (self.evidence/'linked.json').symlink_to(self.evidence/'raw.json')
        ref['path'] = 'linked.json'
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.validate()

    def test_unchanged_runtime_can_be_reused_after_isolated_document_update(self):
        # Engineering/doc maintenance drill: do not relabel old runtime as fresh.
        readme = self.flow/'README.md'
        readme.write_text('corrected entry for new users')
        with self.assertRaisesRegex(ValueError, 'independent_trial'):
            self.validate()
        new = json.loads((self.evidence/'origin.json').read_text())
        next(e for e in new['files'] if e['path'] == 'README.md')['sha256'] = self.digest(readme)
        self.write('new-origin.json', new)
        trial = self.data['checks'][-1]
        trial['origin_sources'] = self.ref('new-origin.json')
        trial['mode'] = 'fresh'
        result = self.validate()
        self.assertEqual([c['mode'] for c in result['checks']], ['reused', 'reused', 'reused', 'fresh'])

    def test_through_release_gate_failed_raw_result_cannot_be_overridden_by_claims(self):
        self.write('failed.json', {'status': 'failed', 'reward': None})
        for check in self.data['checks']:
            check['result'] = self.ref('failed.json')
        self.validate()
        with self.assertRaisesRegex(ValueError, 'actual result failed'):
            validate_evidence(self.manifest, self.flow, self.files)

    def test_cli_drift_is_runtime_change_but_maintenance_note_is_not(self):
        cli = self.flow/'cli.py'
        cli.write_text('# CLI dispatch\n')
        note = self.flow/'templates/change-note.example.md'
        note.parent.mkdir()
        note.write_text('maintenance note')
        self.files += [cli, note]
        original = json.loads((self.evidence/'origin.json').read_text())
        original['files'] += [{'path': p.relative_to(self.flow).as_posix(), 'sha256': self.digest(p),
                               'mode': p.stat().st_mode & 0o777} for p in (cli, note)]
        self.write('origin.json', original)
        for check in self.data['checks']: check['origin_sources'] = self.ref('origin.json')
        note.write_text('corrected maintenance wording')
        newer = copy.deepcopy(original)
        next(e for e in newer['files'] if e['path'].startswith('templates/'))['sha256'] = self.digest(note)
        self.write('new-origin.json', newer)
        self.data['checks'][-1]['origin_sources'] = self.ref('new-origin.json')
        self.validate()  # Runtime evidence unaffected, refreshed independent-entry evidence.
        cli.write_text('# changed runtime dispatch\n')
        with self.assertRaisesRegex(ValueError, 'source changed.*native_runtime'):
            self.validate()

    def install_synthetic_results(self, pending_resume=False, paused_resume=False):
        from test_w3_contract import RuntimeTests
        fixture = RuntimeTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare()
        fixture.runtime.preflight('seed', True)
        fixture.runtime.run('seed', 1, confirm_cost=True)
        if pending_resume:
            fixture.backend.mode = 'pending'
        elif paused_resume:
            fixture.backend.mode = 'budget_pause'
        fixture.runtime.run('seed', 1, resume=True, confirm_cost=True)
        shutil.copytree(fixture.root, self.evidence/'pilot')
        base = 'pilot/.autoresearch-flow/runtime/seed/'
        job = base+'harbor/synthetic/job.json'
        self.write(job, {'verifier': {'disable': True}})
        self.write('observer.json', {'continued_without_observer': True, 'segments': [{'observer_detached': True}]})
        self.write('native.json', {'status': 'passed', 'state': self.ref(base+'state.json'),
            'trajectory': self.ref(base+'formal/output/trajectory.jsonl'),
            'jobs': [self.ref(job)], 'observer': self.ref('observer.json')})
        candidate = self.evidence/'artifacts/workspace/solution/method.py'
        candidate.parent.mkdir(parents=True)
        candidate.write_text('# synthetic transferred method\n')
        candidate_ref = self.ref('artifacts/workspace/solution/method.py')
        self.write('transfer.json', {'status': 'harbor_transfer_probe_passed', 'exit_code': 0,
            'trial': {'reward': 1, 'mode': 'separate', 'candidate_sha256': candidate_ref['sha256']},
            'evidence': [candidate_ref]})
        self.write('harbor.json', {'status': 'passed', 'transfer_report': self.ref('transfer.json')})
        self.write('execution.json', {'exit_code': 0, 'devices': ['GPU-synthetic']})
        self.write('cuda.json', {'cuda_available': True, 'matmul_finite': True, 'visible_devices': ['GPU-synthetic']})
        self.write('gpu.json', {'status': 'passed', 'authorized_devices': ['GPU-synthetic'], 'runs': [
            {'run_id': 'synthetic-1', 'execution': self.ref('execution.json'), 'cuda_result': self.ref('cuda.json')}]})
        self.write('independent.json', {'status': 'passed', 'session_id': 'synthetic-only', 'fresh_session': True,
            'blocking_findings': [], 'session_record': self.ref('raw.json')})
        for check, name in zip(self.data['checks'], ('native', 'harbor', 'gpu', 'independent')):
            check['result'] = self.ref(name+'.json')
        self.validate()

    def test_authority_update_expires_affected_evidence_in_isolated_fixture(self):
        # Authority-update maintenance drill; real tutorial/catalog are untouched.
        manifest = self.flow/'rules/manifest.json'
        manifest.parent.mkdir()
        manifest.write_text('{"synthetic_requirement":"old"}')
        self.files.append(manifest)
        original = json.loads((self.evidence/'origin.json').read_text())
        original['files'].append({'path': 'rules/manifest.json', 'sha256': self.digest(manifest),
                                  'mode': manifest.stat().st_mode & 0o777})
        self.write('origin.json', original)
        for check in self.data['checks']: check['origin_sources'] = self.ref('origin.json')
        self.validate()
        manifest.write_text('{"synthetic_requirement":"new"}')
        with self.assertRaisesRegex(ValueError, 'source changed.*native_runtime'):
            self.validate()
        # No mutation or version-upgrade of a user's existing task is attempted.
        self.assertFalse((self.flow/'.autoresearch-flow').exists())

    def test_actual_outputs_are_checked_not_overridden_by_passed_review(self):
        self.install_synthetic_results()
        result = validate_evidence(self.manifest, self.flow, self.files)
        self.assertTrue(all(c['mechanical_result'] == 'passed' for c in result['checks']))
        changes = [('transfer.json', 'harbor.json', 'transfer_report', lambda d: d['trial'].update(mode='agent')),
                   ('cuda.json', 'gpu.json', None, lambda d: d.update(matmul_finite=False)),
                   ('pilot/.autoresearch-flow/runtime/seed/harbor/synthetic/job.json', 'native.json', None,
                    lambda d: d['verifier'].update(disable=False))]
        for raw, index, ref_key, mutate in changes:
            with self.subTest(raw=raw):
                saved = {p: (self.evidence/p).read_bytes() for p in (raw, index)}
                original_data = copy.deepcopy(self.data)
                value = json.loads(saved[raw]); mutate(value); self.write(raw, value)
                report = json.loads(saved[index])
                if ref_key: report[ref_key] = self.ref(raw)
                elif index == 'gpu.json': report['runs'][0]['cuda_result'] = self.ref(raw)
                else: report['jobs'] = [self.ref(raw)]
                self.write(index, report)
                next(c for c in self.data['checks'] if c['result']['path'] == index)['result'] = self.ref(index)
                self.validate()
                with self.assertRaises(ValueError): validate_evidence(self.manifest, self.flow, self.files)
                for name, content in saved.items(): (self.evidence/name).write_bytes(content)
                self.data = original_data

    def test_omitted_actual_harbor_job_cannot_be_replaced_with_a_benign_reference(self):
        self.install_synthetic_results()
        self.write('pilot/.autoresearch-flow/runtime/seed/harbor/omitted/job.json', {'verifier': {'disable': False}})
        with self.assertRaisesRegex(ValueError, 'actual Harbor job set'):
            validate_evidence(self.manifest, self.flow, self.files)

    def test_first_segment_success_cannot_substitute_for_actual_resume_progress(self):
        self.install_synthetic_results(pending_resume=True)
        with self.assertRaisesRegex(ValueError, 'resume.*successful'):
            validate_evidence(self.manifest, self.flow, self.files)

    def test_budget_paused_resume_with_successful_public_work_is_not_final_completion(self):
        self.install_synthetic_results(paused_resume=True)
        result = validate_evidence(self.manifest, self.flow, self.files)
        native = next(c for c in result['checks'] if c['id'] == 'native_runtime')
        self.assertEqual(native['mechanical_result'], 'passed')
        state = json.loads((self.evidence/'pilot/.autoresearch-flow/runtime/seed/state.json').read_text())
        last = state['segments'][-1]
        self.assertEqual(last['status'], 'budget_exhausted')
        self.assertNotIn('turn.completed', last['event_counts'])
        self.assertFalse((self.evidence/'pilot/.autoresearch-flow/runtime/seed/harbor/final_attempt.json').exists())


if __name__ == '__main__':
    unittest.main()
