"""Release-only validation for independent tracks and native Harbor originals.

Schema 1 remains readable by the historical validator. No runtime, credential,
model or Docker writes are performed here; these checks are not per-task gates.
"""
import ast
import json
import math
from pathlib import Path
import datetime as dt

from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import _sha256
from tools.release_evidence import CLAIMS, checked_ref, require

ENTRYPOINTS = {
    'native_runtime': ['autoresearch_flow/track_runtime.py', 'autoresearch_flow/runtime_controller.py',
                       'autoresearch_flow/runtime_job_process.py', 'autoresearch_flow/harbor_gpu.py'],
    'harbor_transfer': ['autoresearch_flow/harbor_native.py', 'autoresearch_flow/harbor_candidate.py'],
    'gpu_dispatch': ['autoresearch_flow/harbor_gpu.py', 'autoresearch_flow/runtime_gpu.py',
                     'autoresearch_flow/runtime_jobs.py', 'autoresearch_flow/runtime_job_process.py'],
}


def python_scope(flow, files, gate, known_names=()):
    names = {p.relative_to(flow).as_posix(): p for p in files}
    available = set(names) | set(known_names)
    if gate == 'independent_trial':
        return set(names)
    pending, seen = list(ENTRYPOINTS[gate]), set()
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        require(name in names, f'missing current source: {name}')
        seen.add(name)
        for node in ast.walk(ast.parse(names[name].read_text())):
            modules = []
            if isinstance(node, ast.Import):
                modules = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = name.split('/')[:-node.level] if node.level else []
                parts = base + (node.module.split('.') if node.module else [])
                modules = ['.'.join(parts)] + ['.'.join(parts + [a.name]) for a in node.names]
            for module in modules:
                path = module.replace('.', '/')
                candidates = [path + '.py', path + '/__init__.py']
                candidates += ['/'.join(path.split('/')[:i]) + '/__init__.py'
                               for i in range(1, len(path.split('/')))]
                pending.extend(p for p in candidates if p in available and p not in seen)
    if gate in {'native_runtime', 'gpu_dispatch'}:
        seen.update(n for n in names if n.startswith('autoresearch_flow/assets/'))
    if gate == 'harbor_transfer':
        # The CPU Trial never enters job_config's conditional GPU import;
        # that helper/provider has its own real GPU gate, not CPU evidence.
        seen.discard('autoresearch_flow/runtime_gpu.py')
    return seen


def _version_only(left, right):
    """The sole allowed metadata change is the literal FLOW_VERSION assignment."""
    trees = [ast.parse(p.read_text()) for p in (left, right)]
    versions = []
    for tree in trees:
        assignments = [n for n in tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == 'FLOW_VERSION' for t in n.targets)]
        if len(assignments) != 1 or len(assignments[0].targets) != 1:
            return False
        node = assignments[0]
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            return False
        versions.append(node.value.value)
        node.value = ast.Constant(value='<release-version>')
    return versions[0] != versions[1] and ast.dump(trees[0]) == ast.dump(trees[1])


def _sources(root, check, flow, files):
    source = check.get('sources', {})
    record = checked_ref(root, source.get('record'))
    data = json.loads(record.read_text())
    if source.get('kind') == 'runtime_snapshot':
        entries = {n[len('implementation/'):]: {'sha256': h}
                   for n, h in data.get('files', {}).items() if n.startswith('implementation/')}
        base = record.parent / 'implementation'
    elif source.get('kind') == 'harbor_snapshot':
        entries = data.get('program_files', {})
        base = record.parent / 'implementation'
    elif source.get('kind') == 'source_manifest' and check['id'] == 'independent_trial':
        original_files = data.get('files', [])
        entries = {e['path']: e for e in original_files}
        require(len(entries) == len(original_files), 'duplicate original source paths')
        base = record.parent / 'implementation'
    else:
        raise ValueError('invalid original source binding')
    scope, metadata = python_scope(flow, files, check['id'], entries), []
    if check['id'] == 'independent_trial':
        require(scope == set(entries), 'independent entry source set changed')
    for name in sorted(scope):
        require(name in entries and not Path(name).is_absolute() and '..' not in Path(name).parts,
                f'missing frozen dependency: {name}')
        original = checked_ref(base, {'path': name, 'sha256': entries[name]['sha256']})
        if source.get('kind') == 'runtime_snapshot':
            require(not original.stat().st_mode & 0o222, f'frozen runtime source is writable: {name}')
        current = flow / name
        # Freezing makes source read-only; compare executable identity here.
        # Archive validation separately requires every actual rwx bit to match.
        require((original.stat().st_mode & 0o111) == (current.stat().st_mode & 0o111),
                f'executable source mode drift: {name}')
        if _sha256(current) != entries[name]['sha256']:
            require(name == 'autoresearch_flow/__init__.py' and _version_only(original, current),
                    f'source changed; cannot apply {check["id"]} evidence: {name}')
            metadata.append(name + ':FLOW_VERSION')
    return {'bound_source_count': len(scope), 'metadata_only_changes': metadata}


