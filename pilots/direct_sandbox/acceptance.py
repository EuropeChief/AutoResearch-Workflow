"""Bounded synthetic in-sandbox execution; no model calls or training."""
import argparse
import asyncio
import json
from pathlib import Path
import shlex
import sys

FLOW = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.common import _atomic_json, _require
from autoresearch_flow.runtime_container import NativeContainer
from autoresearch_flow.track_runtime import TrackRuntime

DEADLINE_SECONDS = 60


async def run(args):
    _require(args.allow_live, 'LIVE_PERMISSION', '须明确允许本次有界容器联调')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / 'starter').mkdir()
    (out / 'starter/method.py').write_text('VALUE=2\n')
    (out / 'prompt.md').write_text('有界组件联调；不调用模型，不训练。')
    config = {'schema_version': 3, 'track': 'seed', 'image': args.image,
              'codex_version': '0.160.0', 'codex_vendor': str(args.codex_vendor.resolve()),
              'model_profile': str(args.profile.resolve()), 'purpose': 'acceptance',
              'candidate': 'starter', 'prompt': 'prompt.md',
              'public_files': [{'source': str(FLOW / 'pilots/lp5_runtime/runner.py'),
                                'destination': 'public_eval/runner.py'}],
              'evaluation': {'mode': 'direct', 'command': ['/opt/conda/bin/python',
                  '/workspace/public_eval/runner.py', '--candidate', '{candidate}',
                  '--output', '{output}', '--delay', '0.1'] + (['--gpu'] if args.gpu_id else []),
                  'timeout_seconds': 30},
              'resources': {'cpus': 1, 'memory': '2g', 'gpu_ids': [args.gpu_id] if args.gpu_id else []},
              'security': {'mode': 'default'}}
    if args.security_authorization:
        config['security'] = {'mode': 'codex_nested', 'authorization': args.security_authorization}
    runtime = TrackRuntime.prepare(config, out / 'runtime', base_dir=out)
    container = NativeContainer(runtime)
    report = {'status': 'failed', 'model_calls': 0, 'training_runs': 0,
              'image': args.image, 'gpu_ids': config['resources']['gpu_ids'],
              'deadline_seconds': DEADLINE_SECONDS}
    async def exercise():
        await container.start()
        auth = runtime.directory / 'codex_home/auth.json'
        auth.write_text('{"synthetic_auth_marker":true}')
        auth.chmod(0o600)
        report['sandbox'] = await container.preflight()
        command = shlex.join([container.codex, 'sandbox', '-C', '/workspace/solution', '-P',
                              'autoresearch', '--', '/workspace/evaluate'])
        result = await container.exec_agent(command, timeout=40)
        report['execution'] = {'exit_code': result.return_code, 'stdout': result.stdout, 'stderr': result.stderr}
        _require(result.return_code == 0, 'DIRECT_EXECUTION', '直接评分失败，保留实际输出')
        final = json.loads(result.stdout.splitlines()[-1])
        _require(final['raw_metric']['value'] == (131072.0 if args.gpu_id else 4.0),
                 'DIRECT_RESULT', '实际运算不符合合成协议')
        _require(final['evaluation_binding']['candidate_before_sha256'] ==
                 final['evaluation_binding']['candidate_after_sha256'], 'CANDIDATE_DRIFT', '评测期间候选变化')
        report.update(status='passed', result=final,
                      artifact_written=(runtime.directory / 'output/evaluation/artifact.json').is_file())
    try:
        async with asyncio.timeout(DEADLINE_SECONDS):
            await exercise()
    except Exception as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        try:
            _atomic_json(out / 'report.json', report)
        finally:
            await container.stop()
    print(json.dumps({'status': report['status'], 'report': str(out / 'report.json')}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--image', required=True)
    parser.add_argument('--codex-vendor', type=Path, required=True)
    parser.add_argument('--profile', type=Path, required=True, help='仅读配置，不读取其鉴权文件')
    parser.add_argument('--gpu-id', help='本次获准的空闲 GPU 索引；未指定则仅CPU')
    parser.add_argument('--allow-live', action='store_true')
    parser.add_argument('--security-authorization', help='仅本次已明确授权的兼容模式范围原话')
    asyncio.run(run(parser.parse_args()))


if __name__ == '__main__':
    main()
