"""Queue adapter: one small CUDA matmul, actual UUID and finite-result evidence."""
import importlib.util
import json
import os
from pathlib import Path
import random
import sys
import uuid


def evaluate(request):
    assigned = request['assigned_devices']
    if len(assigned) != 1 or os.environ.get('CUDA_VISIBLE_DEVICES') != assigned[0]:
        raise ValueError('expected exactly one queue-assigned CUDA UUID')
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError('CUDA unavailable or more than one device exposed')
    raw_uuid = str(torch.cuda.get_device_properties(0).uuid)
    # PyTorch returns a bare UUID; nvidia-smi/CUDA_VISIBLE_DEVICES use GPU-UUID.
    # Canonicalize the observed value, never substitute the requested device.
    try:
        actual = 'GPU-' + str(uuid.UUID(raw_uuid.removeprefix('GPU-')))
    except ValueError as error:
        raise RuntimeError(f'actual CUDA device {raw_uuid} differs from a valid GPU UUID') from error
    if actual != assigned[0]:
        raise RuntimeError(f'actual CUDA device {actual} differs from queue assignment')
    seed = request['run']['seed']
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.set_num_threads(1)
    spec = importlib.util.spec_from_file_location('synthetic_method', Path(request['method_directory'])/'method.py')
    method = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(method)
    expected, value = method.evaluate(torch)
    torch.cuda.synchronize()
    finite = bool(torch.isfinite(value).all().item())
    correct = finite and bool(torch.equal(expected, value))
    output = Path(request['output_directory'])
    cuda = {'cuda_available': True, 'matmul_finite': finite, 'matmul_correct': correct,
            'visible_devices': [actual], 'observed_cuda_uuid': raw_uuid,
            'torch_version': torch.__version__, 'seed': seed}
    (output/'cuda-result.json').write_text(json.dumps(cuda)+'\n')
    if not correct:
        raise RuntimeError('CUDA identity-matrix product is incorrect or non-finite')
    run = request['run']
    result = {key: run[key] for key in ('seed', 'role', 'method_sha256', 'seed_plan_sha256', 'protocol_sha256')}
    result.update(status='succeeded', raw_metric=float(value[0, 0].item()), quality_passed=True,
                  fixed=request['protocol']['fixed'], actual_budget={'matmuls': 1}, devices=[actual])
    (output/'adapter-result.json').write_text(json.dumps(result)+'\n')
    print(json.dumps(cuda), flush=True)


if __name__ == '__main__':
    evaluate(json.loads(Path(sys.argv[1]).read_text()))
