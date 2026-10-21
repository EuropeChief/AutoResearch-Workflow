"""Project relaxations must reach delivery without weakening real quality gates."""
import json
from pathlib import Path
import sys
import unittest

import implementation_review as qa
import project_policy as policy
import test_implementation_review as fixtures

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from autoresearch_flow.qa_contract import validate_qa_report


class ProjectNoticeTests(unittest.TestCase):
    setUp = fixtures.ImplementationReviewTests.setUp
    tearDown = fixtures.ImplementationReviewTests.tearDown
    review = fixtures.ImplementationReviewTests.review
    report = fixtures.ImplementationReviewTests.report

    def render(self, review):
        return qa.apply_review(self.report(), review, self.root)

    def hardware_review(self):
        path = self.root / 'task.toml'
        path.write_text(path.read_text() + '\n[environment]\ngpus=1\ngpu_types=["H20"]\n')
        review = self.review()
        resources = review['resource_review']
        resources['estimate'] = {'score_seconds': None, 'gpu_count': 1, 'cpu_cores': 1,
            'gpu_type': 'RTX 4090', 'time_accounting': '原卡完整单轮，换卡后未实测',
            'basis': 'Synthetic existing evidence, not real compute.', 'evidence': ['instruction.md']}
        resources['hardware_review'].update(task_type='gpu', score_comparability='unverified',
            advisory_code='HARDWARE_RECHECK', affects_formal_scores=True,
            summary='原卡成绩如实保留，仅换卡后的成绩及耗时影响未核验。')
        resources['runs'][0].update(gpu_count=1, gpu_type='RTX 4090')
        return review

    def test_missing_nop_and_conflicting_hash_are_visible_warnings_and_deliverable(self):
        review = self.review()
        row = next(r for r in review['harbor']['checks'] if r['id'] == 'H06')
        row.update(status='manual', evidence=[], summary='未提供NOP。')
        path = self.root / 'expert_evidence/run_summary.json'
        summary = json.loads(path.read_text())
        for agent in summary['agent_execution']:
            agent['task_binding']['task_content_sha256'] = '0' * 64
        path.write_text(json.dumps(summary))
        report = self.render(review)
        self.assertEqual(report['summary']['decision'], 'PASS')
        rows = {r['id']: r for r in report['checks'] + report['harbor']['checks']}
        for key in ('QA21', 'QA17', 'H06'):
            self.assertEqual(rows[key]['status'], 'warn')
            self.assertTrue(policy.allowed(rows[key]))
        self.assertEqual(report['harbor']['runtime_status'], 'not_run')
        self.assertIsNone(report['harbor']['trial_evidence'])
        self.assertEqual(rows['QA18']['status'], 'pass')
        self.assertEqual(report['trajectory_review']['status'], 'warn')
        validate_qa_report(report, require_pass=True)
        self.assertNotIn('请修改/补充', qa.return_to_expert(report))
        self.assertIn('提示（不单独阻断）', qa.compact_markdown(report))

    def test_card_change_only_does_not_require_new_scores_or_time(self):
        review = self.hardware_review()
        gate = next(r for r in review['content_gates']['checks'] if r['id'] == 'G02')
        gate.update(policy.advisory(gate, 'HARDWARE_RECHECK'))
        report = self.render(review)
        self.assertEqual(report['summary']['decision'], 'PASS')
        rows = {r['id']: r for r in report['checks'] + report['content_gates']['checks']}
        for key in ('G02', 'G03', 'QA03', 'QA13', 'QA15'):
            self.assertEqual(rows[key]['status'], 'warn', key)
        self.assertIsNone(report['resource_review']['estimate']['score_seconds'])
        validate_qa_report(report, require_pass=True)

    def test_quality_gate_failure_and_missing_reference_cannot_be_hidden_by_card_warning(self):
        review = self.hardware_review()
        gate = next(r for r in review['content_gates']['checks'] if r['id'] == 'G03')
        gate['assessment']['quality_valid'] = False
        row = next(r for r in review['checks'] if r['id'] == 'QA03')
        row.update(status='fail', summary='缺实际Reference结果。', remediation='补原始结果', acceptance_evidence='可复核结果')
        report = self.render(review)
        self.assertEqual(report['summary']['decision'], 'FAIL')
        self.assertEqual(next(r for r in report['content_gates']['checks'] if r['id'] == 'G03')['status'], 'fail')
        self.assertEqual(next(r for r in report['checks'] if r['id'] == 'QA03')['status'], 'fail')

    def test_real_resource_overrun_is_still_a_failure(self):
        review = self.hardware_review()
        review['resource_review']['estimate']['score_seconds'] = 9000
        report = self.render(review)
        self.assertEqual(next(r for r in report['checks'] if r['id'] == 'QA15')['status'], 'fail')

    def test_mismatched_trajectory_identity_is_not_only_a_hash_advisory(self):
        review = self.review()
        path = self.root / 'expert_evidence/run_summary.json'
        data = json.loads(path.read_text())
        data['agent_execution'][0]['task_binding']['trajectory_path'] = 'trajectory_b.json'
        data['agent_execution'][0]['task_binding']['task_content_sha256'] = '0' * 64
        # Explicitly selected binding for the first trajectory names another file.
        import task_fingerprint as fp
        result = fp.check_binding(self.root, fp.collect(self.root), 'trajectory_a.json',
                                  data['agent_execution'][0]['task_binding'])
        self.assertEqual(result['status'], 'fail')

    def test_supplied_nop_execution_error_cannot_be_waived(self):
        review = self.review()
        path = self.root / 'run-a/result.json'
        data = json.loads(path.read_text()); data['exception_info'] = {'error': 'verifier crashed'}
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'exception_info'):
            self.render(review)

    def test_unreviewed_collection_and_unrelated_manual_conclusion_still_block(self):
        self.assertEqual(self.report()['summary']['decision'], 'INCOMPLETE')
        import task_fingerprint as fp
        # Missing historical hashes cannot hide a failure to read current inputs.
        binding = fp.check_binding(self.root, {'status': 'manual', 'summary': 'unreadable current task'},
                                   'trajectory_a.json', None)
        self.assertEqual(binding['status'], 'manual')
        review = self.hardware_review()
        gate = next(r for r in review['content_gates']['checks'] if r['id'] == 'G03')
        gate['assessment'].pop('threshold_basis')
        report = self.render(review)
        self.assertEqual(report['summary']['decision'], 'INCOMPLETE')
        self.assertEqual(next(r for r in report['content_gates']['checks'] if r['id'] == 'G03')['status'], 'manual')


if __name__ == '__main__':
    unittest.main()
