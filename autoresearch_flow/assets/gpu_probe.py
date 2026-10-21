"""Bounded CUDA arithmetic inside the Agent sandbox, using provider prerequisites."""
import json
import sys


def probe(expected):
    # The existing GPU provider already requires a CUDA PyTorch image.
    import torch
    if not torch.cuda.is_available() or torch.cuda.device_count() != expected:
        raise RuntimeError('visible CUDA devices differ from the allocated count')
    devices = []
    for index in range(expected):
        x = torch.ones((32, 32), device=f'cuda:{index}')
        value = float((x @ x).sum())
        if value != 32768.0:
            raise RuntimeError('CUDA arithmetic returned an incorrect value')
        devices.append({'index': index, 'name': torch.cuda.get_device_name(index), 'kernel_result': value})
    return {'status': 'succeeded', 'devices': devices, 'execution': 'agent_sandbox'}


if __name__ == '__main__':
    try:
        print(json.dumps(probe(int(sys.argv[1]))))
    except Exception as exc:
        print(json.dumps({'status': 'blocked', 'error': str(exc)}))
        raise SystemExit(1)
