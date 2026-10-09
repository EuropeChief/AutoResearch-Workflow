"""One independent Codex runtime. No task stages or other-track dependencies."""
from __future__ import annotations

import copy
import hashlib
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import tempfile
import tomllib
import uuid

from .common import FlowError, _atomic_json, _canonical_digest, _read_json, _require, _sha256
from .runtime_profiles import load_profile, parameter_application, render_config
from .runtime_security import validate_security

FLOW_ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PARTS = {'.git', '.codex', '.autoresearch', '.autoresearch-flow', 'reference',
                 'optimization_evidence', 'hidden_assets', 'tests', 'auth'}


def _path(value, base):
    _require(isinstance(value, str) and value and '\x00' not in value,
             'INVALID_PATH', '须指定非空路径')
    path = Path(value)
    _require('..' not in path.parts, 'INVALID_PATH', '路径不能包含父目录跳转')
    path = path if path.is_absolute() else base / path
    # Reject symlink components before resolve, not only the final component.
    _require(not any(p.is_symlink() for p in [path, *path.parents]), 'INVALID_PATH', '输入路径不能经过符号链接')
    return path.resolve()


def _tree_files(path):
    _require(path.exists() and not path.is_symlink(), 'INVALID_PATH', '缺少合法普通输入')
    if path.is_file():
        return [path]
    _require(path.is_dir(), 'INVALID_PATH', '输入须为普通文件或目录')
    result = []
    for child in sorted(path.rglob('*')):
        _require(not child.is_symlink(), 'INVALID_PATH', '提交/公开输入不能夹入符号链接')
        _require(child.is_file() or child.is_dir(), 'INVALID_PATH', '不复制设备、socket 或特殊文件')
        if child.is_file():
            result.append(child)
    return result


def _copy_input(source, target, readonly=False):
    if source.is_dir():
        target.mkdir(parents=True)
        for file in _tree_files(source):
            destination = target / file.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, destination)
            destination.chmod((0o555 if readonly else 0o755) if os.access(file, os.X_OK) else (0o444 if readonly else 0o644))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod((0o555 if readonly else 0o755) if os.access(source, os.X_OK) else (0o444 if readonly else 0o644))


