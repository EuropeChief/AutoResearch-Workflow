"""End-to-end standard-plus-waivers fixtures. Never run a task or Harbor."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import audit_standard_with_waivers as wrapper
import audit_legacy_task as legacy
import audit_format_repair as fmt
import implementation_review
import test_implementation_review as native_fixtures
import test_audit_legacy_task as legacy_fixtures


class StandardWaiverTests(unittest.TestCase):
    def setUp(self):
        self.native_fixture = native_fixtures.ImplementationReviewTests()
        self.native_fixture.setUp()
        self.addCleanup(self.native_fixture.tearDown)
        self.root = self.native_fixture.root.resolve()
        self.base = self.root.parent
        self.sr = self.native_fixture.review()
        self.legacy_fixture = legacy_fixtures.FullLegacyReviewTests()
        self.legacy_fixture.setUp()
        self.addCleanup(self.legacy_fixture.tearDown)
        raw = self.legacy_fixture.review()
        for name in ('methods.md', 'formal_results.json'):
            (self.root / 'expert_evidence' / name).write_bytes((self.legacy_fixture.root / 'expert_evidence' / name).read_bytes())
        (self.root / 'environment/public_dev').mkdir()
        (self.root / 'environment/public_dev/dev.csv').write_text('x,y\n1,2\n')
        (self.root / 'environment/Dockerfile').write_text('FROM python:3.11\nWORKDIR /workspace\nCOPY public_dev /workspace/public_dev\n')
        (self.root / 'tests/evaluate.py').write_text('from pathlib import Path\nPath("/logs/verifier/reward.txt").write_text("0")\n')
        # The native original fixture is authoritative for standard input data.
        # Every legacy value below is copied without altering formal scores.
        def rewrite(value):
            if isinstance(value, dict):
                return {k: rewrite(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            if isinstance(value, str):
                return value.replace('workspace/harbor_task/', '').replace('expert_evidence/trajectory_a.json', 'trajectory_a.json').replace('expert_evidence/trajectory_b.jsonl', 'trajectory_b.json').replace('tests/hidden_supply.json', 'tests/hidden_assets/cases.json')
            return value
        self.lr = rewrite(raw)
        self.lr['overview']['baseline_reference'] = copy.deepcopy(self.sr['overview']['baseline_reference'])
        self.lr['overview']['optimization_surface'] = copy.deepcopy(self.sr['overview']['optimization_surface'])
        self.lr['task_root'] = '.'
        # Refresh a schema-valid native review after public asset changes.
        self.sr = self.native_fixture.review()
        self.lr['overview']['baseline_reference'] = copy.deepcopy(self.sr['overview']['baseline_reference'])
        self.lr['checks'] = []
        for key in fmt.CHECKS:
            refs = {'F01':['task.toml'], 'F02':['environment/Dockerfile'], 'F03':['tests/test.sh'], 'F04':['task.toml'],
                'F05':['environment/Dockerfile','tests/hidden_assets/cases.json'], 'F06':['task.toml'], 'F07':['tests/evaluate.py']}[key]
            self.lr['checks'].append({'id': key, 'status': 'pass', 'summary': 'Synthetic current format implementation read.', 'evidence':refs, 'resolutions':[]})
        scan = fmt.inventory(self.root, self.lr)
        for obs in scan['semantic_observations']:
            row = next(r for r in self.lr['checks'] if r['id']==obs['owner'])
            refs = [ref for ref in obs['evidence'] if (self.root/ref).is_file()]
            row['resolutions'].append({'observation_id':obs['observation_id'],'summary':'Read the existing fixture implementation and verified equivalent paths and format.','evidence':refs or row['evidence']})
        self.counter = 0

    def assess(self, sr=None, lr=None):
        self.counter += 1
        return wrapper.assess(self.root, self.sr if sr is None else sr, self.lr if lr is None else lr, self.base / ('out-'+str(self.counter)))

    def row(self, value, key):
        return next(r for r in wrapper.all_rows(value) if r['id']==key)

    def make_waiver(self, key, reason):
        row=self.row(self.lr,key)
        value={'id':'w'+str(len(row['findings'])), 'kind':'legacy_gap','effect':'waived','summary':'Existing historical requirement gap only.',
            'evidence':row['evidence'], 'waiver_reason':reason,'waiver_basis':'Read original records and confirmed authorized migration-only gap.'}
        row['observed_status']='fail';row['findings'].append(value)
        return value

    def resolve_all(self, result, reasons=None):
        self.lr['standard_resolutions']=[]
        for record in result['standard_findings']:
            if record['derived']:
                continue
            entry={'standard_finding_id':record['id'],'summary':'Read original specific issue and existing evidence.',
                'evidence':record['evidence'] or ['task.toml']}
            reason=(reasons or {}).get(record['owner'])
            if reason and reason in record['allowed_waivers']:
                matches=[f for f in self.row(self.lr,record['owner'])['findings'] if f.get('waiver_reason')==reason]
                finding=matches[0] if matches else self.make_waiver(record['owner'],reason)
                entry.update(action='waive',legacy_finding_id=finding['id'])
            elif record['status']=='manual' and not record['protected']:
                entry['action']='resolved_by_existing_evidence'
            else:
                entry['action']='uphold'
            self.lr['standard_resolutions'].append(entry)

    def test_original_entrypoint_and_all_components_really_run(self):
        with patch.object(implementation_review,'main',wraps=implementation_review.main) as original:
            result=self.assess()
        self.assertEqual(original.call_count,1)
        self.assertTrue(result['standard_auditor_executed'])
        self.assertEqual(set(result['standard_components']), {'overview','fingerprint','harbor','trajectory','resources','content_gates','runtime','trajectory_schema'})
        self.assertEqual(result['standard_report']['summary']['decision'],'PASS')
        self.assertEqual(result['decision'],'PASS_WITH_WAIVERS', result)
        self.assertEqual(len(wrapper.all_rows(result)),32)
        self.assertEqual(result['nop_review']['status'],'pass')
        self.assertEqual(result['nop_review']['trials'][0]['details']['rewards'],{'reward':0.0})

    def test_missing_old_nop_original_fail_then_specific_waiver(self):
        import shutil
        shutil.rmtree(self.root/'run-a')
        for row in self.sr['harbor']['checks']:
            if row['id']=='H05':
                row.update(status='not_applicable',evidence=[],summary='No adopted job config.')
            if row['id']=='H06':
                row.update(status='fail',evidence=[],summary='Old phase has no NOP.')
        result=self.assess()
        self.assertEqual(result['standard_report']['harbor']['checks'][5]['status'],'fail')
        self.assertEqual(result['nop_review']['runtime_status'],'not_run')
        self.assertEqual(result['nop_review']['status'],'fail')
        self.resolve_all(result,{'H06':'legacy_nop_or_current_trial_gap'})
        result=self.assess()
        self.assertEqual(result['decision'],'PASS_WITH_WAIVERS',result)
        self.assertEqual(self.row(result,'H06')['status'],'pass_with_waivers')
        self.assertEqual(result['standard_report']['harbor']['checks'][5]['status'],'fail')

    def test_existing_bad_reward_is_not_missing_nop_even_manual_label(self):
        (self.root/'run-a/verifier/reward.txt').write_text('1')
        self.sr['harbor']['checks'][5].update(status='manual',summary='Historical NOP only.')
        result=self.assess()
        self.resolve_all(result,{'H06':'legacy_nop_or_current_trial_gap'})
        result=self.assess()
        self.assertEqual(result['decision'],'FAIL')
        self.assertEqual(result['nop_review']['status'],'fail')
        self.assertTrue(any(r['protected'] and r['source'].startswith('nop/') for r in result['standard_findings']))

    def test_existing_same_sandbox_fails_even_skipped_h06(self):
        p=self.root/'run-a/result.json';data=json.loads(p.read_text());data.update(agent_sandbox_id='same',verifier_sandbox_id='same');p.write_text(json.dumps(data))
        self.sr['harbor']['checks'][5].update(status='fail',evidence=[],summary='No current NOP.')
        result=self.assess();self.resolve_all(result,{'H06':'legacy_nop_or_current_trial_gap'});result=self.assess()
        self.assertEqual(result['decision'],'FAIL')
        self.assertIn('same sandbox',result['nop_review']['trials'][0]['summary'])

    def test_malformed_config_is_discovered_from_result_even_without_h06_refs(self):
        (self.root/'run-a/config.json').write_text('{bad')
        self.sr['harbor']['checks'][5].update(status='fail',evidence=[],summary='No current NOP.')
        result=self.assess()
        self.assertEqual(result['nop_review']['status'],'fail')
        self.assertEqual(len(result['nop_review']['trials']),1)
        self.assertTrue(result['nop_review']['trials'][0]['protected'])

    def test_explicit_old_failed_nop_and_existing_current_fix_can_be_waived(self):
        (self.root/'run-a/verifier/reward.txt').write_text('1')
        self.sr['harbor']['checks'][5].update(status='manual',summary='Documented historical failed Trial; current fixed package not rerun.')
        self.sr['checks'][16].update(remediation='Retain old failed NOP and review current static repair; no invented successful run.',acceptance_evidence='Existing old/current task mapping and current source fix.')
        (self.root/'expert_evidence/nop_migration.md').write_text('run-a belongs to the old task version with a reward export defect. The present tests/test.sh fixes export; current version not run. Keep the old failure.')
        result=self.assess();self.make_waiver('H06','legacy_nop_or_current_trial_gap');self.resolve_all(result,{'H06':'legacy_nop_or_current_trial_gap'})
        for item in self.lr['standard_resolutions']:
            rec=next(r for r in result['standard_findings'] if r['id']==item['standard_finding_id'])
            if rec.get('historical_failed_trial_review_allowed'):
                finding=next(f for f in self.row(self.lr,'H06')['findings'] if f['waiver_reason']=='legacy_nop_or_current_trial_gap')
                item.update(action='waive',legacy_finding_id=finding['id'],historical_trial_review={
                    'trial_dir':'run-a','current_version_not_run':True,'historical_version_basis':'Read the existing old/current mapping; old run-a retains its failed export.',
                    'historical_version_evidence':['expert_evidence/nop_migration.md'], 'current_fix_summary':'The current tests/test.sh export is fixed; no new run was performed.',
                    'current_fix_evidence':['tests/test.sh','expert_evidence/nop_migration.md']})
        result=self.assess()
        self.assertEqual(result['decision'],'PASS_WITH_WAIVERS',result)
        self.assertEqual(result['nop_review']['status'],'fail')
        rec=next(r for r in result['standard_findings'] if r.get('historical_trial_review'))
        self.assertEqual(rec['original_trial_status'],'fail')
        self.assertEqual(rec['current_runtime_status'],'not_run')

    def test_original_resource_limit_cannot_be_handwritten_legacy_pass(self):
        self.sr['resource_review']['runs'][0]['score_seconds']=8000
        result=self.assess();self.resolve_all(result,{'QA15':'legacy_target_resource_evidence_gap'});result=self.assess()
        self.assertEqual(result['decision'],'FAIL')
        self.assertTrue(any(r['source'].startswith('resources/problems/') and r['protected'] for r in result['standard_findings']))

    def test_original_invalid_formal_result_cannot_be_changed_in_legacy_sheet(self):
        self.sr['overview']['baseline_reference']['paired_runs'][0]['reference_valid']=False
        result=self.assess();self.resolve_all(result,{'G03':'legacy_new_validation_dependency'});result=self.assess()
        self.assertEqual(result['decision'],'FAIL')
        self.assertTrue(any(r['id']=='formal-overview-conflict' for r in result['standard_findings']))
        self.assertEqual(self.row(result,'G03')['status'],'fail')

    def test_native_exception_does_not_skip_other_components_or_pass(self):
        self.sr['harbor']['path_contract']={}
        result=self.assess()
        self.assertTrue(result['standard_report'].get('inspection_error'))
        self.assertIn('resources',result['standard_components'])
        self.assertIn('runtime',result['standard_components'])
        self.assertIn('trajectory',result['standard_components'])
        self.assertEqual(result['nop_review']['status'],'pass')
        self.assertNotEqual(result['decision'],'PASS_WITH_WAIVERS')

    def test_two_prompt_substantive_difference_protection_is_retained(self):
        c=self.lr['trajectory_content_review']['comparability'];c['assessment']='substantive_difference'
        c['differences']=[{'dimension':'feedback','impact':'substantive','summary':'Second run receives failing-case feedback absent from first run.','evidence':['trajectory_a.json','trajectory_b.json']}]
        result=self.assess()
        self.assertEqual(result['decision'],'FAIL')
        self.assertEqual(self.row(result,'QA18')['status'],'fail')

    def test_large_legal_array_is_a_reader_schema_gap_not_missing_trajectory(self):
        original=json.loads((self.root/'trajectory_a.json').read_text())['rounds'][0]
        (self.root/'trajectory_a.json').write_text(json.dumps([dict(original, round=i+1, padding='x'*850) for i in range(5000)]))
        result=self.assess()
        issues=[r for r in result['standard_findings'] if r['source'].startswith('trajectory_schema/0/')]
        self.assertTrue(issues)
        self.assertFalse(any(r['protected'] for r in issues))
        self.resolve_all(result,{'QA18':'legacy_trajectory_schema_gap','QA21':'legacy_task_binding_migration'})
        result=self.assess()
        self.assertEqual(result['decision'],'PASS_WITH_WAIVERS',result)
        self.assertTrue(result['review_completed'])

    def test_large_explicit_locator_needs_exact_reader_resolution_and_full_retry(self):
        (self.root/'expert_evidence/large.json').write_text(json.dumps({'text':'x'*(5*1024*1024)}))
        self.sr['overview']['optimization_surface']['evidence'].append('expert_evidence/large.json#text')
        result=self.assess()
        self.assertTrue(result['standard_report'].get('inspection_error'))
        self.assertEqual(result['standard_evaluation_report']['summary']['decision'],'PASS')
        self.assertEqual(len(result['standard_components']),8)
        self.assertNotEqual(result['decision'],'PASS_WITH_WAIVERS')
        self.lr['reader_resolutions']=[]
        for source, message in [('main',result['standard_report']['inspection_error'])] + [('component:'+r['component'],r['message']) for r in result['standard_component_errors']]:
            self.lr['reader_resolutions'].append({'source':source,'message':message,'summary':'Reviewed the exact original large file contents; this is only the explicit-locator reader budget.','content_review_complete':True,'evidence':['expert_evidence/large.json']})
        result=self.assess()
        self.assertEqual(result['decision'],'PASS_WITH_WAIVERS',result)
        self.assertTrue(result['reader_error_resolutions'])

    def test_provided_unreviewed_session_cannot_be_waived_as_missing_runtime_proof(self):
        (self.root/'expert_evidence/session_extra.jsonl').write_text('{"type":"function_call","name":"exec_command","arguments":"cat /tests/hidden_assets/key"}\n')
        result=self.assess()
        self.resolve_all(result,{'QA18':'legacy_runtime_proof_gap'})
        result=self.assess()
        self.assertEqual(result['decision'],'ERROR',result)
        self.assertTrue(any(r['code']=='STANDARD_COMPONENT_ERROR' for r in result['input_and_review_errors']))

    def test_no_internal_worksheets_is_not_a_task_rejection_or_pass(self):
        out=self.base/'unreviewed'
        result=wrapper.assess(self.root,None,None,out)
        self.assertEqual(result['decision'],'ERROR')
        self.assertFalse(result['is_task_rejection'])
        wrapper.write_report(result,out)
        self.assertTrue((out/'standard_review_template.json').is_file())
        self.assertTrue((out/'review_template.json').is_file())
        self.assertTrue((out/'standard/report.json').is_file())

    def test_empty_legacy_pass_cannot_hide_native_missing_nop(self):
        import shutil
        shutil.rmtree(self.root/'run-a')
        self.sr['harbor']['checks'][5].update(status='fail',evidence=[],summary='Missing old NOP.')
        self.sr['harbor']['checks'][4].update(status='not_applicable',evidence=[],summary='No job config.')
        result=self.assess()
        self.assertEqual(result['decision'],'FAIL')
        self.assertEqual(self.row(result,'H06')['status'],'fail')


if __name__=='__main__':
    unittest.main()