def _native(root, report):
    from autoresearch_flow.track_runtime import TrackRuntime
    from autoresearch_flow.runtime_clock import activity_summary
    from autoresearch_flow.trajectory import validate_round
    state_path = checked_ref(root, report.get('state'))
    runtime = TrackRuntime(state_path.parent)
    config, state, _ = runtime._load()  # Frozen bytes and effective model, never auth.json.
    require(config.get('purpose') in {'preflight', 'acceptance'}, 'bounded run needs an honest purpose')
    require(state.get('status') == 'complete' and state.get('goal', {}).get('status') == 'complete',
            'original Goal has not completed')
    thread = state.get('thread_id')
    require(thread and state['goal'].get('threadId') == thread
            and state['goal'].get('objective') == state.get('objective'), 'original Goal identity drift')
    activity_path = checked_ref(root, report.get('activity'))
    rpc_path = checked_ref(root, report.get('rpc'))
    timing_path = checked_ref(root, report.get('timing'))
    require(activity_path == runtime.directory / 'logs/activity.jsonl'
            and rpc_path == runtime.directory / 'logs/rpc.jsonl'
            and timing_path == runtime.directory / 'logs/timing.json', 'runtime originals outside named instance')
    rows = [json.loads(line) for line in rpc_path.read_text().splitlines()]
    starts, statuses = [], []
    observed_goals = 0
    for row in rows:
        message = row['message']
        params = message.get('params', {})
        require(not message.get('error') and message.get('method') != 'error', 'native RPC error')
        goal = params.get('goal') or message.get('result', {}).get('goal')
        if isinstance(goal, dict):
            require(goal.get('createdAt') == state['goal'].get('createdAt')
                    and goal.get('threadId') == thread and goal.get('objective') == state['objective'],
                    'native Goal was replaced')
            observed_goals += 1
        if row['direction'] == 'sent' and message.get('method') in {'turn/start', 'thread/goal/set'}:
            require(params.get('threadId') == thread, 'new thread or cross-track request')
            if message['method'] == 'turn/start':
                starts.append(row['at'])
            else:
                require(params.get('objective', state['objective']) == state['objective'], 'replacement Goal')
                statuses.append(params.get('status'))
    require(observed_goals and len(starts) >= 2 and 'paused' in statuses and statuses.count('active') >= 2,
            'same original Goal pause/resume not proven')
    actual = activity_summary([json.loads(l) for l in activity_path.read_text().splitlines()])
    recorded = json.loads(timing_path.read_text())
    require(not actual['unresolved'] and math.isclose(actual['net_active_seconds'],
            recorded.get('net_active_seconds', -1), abs_tol=1e-5), 'net timing mismatch or unresolved intervals')
    require(recorded.get('formal') is False and actual['net_active_seconds'] < config['duration']['minimum_seconds'],
            'bounded acceptance must not claim formal long-run completion')
    jobs = list((runtime.directory / 'jobs/records').glob('*.json'))
    jobs = [p for p in jobs if not p.name.endswith('.completion.json')]
    good = [json.loads(p.read_text()) for p in jobs]
    require(len(good) >= 2 and all(j.get('status') == 'succeeded' and j.get('exit_code') == 0 for j in good),
            'resume has no new successful public work')
    require(any(j['started_at'] >= starts[1] for j in good), 'first result cannot substitute for resumed work')
    trajectory = checked_ref(root, report.get('trajectory'))
    require(trajectory.parent == runtime.directory / 'output', 'trajectory belongs to another instance')
    rounds = json.loads(trajectory.read_text()).get('rounds')
    require(isinstance(rounds, list) and len(rounds) >= 2, 'Agent trajectory structure invalid')
    for number, row in enumerate(rounds, 1):
        validate_round(row, number)
    observation = checked_ref(root, report.get('observation_review'))
    require(observation.stat().st_size > 0, 'TUI observation review missing')


