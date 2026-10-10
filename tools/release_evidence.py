"""Explicit maintainer evidence binding, not a live runner or scientific QA.

Claim semantics are reviewed against the linked originals by the named reviewer.
This module checks completeness, source applicability and byte-level provenance;
it does not infer a successful experiment from an arbitrary log or a checkbox.
"""
import ast
import datetime as dt
import json
from pathlib import Path
import re

from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import _sha256

CLAIMS = {
    'native_runtime': {'native_tui', 'same_thread_resume', 'observer_detach', 'logs_and_timing', 'short_run_not_final'},
    'harbor_transfer': {'candidate_transfer', 'independent_verifier', 'reward_retrieval'},
    'gpu_dispatch': {'authorized_devices', 'actual_gpu_execution', 'no_duplicate_jobs'},
    'independent_trial': {'fresh_session', 'entry_sufficient', 'legal_pause_resume', 'no_unresolved_defects'},
}
ENTRYPOINTS = {
    'native_runtime': ['autoresearch_flow/runtime.py', 'autoresearch_flow/harbor_agent.py',
                       'autoresearch_flow/runtime_evaluate.py'],
    'harbor_transfer': ['autoresearch_flow/harbor_agent.py', 'autoresearch_flow/harbor_runtime.py'],
    'gpu_dispatch': ['autoresearch_flow/experiment_runner.py'],
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_ref(root, ref):
    require(isinstance(ref, dict), 'evidence reference must be an object')
    name, digest = ref.get('path'), ref.get('sha256')
    require(isinstance(name, str) and name and not Path(name).is_absolute()
            and '..' not in Path(name).parts and '\\' not in name, 'unsafe evidence path')
    require(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'invalid evidence SHA-256')
    path = root/name
    require(not any(p.is_symlink() for p in [path, *path.parents] if p != root.parent)
            and path.resolve().is_relative_to(root.resolve()) and path.is_file(), 'unsafe or missing evidence file')
    require(_sha256(path) == digest, f'evidence drift: {name}')
    return path


def source_scope(flow, files, gate, known_names=()):
    """Local Python imports plus non-code runtime inputs; no module execution."""
    names = {p.relative_to(flow).as_posix(): p for p in files}
    available = set(names) | set(known_names)
    if gate == 'independent_trial':
        return {n for n in names if n.split('/')[0] not in {'tests', 'tools', 'pilots'}}
    pending = [p for p in ENTRYPOINTS[gate] if p in available]
    require(pending, f'missing source entrypoint for {gate}')
    seen = set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        require(name in names, f'source scope drift: removed dependency {name}')
        seen.add(name)
        tree = ast.parse(names[name].read_text(encoding='utf-8'))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = name.split('/')[:-node.level] if node.level else []
                parts = base + (node.module.split('.') if node.module else [])
                modules.append('.'.join(parts))
                modules.extend('.'.join(parts+[alias.name]) for alias in node.names)
        for module in modules:
            path = module.replace('.', '/')
            candidates = [path+'.py', path+'/__init__.py']
            candidates += ['/'.join(path.split('/')[:i])+'/__init__.py' for i in range(1, len(path.split('/')))]
            pending.extend(p for p in candidates if p in available and p not in seen)
    # The GPU probe invokes ExperimentRunner directly; the CLI is not part of
    # that execution path.
    if gate != 'gpu_dispatch':
        seen.update(n for n in available if n == 'cli.py')
    # These files are runtime inputs to native workflow execution, not to the
    # direct experiment runner or standalone Harbor transfer fixture.
    if gate == 'native_runtime':
        inputs = {'templates/agent-prompt.zh.md', 'templates/runtime.example.json',
                  'rules/manifest.json', 'rules/catalog.json',
                  'model_profiles/codex.example.toml', 'model_profiles/seed.example.toml'}
        seen.update(available & inputs)
        seen.update(n for n in available if n == 'autoresearch_flow/runtime_evaluate.py')
    return seen


def validate_bindings(manifest_path, flow, files):
    manifest_path, flow = Path(manifest_path), Path(flow)
    require(manifest_path.is_file() and not manifest_path.is_symlink(), 'explicit evidence manifest is missing or unsafe')
    data = json.loads(manifest_path.read_text(encoding='utf-8'))
    if data.get('schema_version') == 2:
        from tools.release_evidence_current import validate_current
        return validate_current(manifest_path, flow, files, mechanical=False)
    release_version = data.get('release_version')
    require(release_version == FLOW_VERSION, 'release evidence version mismatch')
    require(data.get('schema_version') == 1, 'unsupported release evidence schema')
    checks, limitations = data.get('checks'), data.get('limitations')
    require(isinstance(limitations, list) and all(isinstance(x, str) and x.strip() for x in limitations),
            'limitations must explicitly record unverified scope')
    require(isinstance(checks, list) and all(isinstance(x, dict) for x in checks), 'checks must be objects')
    ids = [c.get('id') for c in checks]
    require(len(ids) == len(CLAIMS) and all(isinstance(x, str) for x in ids)
            and set(ids) == set(CLAIMS), 'required release checks missing or duplicated')
    current = {p.relative_to(flow).as_posix(): {'sha256': _sha256(p), 'mode': p.stat().st_mode & 0o777} for p in files}
    bound = []
    for check in checks:
        gate = check['id']
        if check.get('status') == 'waived':
            require(release_version == '1.0.0' and gate == 'independent_trial',
                    'only independent_trial may be waived for first release 1.0.0')
            require(check.get('mode') == 'explicit_user_authorization',
                    'waiver must bind the explicit first-release user authorization')
            waiver = check.get('waiver')
            require(isinstance(waiver, dict) and waiver.get('approved_by') == 'user'
                    and waiver.get('approved_at') == '2026-10-04'
                    and isinstance(waiver.get('reason'), str) and waiver['reason'].strip(),
                    'first-release waiver lacks user authorization, date, or reason')
            approval = checked_ref(manifest_path.parent, waiver.get('approval'))
            document = json.loads(approval.read_text(encoding='utf-8'))
            require(document.get('kind') == 'first_release_exception'
                    and document.get('release_version') == '1.0.0'
                    and document.get('scope') == 'independent_trial'
                    and document.get('approved_by') == 'user'
                    and document.get('approved_at') == '2026-10-04'
                    and document.get('reason') == waiver['reason'],
                    'first-release waiver record is inconsistent')
            require(not check.get('claims') and not check.get('result'),
                    'waived check must not assert passed claims or results')
            require(any('independent new-session trial' in limitation.lower() and 'waived' in limitation.lower()
                        for limitation in limitations),
                    'release limitations must disclose the independent-trial waiver')
            bound.append({'id': gate, 'status': 'waived', 'mode': check['mode'],
                          'waiver': {**waiver, 'approval': {'path': waiver['approval']['path'],
                                                             'sha256': waiver['approval']['sha256']}}})
            continue
        require(check.get('status') == 'passed' and check.get('mode') in {'fresh', 'reused'}, f'unpassed evidence: {gate}')
        claims = check.get('claims')
        require(isinstance(claims, dict) and set(claims) == CLAIMS[gate]
                and all(v is True for v in claims.values()), f'incomplete reviewed claims: {gate}')
        require(isinstance(check.get('reviewer'), str) and check['reviewer'].strip(), f'missing reviewer: {gate}')
        review = checked_ref(manifest_path.parent, check.get('review'))
        require(bool(review.read_text(encoding='utf-8').strip()), f'empty evidence review: {gate}')
        when = dt.datetime.fromisoformat(check['origin_at'].replace('Z', '+00:00'))
        require(when.tzinfo is not None, 'origin_at needs an explicit timezone')
        original = json.loads(checked_ref(manifest_path.parent, check.get('origin_sources')).read_text(encoding='utf-8'))
        require(isinstance(check.get('origin_version'), str) and check['origin_version']
                == original.get('version'), f'origin version mismatch: {gate}')
        entries = original.get('files')
        require(isinstance(entries, list) and all(isinstance(e, dict) for e in entries), 'invalid origin source manifest')
        expected = {e['path']: {'sha256': e.get('sha256'), 'mode': e.get('mode')} for e in entries}
        require(len(expected) == len(entries), 'duplicate origin source paths')
        scope = source_scope(flow, files, gate, expected)
        require(all(current.get(n) == expected.get(n) for n in scope), f'source changed; cannot apply {gate} evidence')
        # Removed sources in a relevant scope must not disappear from comparison.
        if gate == 'independent_trial':
            original_scope = {n for n in expected if n.split('/')[0] not in {'tests', 'tools', 'pilots'}}
            require(original_scope == scope, 'source scope drift: independent_trial')
        refs = check.get('evidence')
        require(isinstance(refs, list) and bool(refs), f'missing raw evidence: {gate}')
        for ref in refs:
            checked_ref(manifest_path.parent, ref)
        bound.append({k: check[k] for k in ('id', 'status', 'mode', 'origin_version', 'origin_at',
                     'origin_sources', 'evidence', 'review', 'reviewer', 'claims')})
        bound[-1]['bound_source_count'] = len(scope)
    return {'schema_version': 1, 'manifest_sha256': _sha256(manifest_path), 'checks': bound,
            'limitations': limitations, 'validation_scope': 'integrity and source applicability; claim semantics reviewed in linked records'}


def validate_evidence(manifest_path, flow, files):
    """Public release gate: both source/original binding AND mechanical results."""
    if json.loads(Path(manifest_path).read_text(encoding='utf-8')).get('schema_version') == 2:
        from tools.release_evidence_current import validate_current
        return validate_current(Path(manifest_path), Path(flow), files, mechanical=True)
    bound = validate_bindings(manifest_path, flow, files)
    manifest_path = Path(manifest_path)
    checks = json.loads(manifest_path.read_text(encoding='utf-8'))['checks']
    for check in checks:
        if check.get('status') == 'waived':
            item = next(c for c in bound['checks'] if c['id'] == check['id'])
            item['mechanical_result'] = 'waived_by_user'
            continue
        path = checked_ref(manifest_path.parent, check.get('result'))
        report = json.loads(path.read_text(encoding='utf-8'))
        gate = check['id']
        require(report.get('status') == 'passed', f'actual result failed: {gate}')
        # The small index locates native outputs. It cannot replace them with
        # copied means, invented booleans, or historical release_ready flags.
        if gate == 'native_runtime':
            _native_result(path.parent, report)
        elif gate == 'harbor_transfer':
            _transfer_result(path.parent, report)
        elif gate == 'gpu_dispatch':
            _gpu_result(path.parent, report)
        else:
            require(isinstance(report.get('session_id'), str) and report['session_id'].strip()
                    and report.get('fresh_session') is True and report.get('blocking_findings') == [],
                    'independent session has missing identity or unresolved findings')
            record = checked_ref(path.parent, report.get('session_record'))
            require(record.stat().st_size > 0, 'independent session record is empty')
        item = next(c for c in bound['checks'] if c['id'] == gate)
        item['result'] = check['result']
        item['mechanical_result'] = 'passed'
    return bound


def _native_result(root, report):
    from autoresearch_flow.core import FlowError
    from autoresearch_flow.harbor_runtime import final_snapshot
    from autoresearch_flow.runtime import Runtime, EVALUATE, public_evaluation
    from autoresearch_flow.trajectory import validate_round
    state_path = checked_ref(root, report.get('state'))
    require(state_path.parts[-4:-1] == ('.autoresearch-flow', 'runtime', 'seed')
            and state_path.name == 'state.json', 'expected explicit Seed native runtime state')
    runtime = Runtime(state_path.parents[3])
    runtime._load()  # Reads frozen inputs only; does not load credentials or call a model.
    status, state = runtime.status('seed'), runtime._state('seed')
    require(state['active'] is None and state.get('thread_id') and state['preflight'].get('ready') is True,
            'runtime is active, missing identity or failed preflight')
    formal = [s for s in state['segments'] if s['phase'] == 'formal']
    require(len(formal) >= 2 and all(s.get('thread_id') == state['thread_id'] and s.get('mode') == 'native_tui'
            for s in formal), 'not two native segments of the same original session')
    require(formal[-1]['status'] in {'completed', 'budget_exhausted', 'interrupted'}, 'runtime did not recover from failure')
    successful_segments = []
    for segment in formal:
        public, completed, errors, threads = 0, 0, 0, []
        logs = [ref for ref in segment['logs'] if ref['path'].endswith('/events.jsonl')]
        require(len(logs) == 1, 'missing native event record')
        for line in checked_ref(runtime.directory, logs[0]).read_text(encoding='utf-8').splitlines():
            record = json.loads(line)
            if record.get('source') == 'native_rollout':
                event = record.get('event', {})
                if event.get('type') == 'thread.started':
                    require(event.get('thread_id') == state['thread_id'], 'native thread changed')
                    threads.append(event['thread_id'])
                if event.get('type') == 'turn.completed':
                    completed += 1
                if event.get('type') in {'error', 'turn.failed'}:
                    errors += 1
                if event.get('type') == 'item.completed':
                    public += public_evaluation(event.get('item', {}), [EVALUATE]) is not None
        # A bounded continuous run may legitimately pause mid-answer. Its own
        # completed successful public tool result proves resumed work; do not
        # require a final assistant answer or relabel the budget pause as one.
        successful_segments.append(bool(threads) and public > 0 and errors == 0
                                   and (completed > 0 or segment['status'] == 'budget_exhausted'))
    require(sum(successful_segments) >= 2 and successful_segments[-1],
            'runtime resume lacks its own successful public evaluation/progress or has errors')
    trajectory = checked_ref(root, report.get('trajectory'))
    require(trajectory.resolve() == (runtime.directory/'seed/formal/output/trajectory.jsonl').resolve(),
            'trajectory is not from this native runtime')
    rows = trajectory.read_text(encoding='utf-8').splitlines()
    require(bool(rows), 'missing Agent trajectory')
    for number, row in enumerate(rows, 1):
        validate_round(json.loads(row), number)
    jobs = report.get('jobs')
    require(isinstance(jobs, list) and bool(jobs), 'missing actual Harbor job configs')
    paths = [checked_ref(root, ref) for ref in jobs]
    actual = {p.resolve() for p in (runtime.directory/'seed/harbor').glob('*/job.json')}
    require(len(paths) == len(actual) and {p.resolve() for p in paths} == actual,
            'reported jobs differ from actual Harbor job set')
    for path in paths:
        require(json.loads(path.read_text())['verifier']['disable'] is True,
                'iteration job enabled final verifier')
    require(not (runtime.directory/'seed/harbor/final_attempt.json').exists(), 'bounded probe consumed final query')
    require(status['effective_seconds_before_content_review'] < status['minimum_seconds'],
            'this release check expects a bounded, not full scientific, run')
    try:
        final_snapshot(runtime, 'seed')
    except FlowError as error:
        require(error.code == 'FINAL_NOT_READY', 'short-run final gate failed for an unrelated reason')
    else:
        raise ValueError('short run incorrectly passed final scoring gate')
    observer = json.loads(checked_ref(root, report.get('observer')).read_text())
    require(observer.get('continued_without_observer') is True and any(
            s.get('observer_detached') is True for s in observer.get('segments', [])), 'observer detach not demonstrated')


def _transfer_result(root, report):
    path = checked_ref(root, report.get('transfer_report'))
    transfer = json.loads(path.read_text())
    require(transfer.get('status') == 'harbor_transfer_probe_passed' and transfer.get('exit_code') == 0,
            'Harbor transfer probe failed')
    trial = transfer.get('trial', {})
    require(trial.get('reward') == 1 and trial.get('mode') == 'separate', 'independent verifier/reward failed')
    refs = transfer.get('evidence', [])
    require(bool(refs), 'missing original Harbor artifacts')
    for ref in refs:
        checked_ref(path.parent, ref)
    candidates = [r for r in refs if r['path'].endswith('artifacts/workspace/solution/method.py')]
    require(len(candidates) == 1 and trial.get('candidate_sha256') == candidates[0]['sha256'],
            'transferred candidate is not bound to scoring')


def _gpu_result(root, report):
    allowed, runs = report.get('authorized_devices'), report.get('runs')
    require(isinstance(allowed, list) and allowed and all(isinstance(x, str) and x for x in allowed), 'missing authorized GPU IDs')
    require(isinstance(runs, list) and runs, 'missing actual GPU runs')
    ids = []
    for item in runs:
        execution = json.loads(checked_ref(root, item.get('execution')).read_text())
        result = json.loads(checked_ref(root, item.get('cuda_result')).read_text())
        ids.append(item['run_id'])
        devices = execution.get('devices')
        require(execution.get('exit_code') == 0 and isinstance(devices, list) and bool(devices)
                and set(devices) <= set(allowed), 'GPU execution failed or used unapproved device')
        require(result.get('cuda_available') is True and result.get('matmul_finite') is True
                and result.get('visible_devices') == devices, 'CUDA allocation/computation not proven')
    require(len(ids) == len(set(ids)), 'duplicate GPU run IDs')
