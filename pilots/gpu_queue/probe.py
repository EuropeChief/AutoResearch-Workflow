"""Opt-in, bounded maintainer GPU queue probe; never a scientific task result."""
import argparse
import copy
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import sys

HERE = Path(__file__).resolve().parent
FLOW = HERE.parents[1]
RUNS = HERE/'runs'
sys.path.insert(0, str(FLOW))
from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import Registry, TaskStore, _atomic_json, _sha256
from autoresearch_flow.experiments import ExperimentBook
from autoresearch_flow.experiment_runner import ExperimentRunner
from tools.release_check import payload_files, source_snapshot
from tools.release_evidence import checked_ref, source_scope, require, _gpu_result


def ref(root, path):
    return {'path': path.relative_to(root).as_posix(), 'sha256': _sha256(path)}


def location(label):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', label):
        raise ValueError('label must be a simple, new pilot name')
    return RUNS/label


def prepare(label, gpu_ids, python, approval):
    root = location(label)
    if (not 1 <= len(gpu_ids) <= 2 or len(set(gpu_ids)) != len(gpu_ids)
            or not all(re.fullmatch(r'[0-9]+', x) for x in gpu_ids)):
        raise ValueError('provide one or two explicitly authorized GPU indexes')
    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('provide an existing absolute Python executable with CUDA PyTorch')
    if not approval.is_file() or approval.is_symlink() or not approval.read_text().strip():
        raise ValueError('provide this run\'s actual nonempty approval file, not a symlink')
    root.mkdir(parents=True, exist_ok=False)
    TaskStore(root).initialize(Registry(), 'synthetic-gpu-queue')
    shutil.copyfile(approval, root/'approval.md')
    method = root/'.autoresearch-flow/delivery/best_versions/synthetic/method.py'
    method.parent.mkdir(parents=True)
    shutil.copyfile(HERE/'method.py', method)
    selection = method.parent/'selection.json'
    _atomic_json(selection, {'snapshot_files': [ref(root, method)],
                             'fixture_only': 'not an Agent selection or scientific acceptance'})
    _atomic_json(root/'.autoresearch-flow/delivery/best_current.json',
                 {'version': 'synthetic', 'selection_sha256': _sha256(selection)})
    shutil.copyfile(HERE/'cuda_adapter.py', root/'cuda_adapter.py')
    protocol = {'schema_version': 1, 'id': 'serial', 'split': 'synthetic',
                'metric': {'name': 'probe_value', 'direction': 'maximize'},
                'seeds': [1, 2, 3], 'training': False, 'evaluation_mode': 'random',
                'fixed': {'data': _sha256(method), 'preprocessing': _sha256(method),
                          'evaluator': _sha256(root/'cuda_adapter.py')},
                'budget': {'matmuls': {'mode': 'exact', 'value': 1, 'unit': 'operations'}},
                'rationale': 'Synthetic device/queue check, not Baseline/Reference or task acceptance.',
                'reload_tolerance': 0.0}
    plans = []
    for phase, parallel in [('serial', 1), ('parallel', len(gpu_ids))]:
        p = copy.deepcopy(protocol)
        p['id'] = phase
        ExperimentBook(root).lock(p)
        plan = {'schema_version': 1, 'id': phase, 'protocol_id': phase, 'seeds': p['seeds'],
                'selection': ref(root, selection), 'adapter_files': [ref(root, root/'cuda_adapter.py')],
                'command': [str(python), '{adapter_root}/cuda_adapter.py', '{request}'],
                'output_root': phase, 'timeout_seconds': 30,
                'resources': {'gpu_ids': gpu_ids, 'gpus_per_run': 1, 'max_parallel': parallel,
                              'cpu_threads': 1, 'metric_sensitive': False, 'hardware_sensitive': True,
                              'authorization': ref(root, root/'approval.md')}}
        path = root/(phase+'-plan.json')
        _atomic_json(path, plan)
        plans.append(ref(root, path))
    # Capture the source before any device execution, never back-date a new manifest.
    _atomic_json(root/'origin_sources.json', {'version': FLOW_VERSION, 'files': source_snapshot(payload_files())})
    _atomic_json(root/'probe.json', {'scope': 'synthetic_gpu_queue_probe', 'plans': plans,
                 'approval': ref(root, root/'approval.md'), 'gpu_ids': gpu_ids,
                 'origin_sources': ref(root, root/'origin_sources.json'),
                 'pilot_sources': {name: _sha256(HERE/name) for name in ('probe.py', 'cuda_adapter.py', 'method.py')},
                 'maximum_adapter_seconds': 180, 'automatic_retries': 0})
    return root


