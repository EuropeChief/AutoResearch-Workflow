#!/usr/bin/env python3
"""Run the unmodified v0.3.10 auditor, then apply reviewed migration waivers.

Both review JSONs are internal reviewer worksheets, not extra author deliverables.
No submission program, model, Docker image or Harbor process is executed.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import zipfile

import audit_legacy_task as legacy
import audit_format_repair as fmt
import implementation_review as standard
import harbor_review
import resource_review
import trajectory_review
import task_fingerprint
import content_gates

VERSION = '0.3.10-standard-waiver.5'
STAGE = 'standard_review_with_waivers'
NONPASS = {'fail', 'manual'}


def dump(path, value):
    fmt.atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def standard_template():
    return {'overview': standard.empty_overview(), 'checks': [standard.item(i) for i in standard.IDS],
        'content_gates': content_gates.empty(), 'harbor': {'target_version': '', 'provider': '',
            'version_basis': '', 'task_root': None, 'path_contract': {}, 'checks': []},
        'trajectory_review': {'trajectories': []}, 'runtime_review': {'trajectories': []},
        'resource_review': {}, 'format_review': {'status': 'manual', 'summary': '', 'additional_suggestions': []},
        'reviewer_note': '原 v0.3.10 的内部 review.json；按原全部章节完成，包括已有 NOP Trial。不是专家新增文件。'}


def run_standard(root, review, out):
    """Actually invoke the original entry point with --review on every run."""
    native_out = out / 'standard'
    native_out.mkdir(parents=True, exist_ok=True)
    args = [str(root), '--out-dir', str(native_out)]
    if review is not None:
        native_review = out / '_standard_review_input.json'
        dump(native_review, review)
        args += ['--review', str(native_review)]
    with contextlib.redirect_stdout(io.StringIO()):
        code = standard.main(args)
    report = json.loads((native_out / 'report.json').read_text(encoding='utf-8'))
    return report, code


def inspect_components(root, review, original):
    """Continue independent validators even if an earlier original phase raised.

    Results remain original validator outputs. This is not a substitute handwritten
    pass and cannot silently erase the original inspection_error.
    """
    values, errors = {}, []
    if review is None:
        return values, errors
    files = standard.inventory(root)
    def inspect(name, operation):
        try:
            values[name] = operation()
        except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
            errors.append({'component': name, 'message': str(exc)})
    inspect('overview', lambda: standard.validate_overview(review.get('overview'), root))
    selected = review.get('harbor', {}).get('task_root')
    task = root / selected if isinstance(selected, str) else None
    inspect('fingerprint', lambda: task_fingerprint.collect(task))
    inspect('harbor', lambda: harbor_review.apply_review(harbor_review.collect(root, files), review.get('harbor'), root))
    if 'overview' in values:
        overview = values['overview']
        inspect('trajectory', lambda: trajectory_review.apply_review(
            trajectory_review.collect(root, files, values.get('fingerprint', {})), review.get('trajectory_review'),
            overview['trajectories'], root, files, standard.review_evidence))
        inspect('resources', lambda: resource_review.apply_review(
            resource_review.collect(root, files, standard.task_config(task), [r['source_path'] for r in overview['trajectories'] if r.get('source_path')]),
            review.get('resource_review'), root, standard.review_evidence,
            values.get('harbor', {}).get('deployment_contract')))
        inspect('content_gates', lambda: content_gates.apply_review(review.get('content_gates'), overview, root, standard.review_evidence))
        durations, _ = standard.trajectory_durations(root, [r['source_path'] for r in overview['trajectories'] if r.get('source_path')])
        inspect('runtime', lambda: content_gates.assess_runtime(review.get('runtime_review'), overview['trajectories'], root, standard.review_evidence, durations))
        inspect('trajectory_schema', lambda: [standard.validate_trajectory(root / r['source_path'], root)
            for r in overview['trajectories'] if r.get('source_path')])
    return values, errors


def inspect_nop(root, review):
    """Always validate delivered NOPs, including when handwritten H06 is fail/N/A."""
    if review is None:
        return {'status': 'not_reviewed', 'runtime_status': 'not_reviewed', 'trials': []}
    hr = review.get('harbor', {})
    h6 = next((r for r in hr.get('checks', []) if r.get('id') == 'H06'), {})
    cited = h6.get('evidence', [])
    declared_dirs = set()
    for ref in cited:
        try:
            p = harbor_review.resolve_ref(root, ref)
            if p.name in {'config.json', 'result.json', 'trial.log'}:
                declared_dirs.add(p.parent)
            elif p.name in {'reward.txt', 'reward.json', 'test-stdout.txt'} and p.parent.name == 'verifier':
                declared_dirs.add(p.parent.parent)
        except (ValueError, OSError, TypeError):
            pass  # The original reference validator reports malformed citations.
    candidates = set(declared_dirs)
    for filename, field in (('config.json', 'agent'), ('result.json', 'agent_info')):
        for p in root.rglob(filename):
            if p.is_symlink() or not p.resolve().is_relative_to(root):
                continue
            try:
                document = json.loads(harbor_review.bounded_text(p))
                if isinstance(document, dict) and isinstance(document.get(field), dict) and document[field].get('name') == 'nop':
                    candidates.add(p.parent)
            except (OSError, ValueError, UnicodeError):
                if p.parent in declared_dirs:
                    candidates.add(p.parent)
    trials = []
    task = root / hr['task_root'] if isinstance(hr.get('task_root'), str) else None
    for folder in sorted(candidates):
        refs = [p.relative_to(root).as_posix() for p in (folder / 'config.json', folder / 'result.json',
            folder / 'verifier/reward.json', folder / 'verifier/reward.txt', folder / 'trial.log', folder / 'verifier/test-stdout.txt') if p.is_file()]
        row = {'trial_dir': folder.relative_to(root).as_posix(), 'evidence': refs}
        try:
            evidence = harbor_review.validate_trial_evidence(root, refs, task, hr.get('trial_task_binding'))
            row.update(details=evidence, status='pass' if evidence['agent'] == 'nop' and evidence['task_binding']['status'] == 'pass' else 'manual',
                summary='已有 NOP 的同次 Trial、Agent、separate、sandbox 反证、结束与异常、reward 数值和非空日志已按原校验器核查。')
            if evidence['agent'] != 'nop':
                row.update(status='fail', summary='提交的 H06 Trial 不是 NOP。', protected=True)
        except (OSError, ValueError, UnicodeError, TypeError) as exc:
            message = str(exc)
            # Old/current version association is a migration gap. Trial structure,
            # reward inconsistency, non-NOP identities and sandbox contradictions are not.
            binding_gap = any(fragment in message for fragment in ('task.toml hash disagrees', 'identifies a different task', 'different-task evidence needs'))
            row.update(status='manual' if binding_gap else 'fail', summary=message, protected=not binding_gap)
        trials.append(row)
    status = 'fail' if not trials or any(t['status'] == 'fail' for t in trials) else 'manual' if any(t['status'] == 'manual' for t in trials) else 'pass'
    return {'status': status, 'runtime_status': 'not_run' if not trials else 'failed' if status == 'fail' else 'unverified' if status == 'manual' else 'evidence_consistent',
        'trials': trials, 'summary': '缺少已有 NOP Trial，原标准 H06 不通过；仅在历史缺口政策下可逐原因豁免。' if not trials else '逐份读取并校验已有 NOP 记录；未启动新的 Trial。'}


def records(original, components, nop):
    """Stable evidence ledger for EVERY nonpassing original row and detail."""
    output = []
    def add(source, owner, row, *, allowed=(), protected=False, derived=False):
        if row.get('status') not in NONPASS:
            return
        summary = str(row.get('summary', row.get('message', '')))
        identity = source + '|' + summary
        output.append({'id': hashlib.sha256(identity.encode()).hexdigest()[:20], 'source': source, 'owner': owner,
            'status': row['status'], 'summary': summary, 'evidence': copy.deepcopy(row.get('evidence', [])),
            'allowed_waivers': list(allowed), 'protected': protected, 'derived': derived})
    gates = components.get('content_gates', original.get('content_gates', {}))
    harbor = components.get('harbor', original.get('harbor', {}))
    resources = components.get('resources', original.get('resource_review') or {})
    integrity = components.get('trajectory', original.get('trajectory_review') or {})
    schema = components.get('trajectory_schema', original.get('format_alignment', {}).get('reviewed_trajectories', []))
    native_gates = original.get('content_gates', {}).get('checks', [])
    gate_sources = [('gates/' + row['id'], row) for row in native_gates]
    for row in gates.get('checks', []):
        same = next((r for r in native_gates if r['id'] == row['id']), None)
        if same is None or any(same.get(k) != row.get(k) for k in ('status', 'summary', 'reason_code')):
            gate_sources.append(('component_gates/' + row['id'], row))
    for source, row in gate_sources:
        add(source, row['id'], row, allowed=('legacy_new_validation_dependency',) if row['id'] == 'G03' and row.get('reason_code') != 'REFERENCE_THRESHOLD_FAILED' else (), protected=row['id'] != 'G03' or row.get('automatic_status') == 'fail')
    for row in original.get('checks', []):
        owner = row['id']
        allowed = [key for key, owners in legacy.WAIVERS.items() if owner in owners]
        protected = owner not in {'QA03', 'QA05', 'QA13', 'QA15', 'QA16', 'QA17', 'QA18', 'QA21'}
        add('checks/' + owner, owner, row, allowed=allowed, protected=protected, derived=owner == 'QA17')
    for row in harbor.get('checks', []):
        owner = row['id']
        allowed = [key for key, owners in legacy.WAIVERS.items() if owner in owners]
        add('harbor/' + owner, owner, row, allowed=allowed, protected=owner in {'H01', 'H04'}, derived=owner == 'H06')
    for key, owner in [('path_contract', 'H03'), ('deployment_contract', 'H02')]:
        for i, row in enumerate(harbor.get(key, {}).get('findings', [])):
            allow = ('platform_image_preparation_pending', 'platform_execution_verification_pending') if owner == 'H03' and row.get('status') == 'manual' else ()
            if row.get('code') == 'capability_semantic_review':
                allow = ('unsupported_network_policy_transition',)
            add('harbor/' + key + '/' + str(i), owner, row, allowed=allow, protected=row.get('status') == 'fail' and not allow)
    for i, message in enumerate(resources.get('problems', [])):
        add('resources/problems/' + str(i), 'QA15', {'status': 'fail', 'summary': message, 'evidence': resources.get('evidence', [])}, protected=True)
    for i, message in enumerate(resources.get('gaps', [])):
        add('resources/gaps/' + str(i), 'QA15', {'status': 'manual', 'summary': message, 'evidence': resources.get('evidence', [])}, allowed=('legacy_hardware_record_difference', 'legacy_target_resource_evidence_gap'))
    for i, observation in enumerate(schema):
        for j, row in enumerate(observation.get('alignment_issues', [])):
            tool_limit = row.get('code') == 'TRAJECTORY_UNREADABLE' and 'inspection limit' in str(row.get('message', ''))
            missing_source = row.get('code') in {'MISSING_TRAJECTORY', 'TRAJECTORY_UNREADABLE'} and not tool_limit
            add(f'trajectory_schema/{i}/{j}', 'QA18', {**row, 'evidence': [observation['path']] if observation.get('path') else []}, allowed=() if missing_source else ('legacy_trajectory_schema_gap',), protected=missing_source)
    for i, row in enumerate(integrity.get('trajectories', [])):
        add(f'trajectory/{i}/binding', 'QA21', row.get('task_binding', {}), allowed=('legacy_task_binding_migration',))
        for j, finding in enumerate(row.get('findings', [])):
            if finding.get('certainty') == 'confirmed' and finding.get('classification') in {'leakage', 'cheating'}:
                add(f'trajectory/{i}/finding/{j}', 'QA18', {**finding, 'status': 'fail'}, allowed=('historical_agent_runtime_finding',))
                output[-1]['confirmed_original_behavior'] = {k: finding.get(k) for k in ('classification', 'certainty', 'score_effect')}
                if finding.get('score_effect') == 'invalid':
                    output[-1]['confirmed_original_score_status'] = 'invalid'
    for i, path in enumerate(integrity.get('invalid_formal_run_paths', [])):
        add(f'trajectory/invalid_formal/{i}', 'G03', {'status': 'fail', 'summary': '正式 B/R 评分无效：' + path, 'evidence': [path]}, protected=True)
    if nop['status'] not in {'pass', 'not_reviewed'}:
        if not nop['trials']:
            add('nop/missing', 'H06', {'status': 'fail', 'summary': nop['summary'], 'evidence': []}, allowed=('legacy_nop_or_current_trial_gap',))
        for i, row in enumerate(nop['trials']):
            add('nop/trials/' + str(i), 'H06', row, protected=row.get('protected', False), allowed=() if row.get('protected') else ('legacy_nop_or_current_trial_gap', 'platform_execution_verification_pending'))
            if row.get('protected'):
                output[-1]['historical_failed_trial_review_allowed'] = True
                output[-1]['trial_dir'] = row['trial_dir']
    return output


def all_rows(result):
    return (result.get('content_gates', {}).get('checks', []) + result.get('items21', []) + result.get('harbor6', [])
        + result.get('trajectory_content_review', {}).get('trajectories', []))


def reconcile(root, result, native, components, component_errors, nop, worksheet):
    result = copy.deepcopy(result)
    result.update(version=VERSION, stage=STAGE, standard_report=native, standard_components=components,
        standard_component_errors=component_errors, nop_review=nop, standard_auditor_executed=True)
    ledger = records(native, components, nop)
    original_comparison = components.get('overview', {}).get('baseline_reference')
    final_comparison = (result.get('overview') or {}).get('baseline_reference')
    if original_comparison and final_comparison:
        def comparable(value):
            return {k: value.get(k) for k in ('metric', 'direction', 'paired_runs', 'baseline_mean', 'reference_mean', 'baseline_sample_std', 'reference_sample_std')}
        if comparable(original_comparison) != comparable(final_comparison):
            ledger.append({'id': 'formal-overview-conflict', 'source': 'overview/baseline_reference', 'owner': 'G03', 'status': 'fail',
                'summary': '原标准与豁免底稿的正式 B/R 原值、有效性或汇总不一致；不能更换手填成绩以覆盖原判。',
                'evidence': original_comparison.get('evidence', []) + final_comparison.get('evidence', []),
                'allowed_waivers': [], 'protected': True, 'derived': False})
    result['standard_findings'] = ledger
    rows = {r['id']: r for r in all_rows(result)}
    resolutions = (worksheet or {}).get('standard_resolutions', [])
    result['standard_resolution_template'] = [{'standard_finding_id': f['id'], 'source': f['source'], 'owner': f['owner'],
        'action': None, 'legacy_finding_id': None, 'summary': '', 'evidence': []} for f in ledger if not f['derived']]
    errors = result.setdefault('input_and_review_errors', [])
    if not isinstance(resolutions, list) or any(not isinstance(r, dict) for r in resolutions):
        errors.append({'code': 'STANDARD_RESOLUTIONS', 'summary': 'standard_resolutions 应逐原判原因填写。'})
        resolutions = []
    used = set()
    for record in ledger:
        owner = rows.get(record['owner'])
        if record['derived']:
            record['effective_status'] = 'derived_from_details'
            continue
        matches = [r for r in resolutions if r.get('standard_finding_id') == record['id']]
        if len(matches) != 1:
            record['effective_status'] = 'fail' if record['status'] == 'fail' else 'review_not_finished'
            errors.append({'code': 'STANDARD_FINDING_UNRECONCILED', 'owner': record['owner'], 'summary': record['source'] + ' 原判未逐原因处理：' + record['summary']})
        else:
            resolution = matches[0]
            used.add(record['id'])
            try:
                legacy.references(root, resolution.get('evidence'), record['source'] + ' 处理依据', content=True)
                legacy.require(legacy.nonempty(resolution.get('summary')), 'STANDARD_RESOLUTIONS', '需写明原判实际原因及处理说明。')
                action = resolution.get('action')
                if action == 'uphold':
                    record['effective_status'] = 'fail' if record['status'] == 'fail' else 'review_not_finished'
                    if record['status'] != 'fail':
                        errors.append({'code': 'STANDARD_MANUAL_REVIEW_NOT_FINISHED', 'owner': record['owner'], 'summary': record['source'] + ' 原manual仍需质检员审明，不能自动转为作者失败。'})
                elif action == 'waive':
                    findings = [f for f in (owner or {}).get('findings', []) if f.get('id') == resolution.get('legacy_finding_id')]
                    legacy.require(len(findings) == 1 and findings[0].get('final_effect') == 'waived', 'STANDARD_WAIVER_LINK', '需指向本项已经完整核验的具体 legacy finding。')
                    finding = findings[0]
                    if record.get('confirmed_original_score_status') == 'invalid':
                        legacy.require(finding.get('classification') == record['confirmed_original_behavior']['classification']
                            and finding.get('certainty') == 'confirmed' and finding.get('score_effect') == 'invalid'
                            and finding.get('affected_score_status', 'invalid') == 'invalid', 'ORIGINAL_SCORE_STATUS_PROTECTION',
                            '原轨迹已确认的泄漏/作弊及无效分数必须保留，不能将其改写成policy_only或有效分数。')
                    historical_failed = False
                    if record.get('historical_failed_trial_review_allowed') and finding.get('waiver_reason') == 'legacy_nop_or_current_trial_gap':
                        history = resolution.get('historical_trial_review')
                        if isinstance(history, dict):
                            legacy.require(history.get('trial_dir') == record['trial_dir'] and history.get('current_version_not_run') is True
                                and legacy.nonempty(history.get('historical_version_basis')) and legacy.nonempty(history.get('current_fix_summary')),
                                'HISTORICAL_FAILED_NOP_SCOPE', '需精确定位旧版本失败记录、当前已有修正及仅缺迁移后Trial；不可把当前坏NOP称为缺记录。')
                            legacy.references(root, history.get('historical_version_evidence'), '旧版本NOP依据', content=True)
                            legacy.references(root, history.get('current_fix_evidence'), '当前已有静态修正依据', content=True)
                            historical_failed = True
                    legacy.require(not record['protected'] or historical_failed, 'PROTECTED_STANDARD_FINDING', '当前确定缺陷、正式 B/R 无效及当前坏 NOP 不可豁免；明确旧版本失败且已有当前修正时保留原事实再审迁移缺口。')
                    legacy.require(historical_failed or finding.get('waiver_reason') in record['allowed_waivers'], 'STANDARD_WAIVER_SCOPE', '该原判原因不属于此具体白名单豁免。')
                    record.update(effective_status='pass_with_waivers', waiver_reason=finding['waiver_reason'], legacy_finding_id=finding['id'])
                    if historical_failed:
                        record.update(historical_trial_review=copy.deepcopy(history), current_runtime_status='not_run', original_trial_status='fail')
                elif action == 'resolved_by_existing_evidence':
                    legacy.require(record['status'] == 'manual' and not record['protected'], 'STANDARD_RESOLUTION_SCOPE', '只允许以已读等价材料解决原 manual；确认 fail 必须保留或按具体白名单豁免。')
                    legacy.require(owner is not None and owner.get('status') in {'pass', 'pass_with_waivers', 'not_applicable'}, 'STANDARD_RESOLUTION_SCOPE', '对应完整项目也必须已据证据审明。')
                    record['effective_status'] = 'pass'
                else:
                    raise fmt.ReviewError('STANDARD_RESOLUTIONS', 'action 需为 uphold / waive / resolved_by_existing_evidence。')
                record['resolution'] = copy.deepcopy(resolution)
            except (ValueError, OSError, TypeError) as exc:
                record['effective_status'] = 'fail' if record['status'] == 'fail' else 'review_not_finished'
                errors.append({'code': getattr(exc, 'code', 'STANDARD_RESOLUTIONS'), 'owner': record['owner'], 'summary': str(exc)})
        if owner is not None:
            owner.setdefault('standard_original_findings', []).append(copy.deepcopy(record))
            if record['effective_status'] == 'fail':
                owner['status'] = 'fail'
            elif record['effective_status'] == 'review_not_finished' and owner['status'] != 'fail':
                owner['status'] = 'review_not_finished'
            elif record['effective_status'] == 'pass_with_waivers' and owner['status'] == 'pass':
                owner['status'] = 'pass_with_waivers'
    extra = [r.get('standard_finding_id') for r in resolutions if r.get('standard_finding_id') not in {f['id'] for f in ledger}]
    if extra:
        errors.append({'code': 'STALE_STANDARD_RESOLUTION', 'summary': '底稿含本次未产生的原判 ID：' + ', '.join(map(str, extra))})
    # Reader compatibility never erases an original error. It can only close
    # the exact 4 MiB locator budget after the same complete original pipeline
    # has run successfully over bare references and the reviewer read that file.
    reader_closures = []
    def reader_closed(source, message):
        candidates = [r for r in (worksheet or {}).get('reader_resolutions', []) if isinstance(r, dict)
            and r.get('source') == source and r.get('message') == message]
        if len(candidates) != 1 or 'explicit evidence location exceeds the 4 MiB inspection limit:' not in message:
            return False
        resolution = candidates[0]
        try:
            legacy.require(result.get('review_completed') is True and all(k in components for k in
                ('overview', 'harbor', 'trajectory', 'resources', 'content_gates', 'runtime', 'trajectory_schema', 'fingerprint')),
                'READER_RESOLUTION', '必须先实际完成其它原子检查与32项内容审阅，不能用reader说明代替后续检查。')
            legacy.require(legacy.nonempty(resolution.get('summary')) and resolution.get('content_review_complete') is True,
                'READER_RESOLUTION', '需按原文件实际已读内容说明精确reader限制。')
            legacy.references(root, resolution.get('evidence'), 'reader原文件内容审阅', content=True)
            original_ref = message.split('inspection limit:', 1)[1].strip()
            base = original_ref.partition('#')[0]
            import re
            base = re.sub(r':L?\d+(?:-L?\d+)?$', '', base)
            resolved = fmt.safe_reference(root, base)
            reviewed_paths = [fmt.safe_reference(root, ref) for ref in resolution.get('evidence', [])]
            legacy.require(resolved in reviewed_paths, 'READER_RESOLUTION', '必须引用该精确原文件；不能仅引用其它摘要。')
            reader_closures.append({'source': source, 'original_error': message, 'resolution': copy.deepcopy(resolution)})
            return True
        except (OSError, ValueError, TypeError):
            return False
    def old_failed_nop_closed(message):
        return any(r.get('original_trial_status') == 'fail' and r.get('current_runtime_status') == 'not_run'
            and r.get('effective_status') == 'pass_with_waivers' and r['summary'] == message for r in ledger)
    if native.get('inspection_error') and not (reader_closed('main', native['inspection_error']) or old_failed_nop_closed(native['inspection_error'])):
        errors.append({'code': 'ORIGINAL_INSPECTION_ERROR', 'summary': native['inspection_error']})
    for error in component_errors:
        if not (reader_closed('component:' + error['component'], error['message']) or old_failed_nop_closed(error['message'])):
            errors.append({'code': 'STANDARD_COMPONENT_ERROR', 'summary': error['component'] + '：' + error['message']})
    result['reader_error_resolutions'] = reader_closures
    if worksheet is None or not result.get('standard_evaluation_report', native).get('review', {}).get('stage') == 'semantic_review':
        errors.append({'code': 'STANDARD_REVIEW_NOT_FINISHED', 'summary': '原 v0.3.10 内部 review 与完整豁免底稿均须完成；收集初稿不能通过。'})
    if 'QA17' in rows:
        statuses = [rows[k]['status'] for k in legacy.H if k in rows]
        if 'fail' in statuses:
            rows['QA17']['status'] = 'fail'
        elif 'review_not_finished' in statuses:
            rows['QA17']['status'] = 'review_not_finished'
        elif 'pass_with_waivers' in statuses and rows['QA17']['status'] == 'pass':
            rows['QA17']['status'] = 'pass_with_waivers'
    failed = result.get('decision') == 'FAIL' or any(r['status'] == 'fail' for r in rows.values())
    result['review_completed'] = bool(result.get('review_completed')) and not errors
    result['decision'] = 'FAIL' if failed else 'ERROR' if errors else 'PASS_WITH_WAIVERS'
    result['is_task_rejection'] = failed
    result['code'] = 'STANDARD_PLUS_LEGACY_FINDINGS' if failed else 'REVIEW_NOT_FINISHED' if errors else 'ALL_STANDARD_CHECKS_REVIEWED_WITH_WAIVERS'
    result['scope_note'] = ('原 v0.3.10 全部检查及完整内容审阅已完成，包括已有 NOP；仅按具体历史原因豁免。' if result['review_completed'] else '已调用原 v0.3.10 审计入口；实际完成的各组件、原判及未完成原因均保留，未声明全项审阅完成。') + '未执行题包代码或新增 Harbor Trial。'
    return result


def assess(root, standard_review, review, out):
    root, out = Path(root).resolve(), Path(out).resolve()
    if out == root or out.is_relative_to(root):
        raise ValueError('outputs must be outside the submitted artifact')
    out.mkdir(parents=True, exist_ok=True)
    native, code = run_standard(root, standard_review, out)
    nop = inspect_nop(root, standard_review)
    first_attempt = None
    input_corrections = []
    # The original validator raises on a malformed supplied NOP before later
    # phases. Retain that exact failure, then replace only the REVIEWER'S false
    # H06 pass with the now-established fail and actually finish the original
    # pipeline. No submission evidence is modified, and NOP never becomes pass.
    exact_nop_error = next((r for r in nop.get('trials', []) if r.get('summary') == native.get('inspection_error')), None)
    if standard_review is not None and exact_nop_error is not None:
        first_attempt = copy.deepcopy(native)
        saved = out / 'standard_first_attempt'
        saved.mkdir(parents=True, exist_ok=True)
        for name in ('report.json', 'report.md', 'report.txt', 'return_to_expert.txt'):
            path = out / 'standard' / name
            if path.is_file():
                fmt.atomic_write(saved / name, path.read_text(encoding='utf-8'))
        dump(saved / 'review_input.json', standard_review)
        standard_review = copy.deepcopy(standard_review)
        h6 = next((r for r in standard_review.get('harbor', {}).get('checks', []) if r.get('id') == 'H06'), None)
        if h6 is not None:
            before = h6.get('status')
            h6.update(status='fail', summary=('原 NOP 校验失败：' + exact_nop_error['summary'])[:220])
            input_corrections.append({'source': 'harbor/checks/H06', 'from': before, 'to': 'fail',
                'basis': exact_nop_error['summary'], 'evidence': exact_nop_error['evidence'],
                'scope': '仅纠正质检底稿，题包与原NOP文件保持只读；已有错误仍阻断或按精确历史范围保留豁免。'})
            native, code = run_standard(root, standard_review, out)
    components, errors = inspect_components(root, standard_review, native)
    evaluation = native
    reader_adjustments = []
    if standard_review is not None:
        def compatible(value):
            if isinstance(value, dict):
                return {k: compatible(v) for k, v in value.items()}
            if isinstance(value, list):
                return [compatible(v) for v in value]
            if isinstance(value, str) and '#' in value:
                base = value.partition('#')[0]
                try:
                    path = fmt.safe_reference(root, base)
                    if path.stat().st_size > 4 * 1024 * 1024:
                        reader_adjustments.append({'original_reference': value, 'file_reference': base,
                            'reason': 'Original explicit-locator reader has a 4 MiB budget; no submitted file was changed.'})
                        return base
                except (OSError, ValueError, TypeError):
                    pass
            return value
        compatible_review = compatible(standard_review)
        if reader_adjustments:
            evaluation, _ = run_standard(root, compatible_review, out / 'reader_compatibility')
            recovered, recovered_errors = inspect_components(root, compatible_review, evaluation)
            components.update(recovered)
            errors += [dict(r, component='reader_retry:' + r['component']) for r in recovered_errors]
    integrity = components.get('trajectory', {})
    if integrity.get('unreviewed_sources'):
        errors.append({'component': 'trajectory_content_completion', 'message': '已提供的轨迹/sessions 尚未审阅：' + '、'.join(integrity['unreviewed_sources'])})
    for row in integrity.get('trajectories', []):
        if row.get('unresolved_candidates'):
            errors.append({'component': 'trajectory_content_completion', 'message': row['name'] + ' 的已交工具观察尚未逐条审明：' + '、'.join(row['unresolved_candidates'])})
    original = copy.deepcopy(native)
    # Reconciliation uses results of the same original validators on the
    # compatible evidence-reference view, while retaining the raw first report.
    if evaluation is not native:
        original['checks'] = copy.deepcopy(evaluation.get('checks', []))
        original['content_gates'] = copy.deepcopy(evaluation.get('content_gates', {}))
        original['harbor'] = copy.deepcopy(evaluation.get('harbor', {}))
        original['format_alignment'] = copy.deepcopy(evaluation.get('format_alignment', {}))
    initial = legacy.assess(root, review)
    initial['standard_evaluation_report'] = evaluation
    result = reconcile(root, initial, original, components, errors, nop, review)
    result['standard_report'] = native
    result['reader_reference_adjustments'] = reader_adjustments
    result['standard_first_attempt'] = first_attempt
    result['standard_internal_review_corrections'] = input_corrections
    result['standard_exit_code'] = code
    return result


def render(result):
    text = legacy.render(result).replace('阶段：' + legacy.STAGE, '阶段：' + STAGE)
    lines = [text, '## 原 v0.3.10 自动检查及 NOP 原判', '',
        '已调用原标准审计入口：' + str(result.get('standard_auditor_executed')), 'NOP：' + json.dumps(result.get('nop_review'), ensure_ascii=False), '',
        '原报告与全部详细结果：standard/report.json；不因豁免覆盖原判。', '', '| 来源 | 项目 | 原判 | 本轮处理 | 依据及原因 |', '|---|---|---|---|---|']
    for row in result.get('standard_findings', []):
        reason = row['summary'].replace('|', '\\|').replace('\n', ' ')
        lines.append('| ' + ' | '.join([row['source'], row['owner'], row['status'], row.get('effective_status', '未处理'), reason]) + ' |')
    return '\n'.join(lines) + '\n'


def write_report(result, out):
    legacy.write_report(result, out)
    dump(out / 'standard_resolution_template.json', result.get('standard_resolution_template', []))
    dump(out / 'standard_review_template.json', standard_template())
    for name in ('report.md', 'report.txt', 'legacy_review_report.md', 'legacy_review_report.txt', 'return_to_expert.txt'):
        fmt.atomic_write(out / name, render(result))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--standard-review', type=Path, help='原 v0.3.10 review.json：质检员内部底稿')
    parser.add_argument('--review', type=Path, help='完整审阅与逐原因豁免内部底稿，含 standard_resolutions')
    parser.add_argument('--out-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    source, out = args.source.expanduser().resolve(), args.out_dir.expanduser().resolve()
    if out == source or (source.is_dir() and out.is_relative_to(source)):
        parser.error('outputs must be outside the submitted artifact')
    for path in (args.standard_review, args.review):
        if path and path.expanduser().resolve().is_relative_to(out):
            parser.error('internal worksheets must be outside out-dir to prevent overwrite')
    try:
        sr = fmt.json_object(args.standard_review) if args.standard_review else None
        lr = fmt.json_object(args.review) if args.review else None
        if source.is_dir():
            result = assess(source, sr, lr, out)
        elif source.is_file() and zipfile.is_zipfile(source):
            with tempfile.TemporaryDirectory(prefix='standard-waiver-') as temp:
                root = Path(temp).resolve()
                fmt.unpack(source, root)
                result = assess(root, sr, lr, out)
        else:
            raise ValueError('输入应为完整包目录或 ZIP。')
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, zipfile.BadZipFile) as exc:
        result = {'schema_version': 1, 'version': VERSION, 'stage': STAGE, 'decision': 'ERROR', 'code': 'INPUT_OR_REVIEW_ERROR',
            'review_completed': False, 'is_task_rejection': False, 'task_code_executed': False,
            'platform_runtime_status': 'not_executed', 'input_and_review_errors': [{'code': 'INPUT_OR_REVIEW_ERROR', 'summary': str(exc)}]}
    result['source'] = str(source)
    write_report(result, out)
    print(json.dumps({'decision': result['decision'], 'stage': STAGE, 'report': str(out / 'report.json')}, ensure_ascii=False))
    return 0 if result['decision'] == 'PASS_WITH_WAIVERS' else 1 if result['decision'] == 'FAIL' else 2


if __name__ == '__main__':
    raise SystemExit(main())
