"""Exercise the flow boundary against real official synthetic reports."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from autoresearch_flow.common import FlowError
from autoresearch_flow.legacy_qa import _SCRIPTS, validate_legacy_qa
from autoresearch_flow.archive_io import package_snapshot, _write_zip
from autoresearch_flow.package_qa import accepted


_FIXTURE = """
import contextlib, io, json, pathlib, shutil, sys
sys.path.insert(0, sys.argv[1])
from test_audit_standard_with_waivers import StandardWaiverTests
import audit_standard_with_waivers as w
dest = pathlib.Path(sys.argv[2])
f = StandardWaiverTests()
f.setUp()
try:
    shutil.copytree(f.root, dest / 'task')
    f.root = dest / 'task'
    f.base = dest
    (f.root / 'workspace/harbor_task').mkdir(parents=True, exist_ok=True)
    (f.root / 'optimization_evidence').mkdir(exist_ok=True)
    if sys.argv[3] == 'no_nop':
        shutil.rmtree(f.root / 'run-a')
        for row in f.sr['harbor']['checks']:
            if row['id'] == 'H05':
                row.update(status='not_applicable', evidence=[], summary='No adopted job config.')
            if row['id'] == 'H06':
                row.update(status='fail', evidence=[], summary='Old phase has no NOP.')
        f.resolve_all(f.assess(), {'H06': 'legacy_nop_or_current_trial_gap'})
    (dest / 'review.json').write_text(json.dumps(f.sr))
    (dest / 'request.json').write_text(json.dumps(f.lr))
finally:
    f.doCleanups()
"""

_GENERATE = """
import contextlib, io, pathlib, shutil, sys
sys.path.insert(0, sys.argv[1])
import audit_standard_with_waivers as w
dest = pathlib.Path(sys.argv[2])
out = dest / 'qa-output'
with contextlib.redirect_stdout(io.StringIO()):
    w.main([sys.argv[3], '--standard-review', str(dest / 'review.json'),
            '--review', str(dest / 'request.json'), '--out-dir', str(out)])
for source, target in [('standard/report.json','report.json'), ('standard/inventory.json','inventory.json'), ('report.json','waiver.json')]:
    shutil.copyfile(out / source, dest / target)