def _validate(config, base, output, model):
    allowed = {'schema_version', 'track', 'image', 'codex_version', 'model_profile', 'candidate', 'prompt',
               'public_files', 'private_paths', 'evaluation', 'resources', 'duration', 'purpose', 'security', 'codex_vendor'}
    _require(isinstance(config, dict) and config.get('schema_version') == 3 and set(config) <= allowed,
             'INVALID_RUNTIME', '独立运行配置 schema_version 须为 3，且不含旧状态/内联凭据字段')
    _require(config.get('track') in {'codex', 'seed'}, 'INVALID_TRACK', '须显式指定本轨 codex 或 seed')
    _require(re.fullmatch(r'(?:[\w./:-]+@)?sha256:[0-9a-f]{64}', str(config.get('image', ''))),
             'IMAGE_NOT_PINNED', '须指定镜像 ID 或 digest，不使用漂移 tag')
    _require(re.fullmatch(r'\d+\.\d+\.\d+', str(config.get('codex_version', ''))),
             'INVALID_RUNTIME', '须指定 Codex 支持版本')
    _require(config.get('purpose', 'formal') in {'formal', 'preflight'}, 'INVALID_RUNTIME', '运行用途不合法')
    evaluation = config.get('evaluation')
    _require(isinstance(evaluation, dict) and set(evaluation) <= {'command', 'mode', 'timeout_seconds', 'max_candidate_bytes'}
             and evaluation.get('mode', 'direct') in {'direct', 'worker'}, 'INVALID_EVALUATOR', '须指定公开执行模式')
    command = evaluation.get('command')
    _require(isinstance(command, list) and command and all(isinstance(x, str) and x and '\x00' not in x for x in command),
             'INVALID_EVALUATOR', '固定公开命令须为参数列表')
    for argument in command[:2]:
        if argument.startswith('/'):
            p = Path(argument)
            _require('..' not in p.parts and not any(p.is_relative_to(x) for x in
                     ['/workspace/solution', '/expert_evidence', '/codex', '/tmp', '/worker_jobs']),
                     'INVALID_EVALUATOR', '公开命令/解释器入口不能来自候选或其他可写区域')
    _require(Path(command[0]).is_absolute(), 'INVALID_EVALUATOR', '公开命令须指定绝对可执行位置')
    if Path(command[0]).name.startswith(('python', 'pypy')) or Path(command[0]).name in {'sh', 'bash', 'node'}:
        _require(len(command) > 1 and command[1].startswith('/'),
                 'INVALID_EVALUATOR', '解释器须直接执行固定只读脚本，不接受 -c/-m')
    if 'timeout_seconds' in evaluation:
        _require(type(evaluation['timeout_seconds']) is int and evaluation['timeout_seconds'] > 0,
                 'INVALID_EVALUATOR', '可选 timeout 是题目单作业限制，不是整轨墙钟')
    if 'max_candidate_bytes' in evaluation:
        _require(type(evaluation['max_candidate_bytes']) is int and evaluation['max_candidate_bytes'] > 0,
                 'INVALID_EVALUATOR','候选体积上限须为正整数，可按题目模型产物调整')
    resources = config.get('resources')
    _require(isinstance(resources, dict) and set(resources) == {'cpus', 'memory', 'gpu_ids'},
             'INVALID_RESOURCES', '本轨资源须为 cpus/memory/gpu_ids')
    _require(type(resources['cpus']) in (int, float) and math.isfinite(resources['cpus']) and resources['cpus'] > 0,
             'INVALID_RESOURCES', 'CPU 数须为正数')
    _require(isinstance(resources['memory'], str) and re.fullmatch(r'[1-9][0-9]*[mMgG]', resources['memory']),
             'INVALID_RESOURCES', 'memory 须为如 2g')
    ids = resources['gpu_ids']
    _require(isinstance(ids, list) and all(isinstance(x, str) and re.fullmatch(r'\d+', x) for x in ids)
             and len(ids) == len(set(ids)), 'INVALID_RESOURCES', 'GPU 是本轨显式非重复索引列表，CPU 使用 []')
    config['security'] = validate_security(config.get('security', {'mode': 'default'}))
    if 'codex_vendor' in config:
        vendor = _path(config['codex_vendor'], base)
        _require((vendor / 'bin/codex').is_file(), 'CODEX_MISSING', 'codex_vendor 须为本机 Codex vendor 目录')
        config['codex_vendor'] = str(vendor)
    duration = config.get('duration', {'minimum_seconds': 36000})
    _require(isinstance(duration, dict) and set(duration) <= {'minimum_seconds', 'qualification'}
             and duration.get('minimum_seconds') in {25200, 36000}, 'INVALID_DURATION', '正式最低净时长为 10h 或有据 7h')
    if duration['minimum_seconds'] == 25200:
        _require(isinstance(duration.get('qualification'), str), 'INVALID_DURATION', '7h 例外须引用实际资格说明')
        qualification = _path(duration['qualification'], base)
        _require(qualification.is_file() and qualification.stat().st_size > 0,
                 'INVALID_DURATION', '缺少非训练短迭代资格说明；不能事后降格')
    config['duration'] = duration
    _require(isinstance(config.get('public_files'), list), 'INVALID_RUNTIME', 'public_files 须为列表')
    _require(isinstance(config.get('private_paths', []), list), 'INVALID_RUNTIME', 'private_paths 须为显式路径列表')
    private = [_path(x, base) for x in config.get('private_paths', [])]
    private += [_path(config['model_profile'], base), Path(model['auth_ref']['path']).resolve()]
    candidate = _path(config['candidate'], base)
    prompt = _path(config['prompt'], base)
    _require(candidate.is_dir() and prompt.is_file(), 'INVALID_RUNTIME', '须指定候选目录及 Prompt 普通文件')
    mappings, destinations = [], []
    for item in config['public_files']:
        _require(isinstance(item, dict) and set(item) == {'source', 'destination'}, 'INVALID_RUNTIME', '公开映射须含 source/destination')
        source = _path(item['source'], base)
        destination = Path(item['destination'])
        _require(not destination.is_absolute() and destination.parts and '..' not in destination.parts
                 and not set(destination.parts) & PRIVATE_PARTS
                 and destination.parts[0] not in {'solution', 'evaluate', 'runtime', 'output'},
                 'INVALID_PATH', '公开目标须为合法非保留相对位置')
        _require(not any(destination.is_relative_to(d) or d.is_relative_to(destination) for d in destinations),
                 'DUPLICATE_PATH', '公开挂载目标不能重叠')
        destinations.append(destination)
        mappings.append((source, destination))
    for source in [candidate, *(s for s, _ in mappings)]:
        _require(not output.is_relative_to(source) and not source.is_relative_to(output),
                 'INVALID_PATH', '运行输出不能与复制输入重叠')
        for file in _tree_files(source):
            _require(not set(file.relative_to(base).parts if file.is_relative_to(base) else file.parts) & PRIVATE_PARTS,
                     'PRIVATE_ASSET', '候选/公开输入包含私有目录或 Git/配置线索')
            _require(not any(file.is_relative_to(p) or p.is_relative_to(file) for p in private),
                     'PRIVATE_ASSET', '候选/公开映射不能包含认证、模型资料或明确私有资产')
    return candidate, prompt, mappings