def _harbor(root, report, flow, files):
    from autoresearch_flow.harbor_native import inspect_run
    seen = []
    for ref in report.get('trials', []):
        path = checked_ref(root, ref)
        _sources(root, {'id': 'harbor_transfer', 'sources': {'kind': 'harbor_snapshot', 'record': ref}}, flow, files)
        original = json.loads(path.read_text())
        native = original.get('native', {})
        require(native.get('agent_environment', {}).get('gpus') == 0
                and native.get('verifier_environment', {}).get('gpus') == 0,
                'CPU evidence does not prove an untested GPU Final Trial')
        actual = inspect_run(path.parent)
        require(actual.get('verifier_environment_mode') == 'separate', 'independent Verifier not proven')
        seen.append(actual['mode'])
    require(sorted(seen) == ['candidate', 'nop'], 'need actual NOP and actual candidate Trial')


def _gpu(root, report, flow):
    from autoresearch_flow.runtime_gpu import normalize_uuid, validate_requests
    admission_path = checked_ref(root, report.get('admission'))
    admission = json.loads(admission_path.read_text())
    runtime = admission_path.parents[1]
    require(admission_path.parent.name == 'trial', 'GPU admission outside instance')
    config = json.loads((runtime / 'config.json').read_text())
    container = json.loads((runtime / 'container.json').read_text())
    allowed = report.get('authorized_devices')
    require(allowed == admission.get('gpu_ids') == config.get('resources', {}).get('gpu_ids') and allowed
            and admission.get('container_id') == container.get('container_id'), 'unapproved GPU allocation')
    validate_requests(admission.get('device_requests'), allowed)
    uuids = [normalize_uuid(x) for x in admission.get('gpu_uuids', [])]
    require(len(uuids) == len(allowed) and len(uuids) == len(set(uuids)), 'GPU identity missing or duplicated')
    require(admission.get('cuda_matmul') is True and admission.get('privileged') is False
            and admission.get('docker_socket_absent') is True, 'actual CUDA/isolation not proven')
    require(admission.get('provider_sha256') == _sha256(flow / 'autoresearch_flow/harbor_gpu.py')
            and admission.get('gpu_helpers_sha256') == _sha256(flow / 'autoresearch_flow/runtime_gpu.py'),
            'GPU admission used a different provider')
    ids = []
    for ref in report.get('jobs', []):
        path = checked_ref(root, ref)
        require(path.parent == runtime / 'jobs/records', 'GPU job belongs to a different instance')
        job = json.loads(path.read_text())
        ids.append(job.get('job_id'))
        require(job.get('status') == 'succeeded' and job.get('exit_code') == 0
                and isinstance(job.get('score'), (int, float)) and math.isfinite(job['score']),
                'actual public GPU work failed')
    require(len(ids) >= 2 and all(ids) and len(ids) == len(set(ids)), 'missing or duplicate actual GPU jobs')


