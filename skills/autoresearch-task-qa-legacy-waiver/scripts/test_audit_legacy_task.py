"""Complete content review fixtures; no submitted task or model is executed."""
import copy
import json
from pathlib import Path
import unittest
import zipfile

import audit_legacy_task as audit
import test_audit_format_repair as fixtures


class FullLegacyReviewTests(unittest.TestCase):
    tearDown = fixtures.FormatRepairTests.tearDown

    def setUp(self):
        fixtures.FormatRepairTests.setUp(self)
        (self.root / 'expert_evidence/methods.md').write_text('Baseline is a healthy decision stump; Reference composes a depth-two decision tree. Both share data and evaluation budget.\n')
        (self.root / 'expert_evidence/formal_results.json').write_text(json.dumps([
            {'seed': seed, 'baseline': b, 'reference': r, 'baseline_valid': True, 'reference_valid': True}
            for seed, b, r in [(1, 9.9, 7.9), (2, 10, 8), (3, 10.1, 8.1)]]))
        (self.root / 'expert_evidence/trajectory_a.json').write_text('[{"round":1,"method_summary":"stump"},{"round":2,"method_summary":"branch composition","time":null,"status":"infra_invalid"}]')
        (self.root / 'expert_evidence/trajectory_b.jsonl').write_text('{"round":1,"method_summary":"robust split"}\n{"round":2,"method_summary":"two-level composition","status":"old_extension"}\n')

    def item(self, check_id, evidence=None):
        return {'id': check_id, 'review_complete': True, 'observed_status': 'pass',
            'summary': check_id + ': read the existing implementation and evidence and checked this specific requirement.',
            'evidence': evidence or ['workspace/harbor_task/task.toml'], 'findings': []}

    def review(self):
        result = fixtures.FormatRepairTests.review(self, resolve=True)
        result['stage'] = audit.STAGE
        methods, formal = 'expert_evidence/methods.md', 'expert_evidence/formal_results.json'
        result['overview'] = {
            'optimization_surface': {'summary': 'Composable branching algorithms are open; numeric-only tuning is not the entire solution surface.',
                'modifiable': ['candidate tree composition and search'], 'fixed': ['dataset, author metric, budget'],
                'metric_and_gate': 'Minimize held-out loss after the author quality gate.', 'evidence': [methods]},
            'baseline_reference': {'baseline_method': 'A healthy decision stump with the documented training budget.',
                'reference_method': 'A depth-two tree composes two decision rules.', 'metric': 'held-out loss', 'direction': 'minimize',
                'paired_runs': json.loads((self.root / formal).read_text()),
                'baseline_mean': 10, 'reference_mean': 8, 'baseline_sample_std': 0.1, 'reference_sample_std': 0.1,
                'improvement_summary': 'The formal original result improves loss by two units.',
                'quality_gate_summary': 'All original formal paired results are valid under the same author protocol.', 'evidence': [formal, methods]}}
        result['content_gates'] = {'schema_version': 1, 'checks': [self.item(key, [methods, formal]) for key in audit.content_gates.IDS]}
        result['content_gates']['checks'][2]['assessment'] = {'direction': 'minimize', 'evaluation_mode': 'stochastic',
            'formal_seeds': [1, 2, 3], 'declared_run_count': 3, 'same_protocol': True, 'quality_valid': True,
            'upper_bound': 5, 'threshold_basis': 'Original 3σ_B and normalized [0.15,0.8] rule.'}
        result['content_gates']['checks'][1]['dimensions'] = {key: {'summary': label + ': original method and budget were inspected, with no demonstrated weak-control issue.', 'evidence': [methods]}
            for key, label in audit.G02_DIMENSIONS.items()}
        result['items21'] = [self.item(key) for key in audit.QA]
        result['harbor6'] = [self.item(key) for key in audit.H]
        trajectories = []
        for key, name, path in [('T01', 'Agent A', 'expert_evidence/trajectory_a.json'), ('T02', 'Agent B', 'expert_evidence/trajectory_b.jsonl')]:
            trajectories.append({**self.item(key, [path, methods]), 'name': name, 'source_path': path, 'reviewed_sources': [path, methods],
                'method_summary': 'Read the existing stump-to-composite-tree methods.', 'iteration_summary': 'The original rounds change model structure and evaluate the result; this is a content review, not a duration recalculation.',
                'final_result': 'The composed tree is the best recorded candidate in this existing run.',
                'score_use_conclusion': 'Agent candidate results are described separately from the independent author formal paired B/R.'})
        result['trajectory_content_review'] = {'trajectories': trajectories, 'comparability': {
            'review_complete': True, 'assessment': 'same_conditions',
            'summary': 'Read both original runs: same task, Prompt, Dev, failure feedback, access restrictions and resource budget; independent outputs are reviewed separately.',
            'evidence': [row['source_path'] for row in trajectories] + [methods],
            'compared_dimensions': sorted(audit.COMPARISON_DIMENSIONS), 'differences': []}}
        return result

    def row(self, review, key):
        for values in (review.get('items21', []), review.get('harbor6', []), review.get('content_gates', {}).get('checks', []), review.get('trajectory_content_review', {}).get('trajectories', [])):
            for row in values:
                if row['id'] == key:
                    return row
        raise KeyError(key)

    def finding(self, row, *, reason=None, kind='legacy_gap', effect='waived', summary='Specific historical requirement changed; the actual existing evidence was read.', keep_pass=False):
        value = {'id': 'finding_' + str(len(row['findings'])), 'kind': kind, 'effect': effect, 'summary': summary,
            'evidence': row['evidence'], 'remediation': 'Fix the demonstrated substantive issue using the existing protocol.',
            'acceptance_evidence': 'Correct source and existing trustworthy scientific evidence.'}
        if effect == 'waived':
            value.update(waiver_reason=reason, waiver_basis='The delivered original sources show this is only the authorized migration gap; no new run is requested.')
            if reason == 'historical_agent_runtime_finding':
                value.update(classification='cheating', certainty='confirmed', score_effect='invalid',
                    score_effect_basis='Existing recorded action and returned private result contaminate this Agent candidate only.')
        row['findings'].append(value)
        if not keep_pass:
            row['observed_status'] = 'manual' if kind == 'legacy_gap' else 'fail'
        return value

    def assess(self, review=None):
        return audit.assess(self.root, self.review() if review is None else review)

    def test_complete_science_and_all_items_are_required_and_reported(self):
        result = self.assess()
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertTrue(result['review_completed'])
        self.assertEqual(result['reviewed_counts'], {'gates': 3, 'qa': 21, 'harbor': 6, 'trajectories': 2})
        self.assertEqual(result['stage'], 'legacy_task_review')
        self.assertEqual(result['content_gates']['checks'][2]['computed']['normalized_score'], 0.4)
        text = audit.render(result)
        for check_id in [*audit.QA, *audit.H, *audit.T, *audit.content_gates.IDS]:
            self.assertIn('### ' + check_id + ' ', text)
        self.assertIn('A healthy decision stump', text)
        self.assertIn('stump-to-composite-tree', text)

    def comparison(self, review):
        return review['trajectory_content_review']['comparability']

    def comparison_difference(self, review, dimension, impact, summary):
        value = {'dimension': dimension, 'impact': impact, 'summary': summary,
            'evidence': self.comparison(review)['evidence'][:2]}
        self.comparison(review)['differences'].append(value)
        return value

    def test_substantive_failure_feedback_and_ipc_restrictions_override_qa18_pass(self):
        review = self.review()
        comparison = self.comparison(review)
        comparison.update(assessment='substantive_difference', summary='Agent A ran the old task; Agent B received additional error feedback and a new IPC/read-only restriction after instruction.md was edited.')
        self.comparison_difference(review, 'feedback', 'substantive', 'A gets only a scalar score; B gets the failing case and exception details, changing the information available for optimization.')
        self.comparison_difference(review, 'constraints', 'substantive', 'B is subject to an IPC prohibition and read-only boundary that were absent in the original A instruction.')
        before = copy.deepcopy(review)
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL', result)
        self.assertTrue(result['review_completed'])
        qa18 = self.row(result, 'QA18')
        self.assertEqual(qa18['original_observed_status'], 'pass')
        self.assertEqual(qa18['status'], 'fail')
        self.assertEqual(qa18['findings'][-1]['id'], 'automatic_two_trajectory_comparability')
        self.assertEqual(qa18['findings'][-1]['final_effect'], 'blocking')
        self.assertEqual(self.row(result, 'T01')['status'], 'pass')
        self.assertEqual(self.row(result, 'T02')['status'], 'pass')
        self.assertEqual(self.comparison(result)['comparison_validity'], 'not_comparable')
        self.assertFalse(self.comparison(result)['individual_trajectory_validity_changed'])
        self.assertEqual(review, before)
        text = audit.render(result, expert=True)
        self.assertIn('failing case and exception', text)
        self.assertIn('IPC prohibition', text)
        self.assertIn('修改当前instruction.md不能追溯统一原两轨', text)
        self.assertIn('## 两轨实际条件对比', text)

    def test_substantive_comparison_cannot_be_washed_by_same_row_schema_waiver(self):
        review = self.review()
        self.finding(self.row(review, 'QA18'), reason='legacy_trajectory_schema_gap')
        self.comparison(review)['assessment'] = 'substantive_difference'
        self.comparison_difference(review, 'prompt', 'substantive', 'The newer Prompt permits a new tool and reveals per-example failure feedback.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertEqual([row['final_effect'] for row in self.row(result, 'QA18')['findings']], ['waived', 'blocking'])

    def test_editorial_prompt_change_is_explained_without_forcing_failure(self):
        review = self.review()
        self.comparison(review)['assessment'] = 'editorial_only'
        self.comparison_difference(review, 'prompt', 'editorial_only', 'Only punctuation and a spelling mistake changed; task objective, inputs, scoring feedback and restrictions remain identical.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertEqual(self.comparison(result)['comparison_validity'], 'comparable')
        self.assertEqual(self.row(result, 'QA18')['status'], 'pass')

    def test_historical_hash_gap_does_not_require_new_snapshot_or_rerun(self):
        review = self.review()
        self.comparison(review).update(assessment='historical_evidence_gap', summary='Both original runs were read; the old package has no task hash, so exact historical binding cannot be proved. No actual semantic difference was established.')
        self.comparison_difference(review, 'task', 'legacy_format_or_resource', 'The migration changes package paths and schema; the original run did not record the newly introduced package hash.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertTrue(result['review_completed'])
        self.assertEqual(self.comparison(result)['comparison_validity'], 'unverified')
        self.assertEqual(self.row(result, 'QA18')['status'], 'pass_with_waivers')
        self.assertEqual(self.row(result, 'QA18')['findings'][-1]['waiver_reason'], 'legacy_runtime_proof_gap')

    def test_historical_resource_migration_is_not_automatically_substantive(self):
        review = self.review()
        self.comparison(review).update(assessment='legacy_resource_difference', summary='Original runs used historical 1472/1536 MiB settings; the final candidate already has a common-condition record. We preserve the known exploration resource difference rather than calling it identical or unproved.')
        self.comparison_difference(review, 'resources', 'legacy_format_or_resource', 'The original exploration memory declarations differ and are retained as original hardware records; no new hardware run is required for this migration.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertEqual(self.row(result, 'T01')['status'], 'pass')
        self.assertEqual(self.comparison(result)['comparison_validity'], 'comparable_with_legacy_waivers')
        self.assertEqual(self.row(result, 'QA18')['findings'][-1]['waiver_reason'], 'legacy_hardware_record_difference')

    def test_editorial_change_can_coexist_with_authorized_known_resource_difference(self):
        review = self.review()
        self.comparison(review)['assessment'] = 'editorial_only'
        self.comparison_difference(review, 'prompt', 'editorial_only', 'Only a typo was corrected; operative task instructions are semantically equivalent.')
        self.comparison_difference(review, 'resources', 'legacy_format_or_resource', 'Original exploration memory differs; final validation already uses the same 1536 MiB budget.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertEqual(self.comparison(result)['comparison_validity'], 'comparable_with_legacy_waivers')

    def test_legacy_resource_assessment_does_not_hide_non_resource_change(self):
        review = self.review()
        self.comparison(review)['assessment'] = 'legacy_resource_difference'
        self.comparison_difference(review, 'feedback', 'legacy_format_or_resource', 'Failure feedback source differs; this needs actual semantic classification, not a resource waiver.')
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_missing_two_run_comparison_is_internal_unfinished_work(self):
        review = self.review()
        del review['trajectory_content_review']['comparability']
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR', result)
        self.assertFalse(result['review_completed'])
        self.assertFalse(result['is_task_rejection'])
        self.assertEqual(self.row(result, 'QA18')['status'], 'review_not_finished')
        self.assertTrue(any(row['code'] == 'REVIEW_COMPARISON_NOT_FINISHED' for row in result['input_and_review_errors']))

    def test_malformed_internal_comparison_still_emits_an_error_report(self):
        review = self.review()
        self.comparison(review).update(summary=None, compared_dimensions=None, evidence=None, differences=None)
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR')
        self.assertFalse(result['is_task_rejection'])
        self.assertIn('质检流程需继续完成', audit.render(result))

    def test_partial_dimension_comparison_cannot_claim_full_review(self):
        review = self.review()
        self.comparison(review)['compared_dimensions'].remove('feedback')
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_comparison_must_reference_both_actual_trajectory_sources(self):
        review = self.review()
        self.comparison(review)['evidence'] = ['expert_evidence/methods.md']
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_legacy_identical_prompt_false_cannot_be_ignored_as_same_conditions(self):
        review = self.review()
        review['task_version_comparison'] = {'identical_prompt': False}
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR', result)
        self.assertFalse(result['is_task_rejection'])
        self.assertTrue(any(row['code'] == 'REVIEW_COMPARISON_INCONSISTENT' for row in result['input_and_review_errors']))

    def test_exact_existing_source_marker_is_crosschecked_in_array_without_keyword_inference(self):
        review = self.review()
        path = self.root / 'expert_evidence/version_analysis.json'
        path.write_text(json.dumps([{'task_version_comparison': {'identical_prompt': False}, 'explanation': 'Original tasks differ; semantics must actually be read.'}]))
        self.comparison(review)['evidence'].append('expert_evidence/version_analysis.json')
        self.assertEqual(self.assess(review)['decision'], 'ERROR')
        self.comparison(review)['assessment'] = 'editorial_only'
        self.comparison_difference(review, 'prompt', 'editorial_only', 'The exact existing false marker corresponds only to an original punctuation change; all operative task conditions were compared.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertTrue(self.comparison(result)['existing_prompt_difference_signals'])

    def test_existing_source_jsonl_false_marker_requires_explanation(self):
        review = self.review()
        path = self.root / 'expert_evidence/version_analysis.jsonl'
        path.write_text('{"event":"comparison","task_version_comparison":{"identical_prompt":false}}\n')
        self.comparison(review)['evidence'].append('expert_evidence/version_analysis.jsonl')
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_false_marker_in_other_already_reviewed_sources_cannot_be_ignored(self):
        for owner in ('QA18', 'QA21', 'T01'):
            with self.subTest(owner=owner):
                review = self.review()
                path = self.root / 'expert_evidence/version_analysis.json'
                path.write_text('{"task_version_comparison":{"identical_prompt":false}}')
                row = self.row(review, owner)
                row['evidence' if owner.startswith('QA') else 'reviewed_sources'].append('expert_evidence/version_analysis.json')
                self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_bom_json_and_mixed_jsonl_do_not_hide_existing_false_marker(self):
        for suffix, source in (('.json', '\ufeff{"task_version_comparison":{"identical_prompt":false}}'),
                ('.jsonl', 'an old non-JSON log line\n{"task_version_comparison":{"identical_prompt":false}}\n')):
            with self.subTest(suffix=suffix):
                review = self.review()
                path = self.root / ('expert_evidence/run_summary' + suffix)
                path.write_text(source)
                self.row(review, 'QA21')['evidence'].append(path.relative_to(self.root).as_posix())
                self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_source_keywords_do_not_automatically_judge_semantic_difference(self):
        review = self.review()
        path = self.root / 'expert_evidence/source_notes.json'
        path.write_text(json.dumps({'instruction_note': 'Do not confuse a different Prompt hash, IPC documentation or failure feedback wording with a substantive condition change. These raw words alone do not establish a defect.'}))
        self.comparison(review)['evidence'].append('expert_evidence/source_notes.json')
        self.assertEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_substantive_detail_overrides_editorial_or_historical_total(self):
        for assessment in ('same_conditions', 'editorial_only', 'historical_evidence_gap'):
            with self.subTest(assessment=assessment):
                review = self.review()
                self.comparison(review)['assessment'] = assessment
                self.comparison_difference(review, 'dev', 'substantive', 'The second run receives a different Dev dataset and scoring feedback.')
                result = self.assess(review)
                self.assertEqual(result['decision'], 'FAIL', result)
                self.assertEqual(self.row(result, 'QA18')['status'], 'fail')
                self.assertFalse(result['review_completed'])

    def test_substantive_total_without_finished_difference_analysis_still_cannot_pass(self):
        review = self.review()
        self.comparison(review)['assessment'] = 'substantive_difference'
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertFalse(result['review_completed'])
        self.assertEqual(self.row(result, 'QA18')['status'], 'fail')

    def test_known_substantive_fact_is_retained_when_its_review_evidence_field_needs_repair(self):
        review = self.review()
        self.comparison(review)['assessment'] = 'substantive_difference'
        difference = self.comparison_difference(review, 'constraints', 'substantive', 'The original tasks impose genuinely different IPC and write permissions.')
        difference['evidence'] = None
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertFalse(result['review_completed'])
        self.assertEqual(self.row(result, 'QA18')['status'], 'fail')
        self.assertIn('两轨实际条件对比', audit.render(result))

    def test_new_template_explains_comparison_is_reviewer_work_not_expert_schema(self):
        result = audit.assess(self.root)
        value = result['review_template']['trajectory_content_review']['comparability']
        self.assertFalse(value['review_complete'])
        self.assertEqual(value['differences'], [])
        self.assertIn('质检员内部底稿', result['review_template']['reviewer_note'])

    def test_old_format_only_review_cannot_claim_full_pass(self):
        review = fixtures.FormatRepairTests.review(self, resolve=True)
        review['stage'] = audit.STAGE
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR', result)
        self.assertFalse(result['is_task_rejection'])
        self.assertEqual(result['format_precheck']['decision'], 'PASS_WITH_WAIVERS')

    def test_missing_any_mandatory_section_cannot_pass(self):
        for field in ('overview', 'content_gates', 'items21', 'harbor6', 'trajectory_content_review'):
            with self.subTest(field=field):
                review = self.review()
                del review[field]
                self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_unread_qa_is_internal_error_not_expert_rerun(self):
        review = self.review()
        self.row(review, 'QA18')['review_complete'] = False
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR')
        self.assertFalse(result['is_task_rejection'])
        self.assertIn('不是专家新增文件或补跑要求', audit.render(result))

    def test_mixed_finding_waives_only_migration_gap(self):
        review = self.review()
        row = self.row(review, 'QA15')
        self.finding(row, reason='legacy_target_resource_evidence_gap', summary='No new target resource measurement after format migration.')
        self.finding(row, kind='substantive', effect='unwaived', summary='An existing actual target configuration exceeds the accepted CPU resource limit.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL', result)
        actual = self.row(result, 'QA15')
        self.assertEqual(actual['status'], 'fail')
        self.assertEqual([f['final_effect'] for f in actual['findings']], ['waived', 'blocking'])

    def test_no_nop_no_hash_two_field_trajectories_keep_complete_review(self):
        review = self.review()
        for key, reason in [('H06', 'legacy_nop_or_current_trial_gap'), ('QA21', 'legacy_task_binding_migration'), ('QA18', 'legacy_trajectory_schema_gap')]:
            self.finding(self.row(review, key), reason=reason)
        qa17 = self.row(review, 'QA17')
        qa17.update(observed_status='manual', derived_from=list(audit.H))
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertEqual(self.row(result, 'QA17')['status'], 'pass_with_waivers')
        self.assertEqual(self.row(result, 'H06')['original_observed_status'], 'manual')

    def test_observed_pass_can_have_a_separate_waived_gap(self):
        review = self.review()
        self.finding(self.row(review, 'QA18'), reason='legacy_trajectory_schema_gap', keep_pass=True)
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(self.row(result, 'QA18')['observed_status'], 'pass')
        self.assertEqual(self.row(result, 'QA18')['status'], 'pass_with_waivers')

    def test_unknown_reason_or_wrong_scope_never_passes(self):
        for reason in ('not_authorized', 'legacy_nop_or_current_trial_gap'):
            review = self.review()
            self.finding(self.row(review, 'QA01'), reason=reason)
            self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_true_gate_failure_is_not_waivable(self):
        review = self.review()
        self.finding(self.row(review, 'G02'), reason='legacy_hardware_record_difference', kind='substantive', summary='Baseline is deliberately undertrained under the same original budget.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL', result)

    def test_g01_pure_numeric_search_is_a_real_failure(self):
        review = self.review()
        self.finding(self.row(review, 'G01'), kind='substantive', effect='unwaived', summary='The task only exposes a fixed small numeric hyperparameter search.')
        self.assertEqual(self.assess(review)['decision'], 'FAIL')

    def test_g03_threshold_failure_survives_legacy_validation_waiver(self):
        review = self.review()
        for pair in review['overview']['baseline_reference']['paired_runs']:
            pair['reference'] = pair['baseline'] - 0.1
        review['overview']['baseline_reference']['reference_mean'] = 9.9
        self.finding(self.row(review, 'G03'), reason='legacy_new_validation_dependency')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL', result)
        g03 = self.row(result, 'G03')
        self.assertEqual(g03['numerical_assessment']['status'], 'fail')
        self.assertEqual(g03['status'], 'fail')
        self.assertTrue(any(f['kind'] == 'substantive' for f in g03['findings']))

    def test_formal_quality_invalid_is_not_an_agent_behavior_waiver(self):
        review = self.review()
        review['overview']['baseline_reference']['paired_runs'][0]['reference_valid'] = False
        finding = self.finding(self.row(review, 'QA18'), reason='historical_agent_runtime_finding')
        finding.update(affected_score_status='invalid', formal_br_affected=False)
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertEqual(self.row(result, 'QA18')['status'], 'pass_with_waivers')
        self.assertEqual(self.row(result, 'G03')['status'], 'fail')

    def test_agent_invalid_scores_are_preserved_but_do_not_blame_independent_author_br(self):
        review = self.review()
        finding = self.finding(self.row(review, 'T01'), reason='historical_agent_runtime_finding', summary='Historical Agent candidate read private answers; affected candidate score is invalid and is not a formal author B/R result.')
        finding.update(affected_score_status='invalid', formal_br_affected=False)
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertEqual(self.row(result, 'T01')['findings'][0]['affected_score_status'], 'invalid')
        self.assertIn('不作为作者正式 B/R 正证', audit.render(result))

    def test_affected_author_formal_results_cannot_use_runtime_waiver(self):
        review = self.review()
        finding = self.finding(self.row(review, 'QA18'), reason='historical_agent_runtime_finding')
        finding.update(affected_score_status='invalid', formal_br_affected=True)
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_policy_only_historical_difference_does_not_force_score_invalid(self):
        review = self.review()
        finding = self.finding(self.row(review, 'T01'), reason='historical_agent_runtime_finding', summary='Only the historical working-directory policy differed; no demonstrated private-answer contamination.')
        finding.update(classification='policy_only', certainty='confirmed', score_effect='none', affected_score_status='valid', formal_br_affected=False,
            score_effect_basis='Existing original task permitted this environment; the existing logs show no private content obtained and no forged reward.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        kept = self.row(result, 'T01')['findings'][0]
        self.assertEqual(kept['affected_score_status'], 'valid')
        self.assertEqual(kept['score_effect'], 'none')

    def test_confirmed_private_contamination_cannot_be_no_score_effect(self):
        review = self.review()
        finding = self.finding(self.row(review, 'QA18'), reason='historical_agent_runtime_finding')
        finding.update(classification='leakage', certainty='confirmed', score_effect='none', affected_score_status='valid', formal_br_affected=False)
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_suspected_attempt_is_not_automatically_confirmed_leakage(self):
        review = self.review()
        finding = self.finding(self.row(review, 'QA18'), reason='historical_agent_runtime_finding', summary='A blocked private-file access attempt appears in the existing log; no private response was obtained.')
        finding.update(classification='suspicious', certainty='suspected', score_effect='none', affected_score_status='valid', formal_br_affected=False,
            score_effect_basis='The available action and outcome show a rejected attempt only, with no evidence of score contamination.')
        self.assertEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_format_automatic_failure_survives_every_handwritten_pass(self):
        (self.task / 'environment/Dockerfile').write_text('FROM python:3.11\nCOPY missing.txt /workspace/missing.txt\n')
        result = self.assess()
        self.assertEqual(result['decision'], 'FAIL')
        self.assertTrue(result['format_precheck']['current_findings'])
        self.assertEqual(self.row(result, 'H03')['status'], 'fail')
        self.assertEqual(self.row(result, 'QA17')['status'], 'fail')

    def test_reviewed_format_semantic_failure_is_also_shown_under_related_harbor_check(self):
        review = self.review()
        f03 = next(row for row in review['checks'] if row['id'] == 'F03')
        f03.update(status='fail', summary='Current grader entry exits successfully without writing author-owned reward.',
            remediation='Write the fixed reward result from the author evaluator.', acceptance_evidence='The current entry and reward path agree.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertEqual(self.row(result, 'H04')['status'], 'fail')
        self.assertEqual(self.row(result, 'QA17')['status'], 'fail')
        self.assertTrue(any(item['code'] == 'SEMANTIC_REVIEW_FAILURE' for item in self.row(result, 'H04')['format_root_causes']))

    def test_missing_instruction_is_h01_fault_without_unrelated_h02_failure(self):
        (self.task / 'instruction.md').unlink()
        result = self.assess()
        self.assertEqual(result['decision'], 'FAIL')
        self.assertEqual(self.row(result, 'H01')['status'], 'fail')
        self.assertEqual(self.row(result, 'H02')['status'], 'pass')

    def test_unmapped_f01_semantic_failure_is_not_scattered_across_harbor_items(self):
        review = self.review()
        f01 = next(row for row in review['checks'] if row['id'] == 'F01')
        f01.update(status='fail', summary='A reviewed current delivery interface has a demonstrated defect requiring the described repair.',
            remediation='Repair the specific current interface.', acceptance_evidence='The corrected source contract is consistent.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertEqual(self.row(result, 'H01')['status'], 'pass')
        self.assertEqual(self.row(result, 'H02')['status'], 'pass')
        self.assertIn(f01['summary'], audit.render(result))

    def test_known_true_failure_takes_priority_over_unfinished_review(self):
        review = self.review()
        del review['trajectory_content_review']
        self.finding(self.row(review, 'QA06'), kind='substantive', effect='unwaived', summary='Author grader accepts an arbitrary reward from the candidate.')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertFalse(result['review_completed'])

    def test_null_time_extended_status_and_large_array_are_valid_carriers(self):
        path = self.root / 'expert_evidence/trajectory_a.json'
        path.write_text('[{"round":1,"method_summary":"open algorithm","time":null,"status":"infra_invalid","log":"' + 'x' * (5 * 1024 * 1024) + '"}]')
        self.assertEqual(self.assess()['decision'], 'PASS_WITH_WAIVERS')

    def test_supplied_trajectory_content_cannot_be_skipped_as_schema_waiver(self):
        review = self.review()
        row = self.row(review, 'T01')
        self.finding(row, reason='legacy_trajectory_schema_gap')
        row['review_complete'] = False
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_trajectory_main_file_must_actually_be_in_reviewed_sources(self):
        review = self.review()
        self.row(review, 'T01')['reviewed_sources'] = ['expert_evidence/methods.md']
        self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_shared_merged_log_requires_two_actual_run_locators(self):
        review = self.review()
        a, b = review['trajectory_content_review']['trajectories']
        b.update(source_path=a['source_path'], reviewed_sources=a['reviewed_sources'])
        self.assertEqual(self.assess(review)['decision'], 'ERROR')
        a['run_locator'], b['run_locator'] = 'run=A', 'run=B'
        self.assertEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_missing_scientific_work_is_not_silently_passed(self):
        review = self.review()
        del self.row(review, 'G03')['assessment']['same_protocol']
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR')
        self.assertIn('从原材料核清', audit.render(result))

    def test_research_gates_and_two_trajectories_cannot_be_not_applicable(self):
        for key in ('G01', 'G02', 'G03', 'T01', 'T02'):
            review = self.review()
            self.row(review, key).update(observed_status='not_applicable', not_applicable_basis='Blanket exemption attempt.')
            self.assertNotEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_pass_expert_report_contains_every_reviewed_item_and_sources(self):
        result = self.assess()
        out = self.base / 'reports'
        audit.write_report(result, out)
        text = (out / 'return_to_expert.txt').read_text()
        self.assertGreater(len(text.splitlines()), 100)
        for key in [*audit.QA, *audit.H, *audit.T, *audit.content_gates.IDS]:
            self.assertIn('### ' + key + ' ', text)
        self.assertIn('depth-two tree', text)
        self.assertIn('expert_evidence/trajectory_a.json', text)
        self.assertIn('仅格式前检子报告', (out / 'format_report.md').read_text())
        self.assertEqual(json.loads((out / 'report.json').read_text())['stage'], 'legacy_task_review')

    def test_total_report_has_one_full_review_scope_without_old_format_history_exclusions(self):
        result = self.assess()
        text = audit.render(result)
        self.assertEqual(text.count('本轮结论：'), 1)
        self.assertIn('阶段：legacy_task_review', text)
        self.assertIn('format_decision：PASS_WITH_WAIVERS', text)
        self.assertNotIn('阶段：format_repair', text)
        self.assertNotIn('本轮不复查的历史事项', text)
        self.assertNotIn('历史轨迹八字段、状态、时间及行为重审', text)
        self.assertNotIn('本轮不重算历史资源或成绩', text)
        self.assertIn('已有原硬件结果本轮复核', text)
        self.assertIn('## 两轨已有内容', text)
        self.assertIn('## 平台后续事项', text)
        for key in audit.format_review.CHECKS:
            self.assertIn('- ' + key + ' [', text)

    def test_total_report_keeps_format_fail_evidence_and_repair_without_nested_verdict(self):
        (self.task / 'environment/Dockerfile').write_text('FROM python:3.11\nCOPY missing-current-file /workspace/missing\n')
        result = self.assess()
        text = audit.render(result)
        self.assertEqual(text.count('本轮结论：'), 1)
        self.assertIn('format_decision：FAIL', text)
        self.assertIn('missing-current-file', text)
        self.assertIn('environment/Dockerfile', text)
        self.assertIn('修改方向：', text)

    def test_inputs_and_original_format_checker_are_never_modified(self):
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        source = Path(audit.format_review.__file__)
        original = source.read_bytes()
        review = self.review()
        original_review = copy.deepcopy(review)
        self.assess(review)
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertEqual(original_review, review)
        self.assertEqual(source.read_bytes(), original)

    def test_no_review_generates_full_template_as_internal_error(self):
        result = audit.assess(self.root)
        self.assertEqual(result['decision'], 'ERROR')
        self.assertFalse(result['is_task_rejection'])
        self.assertEqual(len(result['review_template']['items21']), 21)
        self.assertEqual(len(result['review_template']['harbor6']), 6)
        self.assertIn('assessment', result['review_template']['content_gates']['checks'][2])
        self.assertEqual(set(result['review_template']['content_gates']['checks'][1]['dimensions']), set(audit.G02_DIMENSIONS))

    def test_missing_review_items_are_visible_placeholders_not_silently_deleted(self):
        review = self.review()
        review['items21'].pop()
        review['harbor6'].pop()
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR')
        self.assertEqual(len(result['items21']), 21)
        self.assertEqual(len(result['harbor6']), 6)
        self.assertEqual(self.row(result, 'QA21')['status'], 'review_not_finished')
        text = audit.render(result)
        self.assertIn('### QA21 ', text)
        self.assertIn('### H06 ', text)

    def test_g02_requires_five_existing_content_dimensions(self):
        review = self.review()
        del self.row(review, 'G02')['dimensions']['training_sufficiency']
        result = self.assess(review)
        self.assertEqual(result['decision'], 'ERROR')
        self.assertEqual(self.row(result, 'G02')['status'], 'review_not_finished')

    def test_g02_dimensions_are_displayed_in_final_report(self):
        text = audit.render(self.assess())
        for label in audit.G02_DIMENSIONS.values():
            self.assertIn(label + '：', text)

    def test_g02_nonempty_dimension_text_can_use_overall_existing_evidence(self):
        review = self.review()
        self.row(review, 'G02')['dimensions'] = {key: label + ': existing source was reviewed.' for key, label in audit.G02_DIMENSIONS.items()}
        self.assertEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_g03_real_failure_survives_two_trajectory_locator_review_error(self):
        review = self.review()
        a, b = review['trajectory_content_review']['trajectories']
        b['name'] = a['name']
        review['overview']['baseline_reference']['paired_runs'][0]['baseline_valid'] = False
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL')
        self.assertFalse(result['review_completed'])

    def test_g03_existing_positive_values_can_waive_only_new_environment_validation(self):
        review = self.review()
        self.finding(self.row(review, 'G03'), reason='legacy_new_validation_dependency')
        result = self.assess(review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS')
        self.assertEqual(self.row(result, 'G03')['numerical_assessment']['status'], 'pass')
        self.assertEqual(self.row(result, 'G03')['computed']['normalized_score'], 0.4)

    def test_mandatory_qa_or_harbor_cannot_skip_via_not_applicable(self):
        for key in ('QA01', 'QA12', 'QA15', 'QA18', 'QA21', 'H01', 'H02', 'H03', 'H04', 'H06'):
            with self.subTest(key=key):
                review = self.review()
                self.row(review, key).update(observed_status='not_applicable', not_applicable_basis='CPU task without GPU; skip this check.')
                self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_random_science_cannot_skip_sigma_or_seed_review(self):
        for key in ('QA04', 'QA19'):
            review = self.review()
            self.row(review, key).update(observed_status='not_applicable', not_applicable_basis='Claimed deterministic.')
            self.assertEqual(self.assess(review)['decision'], 'ERROR')

    def test_deterministic_science_can_explain_sigma_seed_not_applicable(self):
        review = self.review()
        self.row(review, 'G03')['assessment']['evaluation_mode'] = 'deterministic'
        for key in ('QA04', 'QA19'):
            self.row(review, key).update(observed_status='not_applicable', not_applicable_basis='Existing deterministic evaluator has no random seed variation under this original protocol.')
        self.assertEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_no_supplied_job_configuration_can_be_reviewed_h05_not_applicable(self):
        review = self.review()
        self.row(review, 'H05').update(observed_status='not_applicable', not_applicable_basis='Existing delivered inventory contains no Job/Trial invocation configuration; the current native task interface was inspected.', evidence=['@legacy_inventory'])
        self.assertEqual(self.assess(review)['decision'], 'PASS_WITH_WAIVERS')

    def test_cli_review_can_share_output_directory_without_overwrite(self):
        out = self.base / 'reports'
        out.mkdir()
        reviewer = out / 'legacy_review.json'
        reviewer.write_text(json.dumps(self.review()))
        before = reviewer.read_bytes()
        code = audit.main([str(self.root), '--review', str(reviewer), '--out-dir', str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(before, reviewer.read_bytes())
        self.assertTrue((out / 'report.json').exists())

    def test_cli_complete_zip_is_read_only(self):
        archive = self.base / 'task.zip'
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as stream:
            for path in self.root.rglob('*'):
                stream.write(path, path.relative_to(self.root).as_posix())
        before = archive.read_bytes()
        reviewer = self.base / 'review.json'
        reviewer.write_text(json.dumps(self.review()))
        self.assertEqual(audit.main([str(archive), '--review', str(reviewer), '--out-dir', str(self.base / 'reports')]), 0)
        self.assertEqual(before, archive.read_bytes())


if __name__ == '__main__':
    unittest.main()