class TrackRuntime:
    def __init__(self, directory):
        self.directory = _path(str(directory), Path.cwd())

    @classmethod
    def prepare(cls, requested, output, *, base_dir):
        base = Path(base_dir).resolve()
        output = _path(str(output), base)
        _require(not output.exists(), 'RUNTIME_EXISTS', '不覆盖已有本轨运行目录')
        _require(isinstance(requested, dict) and isinstance(requested.get('model_profile'), str),
                 'INVALID_RUNTIME', '须提供本轨模型资料引用')
        model, profile_source = load_profile(_path(requested['model_profile'], base))
        config = copy.deepcopy(requested)
        candidate, prompt, mappings = _validate(config, base, output, model)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.track-prepare-', dir=output.parent))
        try:
            temporary.chmod(0o700)
            for name in ['public', 'solution', 'output', 'codex_home', 'jobs', 'logs', 'implementation']:
                (temporary / name).mkdir(mode=0o700 if name in {'codex_home', 'logs'} else 0o755)
            (temporary / 'solution').rmdir()
            _copy_input(candidate, temporary / 'solution')
            for source, destination in mappings:
                _copy_input(source, temporary / 'public' / destination, readonly=True)
            # Nested rw bind target must exist before its readonly parent mount.
            (temporary / 'public/solution').mkdir()
            if config['evaluation'].get('mode', 'direct') == 'worker':
                _copy_input(FLOW_ROOT / 'autoresearch_flow/assets/evaluate.py',
                            temporary / 'public/evaluate.py', readonly=True)
            if config.get('codex_vendor'):
                _copy_input(Path(config['codex_vendor']), temporary/'codex_runtime',readonly=True)
            prompt_text=prompt.read_text(encoding='utf-8')
            seconds=config['duration']['minimum_seconds']
            duration=(f'本轨净有效迭代至少 {seconds//3600} 小时；以只读 /run/autoresearch/responses/progress.json 查询进度。'
                      '由你自主收口，不以最终提升为必须条件，不把外部中断墙钟算入有效时间。')
            if config['evaluation'].get('mode','direct')=='worker':
                entry=('python /workspace/evaluate.py submit；保存 job_id 后用 '
                       'python /workspace/evaluate.py status 或 logs 或 result --job-id 原ID 查询，'
                       '等待终态并用 result 的真实 raw_metric/score 比较，不重复提交健康作业。')
            else:
                entry=shlex.join([a.replace('{candidate}','/workspace/solution').replace('{output}','/expert_evidence/evaluation')
                                  for a in config['evaluation']['command']])
            prompt_text=prompt_text.replace('{{DURATION_REQUIREMENT}}',duration).replace('{{PUBLIC_EVALUATION}}',entry)
            (temporary/'prompt.md').write_text(prompt_text,encoding='utf-8')
            (temporary / 'prompt.md').chmod(0o444)
            config['model'] = model
            config['profile_source'] = profile_source
            config['instance_id'] = uuid.uuid4().hex
            config['candidate'] = str(candidate)
            config['prompt'] = str(prompt)
            _atomic_json(temporary / 'config.json', config)
            rendered = render_config(model, readable=['/workspace', '/run/autoresearch/responses'],
                                     writable=['/workspace/solution', '/expert_evidence', '/tmp', '/run/autoresearch/requests'],
                                     denied=['/workspace/runtime', '/runtime', '/worker_jobs'])
            (temporary / 'codex_home/config.toml').write_text(rendered, encoding='utf-8')
            (temporary / 'codex_home/config.toml').chmod(0o444)
            (temporary / 'codex_home/config.frozen.toml').write_text(rendered,encoding='utf-8')
            (temporary / 'codex_home/config.frozen.toml').chmod(0o444)
            # Each instance executes a frozen source copy, never a live shared update.
            package = temporary / 'implementation/autoresearch_flow'
            package.mkdir()
            for file in sorted((FLOW_ROOT / 'autoresearch_flow').glob('*.py')):
                shutil.copyfile(file, package / file.name)
                (package / file.name).chmod(0o444)
            assets = FLOW_ROOT / 'autoresearch_flow/assets'
            if assets.is_dir():
                _copy_input(assets, package / 'assets', readonly=True)
            shutil.copyfile(FLOW_ROOT / 'cli.py', temporary / 'implementation/cli.py')
            (temporary / 'implementation/cli.py').chmod(0o444)
            refs = {}
            groups=['public', 'implementation'] + (['codex_runtime'] if config.get('codex_vendor') else [])
            for group in groups:
                for file in _tree_files(temporary / group):
                    refs[str(file.relative_to(temporary))] = _sha256(file)
            for name in ['config.json', 'prompt.md', 'codex_home/config.frozen.toml']:
                refs[name] = _sha256(temporary / name)
            code_digest = _canonical_digest({k: v for k, v in refs.items() if k.startswith('implementation/')})
            _atomic_json(temporary / 'snapshot.json', {'schema_version': 1, 'files': refs,
                                                     'implementation_sha256': code_digest})
            _atomic_json(temporary / 'state.json', {'schema_version': 1, 'status': 'prepared',
                                                  'thread_id': None, 'goal': None, 'segments': []})
            temporary.rename(output)
        except BaseException:
            shutil.rmtree(temporary)
            raise
        return cls(output)

    def _load(self):
        _require(self.directory.is_dir() and not self.directory.is_symlink(), 'RUNTIME_MISSING', '缺少本轨运行目录')
        snapshot = _read_json(self.directory / 'snapshot.json')
        for name, digest in snapshot['files'].items():
            path = self.directory / name
            _require(not Path(name).is_absolute() and '..' not in Path(name).parts
                     and path.is_file() and not path.is_symlink() and _sha256(path) == digest,
                     'RUNTIME_DRIFT', '本轨冻结文件发生变化：' + name)
        expected = tomllib.loads((self.directory/'codex_home/config.frozen.toml').read_text())
        actual = tomllib.loads((self.directory/'codex_home/config.toml').read_text())
        # Native TUI records display acknowledgements/preferences in its home.
        # These are not research/security/model configuration drift.
        for section in ['tui','notice']:
            actual.pop(section,None)
            expected.pop(section,None)
        _require(actual == expected,'RUNTIME_DRIFT','本轨有效模型/权限配置改变；原生显示偏好除外')
        return _read_json(self.directory / 'config.json'), _read_json(self.directory / 'state.json'), snapshot

    def status(self):
        config, state, snapshot = self._load()
        return {'status': state['status'], 'track': config['track'], 'instance_id': config['instance_id'],
                'runtime_dir': str(self.directory), 'thread_id': state['thread_id'], 'goal': state['goal'],
                'implementation_sha256': snapshot['implementation_sha256'],
                'model_parameters': parameter_application(config['model']),
                'minimum_seconds': config['duration']['minimum_seconds'], 'purpose': config.get('purpose', 'formal')}