def validate_current(manifest_path, flow, files, *, mechanical):
    require(manifest_path.is_file() and not any(p.is_symlink() for p in [manifest_path, *manifest_path.parents]),
            'explicit evidence manifest is missing or unsafe')
    manifest_path, flow = manifest_path.resolve(), flow.resolve()
    data = json.loads(manifest_path.read_text())
    require(data.get('release_version') == FLOW_VERSION, 'release evidence version mismatch')
    checks, limitations = data.get('checks'), data.get('limitations')
    require(isinstance(limitations, list) and limitations
            and all(isinstance(x, str) and x.strip() for x in limitations), 'unverified scope must be disclosed')
    require(isinstance(checks, list) and len(checks) == len(CLAIMS)
            and all(isinstance(c, dict) for c in checks)
            and {c.get('id') for c in checks} == set(CLAIMS), 'required checks missing or duplicated')
    bound = []
    for check in checks:
        gate = check['id']
        item = {k: check.get(k) for k in ('id', 'status', 'mode', 'origin_version', 'origin_at')}
        if check.get('status') == 'waived':
            require(gate == 'independent_trial' and check.get('mode') == 'explicit_user_authorization'
                    and not check.get('claims') and not check.get('result'), 'only independent_trial can be explicitly excepted')
            approval = checked_ref(manifest_path.parent, check.get('approval'))
            record = json.loads(approval.read_text())
            require(record.get('kind') == 'release_exception' and record.get('scope') == gate
                    and record.get('approved_by') == 'user' and record.get('release_version') == FLOW_VERSION
                    and isinstance(record.get('reason'), str) and record['reason'].strip()
                    and isinstance(record.get('user_reply'), str) and record['user_reply'].strip(),
                    'waiver not authorized for this version')
            dt.date.fromisoformat(record['approved_at'])
            require(any('independent' in x.lower() and 'waived' in x.lower() for x in limitations),
                    'waiver not disclosed in limitations')
            item.update(approval=check['approval'], mechanical_result='waived_by_user')
        else:
            require(check.get('status') == 'passed' and check.get('mode') in {'fresh', 'reused'}, f'unpassed evidence: {gate}')
            require(isinstance(check.get('claims'), dict) and set(check['claims']) == CLAIMS[gate]
                    and all(v is True for v in check['claims'].values()), f'incomplete reviewed claims: {gate}')
            require(isinstance(check.get('reviewer'), str) and check['reviewer'].strip(), 'missing reviewer')
            review = checked_ref(manifest_path.parent, check.get('review'))
            require(review.stat().st_size > 0, 'empty review')
            require(isinstance(check.get('origin_version'), str) and check['origin_version'], 'missing original version')
            require(dt.datetime.fromisoformat(check['origin_at'].replace('Z', '+00:00')).tzinfo is not None,
                    'original time needs a timezone')
            item.update(_sources(manifest_path.parent, check, flow, files))
            refs = check.get('evidence')
            require(isinstance(refs, list) and refs, 'missing original evidence')
            for ref in refs:
                checked_ref(manifest_path.parent, ref)
            result = checked_ref(manifest_path.parent, check.get('result'))
            report = json.loads(result.read_text())
            if mechanical:
                require(report.get('status') == 'passed', f'actual result failed: {gate}')
                if gate == 'native_runtime':
                    require(checked_ref(manifest_path.parent, check['sources']['record']).parent
                            == checked_ref(manifest_path.parent, report['state']).parent, 'runtime source/instance mismatch')
                    _native(manifest_path.parent, report)
                elif gate == 'harbor_transfer':
                    _harbor(manifest_path.parent, report, flow, files)
                elif gate == 'gpu_dispatch':
                    require(checked_ref(manifest_path.parent, check['sources']['record']).parent
                            == checked_ref(manifest_path.parent, report['admission']).parents[1], 'GPU source/instance mismatch')
                    _gpu(manifest_path.parent, report, flow)
                else:
                    require(report.get('fresh_session') is True and report.get('session_id')
                            and report.get('blocking_findings') == [], 'independent trial incomplete')
                    checked_ref(manifest_path.parent, report.get('session_record'))
                item['mechanical_result'] = 'passed'
            item.update(sources=check['sources'], evidence=refs, result=check['result'],
                        review=check['review'], reviewer=check['reviewer'], claims=check['claims'])
        bound.append(item)
    return {'schema_version': 2, 'manifest_sha256': _sha256(manifest_path), 'checks': bound,
            'limitations': limitations,
            'validation_scope': 'originals and current execution-source binding; TUI observation/authorization reviewed separately'}
