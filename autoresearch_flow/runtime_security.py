"""Container compatibility is explicit and scoped, never an automatic downgrade."""
from pathlib import Path
import re

from .common import _read_json, _require, _sha256

PROFILE = Path(__file__).with_name('assets') / 'docker-codex-nested.json'


def validate_security(value):
    _require(isinstance(value, dict), 'INVALID_SECURITY', 'security 须为对象')
    mode = value.get('mode')
    if mode == 'default':
        _require(set(value) == {'mode'}, 'INVALID_SECURITY', '默认策略不接受隐藏扩权配置')
    else:
        _require(mode == 'codex_nested' and set(value) == {'mode', 'authorization'}
                 and isinstance(value['authorization'], str) and value['authorization'].strip(),
                 'SECURITY_AUTHORIZATION_REQUIRED', '限定兼容模式须声明本次明确许可范围，不继承历史授权')
        profile = _read_json(PROFILE)
        _require(profile.get('defaultAction') == 'SCMP_ACT_ERRNO', 'INVALID_SECURITY', '兼容 seccomp 须保持默认拒绝')
    return value


def docker_security_options(value):
    validate_security(value)
    options = ['--security-opt', 'no-new-privileges', '--cap-drop', 'ALL']
    if value['mode'] == 'codex_nested':
        options += ['--security-opt', 'apparmor=unconfined', '--security-opt', 'seccomp=' + str(PROFILE)]
    return options


def compose_security_options(value):
    validate_security(value)
    result = {'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL']}
    if value['mode'] == 'codex_nested':
        result['security_opt'] += ['apparmor=unconfined', 'seccomp=' + PROFILE.read_text()]
    return result


def classify_sandbox_result(exit_code, stdout, stderr):
    """Report only observed stages; failure never enables the compatibility mode."""
    text = stdout + '\n' + stderr
    if exit_code == 0:
        return {'status': 'succeeded', 'stage': 'sandbox_command'}
    if re.search(r'unshare|(?:Failed|No permissions) to create.*namespace|CLONE_NEWUSER', text, re.I):
        stage = 'namespace'
    elif re.search(r'mount|/\.git', text, re.I):
        stage = 'mount'
    elif re.search(r'Permission denied|Operation not permitted', text, re.I):
        stage = 'access'
    else:
        stage = 'unknown'
    return {'status': 'blocked', 'stage': stage, 'exit_code': exit_code,
            'next_action': '只检查受影响路径；默认失败不自动放宽权限'}


def compatibility_identity(value):
    validate_security(value)
    return {'mode': value['mode'], 'seccomp_sha256': _sha256(PROFILE) if value['mode'] == 'codex_nested' else None}