def summarize(root, gpu_ids, outputs):
    require(len(outputs) == 2 and all(x['status'] == 'ok' for x in outputs), 'incomplete queues')
    groups = [x['report']['groups']['best_method'] for x in outputs]
    require(groups[0] == groups[1] and groups[0]['count'] == 3, 'serial/parallel aggregates differ')
    runs, intervals, uuids = [], [], set()
    for output in outputs:
        require(len(output['run_directories']) == 3, 'missing seed outputs')
        for seed, relative in output['run_directories'].items():
            directory = root/relative
            request_ref = ref(root, directory/'request.json')
            run_record = json.loads(checked_ref(root, request_ref).read_text())['run']
            require(str(run_record['seed']) == seed, 'queue seed/request mismatch')
            run_id = run_record['run_id']
            execution_ref = ref(root, directory/'execution.json')
            cuda_ref = ref(root, directory/'cuda-result.json')
            execution = json.loads(checked_ref(root, execution_ref).read_text())
            cuda = json.loads(checked_ref(root, cuda_ref).read_text())
            inventory = execution['device_inventory']
            require(len(inventory) == 1 and inventory[0]['id'] in gpu_ids
                    and execution['devices'] == [inventory[0]['uuid']], 'unauthorized actual GPU')
            require(cuda.get('matmul_correct') is True, 'incorrect matrix product')
            start, end = [dt.datetime.fromisoformat(execution[key])
                          for key in ('started_at', 'finished_at')]
            require(start.tzinfo is not None and end.tzinfo is not None and start <= end,
                    'invalid execution interval')
            intervals.append((start, end, inventory[0]['uuid']))
            uuids.add(inventory[0]['uuid'])
            runs.append({'run_id': run_id, 'request': request_ref,
                         'execution': execution_ref, 'cuda_result': cuda_ref})
    cross_overlap = False
    for i, (start, end, device) in enumerate(intervals):
        for other_start, other_end, other_device in intervals[i+1:]:
            if max(start, other_start) < min(end, other_end):
                require(device != other_device, 'same-device jobs overlap')
                cross_overlap = True
    require(len(gpu_ids) == 1 or cross_overlap, 'no cross-device overlap observed')
    result = {'status': 'passed', 'scope': 'synthetic_gpu_queue_probe',
              'authorized_devices': sorted(uuids), 'runs': runs,
              'aggregate': groups[0], 'cross_device_overlap_observed': cross_overlap}
    _gpu_result(root, result)
    return result


def run(label):
    root = location(label)
    require(not root.is_symlink(), 'unsafe pilot directory')
    frozen = json.loads((root/'probe.json').read_text())
    require(frozen.get('scope') == 'synthetic_gpu_queue_probe', 'not a prepared synthetic pilot')
    checked_ref(root, frozen['approval'])
    original = json.loads(checked_ref(root, frozen['origin_sources']).read_text())
    current = {x['path']: x for x in source_snapshot(payload_files())}
    previous = {x['path']: x for x in original['files']}
    scope = source_scope(FLOW, payload_files(), 'gpu_dispatch', previous)
    require(all(current.get(n) == previous.get(n) for n in scope), 'queue source drift since preparation')
    require(all(_sha256(HERE/name) == digest for name, digest in frozen['pilot_sources'].items()),
            'pilot source drift since preparation')
    plans = [json.loads(checked_ref(root, x).read_text()) for x in frozen['plans']]
    require(len(plans) == 2 and 1 <= len(frozen['gpu_ids']) <= 2, 'invalid bounded plan')
    for phase, plan in zip(('serial', 'parallel'), plans):
        resources = plan['resources']
        require(plan['id'] == phase and plan['seeds'] == [1, 2, 3] and plan['timeout_seconds'] == 30
                and resources['gpu_ids'] == frozen['gpu_ids'] and resources['gpus_per_run'] == 1
                and resources['max_parallel'] == (1 if phase == 'serial' else len(frozen['gpu_ids'])),
                'bounded probe plan changed')
    if (root/'result.json').exists():
        result = json.loads((root/'result.json').read_text())
        _gpu_result(root, result)
        return result
    outputs = []
    for plan in plans:
        runner = ExperimentRunner(root)
        output = runner.execute(plan)
        _atomic_json(root/(plan['id']+'-queue.json'), output)
        if output['status'] != 'ok':
            return {'status': output['status'], 'phase': plan['id'],
                    'note': 'Original attempts retained; no automatic retry or extra budget.'}
        reused = runner.execute(plan)
        require(reused['status'] == 'ok' and not reused['launched']
                and reused['report']['groups'] == output['report']['groups'], 'completed queue relaunched or changed')
        outputs.append(output)
    result = summarize(root, frozen['gpu_ids'], outputs)
    result['completed_reused_without_launch'] = True
    result['approval'] = frozen['approval']
    result['origin_sources'] = frozen['origin_sources']
    _atomic_json(root/'result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    create = sub.add_parser('prepare', help='offline only; does not inspect or initialize CUDA')
    create.add_argument('label')
    create.add_argument('--gpu-ids', nargs='+', required=True)
    create.add_argument('--python-path', type=Path, required=True)
    create.add_argument('--approval', type=Path, required=True)
    execute = sub.add_parser('run')
    execute.add_argument('label')
    execute.add_argument('--allow-gpu', action='store_true')
    args = parser.parse_args()
    if args.action == 'run' and not args.allow_gpu:
        parser.error('actual device execution requires --allow-gpu and the prepared approval')
    if args.action == 'prepare':
        root = prepare(args.label, args.gpu_ids, args.python_path, args.approval)
        print(json.dumps({'status': 'prepared_not_run', 'root': str(root)}))
    else:
        result = run(args.label)
        print(json.dumps(result))
        return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
