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
from autoresearch_flow.legacy_qa import _SCRIPTS, _ASSESS, validate_legacy_qa
from autoresearch_flow.archive_io import package_snapshot
from autoresearch_flow.package_qa import accepted


_FIXTURE = """
import json, pathlib, shutil, sys
sys.path.insert(0, sys.argv[1])
from test_legacy_migration_waiver import LegacyMigrationWaiverTests
import legacy_migration_waiver as w
import task_fingerprint as fp
dest = pathlib.Path(sys.argv[2])
f = LegacyMigrationWaiverTests()
f.setUp()
try:
    shutil.copytree(f.root, dest / 'task')
    f.root = dest / 'task'
    (f.root / 'workspace/harbor_task').mkdir(parents=True, exist_ok=True)
    (f.root / 'optimization_evidence').mkdir(exist_ok=True)
    f.rebuild()
    f.no_nop()
    report, review, request = [dest / n for n in ('report.json', 'review.json', 'request.json')]
    report.write_text(json.dumps(f.report))
    review.write_text(json.dumps(f.review))
    manifest = f.manifest({'H06': ['new_current_trial_requirement']})
    manifest['strict_report_sha256'] = fp.sha256_file(report)
    manifest['review_sha256'] = fp.sha256_file(review)
    request.write_text(json.dumps(manifest))
    result = w.assess(f.report, f.review, manifest, f.root,
        fp.sha256_file(report), fp.sha256_file(review), worksheet_outside_artifact=True)
    result['strict_report_path'] = str(report)
    (dest / 'waiver.json').write_text(json.dumps(result))
finally:
    f.tearDown()
"""


class LegacyQaContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        subprocess.run([sys.executable, '-I', '-B', '-c', _FIXTURE,
                        str(_SCRIPTS), str(self.base)], check=True, capture_output=True)

    def validate(self, **kwargs):
        return validate_legacy_qa(
            self.base / 'task', self.base / 'report.json', self.base / 'review.json',
            self.base / 'request.json', self.base / 'waiver.json', **kwargs)

    def test_old_task_without_nop_can_pass_with_bound_official_waiver(self):
        result = self.validate(require_pass=True)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(result['strict_decision'], 'FAIL')
        self.assertTrue(result['platform_followup_pending'])

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

    def test_disabled_worksheet_cannot_reuse_accepted_result(self):
        path = self.base / 'request.json'
        value = json.loads(path.read_text())
        value['enabled'] = False
        path.write_text(json.dumps(value))
        with self.assertRaises(FlowError):
            self.validate(require_pass=True)

    def test_genuine_nonpassing_official_results_remain_blocking(self):
        request = self.base / 'request.json'
        original = json.loads(request.read_text())
        for changes in ({'enabled': False}, {'requests': []}):
            with self.subTest(changes=changes):
                request.write_text(json.dumps({**original, **changes}))
                payload = {'root': str(self.base / 'task'),
                           'report': str(self.base / 'report.json'),
                           'review': str(self.base / 'review.json'),
                           'worksheet': str(request)}
                proc = subprocess.run([sys.executable, '-I', '-B', '-c', _ASSESS, str(_SCRIPTS)],
                    input=json.dumps(payload), text=True, capture_output=True, check=True)
                result = json.loads(proc.stdout)
                result['strict_report_path'] = payload['report']
                (self.base / 'waiver.json').write_text(json.dumps(result))
                verified = self.validate()
                self.assertIn(verified['decision'], {'FAIL', 'INCOMPLETE'})
                with self.assertRaises(FlowError) as caught:
                    self.validate(require_pass=True)
                self.assertEqual(caught.exception.code, 'QA_UNRESOLVED')

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
