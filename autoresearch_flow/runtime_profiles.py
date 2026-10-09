"""Explicit one-model configuration; preparation never reads credentials."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import tomllib
from urllib.parse import urlsplit

from .common import FlowError, _require, _sha256


def load_profile(path: Path) -> tuple[dict, dict]:
    _require(path.is_file() and not path.is_symlink(), 'PROFILE_MISSING', '须指定本轨普通 TOML 模型文件')
    try:
        raw = path.read_bytes()
        model = tomllib.loads(raw.decode('utf-8'))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise FlowError('PROFILE_INVALID', '无法解析本轨模型 TOML') from exc
    _require(model.pop('schema_version', None) == 1, 'PROFILE_INVALID', '模型 TOML schema_version 须为 1')
    allowed = {'model', 'reasoning_effort', 'base_url', 'auth_ref', 'context_window',
               'auto_compact_token_limit', 'max_output_tokens'}
    _require(set(model) <= allowed, 'PROFILE_INVALID', '模型参数包含未知字段，不接受内联鉴权')
    _require(isinstance(model.get('model'), str) and model['model'].strip(), 'PROFILE_INVALID', '须指定模型 ID')
    _require(model.get('reasoning_effort') in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'},
             'PROFILE_INVALID', '须指定模型推理档位')
    auth = model.get('auth_ref')
    _require(isinstance(auth, dict) and set(auth) <= {'kind', 'path', 'key'}
             and auth.get('kind') in {'api_key_json', 'codex_login'}
             and isinstance(auth.get('path'), str) and Path(auth['path']).is_absolute(),
             'INVALID_AUTH', '鉴权须为显式绝对文件引用，不使用当前专家会话凭据')
    if auth['kind'] == 'api_key_json':
        _require(isinstance(auth.get('key'), str) and auth['key'], 'INVALID_AUTH', '须指定 JSON key 字段')
        url = urlsplit(model.get('base_url', ''))
        _require(url.scheme == 'https' and url.netloc and not url.username and not url.password
                 and not url.query and not url.fragment, 'INVALID_PROVIDER', 'API URL 须为无鉴权参数的 HTTPS 地址')
    else:
        _require(not model.get('base_url'), 'INVALID_PROVIDER', '登录凭据不覆盖默认 provider')
    fields = ('context_window', 'auto_compact_token_limit', 'max_output_tokens')
    if any(field in model for field in fields):
        _require(all(type(model.get(field)) is int and model[field] > 0 for field in fields),
                 'INVALID_CONTEXT', '上下文、压缩和输出余量须同时提供正整数')
        _require(model['auto_compact_token_limit'] + model['max_output_tokens'] < model['context_window'],
                 'INVALID_CONTEXT', '压缩须为输出和协议开销预留空间')
    return model, {'path': str(path.resolve()), 'sha256': hashlib.sha256(raw).hexdigest()}


def render_config(model: dict, *, readable=(), writable=(), denied=()) -> str:
    """No credential values; output capacity is validation, not a server knob."""
    q = lambda value: json.dumps(value, ensure_ascii=False)
    lines = [f'model = {q(model["model"])}',
             f'model_reasoning_effort = {q(model["reasoning_effort"])}',
             'approval_policy = "never"', 'default_permissions = "autoresearch"',
             'cli_auth_credentials_store = "file"']
    for field, key in [('context_window', 'model_context_window'),
                       ('auto_compact_token_limit', 'model_auto_compact_token_limit')]:
        if field in model:
            lines.append(f'{key} = {model[field]}')
    lines.extend(['[features]', 'goals = true'])
    if model['auth_ref']['kind'] == 'api_key_json':
        # Provider selection is a root field, not a field under [features].
        lines.insert(0, 'model_provider = "autoresearch"')
        lines.extend(['[model_providers.autoresearch]', 'name = "AutoResearch configured provider"',
                      f'base_url = {q(model["base_url"])}', 'wire_api = "responses"',
                      'requires_openai_auth = true'])
    lines.extend(['[projects."/workspace/solution"]', 'trust_level = "trusted"',
                  '[shell_environment_policy]', 'inherit = "all"',
                  'include_only = ["PATH", "LANG", "LC_ALL", "TERM", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES"]',
                  '[permissions.autoresearch.filesystem]', '":minimal" = "read"'])
    paths = {p: 'read' for p in ('/usr', '/opt', '/bin', '/sbin', '/lib', '/lib64', '/etc', '/proc', '/sys', *readable)}
    paths.update({p: 'write' for p in writable})
    paths.update({p: 'deny' for p in ('/codex', '/tests', '/reference', '/optimization_evidence', *denied)})
    lines.extend(f'{q(path)} = {q(access)}' for path, access in paths.items())
    lines.extend(['[permissions.autoresearch.network]', 'enabled = false'])
    return '\n'.join(lines) + '\n'


def parameter_application(model: dict) -> dict:
    mapping = {'context_window': 'model_context_window', 'auto_compact_token_limit': 'model_auto_compact_token_limit',
               'max_output_tokens': 'compaction_headroom_validation'}
    return {field: {'value': model[field], 'application': application}
            for field, application in mapping.items() if field in model}


def acknowledge_kept_model(path: Path, model: str, catalog: dict) -> dict | None:
    """Acknowledge native UI marketing without changing the explicit model.

    model/list supplies the advertised target; never hard-code model generations
    or select that target. This runs only before a fresh thread is created.
    """
    if not isinstance(catalog, dict) or not isinstance(catalog.get('data'), list):
        return None
    entry = next((m for m in catalog['data'] if isinstance(m, dict) and m.get('model') == model), {})
    target = entry.get('upgrade')
    if not isinstance(target, str) or not target or target == model:
        return None
    actual = tomllib.loads(path.read_text())
    _require(actual.get('model') == model, 'RUNTIME_DRIFT', '可视化提示处理不能更改本轨模型')
    # Do not overwrite existing native acknowledgements/preferences.
    if 'notice' not in actual:
        with path.open('a', encoding='utf-8') as stream:
            stream.write('\n[notice.model_migrations]\n' + json.dumps(model) + ' = ' + json.dumps(target) + '\n')
    return {'configured_model': model, 'advertised_upgrade': target,
            'effective_model_changed': False, 'notice_only': True}
