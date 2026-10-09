"""CPU-only arithmetic or tiny CUDA arithmetic; no training or model calls."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import time

parser=argparse.ArgumentParser()
parser.add_argument('--candidate',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--gpu',action='store_true')
parser.add_argument('--delay',type=float,default=1.0)
args=parser.parse_args()
spec=importlib.util.spec_from_file_location('method',args.candidate/'method.py')
method=importlib.util.module_from_spec(spec)
spec.loader.exec_module(method)
print('PUBLIC_RUNNER_STARTED uid='+str(os.getuid()),flush=True)
time.sleep(args.delay)
value=method.VALUE
if args.gpu:
    import torch
    assert torch.cuda.is_available() and torch.cuda.device_count()==1
    x=torch.full((32,32),float(value),device='cuda:0')
    measured=float((x@x).sum())
else:
    measured=float(value*value)
args.output.mkdir(exist_ok=True)
(args.output/'artifact.json').write_text(json.dumps({'value':measured}))
print(json.dumps({'status':'succeeded','score':measured/100.0,
    'raw_metric':{'name':'synthetic_checksum','direction':'maximize','value':measured}}),flush=True)
