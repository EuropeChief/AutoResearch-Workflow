"""Prepare a new, isolated CPU Seed pilot; never overwrite an existing run."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parent
FLOW = ROOT.parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import Registry, TaskStore, _atomic_json, _sha256
from autoresearch_flow.runtime import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('label')
    parser.add_argument('--allow-authorized-apparmor-exception', action='store_true')
    args = parser.parse_args()
    assert re.fullmatch('[a-zA-Z0-9_-]+', args.label)
    root = ROOT/'runs'/args.label
    root.mkdir(parents=True, exist_ok=False)
    task = root/'harbor_task'
    task.mkdir()
    for name in ('environment', 'tests'):
        shutil.copytree(ROOT/name, task/name, ignore=shutil.ignore_patterns('__pycache__'))
    shutil.copy2(ROOT/'instruction.md', task/'instruction.md')
    template = (ROOT/'task.toml').read_text()
    old = tomllib.loads(template)
    image = subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',
                                    'autoresearch-pca:codex-pilot-20260930'], text=True).strip()
    verifier = 'sha256:2ba743f8dda40a36618ace26aa438a6ae6c9cfc52ecf28ad48f8d67dc4e8c65e'
    template = template.replace(old['environment']['docker_image'], image)
    template = template.replace(old['verifier']['environment']['docker_image'], verifier)
    template = template.replace('memory_mb = 512', 'memory_mb = 1024', 1)
    template = template.replace('network_mode = "no-network"', 'network_mode = "public"', 1)
    (task/'task.toml').write_text(template)
    (root/'prompt.md').write_text('''这是合成 CPU 运行底座联调，不是正式科研轨迹，不需要等待十小时。
请阅读 /workspace/instruction.md，运行 /workspace/evaluate。仅在 /workspace/solution/method.py 内进行一个保持功能的实现改写，再真实评测。
每次完成一轮，请向 /expert_evidence/trajectory.jsonl 追加一行 JSON，恰含八字段：round（从1递增）、policy_name、method_summary（中文）、status（成功ok）、score（公开raw_metric.value）、failure_reason（成功null）、retained_best（布尔）、time（YYYY-MM-DD HH:mm:ss）。
维护 /expert_evidence/best_method/method.py，确保最佳代码与 /workspace/solution/method.py 一致。结束前复测并恢复最佳候选。每次收到继续指令再做一轮；不要空等，不尝试读取私有目录或凭据。本次只完成一轮，然后结束回答。
''')
    ref = lambda path: {'path': str(path.relative_to(root)), 'sha256': _sha256(path)}
    config = {'schema_version': 2, 'image': image, 'codex_version': '0.147.0',
              'public_files': [{'source': ref(task/'instruction.md'), 'destination': 'instruction.md'}],
              'starter_files': [{'source': ref(task/'environment/starter/method.py'), 'destination': 'method.py'}],
              'prompt': ref(root/'prompt.md'),
              'evaluation': {'command': ['/opt/conda/bin/python3', '/workspace/public_eval/evaluate.py'],
                             'timeout_seconds': 120},
              'boundaries': {'readable': ['/workspace/instruction.md'],
                             'readonly': ['/workspace/starter', '/workspace/public_eval'],
                             'unreadable': ['/tests', '/var/run/docker.sock']},
              'resources': {'cpus': 1, 'memory': '1g', 'gpus': {'codex': None, 'seed': None}},
              'harness': {'version': '0.23.0', 'executable': str(ROOT/'build/harbor-venv/bin/harbor'),
                          'docker_config': str(ROOT/'build/docker-config'), 'task': 'harbor_task'}}
    if args.allow_authorized_apparmor_exception:
        approval = root/'approval.md'
        approval.write_text('2026-09-30，用户针对本次新版 Seed CPU 短联调确认：允许，仅限本次 CPU 短联调。\n'
                            '仅 apparmor=unconfined + 既有受限 seccomp；保留非 root Codex、只读面、Codex 沙箱；不修改宿主、不用于正式题目。\n')
        shutil.copy2(FLOW/'pilots/seed_cpu/docker-codex-nested.json', root/'seccomp.json')
        config['docker_security'] = {'apparmor': 'unconfined', 'seccomp': ref(root/'seccomp.json'),
                                     'approval': ref(approval)}
    _atomic_json(root/'runtime.json', config)
    TaskStore(root).initialize(Registry(), 'pca-seed-cpu-pilot')
    Runtime(root).prepare(config)
    print(json.dumps({'root': str(root), 'image': image, 'model_calls': 0}))


if __name__ == '__main__':
    main()