"""


class LegacyQaContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        subprocess.run([sys.executable, '-I', '-B', '-c', _FIXTURE,
                        str(_SCRIPTS), str(self.base), 'no_nop'], check=True, capture_output=True)
        self.generate()

    def generate(self, source=None):
        subprocess.run([sys.executable, '-I', '-B', '-c', _GENERATE, str(_SCRIPTS),
                        str(self.base), str(source or self.base / 'task')], check=True, capture_output=True)

    def validate(self, **kwargs):
        return validate_legacy_qa(
            self.base / 'task', self.base / 'report.json', self.base / 'review.json',
            self.base / 'request.json', self.base / 'waiver.json', **kwargs)

    def test_old_task_without_nop_can_pass_with_bound_official_waiver(self):
        result = self.validate(require_pass=True)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(result['strict_decision'], 'FAIL')
        self.assertEqual(result['waived_findings'][0]['waiver_reason'], 'legacy_nop_or_current_trial_gap')

    def test_modified_waiver_conclusion_is_rejected(self):
        path = self.base / 'waiver.json'
        value = json.loads(path.read_text())
        value['decision'] = 'PASS'
        path.write_text(json.dumps(value))
        with self.assertRaises(FlowError):
            self.validate(require_pass=True)

    def test_missing_input_returns_contract_error(self):
        (self.base / 'review.json').unlink()
        with self.assertRaises(FlowError) as caught:
            self.validate(require_pass=True)
        self.assertEqual(caught.exception.code, 'QA_REPORT_MISSING')

    def test_missing_task_returns_scope_error(self):
        (self.base / 'task').rename(self.base / 'moved-task')
        with self.assertRaises(FlowError) as caught:
            self.validate(require_pass=True)
        self.assertEqual(caught.exception.code, 'QA_SCOPE_MISMATCH')

    def test_old_delivery_binding_and_stage_reuse_verified_pair(self):
        from autoresearch_flow.w4_package import DeliveryPackage
        from autoresearch_flow.stages import StageFlow
        delivery = DeliveryPackage.__new__(DeliveryPackage)
        delivery.root = self.base
        delivery.directory = self.base / '.state/delivery'
        record = delivery.qa_bind(self.base / 'task', self.base / 'report.json',
            legacy_review=self.base / 'review.json', legacy_worksheet=self.base / 'request.json',
            legacy_result=self.base / 'waiver.json')
        self.assertEqual(record['legacy_qa']['decision'], 'PASS_WITH_WAIVERS')
        flow = StageFlow.__new__(StageFlow)
        flow.root = self.base
        flow.store = SimpleNamespace(state_dir=self.base / '.state')
        with patch.object(flow, '_nop_record', side_effect=AssertionError('must use official waiver')):
            result = flow._gate('6.2', {'package_root': 'task'})
        self.assertEqual(result['legacy_qa']['strict_decision'], 'FAIL')
        with patch.object(DeliveryPackage, 'delivery_state', return_value={'delivery_phase': 'qa_verified'}):
            result = flow._gate('6.5', {'package_root': 'task'})
        self.assertEqual(result['delivery_phase'], 'qa_verified')
        # Exercise real ZIP construction with the independently checked gate.
        with patch.object(StageFlow, 'check', return_value={
                'status': 'checked', 'issues': [], 'machine_check': {'result': result}}):
            archived = delivery.archive(self.base / 'task', name='synthetic-benchmark')
        self.assertEqual(archived['legacy_qa']['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(archived['legacy_qa']['strict_decision'], 'FAIL')
        self.assertEqual(delivery.delivery_state(result)['delivery_phase'], 'archives_verified')
        (self.base / 'request.json').write_text('{}')
        with self.assertRaises(FlowError) as caught:
            flow._gate('6.2', {'package_root': 'task'})
        self.assertEqual(caught.exception.code, 'QA_REPORT_DRIFT')

    def test_package_consumes_pair_without_relabelling_strict_failure(self):
        root = self.base / 'task'
        report, outcome = accepted(
            root, self.base / 'report.json', package_snapshot(root),
            legacy_review=self.base / 'review.json',
            legacy_worksheet=self.base / 'request.json',
            legacy_result=self.base / 'waiver.json',
        )
        self.assertEqual(report['summary']['decision'], 'FAIL')
        self.assertEqual(outcome['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(len(outcome['inputs']), 4)

    def test_package_rejects_partial_legacy_arguments(self):
        root = self.base / 'task'
        with self.assertRaises(FlowError):
            accepted(root, self.base / 'report.json', package_snapshot(root),
                     legacy_result=self.base / 'waiver.json')

    def test_changed_artifact_invalidates_old_pair(self):
        with (self.base / 'task/instruction.md').open('a') as stream:
            stream.write('\nChanged current task.\n')
        with self.assertRaises(FlowError):
            self.validate(require_pass=True)

    def test_changed_worksheet_cannot_reuse_accepted_result(self):
        path = self.base / 'request.json'
        value = json.loads(path.read_text())
        value['standard_resolutions'] = []
        path.write_text(json.dumps(value))
        with self.assertRaises(FlowError):
            self.validate(require_pass=True)

    def test_genuine_nonpassing_official_results_remain_blocking(self):
        request = self.base / 'request.json'
        original = json.loads(request.read_text())
        request.write_text(json.dumps({**original, 'standard_resolutions': []}))
        self.generate()
        self.assertEqual(self.validate()['decision'], 'FAIL')
        with self.assertRaises(FlowError) as caught:
            self.validate(require_pass=True)
        self.assertEqual(caught.exception.code, 'QA_UNRESOLVED')

    def test_complete_review_without_actual_waivers_does_not_invent_them(self):
        import shutil
        shutil.rmtree(self.base / 'task')
        subprocess.run([sys.executable, '-I', '-B', '-c', _FIXTURE,
                        str(_SCRIPTS), str(self.base), 'normal'], check=True, capture_output=True)
        self.generate()
        result = self.validate(require_pass=True)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(result['strict_decision'], 'PASS')
        self.assertEqual(result['waived_findings'], [])

    def test_review_error_is_not_expert_rejection(self):
        path = self.base / 'request.json'
        value = json.loads(path.read_text())
        value['overview'] = None
        path.write_text(json.dumps(value))
        self.generate()
        outcome = self.validate()
        self.assertEqual(outcome['decision'], 'ERROR')
        self.assertFalse(outcome['is_task_rejection'])
        with self.assertRaises(FlowError) as caught:
            self.validate(require_pass=True)
        self.assertEqual(caught.exception.code, 'QA_REVIEW_INCOMPLETE')

    def test_zip_source_recomputes_with_temporary_roots(self):
        archive = self.base / 'submission.zip'
        _write_zip(self.base / 'task', archive, '', snapshot=[row for row in
                   package_snapshot(self.base / 'task') if row['path'] != '.'])
        self.generate(archive)
        outcome = self.validate(require_pass=True)
        self.assertEqual(outcome['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(outcome['source_archive']['path'], str(archive))
        with (self.base / 'task/instruction.md').open('a') as stream:
            stream.write('tampered')
        with self.assertRaises(FlowError):
            self.validate()

    def test_subreport_and_old_report_are_explicitly_rejected(self):
        target = self.base / 'waiver.json'
        saved = json.loads(target.read_text())
        for changes in ({'stage': 'format_repair'}, {'version': '0.3.10-legacy-waiver.2'}):
            target.write_text(json.dumps({**saved, **changes}))
            with self.assertRaises(FlowError) as caught:
                self.validate()
            self.assertEqual(caught.exception.code, 'QA_REPORT_VERSION')

    def test_modified_component_evidence_cannot_hide_behind_timestamps(self):
        target = self.base / 'waiver.json'
        saved = json.loads(target.read_text())
        saved['standard_components']['fingerprint']['task_content_sha256'] = 'f' * 64
        target.write_text(json.dumps(saved))
        with self.assertRaises(FlowError) as caught:
            self.validate()
        self.assertEqual(caught.exception.code, 'QA_REPORT_DRIFT')

    def test_same_length_evidence_edit_is_not_a_current_qa21_waiver(self):
        target = self.base / 'task/expert_evidence/methods.md'
        value = target.read_bytes()
        target.write_bytes(b'X' + value[1:])
        with self.assertRaises(FlowError) as caught:
            self.validate()
        self.assertEqual(caught.exception.code, 'QA_VERSION_UNVERIFIED')

    def test_strict_report_is_preserved_and_checked_separately(self):
        target = self.base / 'report.json'
        value = json.loads(target.read_text())
        value['summary']['decision'] = 'PASS'
        target.write_text(json.dumps(value))
        with self.assertRaises(FlowError) as caught:
            self.validate()
        self.assertEqual(caught.exception.code, 'QA_REPORT_DRIFT')

    def test_package_change_during_official_recheck_is_rejected(self):
        run = subprocess.run
        def change_after_recheck(*args, **kwargs):
            result = run(*args, **kwargs)
            with (self.base / 'task/expert_evidence/methods.md').open('a') as stream:
                stream.write('changed during recheck')
            return result
        with patch('autoresearch_flow.legacy_qa.subprocess.run', side_effect=change_after_recheck):
            with self.assertRaises(FlowError) as caught:
                self.validate()
        self.assertEqual(caught.exception.code, 'QA_PACKAGE_DRIFT')

    def test_materials_cli_consumes_actual_official_pair(self):
        cli = Path(__file__).resolve().parents[1] / 'cli.py'
        proc = subprocess.run([sys.executable, str(cli), '--format', 'json',
            'materials', 'legacy-qa-check', '--package-root', str(self.base / 'task'),
            '--report', str(self.base / 'report.json'), '--review', str(self.base / 'review.json'),
            '--worksheet', str(self.base / 'request.json'), '--result', str(self.base / 'waiver.json')],
            text=True, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['decision'], 'PASS_WITH_WAIVERS')


if __name__ == '__main__':
    unittest.main()
