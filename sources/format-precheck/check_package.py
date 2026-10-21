#!/usr/bin/env python3
"""提交包轻量前置检查。Python 3.11+；独立脚本，不调用模型、不运行题包。"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import lzma
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
import zlib

if sys.version_info < (3, 11):
    raise SystemExit("请使用 Python 3.11 或以上版本。")

def _load_preflight_artifacts():
    """Conservative, read-only checks for the separate-Verifier transfer contract.
    
    Harbor's default /logs/artifacts source remains valid when artifacts is omitted
    or empty. Explicit entries may be strings or objects with an absolute source;
    destination names a host collection location, never a Verifier path remapping.
    Only explicit contracts and simple shell candidate arguments can establish a
    blocking mismatch. Python source hints and complex shell control flow remain
    warnings because this precheck does not prove which entry or branch executes.
    Dynamic glob/exclude/service policies and unlocated reads also remain warnings.
    This module does not execute scripts, import task code or inspect
    expert snapshots, and does not assume all tasks submit /workspace/solution.
    """
    
    import ast
    from pathlib import Path, PurePosixPath
    import posixpath
    import re
    import shlex
    
    ARTIFACT_TEXT_LIMIT = 2 * 1024 * 1024
    ARTIFACT_PYTHON_LIMIT = 128
    _FLAGS = {
        '--submission', '--submission-dir', '--submission_dir', '--submission-path',
        '--submission_path', '--submission-file', '--submission_file',
        '--candidate', '--candidate-dir', '--candidate_dir', '--candidate-path',
        '--candidate_path', '--candidate-file', '--candidate_file',
        '--solution', '--solution-dir', '--solution_dir', '--solution-path',
        '--solution_path', '--solution-file', '--solution_file',
    }
    _READ_METHODS = {'read_text', 'read_bytes', 'open', 'iterdir', 'glob', 'rglob',
                     'exists', 'is_file', 'is_dir', 'stat'}
    _DYNAMIC = re.compile(r'[$`*?\[{}]')
    _VARIABLE = re.compile(r'\$(?:\{([A-Za-z_][A-Za-z0-9_]*)\}|([A-Za-z_][A-Za-z0-9_]*))')
    
    
    def _concrete_absolute(value):
        return (isinstance(value, str) and bool(value.strip()) and value.startswith('/')
                and '\x00' not in value and '\\' not in value
                and '..' not in PurePosixPath(value).parts and not _DYNAMIC.search(value))
    
    
    def _under(path, directory):
        return path == directory or path.startswith(directory.rstrip('/') + '/')
    
    
    def _read_mode(mode):
        return isinstance(mode, str) and not any(c in mode for c in 'wax')
    
    
    def _candidate_literal(path):
        # Only a known candidate convention is inferred from unlabelled Python
        # file reads. Arbitrary Hidden/data/reward paths are never promoted.
        return _concrete_absolute(path) and _under(path, '/workspace/solution')
    
    
    def _source_might_cover(path, source):
        if not isinstance(source, str) or not source.startswith('/'):
            return True
        prefix = re.split(r'[$`*?\[{}]', source, maxsplit=1)[0].rstrip('/')
        return not prefix or _under(path, prefix) or path.startswith(prefix)
    
    
    def check_artifacts(root: Path, task: Path, cfg: dict, emit) -> list[str]:
        """Emit ERROR/WARN/INFO findings and return definite source container paths.
    
        Only malformed explicit sources and definitely uncovered candidate reads
        block this check. The caller decides the overall preliminary-gate result.
        """
        root, task = Path(root).resolve(), Path(task).resolve()
        config_path = task / 'task.toml'
        if not isinstance(cfg, dict):
            emit('WARN', 'ARTIFACTS_CONFIG_UNAVAILABLE', config_path,
                 '未获得有效配置，不能核对提交物移交。')
            return []
        if not task.is_relative_to(root):
            emit('ERROR', 'ARTIFACTS_TASK_ESCAPE', task, '任务路径越出待检提交包。')
            return []
    
        definite = {'/logs/artifacts'}
        uncertain = []
        invalid = False
        entries = cfg.get('artifacts', [])
        if not isinstance(entries, list):
            emit('ERROR', 'ARTIFACTS_TYPE', config_path,
                 '顶层 artifacts 必须为数组；可省略或使用空数组保留默认 /logs/artifacts。')
            entries, invalid = [], True
        for index, entry in enumerate(entries):
            label = f'artifacts[{index}]'
            if not isinstance(entry, (str, dict)):
                emit('ERROR', 'ARTIFACT_SOURCE_TYPE', config_path,
                     f'{label} 必须是绝对源路径字符串或含 source 的对象。')
                invalid = True
                continue
            source = entry.get('source') if isinstance(entry, dict) else entry
            if not isinstance(source, str) or not source.strip() or not source.startswith('/') or '\x00' in source or '\\' in source:
                emit('ERROR', 'ARTIFACT_SOURCE_PATH', config_path,
                     f'{label}.source 必须是非空 POSIX 绝对容器路径。')
                invalid = True
                continue
            if '..' in PurePosixPath(source).parts:
                emit('ERROR', 'ARTIFACT_SOURCE_TRAVERSAL', config_path,
                     f'{label}.source 含上级目录跳转：{source}。')
                invalid = True
                continue
            normalized = posixpath.normpath(source)
            complex_policy = bool(_DYNAMIC.search(source))
            if isinstance(entry, dict):
                complex_policy |= bool(entry.get('exclude')) or entry.get('service', 'main') != 'main'
                if 'destination' in entry:
                    emit('INFO', 'ARTIFACT_DESTINATION_HOST_ONLY', config_path,
                         f'{label}.destination 是宿主收集位置；Verifier 仍按源路径 {source} 读取。')
            if complex_policy:
                # An explicit qualified entry may replace the default entry in a
                # target version, so do not use that same source to certify coverage.
                definite.discard(normalized)
                uncertain.append(source)
                emit('WARN', 'ARTIFACT_POLICY_DYNAMIC', config_path,
                     f'{label} 含 glob、变量、exclude 或非 main service，静态未确认实际移交范围。',
                     '结合目标 Harbor 版本和实际移交记录核对；不把 destination 当容器重映射。')
            else:
                definite.add(normalized)
    
        reads = {}
        dynamic_reads = False
        def requested(value, evidence, confirmed=True):
            nonlocal dynamic_reads
            if _concrete_absolute(value):
                value = posixpath.normpath(value)
                if _under(value, '/logs/verifier') or _under(value, '/tests') or PurePosixPath(value).name in {'reward.txt', 'reward.json'}:
                    emit('WARN', 'ARTIFACT_READ_PATH_UNRESOLVED', evidence,
                         '提交接口指向评分输出或私有测试路径，需核对实际候选读取位置。')
                    dynamic_reads = True
                    return
                reads.setdefault(value, []).append((str(evidence), confirmed))
            else:
                dynamic_reads = True
                emit('WARN', 'ARTIFACT_CANDIDATE_DYNAMIC', evidence,
                     '候选参数或默认路径需运行时解析，静态未确认提交物读取位置。')
    
        def text(path):
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(task):
                    emit('WARN', 'ARTIFACT_SOURCE_UNREADABLE', path, '评分源码路径为链接或越出当前任务，未读取。')
                    return None
                with path.open('rb') as f:
                    raw = f.read(ARTIFACT_TEXT_LIMIT + 1)
                if len(raw) > ARTIFACT_TEXT_LIMIT:
                    emit('WARN', 'ARTIFACT_SOURCE_LIMIT', path, '评分源码超过静态读取预算，候选路径留待复核。')
                    return None
                return raw.decode('utf-8-sig')
            except (OSError, UnicodeError):
                emit('WARN', 'ARTIFACT_SOURCE_UNREADABLE', path, '评分源码无法读取，候选路径留待复核。')
                return None
    
        adapter = cfg.get('adapter')
        if isinstance(adapter, dict) and 'agent_submission_dir' in adapter:
            requested(adapter['agent_submission_dir'], str(config_path) + ':adapter.agent_submission_dir')
    
        shell_flags = set()
        shell = task / 'tests/test.sh'
        if shell.is_file():
            raw = text(shell)
            if raw is not None:
                # Do not attempt to prove execution through functions, conditions,
                # pipelines or command substitutions with a line tokenizer.
                logical_shell = raw.replace('\\\n', '')
                shell_complex = bool(re.search(
                    r'(?m)^\s*(?:if|elif|else|fi|case|esac|for|while|until|select|function|exit|return)\b'
                    r'|(?m:^\s*[A-Za-z_][A-Za-z0-9_]*\s*\(\s*\))'
                    r'|&&|\|\||[;|`]|\$\(', logical_shell))
                variables = {}
                here_end = None
                continued = ''
                for lineno, raw_line in enumerate(raw.splitlines(), 1):
                    if here_end is not None:
                        if raw_line.strip() == here_end:
                            here_end = None
                        continue
                    line = continued + raw_line
                    if line.rstrip().endswith('\\'):
                        continued = line.rstrip()[:-1] + ' '
                        continue
                    continued = ''
                    try:
                        tokens = shlex.split(line, comments=True)
                    except ValueError:
                        if any(flag in line for flag in _FLAGS):
                            requested(None, f'{shell}:{lineno}')
                        continue
                    if not tokens:
                        continue
                    hd = re.search(r'<<-?\s*[\'"]?([A-Za-z_][A-Za-z0-9_]*)', line)
                    if hd:
                        here_end = hd.group(1)
                        tokens = tokens[:next((i for i,t in enumerate(tokens) if t.startswith('<<')), len(tokens))]
                    def expand(value):
                        for _ in range(8):
                            updated = _VARIABLE.sub(lambda m: variables.get(m.group(1) or m.group(2), m.group(0)), value)
                            if updated == value:
                                return value
                            value = updated
                        return value
                    assignments = tokens[1:] if tokens[0] in {'export', 'readonly', 'local', 'declare'} else tokens
                    for token in assignments:
                        match = re.fullmatch(r'([A-Za-z_][A-Za-z0-9_]*)=(.*)', token, re.S)
                        if match:
                            variables[match.group(1)] = expand(match.group(2))
                        elif tokens[0] not in {'export', 'readonly', 'local', 'declare'}:
                            break
                    commands = [t for t in tokens if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', t, re.S)]
                    if not commands or commands[0] in {'echo', 'printf', 'cat', 'export', 'readonly', 'local', 'declare'}:
                        continue
                    for i, token in enumerate(tokens):
                        flag, sep, inline = token.partition('=')
                        if flag not in _FLAGS:
                            continue
                        shell_flags.add(flag)
                        value = inline if sep else tokens[i+1] if i+1 < len(tokens) else None
                        requested(expand(value) if value is not None else None, f'{shell}:{lineno}',
                                  confirmed=not shell_complex)
    
        tests_dir = task / 'tests'
        try:
            python_files = sorted(tests_dir.glob('*.py')) if tests_dir.is_dir() else []
        except OSError:
            python_files = []
        if len(python_files) > ARTIFACT_PYTHON_LIMIT:
            emit('WARN', 'ARTIFACT_SOURCE_LIMIT', tests_dir,
                 '评分源码文件数超过静态读取预算，部分候选路径未检查。')
        for py in python_files[:ARTIFACT_PYTHON_LIMIT]:
            raw = text(py)
            if raw is None:
                continue
            try:
                tree = ast.parse(raw)
            except (SyntaxError, ValueError, RecursionError):
                emit('WARN', 'ARTIFACT_PYTHON_PARSE', py, '评分源码无法作保守语法分析，提交物读取位置留待复核。')
                continue
            values = {}
            def literal(node):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    return node.value
                if isinstance(node, ast.Name):
                    return values.get(node.id)
                if isinstance(node, ast.Call) and node.args and ((isinstance(node.func, ast.Name) and node.func.id in {'Path', 'PurePosixPath'}) or (isinstance(node.func, ast.Attribute) and node.func.attr in {'Path', 'PurePosixPath'})):
                    return literal(node.args[0])
                if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
                    left, right = literal(node.left), literal(node.right)
                    if left is not None and right is not None:
                        return posixpath.join(left, right)
                return None
            # Only simple module-level constants are propagated. Function locals or
            # conditional assignments are not reliable runtime defaults.
            for node in tree.body:
                if isinstance(node, ast.Assign):
                    value = literal(node.value)
                    for name in node.targets:
                        if isinstance(name, ast.Name):
                            values[name.id] = value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    values[node.target.id] = literal(node.value)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                evidence = f'{py}:{node.lineno}'
                if isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
                    flags = {arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)}
                    matched = flags & _FLAGS
                    if matched and not (matched & shell_flags):
                        default = next((kw.value for kw in node.keywords if kw.arg == 'default'), None)
                        if default is not None:
                            requested(literal(default), evidence, confirmed=False)
                elif isinstance(node.func, ast.Name) and node.func.id == 'open' and node.args:
                    mode_node = node.args[1] if len(node.args) > 1 else next((kw.value for kw in node.keywords if kw.arg == 'mode'), ast.Constant('r'))
                    path, mode = literal(node.args[0]), literal(mode_node)
                    if _candidate_literal(path) and _read_mode(mode):
                        requested(path, evidence, confirmed=False)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in _READ_METHODS:
                    path = literal(node.func.value)
                    if _candidate_literal(path):
                        if node.func.attr == 'open':
                            mode_node = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == 'mode'), ast.Constant('r'))
                            if not _read_mode(literal(mode_node)):
                                continue
                        requested(path, evidence, confirmed=False)
    
        if not reads:
            emit('WARN', 'ARTIFACT_READ_PATH_UNRESOLVED', tests_dir,
                 '未从当前任务接口及评分源码确定候选读取路径；未强制假定 /workspace/solution。',
                 '后续核对实际提交接口、artifacts 和独立 Verifier 的读取路径。')
        for path, evidence in sorted(reads.items()):
            location = evidence[0][0]
            if any(_under(path, source) for source in definite):
                emit('INFO', 'ARTIFACT_READ_COVERED', location,
                     f'候选路径线索 {path} 在默认或显式 artifacts 声明覆盖范围内；未验证实际调用或移交。')
            elif any(_source_might_cover(path, source) for source in uncertain):
                emit('WARN', 'ARTIFACT_COVERAGE_DYNAMIC', location,
                     f'候选读取路径 {path} 的移交范围受动态 artifacts 策略影响，需运行记录核对。')
            elif not any(confirmed for _, confirmed in evidence):
                emit('WARN', 'ARTIFACT_READ_EXECUTION_UNCONFIRMED', location,
                     f'源码或复杂脚本中发现候选路径 {path}，artifacts 未覆盖；尚未确认该入口或分支实际执行。',
                     '按正式评分调用链核对，移除废弃代码或补齐实际所需的提交路径；本项不作确定移交失败。')
            elif not invalid:
                emit('ERROR', 'ARTIFACT_READ_UNCOVERED', location,
                     f'评分读取候选路径 {path}，但默认 /logs/artifacts 或显式 artifacts 未覆盖该源路径。',
                     f'将候选源路径 {path} 或其明确父目录加入 artifacts；destination 不改变容器内路径。')
        if definite:
            emit('INFO', 'ARTIFACT_SOURCES_DECLARED', config_path,
                 '已识别确定的容器源路径：' + '、'.join(sorted(definite)) + '。')
        return sorted(definite)
    return check_artifacts

check_artifacts = _load_preflight_artifacts()

def _load_preflight_config():
    """Read-only configuration and conservative Docker context checks.
    
    Python 3.11+, standard library only. This module never builds/pulls an image,
    starts a process from the submission, connects to a service, or executes code.
    """
    
    import glob
    import json
    import math
    from pathlib import Path, PurePosixPath
    import posixpath
    import re
    import shlex
    import tomllib
    
    CFG_READ_LIMIT = 2 * 1024 * 1024
    CFG_COMPOSE_NAMES = ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml")
    CFG_GPU_TYPES = {"H20", "L20"}
    CFG_PLACEHOLDER = re.compile(r"<[^>]*>|\$\{|\b(?:YOUR(?:_[A-Z0-9]+)*|REPLACE_ME|CHANGEME|TODO|TBD|PLACEHOLDER)\b", re.I)
    
    
    def _relative(path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)
    
    
    def _read(path: Path, root: Path, emit, code: str) -> str | None:
        """Bound the bytes read; do not inspect references outside the input tree."""
        try:
            if not path.resolve().is_relative_to(root):
                emit("ERROR", code + "_ESCAPE", path, "文件路径越出提交包。", "将实际文件放在提交包内，移除越界符号链接。")
                return None
            with path.open("rb") as stream:
                raw = stream.read(CFG_READ_LIMIT + 1)
            if len(raw) > CFG_READ_LIMIT:
                emit("WARN", code + "_TOO_LARGE", path, "配置/脚本文本超过本工具 2 MiB 读取预算，未完成该项检查；这不是平台文件大小限制。", "检查是否误放大文件或生成内容；确认实际文本后调整工具读取预算或转人工核对。")
                return None
            return raw.decode("utf-8-sig")
        except (OSError, UnicodeError) as exc:
            emit("ERROR", code + "_READ", path, f"无法读取 UTF-8 文本：{exc}", "修复文件类型、编码或读取权限。")
            return None
    
    
    def _image(value, location: str, path: Path, emit) -> bool:
        if not isinstance(value, str) or not value.strip():
            emit("ERROR", "CFG_IMAGE_VALUE", path, f"{location} 必须是非空镜像标识字符串。", "填写平台可用仓库中的实际镜像标识，或删除该字段后按构建分支准备镜像。")
            return False
        value = value.strip()
        if CFG_PLACEHOLDER.search(value) or value.upper() in {"YOUR_IMAGE", "IMAGE", "NONE", "NULL"}:
            emit("ERROR", "CFG_IMAGE_PLACEHOLDER", path, f"{location} 仍是占位或未展开值：{value}", "替换为本题实际镜像标识。")
            return False
        if re.search(r"\s", value) or "://" in value or value.startswith("/") or value.endswith("/"):
            emit("ERROR", "CFG_IMAGE_SYNTAX", path, f"{location} 不是正常 Docker 镜像引用：{value}", "使用 registry/namespace/name:tag 或带 digest 的镜像标识，不填写 URL。")
            return False
        if "@sha256:" in value and not re.fullmatch(r"[0-9a-fA-F]{64}", value.split("@sha256:", 1)[1]):
            emit("ERROR", "CFG_IMAGE_DIGEST", path, f"{location} 的 sha256 digest 格式不正确。", "填写完整的 64 位十六进制 digest。")
            return False
        emit("INFO", "CFG_IMAGE_DECLARED", path, f"{location} 已填写镜像标识 {value}；静态检查未验证镜像存在、拉取权限、依赖或预置内容。")
        return True
    
    
    def _positive_number(value) -> bool:
        # TOML integers are unbounded; avoid float conversion of huge integers.
        return (isinstance(value, int) and not isinstance(value, bool) and value > 0) or (
            isinstance(value, float) and math.isfinite(value) and value > 0)
    
    
    def _resources(env: dict, role: str, task_kind: str, path: Path, emit) -> None:
        for field, maximum in (("gpus", 8), ("cpus", 64)):
            if field not in env:
                # Harbor defaults are provider/version dependent; missing counts do
                # not mean a CPU task has definitely requested a GPU.
                emit("CHECK", "CFG_RESOURCE_UNDECLARED", path, f"{role} 未显式声明 {field}，须核对目标平台实际资源默认值。", f"按实际需要明确 {role} 的 {field}，或提供任务卡确认其有效默认值。")
                continue
            value = env[field]
            minimum = 0 if field == "gpus" else 1
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                emit("ERROR", "CFG_RESOURCE_TYPE", path, f"{role}.{field} 必须是大于等于 {minimum} 的整数（不能用布尔值）。", "修正资源字段的类型和数值。")
            elif value > maximum:
                emit("ERROR", "CFG_RESOURCE_LIMIT", path, f"{role}.{field}={value} 超过本批次上限 {maximum}。", "调整题目与资源配置，使单次运行符合内场上限。")
        count = env.get("gpus")
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            if task_kind == "cpu":
                emit("ERROR", "CFG_CPU_GPU", path, f"已声明 CPU 题，但 {role} 申请了 {count} 张 GPU。", "CPU 题两侧均保持 gpus = 0；不要为适配模板增加 GPU。")
            types = env.get("gpu_types")
            if types is None or types == []:
                emit("CHECK", "CFG_GPU_TYPES_MISSING", path, f"{role} 申请 GPU，但未声明允许卡型 gpu_types。", '明确允许 H20（优先）或 L20，并核对实际内场选卡。')
            elif not isinstance(types, list) or not all(isinstance(v, str) and v.strip() for v in types):
                emit("ERROR", "CFG_GPU_TYPES_SHAPE", path, f"{role}.gpu_types 必须是非空卡型字符串数组。", '例如 gpu_types = ["H20"]。')
            elif not ({v.strip().upper() for v in types} & CFG_GPU_TYPES):
                emit("ERROR", "CFG_GPU_UNSUPPORTED", path, f"{role}.gpu_types={types} 未允许 H20/L20。", "原题可保留历史卡型记录，但内场交付配置须允许 H20 或 L20，并核对换卡影响。")
            else:
                emit("INFO", "CFG_GPU_SELECTION", path, f"{role} 已允许 H20/L20；即使候选列表含其他型号也不据此判错，实际内场必须选用 H20（优先）或 L20。")
        for field in ("memory_mb", "build_timeout_sec"):
            if field in env and not _positive_number(env[field]):
                emit("ERROR", "CFG_RESOURCE_VALUE", path, f"{role}.{field} 必须是有限正数。", "修正配置中的数值与单位。")
    
    
    def _unsupported(policy: dict, role: str, stage: str, path: Path, emit) -> None:
        if "storage_mb" in policy:
            emit("ERROR", "CFG_STORAGE_UNSUPPORTED", path, f"{role}{stage}声明 storage_mb，当前内场不支持。", "移除该字段；本批不接收以磁盘限额作为研究或评分必要条件的题目，题目设计仍需后续质检核对。")
        mode = policy.get("network_mode")
        mode = mode.strip().lower() if isinstance(mode, str) else mode
        deny_modes = {"no-network", "none", "allowlist", "whitelist", "no_network"}
        if isinstance(mode, str) and mode in deny_modes:
            emit("ERROR", "CFG_NETWORK_UNSUPPORTED", path, f"{role}{stage}声明 network_mode={mode}，当前内场不支持该禁网/白名单约束。", "移除未支持请求并调整依赖该约束的题面与评分；warning 或降级联网不表示约束生效。")
        if policy.get("allow_internet") is False:
            emit("ERROR", "CFG_NETWORK_UNSUPPORTED", path, f"{role}{stage}声明 allow_internet=false，当前内场不能保证禁网。", "移除未支持请求，核对联网条件下题目与评分是否仍成立。")
        if policy.get("network_access") is False:
            emit("ERROR", "CFG_NETWORK_UNSUPPORTED", path, f"{role}{stage}声明旧 network_access=false 禁网请求，当前内场不支持。", "移除旧字段并按当前配置迁移，不能把旧禁网声明视为已生效。")
        hosts = policy.get("allowed_hosts")
        if hosts is not None and hosts != []:
            emit("ERROR", "CFG_ALLOWED_HOSTS_UNSUPPORTED", path, f"{role}{stage}声明 allowed_hosts 网络白名单，当前内场不支持。", "移除白名单请求并调整依赖该约束的题面与评分。")
    
    
    def _docker_instructions(raw: str):
        pending, start = "", 0
        for number, line in enumerate(raw.splitlines(), 1):
            stripped = line.strip()
            if not pending and (not stripped or stripped.startswith("#")):
                continue
            if not pending:
                start = number
            pending += stripped[:-1] + " " if stripped.endswith("\\") else stripped
            if stripped.endswith("\\"):
                continue
            match = re.match(r"([A-Za-z]+)\s+(.*)", pending, re.S)
            yield start, match.group(1).upper() if match else "UNKNOWN", match.group(2) if match else pending
            pending = ""
        if pending:
            yield start, "UNKNOWN", pending
    
    
    def _dockerfile(path: Path, context: Path, root: Path, role: str, emit) -> dict:
        summary = {"dockerfile": _relative(path, root), "context": _relative(context, root), "copy_sources_checked": 0, "runtime_pending": []}
        raw = _read(path, root, emit, "CFG_DOCKERFILE")
        if raw is None:
            return summary
        if not raw.strip():
            emit("ERROR", "CFG_DOCKERFILE_EMPTY", path, f"{role} 选中的 Dockerfile 为空。", "提供实际镜像构建定义或有效预构建镜像标识。")
            return summary
        if re.search(r"(?im)^\s*#\s*escape\s*=\s*`", raw):
            emit("CHECK", "CFG_DOCKER_ESCAPE", path, "Dockerfile 使用非默认 escape，未静态解析 COPY/ADD。", "在目标构建环境核对构建上下文与源路径。")
            summary["runtime_pending"].append("non-default escape")
            return summary
        operations = list(_docker_instructions(raw))
        if not any(instruction == "FROM" for _, instruction, _ in operations):
            emit("ERROR", "CFG_DOCKERFILE_FROM", path, f"{role} Dockerfile 未找到 FROM。", "补齐可构建的镜像定义；本工具不执行构建。")
        for lineno, instruction, arguments in operations:
            if instruction not in {"COPY", "ADD"}:
                continue
            location = f"{_relative(path, root)}:{lineno}"
            if "<<" in arguments:
                emit("CHECK", "CFG_DOCKER_COMPLEX_COPY", location, f"{instruction} 使用 heredoc，需目标环境核对。", "核对内联文件和构建输入；静态检查未展开 heredoc。")
                summary["runtime_pending"].append(f"line {lineno}: heredoc")
                continue
            try:
                flags = []
                rest = arguments.lstrip()
                while rest.startswith("--"):
                    match = re.match(r"(--[^\s]+)(?:\s+|$)(.*)", rest, re.S)
                    if not match:
                        raise ValueError("无法解析参数")
                    flag, rest = match.groups()
                    if flag in {"--from", "--chown", "--chmod", "--exclude"}:
                        next_value = re.match(r"([^\s]+)(?:\s+|$)(.*)", rest, re.S)
                        if not next_value:
                            raise ValueError("缺少 flag 值")
                        item, rest = next_value.groups()
                        flag += "=" + item
                    flags.append(flag)
                if any(flag.startswith("--from=") for flag in flags):
                    emit("INFO", "CFG_DOCKER_FROM_STAGE", location, f"{instruction} 从构建阶段或外部镜像复制；不按本地 context 查找。")
                    summary["runtime_pending"].append(f"line {lineno}: stage/image source")
                    continue
                parts = json.loads(rest) if rest.startswith("[") else shlex.split(rest)
                if not isinstance(parts, list) or len(parts) < 2 or not all(isinstance(p, str) for p in parts):
                    raise ValueError("应含至少一个源和目标")
            except (ValueError, json.JSONDecodeError) as exc:
                emit("CHECK", "CFG_DOCKER_COPY_PARSE", location, f"无法可靠静态解析 {instruction}：{exc}", "在目标环境核对该构建指令及本地源路径。")
                summary["runtime_pending"].append(f"line {lineno}: unresolved syntax")
                continue
            for source in parts[:-1]:
                if "$" in source or "\\" in source or source.startswith("~"):
                    emit("CHECK", "CFG_DOCKER_COPY_VARIABLE", location, f"{instruction} 源 {source} 含变量或复杂路径，未静态展开。", "按实际构建参数核对源文件存在于选中的 context 内。")
                    summary["runtime_pending"].append(f"line {lineno}: dynamic source")
                    continue
                if re.match(r"(?:https?|git|ssh)://|git@", source):
                    emit("CHECK", "CFG_DOCKER_REMOTE_SOURCE", location, f"{instruction} 使用远程源；本工具未联网获取或验证。", "在受控构建环境核对远程源可获取性和固定版本。")
                    summary["runtime_pending"].append(f"line {lineno}: remote source")
                    continue
                if ".." in PurePosixPath(source).parts:
                    emit("ERROR", "CFG_DOCKER_COPY_ESCAPE", location, f"{instruction} 源 {source} 越出约定的 {_relative(context, root)} context。", "将构建输入放入该 context 并改用相对路径；不要跨目录 COPY。")
                    continue
                local = source.lstrip("/") or "."
                candidate = context / local
                if not candidate.resolve().is_relative_to(context.resolve()):
                    emit("ERROR", "CFG_DOCKER_COPY_ESCAPE", location, f"{instruction} 源 {source} 通过链接越出构建 context。", "将实际输入保存在 context 内，移除越界链接。")
                    continue
                try:
                    found = next(context.glob(local), None) is not None if glob.has_magic(local) else candidate.exists()
                except (OSError, ValueError, NotImplementedError):
                    emit("CHECK", "CFG_DOCKER_COPY_GLOB", location, f"无法可靠展开 {instruction} 源模式 {source}。", "按目标 Docker 构建器的匹配规则核对。")
                    summary["runtime_pending"].append(f"line {lineno}: source pattern")
                    continue
                if not found:
                    # Historical task-root builds may contain this source while
                    # the current environment/tests context does not. Report the
                    # migration needed without falsely calling the package absent.
                    historical = context.parent / local
                    in_task_root = False
                    if historical.resolve().is_relative_to(context.parent.resolve()):
                        try:
                            in_task_root = (next(context.parent.glob(local), None) is not None
                                            if glob.has_magic(local) else historical.exists())
                        except (OSError, ValueError, NotImplementedError):
                            pass
                    if in_task_root:
                        emit("ERROR", "CFG_DOCKER_CONTEXT_MISMATCH", location,
                             f"{instruction} 源 {source} 在任务根目录中存在，但与当前默认 {_relative(context, root)} context 不一致；按该默认 context 构建时无法读取。",
                             "将构建输入迁移到当前 environment/ 或 tests/ context 并调整 COPY/ADD；或提供目标平台认可的构建方案。不要把历史 task-root 构建上下文直接当作当前默认上下文。")
                    else:
                        emit("ERROR", "CFG_DOCKER_COPY_MISSING", location, f"{instruction} 本地源 {source} 在当前 {_relative(context, root)} context 和任务根目录中均未找到。", "补齐文件或修正相对路径；不能使用另一个 context 的路径前缀。")
                else:
                    summary["copy_sources_checked"] += 1
        emit("INFO", "CFG_DOCKER_STATIC_ONLY", path, f"{role} Dockerfile 已做有限静态检查；未构建镜像，也未验证 RUN、.dockerignore、基础镜像、依赖或镜像内入口。")
        return summary
    
    
    def check_task_config(root: Path, task: Path, emit, task_kind: str = "auto") -> dict:
        """Inspect selected Harbor task configuration; send findings to ``emit``.
    
        ``task_kind`` is explicit user metadata (auto/cpu/gpu). It is never inferred
        from S1/S2 or whether the package has model checkpoints.
        """
        root, task = Path(root).resolve(), Path(task).resolve()
        result = {"parsed": False, "config": None, "agent": None, "verifier": None,
                  "effective_environments": {}, "environment_sources": {}, "artifacts": [], "dockerfiles": []}
        if not task.is_relative_to(root):
            emit("ERROR", "CFG_TASK_ESCAPE", task, "任务目录越出提交包。", "选择提交包内实际 task.toml 所在目录。")
            return result
        path = task / "task.toml"
        if not path.is_file():
            emit("ERROR", "CFG_TASK_MISSING", path, "缺少 task.toml。", "补齐标准 Harbor 任务配置。")
            return result
        raw = _read(path, root, emit, "CFG_TOML")
        if raw is None:
            return result
        try:
            config = tomllib.loads(raw)
        except tomllib.TOMLDecodeError as exc:
            emit("ERROR", "CFG_TOML_PARSE", path, f"task.toml 无法解析：{exc}", "修正 TOML 语法后重新自检。")
            return result
        result.update(parsed=True, config=config)
        tables = {}
        for field in ("environment", "agent", "verifier"):
            value = config.get(field)
            if value is None:
                if field in {"environment", "verifier"}:
                    emit("ERROR", "CFG_TABLE_MISSING", path, f"缺少 [{field}] table。", "补齐标准 Harbor 配置；Verifier 须显式 separate。")
                tables[field] = {}
            elif not isinstance(value, dict):
                emit("ERROR", "CFG_TABLE_SHAPE", path, f"{field} 必须是 TOML table。", f"使用 [{field}]，不要填写列表或标量。")
                tables[field] = {}
            else:
                tables[field] = value
        agent_env, agent_phase, verifier = tables["environment"], tables["agent"], tables["verifier"]
        legacy = config.get("resources")
        if isinstance(legacy, dict):
            emit("WARN", "CFG_LEGACY_RESOURCES", path,
                 "发现旧 [resources] 表；它不能代替标准 [environment] / [verifier.environment] 的有效资源声明。",
                 "迁移配置，核对原表的 cpu_cores/gpu_count/gpu_type 等是否实际被当前平台使用。")
            def legacy_emit(level, code, location, message, fix=""):
                emit("WARN", "LEGACY_" + code, location, message,
                     "旧字段不是当前有效配置，须先迁移并核对实际资源/约束。" + fix)
            _unsupported(legacy, "旧 resources", "声明", path, legacy_emit)
            gpu_count = legacy.get("gpu_count")
            gpu_type = legacy.get("gpu_type")
            if isinstance(gpu_count, int) and not isinstance(gpu_count, bool) and gpu_count > 0 and isinstance(gpu_type, str):
                if not any(re.search(r"(?<![A-Z0-9])" + allowed + r"(?![A-Z0-9])", gpu_type.upper()) for allowed in CFG_GPU_TYPES):
                    emit("WARN", "CFG_LEGACY_GPU_UNSUPPORTED", path,
                         f"旧 resources.gpu_type={gpu_type} 未允许当前 H20/L20 交付卡型；旧表不是已生效资源的证明。",
                         "迁移标准环境资源配置，允许 H20（优先）或 L20，并核对换卡影响。")
        has_specific = "environment" in verifier
        specific = verifier.get("environment")
        if has_specific and not isinstance(specific, dict):
            emit("ERROR", "CFG_TABLE_SHAPE", path, "verifier.environment 必须是 TOML table。", "使用 [verifier.environment] 或删除无效字段后按复用分支准备。")
            specific = {}
        venv = specific if has_specific else agent_env
        result["effective_environments"] = {"agent": agent_env, "verifier": venv}
        result["environment_sources"] = {"agent": "environment", "verifier": "verifier.environment" if has_specific else "environment (reused)"}
        if verifier.get("environment_mode") != "separate":
            emit("ERROR", "CFG_SEPARATE", path, "[verifier] 必须显式声明 environment_mode = \"separate\"。", '使用独立 Verifier sandbox；复用镜像也须保持 separate。')
        for role, env in (("agent", agent_env), ("verifier", venv)):
            _resources(env, role, task_kind, path, emit)
            _unsupported(env, role, "环境启动阶段", path, emit)
        for role, phase in (("agent", agent_phase), ("verifier", verifier)):
            _unsupported(phase, role, "执行阶段", path, emit)
            if "timeout_sec" in phase and not _positive_number(phase["timeout_sec"]):
                emit("ERROR", "CFG_TIMEOUT", path, f"{role}.timeout_sec 必须是有限正数。", "按运行预算填写有效秒数；Agent 总时长不等于单轮评分时长。")
        if task_kind not in {"auto", "cpu", "gpu"}:
            emit("ERROR", "CFG_TASK_KIND", path, f"未知 task_kind={task_kind}。", "使用 auto、cpu 或 gpu。")
        if task_kind == "gpu" and not any(isinstance(e.get("gpus"), int) and not isinstance(e.get("gpus"), bool) and e["gpus"] > 0 for e in (agent_env, venv)):
            emit("CHECK", "CFG_GPU_TASK_NO_GPU", path, "已声明 GPU 题，但两侧未发现有效 GPU 申请。", "按实际训练/评分需求核对各自环境，不为 CPU 侧额外加 GPU。")
        for directory in ("environment", "tests"):
            for name in CFG_COMPOSE_NAMES:
                entry = task / directory / name
                if entry.exists() or entry.is_symlink():
                    emit("ERROR", "CFG_COMPOSE", entry, "正式运行目录直属位置含 Compose 文件；即使已有 Dockerfile/预构建镜像也不接受。", "改为每个 sandbox 单容器并移除正式目录的 Compose 文件；保留 Solver/Verifier 独立 sandbox。")
        result["artifacts"] = check_artifacts(root, task, config, emit)
        agent_df, verifier_df = task / "environment/Dockerfile", task / "tests/Dockerfile"
        if "docker_image" in agent_env:
            valid = _image(agent_env["docker_image"], "environment.docker_image", path, emit)
            agent_selection = {"source": "agent_image", "image": agent_env["docker_image"], "valid_reference": valid, "runtime_pending": ["image availability and contents"]}
        elif agent_df.is_file():
            emit("CHECK", "CFG_AGENT_IMAGE_PREPARATION", agent_df, "Agent 仅提供 Dockerfile，尚未填写内场可用 docker_image。", "在 AIDP 实跑前构建/上传镜像，并按任务卡填写实际镜像标识；Dockerfile 存在不能证明镜像已准备。")
            agent_selection = {"source": "agent_dockerfile", "dockerfile": _relative(agent_df, root), "runtime_pending": ["image preparation"]}
            result["dockerfiles"].append(_dockerfile(agent_df, agent_df.parent, root, "Agent", emit))
        else:
            emit("ERROR", "CFG_AGENT_IMAGE_MISSING", path, "缺少有效 Agent 镜像来源：未填写 environment.docker_image，也没有 environment/Dockerfile。", "提供实际预构建镜像标识或本题可构建的 environment/Dockerfile。")
            agent_selection = {"source": "missing", "runtime_pending": []}
        if isinstance(specific, dict) and "docker_image" in specific:
            valid = _image(specific["docker_image"], "verifier.environment.docker_image", path, emit)
            verifier_selection = {"source": "verifier_image", "image": specific["docker_image"], "valid_reference": valid, "tests_delivery": "baked", "runtime_pending": ["image availability, /tests/test.sh and private dependencies baked in image"]}
            emit("INFO" if valid and (task / "tests/test.sh").is_file() else "CHECK", "CFG_VERIFIER_PREBAKED", path, "选中专用 Verifier 预构建镜像；/tests/test.sh、评分实现、私有材料及依赖须已预置，不能假设自动上传 tests；镜像内容留待实跑验证。")
        elif verifier_df.is_file():
            verifier_selection = {"source": "tests_dockerfile", "dockerfile": _relative(verifier_df, root), "tests_delivery": "baked", "runtime_pending": ["image preparation and baked /tests content"]}
            emit("CHECK", "CFG_VERIFIER_IMAGE_PREPARATION", verifier_df, "Verifier 选中 tests/Dockerfile 分支；内场实跑前需准备平台可用的评分镜像。", "构建/上传专用镜像，核对预置评分入口及依赖；不能将其误认为复用 Agent 镜像并自动上传 tests。")
            result["dockerfiles"].append(_dockerfile(verifier_df, verifier_df.parent, root, "Verifier", emit))
        else:
            verifier_selection = {"source": "reuse_" + agent_selection["source"], "image": agent_selection.get("image"), "tests_delivery": "runtime_upload", "runtime_pending": ["tests upload in independent Verifier and compatible dependencies"]}
            emit("INFO", "CFG_VERIFIER_REUSE", path, "未选专用 Verifier 镜像或 tests/Dockerfile，按复用 Solver 镜像分支检查；无需另交 tests/Dockerfile。")
        result["agent"], result["verifier"] = agent_selection, verifier_selection
        result["image_selection"] = {"agent": agent_selection, "verifier": verifier_selection}
        entry = task / "tests/test.sh"
        if not entry.is_file():
            if verifier_selection["source"] == "verifier_image":
                emit("CHECK", "CFG_TEST_ENTRY_BAKED", entry, "完整包未提供 tests/test.sh；专用镜像可能已预置，但静态无法确认。", "推荐随完整包补交源码入口；否则提供明确的预置路径与镜像内容依据，实跑确认 bash /tests/test.sh。")
            else:
                emit("ERROR", "CFG_TEST_ENTRY_MISSING", entry, "缺少标准最终评分入口 tests/test.sh。", "补齐可上传或烘焙到 /tests/test.sh 的实际评分脚本。")
        else:
            test_raw = _read(entry, root, emit, "CFG_TEST_ENTRY")
            if test_raw is not None and not test_raw.strip():
                emit("ERROR", "CFG_TEST_ENTRY_EMPTY", entry, "tests/test.sh 为空，未提供实际评分入口。", "补齐实际评分调用并写约定 reward 文件；不能只创建空文件。")
            elif test_raw is not None:
                emit("INFO", "CFG_TEST_ENTRY_PRESENT", entry, "tests/test.sh 非空；静态未执行评分、验证依赖或确认 reward 产生。")
        return result
    return check_task_config

check_task_config = _load_preflight_config()

def _load_preflight_paths():
    """Small, conservative path checks for selected Dockerfiles only.
    
    This is not a Docker builder or a complete Dockerfile/dockerignore interpreter.
    It does not execute task code, infer arbitrary `hidden` names, or inspect snapshots.
    """
    
    import json
    from pathlib import Path, PurePosixPath
    import posixpath
    import re
    import shlex
    
    
    _PP_LIMIT = 2 * 1024 * 1024
    _PP_PRIVATE_TEST_DIRS = ("hidden_assets", "hidden_tests", "private_assets")
    
    
    def _pp_read(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _PP_LIMIT:
            raise ValueError("不是可读取的常规小文本文件")
        return path.read_text(encoding="utf-8-sig")
    
    
    def _pp_operations(raw):
        pending, start = "", 0
        for number, line in enumerate(raw.splitlines(), 1):
            stripped = line.strip()
            if not pending and (not stripped or stripped.startswith("#")):
                continue
            if not pending:
                start = number
            pending += stripped[:-1] + " " if stripped.endswith("\\") else stripped
            if stripped.endswith("\\"):
                continue
            match = re.match(r"([A-Za-z]+)\s+(.*)", pending, re.S)
            yield start, match.group(1).upper() if match else "UNKNOWN", match.group(2) if match else pending
            pending = ""
        if pending:
            yield start, "UNKNOWN", pending
    
    
    def _pp_copy(arguments):
        flags = []
        rest = arguments.lstrip()
        if "<<" in rest:
            raise ValueError("heredoc")
        while rest.startswith("--"):
            match = re.match(r"(--[^\s]+)(?:\s+|$)(.*)", rest, re.S)
            if not match:
                raise ValueError("flag")
            flag, rest = match.groups()
            if flag in {"--from", "--chown", "--chmod", "--exclude"}:
                value = re.match(r"([^\s]+)(?:\s+|$)(.*)", rest, re.S)
                if not value:
                    raise ValueError("flag value")
                part, rest = value.groups()
                flag += "=" + part
            flags.append(flag)
        values = json.loads(rest) if rest.startswith("[") else shlex.split(rest)
        if not isinstance(values, list) or len(values) < 2 or not all(isinstance(x, str) for x in values):
            raise ValueError("source/destination")
        return flags, values[:-1], values[-1]
    
    
    def _pp_dynamic(value):
        return bool(re.search(r"[$*?\[\]\\]", value)) or value.startswith("~")
    
    
    def _pp_inside(path, parent):
        try:
            return path.resolve().is_relative_to(parent.resolve())
        except (OSError, ValueError, RuntimeError):
            return False
    
    
    def _pp_ignore(context, dockerfile, emit):
        specific = dockerfile.with_name(dockerfile.name + ".dockerignore")
        selected = specific if specific.is_file() else context / ".dockerignore"
        if not selected.exists():
            return [], False
        try:
            lines = _pp_read(selected).splitlines()
        except (OSError, UnicodeError, ValueError) as exc:
            emit("WARN", "PATH_DOCKERIGNORE_UNREADABLE", selected,
                 f"未能静态读取选中 Dockerfile 的忽略规则：{exc}。", "在构建环境核对实际上下文。")
            return [], True
        patterns = [line.strip().strip("/") for line in lines if line.strip() and not line.lstrip().startswith("#")]
        patterns = [p for p in patterns if p != "."]
        complex_rules = any(p.startswith("!") or _pp_dynamic(p) or ".." in PurePosixPath(p).parts for p in patterns)
        if complex_rules:
            emit("WARN", "PATH_DOCKERIGNORE_COMPLEX", selected,
                 "忽略规则含回包含、变量或通配模式，本次不据此断言 COPY 源已被排除。", "按 Docker 实际匹配顺序核对。")
        return [posixpath.normpath(p.removeprefix("./")) for p in patterns], complex_rules
    
    
    def _pp_ignored(source, patterns, complex_rules):
        if complex_rules or _pp_dynamic(source):
            return None
        name = posixpath.normpath(source.lstrip("/") or ".")
        return any(name == pattern or name.startswith(pattern + "/") for pattern in patterns)
    
    
    def _pp_private_candidates(root, task):
        candidates = [root / "workspace/reference", root / "expert_evidence", root / "optimization_evidence",
                      task / "reference", task / "expert_evidence", task / "optimization_evidence"]
        candidates += [task / "tests" / name for name in _PP_PRIVATE_TEST_DIRS]
        return [path.resolve() for path in candidates if path.exists()]
    
    
    def _pp_context(root, task, dockerfile, summary, default):
        # A matching, explicit summary context may describe an acknowledged adapter.
        # Otherwise use current Harbor per-image defaults, never guess task-root mode.
        entries = summary.get("dockerfiles", [])
        if not isinstance(entries, list):
            return default
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get("dockerfile"), str):
                continue
            supplied = Path(entry["dockerfile"])
            supplied = supplied if supplied.is_absolute() else root / supplied
            if supplied.resolve() != dockerfile.resolve() or not isinstance(entry.get("context"), str):
                continue
            context = Path(entry["context"])
            context = context if context.is_absolute() else root / context
            if _pp_inside(context, root) and context.is_dir() and not context.is_symlink():
                return context.resolve()
        return default
    
    
    def check_selected_paths(root, task, config_summary: dict, emit) -> dict:
        """Emit ERROR only for a reliable subset; emit WARN for unresolved paths.
    
        ``emit(level, code, path, message, fix='')`` follows the preliminary checker.
        Missing physical COPY inputs are left to the existing configuration checker.
        """
        root, task = Path(root).resolve(), Path(task).resolve()
        summary = config_summary if isinstance(config_summary, dict) else {}
        result = {"scanned_dockerfiles": [], "static_only": True}
        if not _pp_inside(task, root):
            emit("WARN", "PATH_TASK_OUTSIDE_PACKAGE", task, "任务目录不在完整包内，未继续路径检查。")
            return result
        selections = summary.get("image_selection", {})
        selections = selections if isinstance(selections, dict) else {}
        for role, source, default in (("agent", "agent_dockerfile", task / "environment"),
                                      ("verifier", "tests_dockerfile", task / "tests")):
            selected = selections.get(role, summary.get(role, {}))
            selected = selected if isinstance(selected, dict) else {}
            if selected.get("source") != source:
                continue
            dockerfile = default / "Dockerfile"
            if not _pp_inside(dockerfile, root):
                emit("WARN", "PATH_DOCKERFILE_OUTSIDE_PACKAGE", dockerfile, "所选 Dockerfile 路径越出完整包，未扫描。")
                continue
            try:
                raw = _pp_read(dockerfile)
            except (OSError, UnicodeError, ValueError) as exc:
                emit("WARN", "PATH_DOCKERFILE_UNREADABLE", dockerfile, f"未能静态读取所选 Dockerfile：{exc}。")
                continue
            context = _pp_context(root, task, dockerfile, summary, default)
            result["scanned_dockerfiles"].append({"role": role, "dockerfile": dockerfile.relative_to(root).as_posix(),
                                                   "context": context.relative_to(root).as_posix()})
            if re.search(r"(?im)^\s*#\s*escape\s*=\s*`", raw):
                emit("WARN", "PATH_DOCKER_ESCAPE_COMPLEX", dockerfile, "Dockerfile 使用非默认转义符，未解释其复制路径。")
                continue
            patterns, complex_ignore = _pp_ignore(context, dockerfile, emit)
            operations = list(_pp_operations(raw))
            multistage = sum(command == "FROM" for _, command, _ in operations) > 1
            uncertain = multistage or complex_ignore
            workdir = None  # FROM image cwd is unknown until an explicit WORKDIR.
            expected = task / "tests/test.sh"
            correct_entry, entry_target_seen, wrong_entries = False, False, []
            private_roots = _pp_private_candidates(root, task)
            for line, command, arguments in operations:
                location = f"{dockerfile.relative_to(root).as_posix()}:{line}"
                if command == "FROM":
                    workdir = None
                    continue
                if command == "WORKDIR":
                    if _pp_dynamic(arguments):
                        workdir = None
                        uncertain = True
                    elif arguments.startswith("/"):
                        workdir = posixpath.normpath(arguments)
                    elif workdir is not None:
                        workdir = posixpath.normpath(posixpath.join(workdir, arguments))
                    continue
                if command in {"RUN", "ONBUILD", "UNKNOWN"}:
                    uncertain = True
                if command not in {"COPY", "ADD"}:
                    continue
                try:
                    flags, sources, destination = _pp_copy(arguments)
                except (ValueError, json.JSONDecodeError):
                    uncertain = True
                    emit("WARN", "PATH_COPY_COMPLEX", location, "COPY/ADD 使用本次未可靠解释的语法，路径留待构建核对。")
                    continue
                if any(flag.startswith("--from=") for flag in flags):
                    uncertain = True
                    emit("WARN", "PATH_COPY_FROM_STAGE", location, "COPY --from 的阶段或镜像内容未静态展开。")
                    continue
                unfamiliar = any(not flag.startswith(("--chown=", "--chmod=")) for flag in flags)
                if unfamiliar:
                    uncertain = True
                    emit("WARN", "PATH_COPY_FLAGS_COMPLEX", location, "COPY/ADD 使用路径扩展参数，未断言实际复制范围。")
                destination_dynamic = _pp_dynamic(destination) or (not destination.startswith("/") and workdir is None)
                target = None if destination_dynamic else posixpath.normpath(
                    destination if destination.startswith("/") else posixpath.join(workdir, destination))
                if destination_dynamic:
                    uncertain = True
                    emit("WARN", "PATH_COPY_DESTINATION_UNKNOWN", location, "复制目标依赖变量或基础镜像工作目录，未确定容器目标路径。")
                for name in sources:
                    if _pp_dynamic(name) or re.match(r"(?:https?|git|ssh)://|git@", name):
                        uncertain = True
                        emit("WARN", "PATH_COPY_SOURCE_DYNAMIC", location, f"复制源 {name} 含变量、通配符或远程地址，未展开。")
                        continue
                    excluded = _pp_ignored(name, patterns, complex_ignore)
                    if excluded is True and not unfamiliar:
                        emit("ERROR", "PATH_COPY_SOURCE_IGNORED", location,
                             f"COPY/ADD 明确来源 {name} 被当前字面 .dockerignore 规则排除。", "调整忽略规则或复制输入，并重新构建验证。")
                        continue
                    normalized = name.lstrip("/") or "."
                    local = context / normalized
                    if role == "agent":
                        # Only the selected context determines the actual COPY source.
                        # Same-named task/package paths are historical context clues,
                        # not evidence that an existing public local input is private.
                        selected_source = local.resolve() if local.exists() and _pp_inside(local, context) else None
                        historical = [candidate.resolve() for candidate in (task / normalized, root / normalized)
                                      if not local.exists() and candidate.exists() and _pp_inside(candidate, root)]
                        if not unfamiliar and selected_source is not None and any(
                                selected_source == private or selected_source.is_relative_to(private) for private in private_roots):
                            emit("ERROR", "PATH_SOLVER_PRIVATE_COPY", location,
                                 f"Solver Dockerfile 显式复制私有评测或参考证据来源 {name}。", "只复制公开 Dev/共享模块；Reference 与私有评分资产留在可信侧。")
                        elif not unfamiliar and any(candidate == private or candidate.is_relative_to(private)
                                                    for candidate in historical for private in private_roots):
                            emit("WARN", "PATH_SOLVER_PRIVATE_CONTEXT_UNRESOLVED", location,
                                 f"来源 {name} 未在当前 context 找到；其他历史 context 的同名路径包含私有评测或参考材料，尚不能认定实际复制。",
                                 "先核对目标构建 context；只将公开 Dev/共享模块交付 Agent，私有材料留在可信侧。")
                        elif selected_source == (task / "tests").resolve() or any(
                                candidate == (task / "tests").resolve() for candidate in historical):
                            emit("WARN", "PATH_SOLVER_WHOLE_TESTS", location,
                                 "Solver 显式复制整个 tests/，其中可能同时有公开 Dev 与私有内容。", "按实际内容核对，只公开必要 Dev 和共享模块。")
                        elif context.resolve() in {root, task} and local.exists() and local.is_dir() and any(
                                private.is_relative_to(local.resolve()) for private in private_roots):
                            emit("WARN", "PATH_SOLVER_BROAD_CONTEXT_COPY", location,
                                 f"宽范围复制 {name} 的已知构建上下文包含参考解或私有材料。", "结合忽略规则核对实际输入，缩小 Solver 复制范围。")
                    if role != "verifier" or unfamiliar or not local.exists() or not _pp_inside(local, context):
                        continue
                    # Another supplied script/template can legitimately provide the
                    # canonical container entry. Do not assume its contents must be
                    # identical to the outer tests/test.sh file.
                    if target is not None:
                        supplied_entry = None
                        if local.is_file() and (target == "/tests/test.sh" or
                                (destination.endswith("/") and posixpath.join(target, local.name) == "/tests/test.sh")):
                            supplied_entry = local
                        elif local.is_dir():
                            try:
                                entry_relative = PurePosixPath("/tests/test.sh").relative_to(PurePosixPath(target))
                                supplied_entry = local.joinpath(*entry_relative.parts)
                            except ValueError:
                                pass
                        if supplied_entry is not None and supplied_entry.is_file() and _pp_inside(supplied_entry, context):
                            # The destination is correct even if complex ignore rules
                            # prevent proving whether this input reaches the image.
                            # Keep ignore uncertainty separate from destination errors.
                            entry_target_seen = True
                            entry_excluded = _pp_ignored(supplied_entry.relative_to(context).as_posix(), patterns, complex_ignore)
                            if entry_excluded is False:
                                correct_entry = True
                            elif entry_excluded is True:
                                emit("ERROR", "PATH_VERIFIER_ENTRY_IGNORED", location,
                                     "目录 COPY 本可提供 /tests/test.sh，但对应脚本被字面 .dockerignore 规则排除。",
                                     "调整忽略规则并核对评分入口确实进入镜像。")
                    # Only the supplied canonical scoring source is tracked. Arbitrary
                    # other script contents are never inspected for equivalence.
                    if not expected.is_file() or not _pp_inside(expected, local if local.is_dir() else local.parent):
                        continue
                    if local.is_file() and local.resolve() != expected.resolve():
                        continue
                    if target is None:
                        continue
                    if local.is_dir():
                        final_target = posixpath.normpath(posixpath.join(target, expected.resolve().relative_to(local.resolve()).as_posix()))
                    elif destination.endswith("/") or target == "/":
                        final_target = posixpath.join(target, expected.name)
                    elif target == "/tests":
                        uncertain = True  # Could be an already-existing directory.
                        continue
                    else:
                        final_target = target
                    if final_target == "/tests/test.sh":
                        entry_target_seen = True
                        if excluded is False:
                            correct_entry = True
                    else:
                        wrong_entries.append((location, name, final_target, local.is_file()))
            if role == "verifier" and wrong_entries and not (correct_entry or entry_target_seen):
                explicit_file_copy = any(item[3] for item in wrong_entries)
                level = "ERROR" if explicit_file_copy and not uncertain else "WARN"
                targets = ", ".join(sorted({item[2] for item in wrong_entries}))
                emit(level, "PATH_VERIFIER_ENTRY_DESTINATION", dockerfile,
                     f"Dockerfile 对所提供 tests/test.sh 的可见复制目标为 {targets}，未发现复制到 /tests/test.sh。",
                     "将评分入口准备为 /tests/test.sh；存在 RUN、多阶段或动态生成时须在实际镜像中核对。")
        return result
    return check_selected_paths

check_selected_paths = _load_preflight_paths()


VERSION = "1.2.1"
IGNORED = {"__MACOSX", ".DS_Store"}

class InspectionError(ValueError):
    pass

def file_sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(2 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def archive_name(name):
    if not isinstance(name, str) or "\x00" in name or "\\" in name:
        raise InspectionError("压缩包包含不安全的成员路径。")
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or (p.parts and re.match(r"^[A-Za-z]:", p.parts[0])):
        raise InspectionError("压缩包成员越界：" + name[:200])
    return p

def safe_unpack(source, destination, max_files, max_bytes):
    """Validate every member before extracting. No extractall, links, or execution."""
    records, seen = [], {}
    total = 0
    is_zip = zipfile.is_zipfile(source)
    if not is_zip:
        try:
            is_tar = tarfile.is_tarfile(source)
        except (OSError, tarfile.TarError):
            is_tar = False
        if not is_tar:
            raise InspectionError("输入不是可读取的 ZIP / TAR 压缩包；也可传入完整包目录。")
    archive = zipfile.ZipFile(source) if is_zip else tarfile.open(source, "r:*")
    try:
        members = archive.infolist() if is_zip else archive
        for index, item in enumerate(members):
            if index >= max_files:
                raise InspectionError("压缩包成员数超过本次检查上限；请提高 --max-files，或使用已安全解压的目录。")
            name = item.filename if is_zip else item.name
            p = archive_name(name)
            if str(p) == ".":
                continue
            mode = item.external_attr >> 16 if is_zip else item.mode
            directory = item.is_dir() if is_zip else item.isdir()
            if is_zip:
                kind = stat.S_IFMT(mode)
                if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (kind == stat.S_IFDIR and not directory):
                    raise InspectionError("压缩包含链接或特殊文件：" + name[:200])
                if item.flag_bits & 1:
                    raise InspectionError("不检查加密 ZIP，请提供可读取的完整包。")
                size = item.file_size
            else:
                if not (item.isdir() or item.isfile()):
                    raise InspectionError("压缩包含链接或特殊文件：" + name[:200])
                size = item.size
            key = p.as_posix().casefold()
            if key in seen:
                raise InspectionError("压缩包存在重复路径或大小写冲突：" + name[:200])
            seen[key] = (p, directory)
            if not directory:
                total += size
            if size < 0 or total > max_bytes:
                raise InspectionError("展开体积超过本次检查上限；请提高 --max-unpacked-gib，或直接检查已解压目录。")
            records.append((item, p, directory, size, mode))
        for _, p, _, _, _ in records:
            for parent in p.parents:
                if str(parent) != "." and parent.as_posix().casefold() in seen:
                    if not seen[parent.as_posix().casefold()][1]:
                        raise InspectionError("压缩包把同一路径同时作为文件和目录使用。")
        if total + 64 * 1024 * 1024 > shutil.disk_usage(destination).free:
            raise InspectionError("临时目录磁盘空间不足。请先安全解压到有足够空间的磁盘，再传入目录，或用 --temp-dir 指定位置。")
        for item, p, directory, size, _ in records:
            target = destination.joinpath(*p.parts)
            if directory:
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = archive.open(item) if is_zip else archive.extractfile(item)
            if stream is None:
                raise InspectionError("无法读取压缩包成员：" + str(p))
            with stream, target.open("xb") as out:
                count = 0
                while True:
                    block = stream.read(min(2 * 1024 * 1024, size - count + 1))
                    if not block:
                        break
                    count += len(block)
                    if count > size:
                        raise InspectionError("压缩包实际展开大小与声明不一致。")
                    out.write(block)
                if count != size:
                    raise InspectionError("压缩包成员不完整：" + str(p))
        return {"kind": "zip" if is_zip else "tar", "member_count": len(records), "expanded_bytes": total}
    except (zlib.error, lzma.LZMAError, EOFError, RuntimeError) as exc:
        raise InspectionError("压缩包数据无法完整展开：" + str(exc)[:240]) from exc
    finally:
        archive.close()

def scan_directory(path, max_files, max_bytes):
    count, total = 0, 0
    def unreadable(exc):
        raise InspectionError("无法完整清点目录：" + str(exc)) from exc
    for base, dirs, files in os.walk(path, followlinks=False, onerror=unreadable):
        for name in dirs + files:
            p = Path(base) / name
            mode = p.lstat().st_mode
            if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise InspectionError("提交包包含链接或特殊文件，无法安全静态检查：" + p.relative_to(path).as_posix())
            count += 1
            if count > max_files:
                raise InspectionError("目录成员数超过检查上限；可调整 --max-files（这不是平台包体规则）。")
            if stat.S_ISREG(mode):
                total += p.stat().st_size
            if total > max_bytes:
                raise InspectionError("目录体积超过检查上限；可调整 --max-unpacked-gib（这不是平台包体规则）。")
    return {"entry_count": count, "expanded_bytes": total}

def submission_root(path):
    """Allow a normal outer archive folder, but never silently pick one of many tasks."""
    root = path
    for _ in range(10):
        if any((root / k).exists() for k in ("workspace", "expert_evidence", "optimization_evidence")):
            return root
        children = [p for p in root.iterdir() if p.name not in IGNORED]
        if len(children) == 1 and children[0].is_dir():
            root = children[0]
        else:
            return root
    return root

def atomic_report_write(path, content):
    # Replacing the directory entry never follows a pre-existing report symlink
    # or hard link into the inspected submission.
    pending = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".preflight-", delete=False) as stream:
            pending = Path(stream.name)
            stream.write(content)
        os.replace(pending, path)
    finally:
        if pending is not None and pending.exists():
            pending.unlink()

# Deterministic configuration errors in the v0.3.10 format subset stop this gate.
# Dynamic build/image availability and semantic research reviews stay separate.
BLOCKING_CONFIG_CODES = {
    "CFG_TASK_MISSING", "CFG_TOML_PARSE", "CFG_TOML_READ", "CFG_TOML_ESCAPE",
    "CFG_TABLE_SHAPE", "CFG_TABLE_MISSING", "CFG_TASK_ESCAPE", "CFG_SEPARATE",
    "CFG_IMAGE_VALUE", "CFG_IMAGE_PLACEHOLDER", "CFG_IMAGE_SYNTAX", "CFG_IMAGE_DIGEST",
    "CFG_AGENT_IMAGE_MISSING", "CFG_DOCKERFILE_EMPTY", "CFG_DOCKERFILE_FROM",
    "CFG_TEST_ENTRY_MISSING", "CFG_TEST_ENTRY_EMPTY", "CFG_COMPOSE",
    "CFG_CPU_GPU", "CFG_GPU_UNSUPPORTED", "CFG_GPU_TYPES_SHAPE", "CFG_RESOURCE_TYPE",
    "CFG_RESOURCE_LIMIT", "CFG_RESOURCE_VALUE", "CFG_TIMEOUT",
    "CFG_STORAGE_UNSUPPORTED", "CFG_NETWORK_UNSUPPORTED", "CFG_ALLOWED_HOSTS_UNSUPPORTED",
    "CFG_DOCKER_COPY_MISSING", "CFG_DOCKER_COPY_ESCAPE",
}


def alignment_refs(code):
    """Stable links to the delivered v3.10 format-subset correspondence table."""
    if code == "CFG_TOML_TOO_LARGE":
        return ["S01"], []
    if code.startswith("ARTIFACT"):
        return ["A01"], ["QA17/H03"]
    if code.startswith("LEGACY_") or "LEGACY" in code:
        return ["C02"], ["QA17/H02"]
    if code == "CFG_SEPARATE" or code.startswith("CFG_TABLE") or code.startswith("CFG_TOML"):
        return ["C01", "C02"], ["QA17/H02"]
    if code == "CFG_STORAGE_UNSUPPORTED":
        return ["C03"], ["QA05", "QA17/H02"]
    if code in {"CFG_NETWORK_UNSUPPORTED", "CFG_ALLOWED_HOSTS_UNSUPPORTED"}:
        return ["C04"], ["QA05", "QA17/H02"]
    if any(word in code for word in ("GPU", "RESOURCE", "TIMEOUT")):
        return ["C05", "C06", "C07"], ["QA15", "QA17/H02"]
    if code == "CFG_COMPOSE":
        return ["D01"], ["QA17/H03"]
    if code == "PATH_SOLVER_PRIVATE_COPY":
        return ["D06"], ["QA17/H03"]
    if code.startswith("PATH_") or code.startswith("CFG_DOCKER"):
        return ["D03", "D04", "D05"], ["QA17/H03"]
    if "IMAGE" in code or "VERIFIER_REUSE" in code:
        return ["I01", "I02"], ["QA17/H01", "QA17/H03"]
    if "TEST_ENTRY" in code:
        return ["I03"], ["QA17/H01", "QA17/H04"]
    if "REFERENCE" in code:
        return ["F04"], ["QA17/H01"]
    if code == "INSPECTION_ERROR":
        return ["S01"], []
    return ["F01", "F02", "F03"], ["QA17/H01"]


def check_minimum_package(root, emit, task_kind):
    for name in ("workspace", "expert_evidence", "optimization_evidence"):
        directory = root / name
        if not directory.is_dir():
            emit("ERROR", "MISSING_DELIVERY_DIRECTORY", name,
                 f"缺少完整包目录 {name}/。", "重传包含三类目录的完整包，不要只传补丁或 harbor_task。")
        elif not any(p.name not in IGNORED for p in directory.iterdir()):
            emit("WARN", "EMPTY_DELIVERY_DIRECTORY", name,
                 f"{name}/ 当前为空，后续质检需核对材料完整性。")
    task = root / "workspace/harbor_task"
    if not task.is_dir():
        emit("ERROR", "MISSING_HARBOR_TASK", "workspace/harbor_task", "缺少 Harbor 任务目录。")
        return {}
    instruction = task / "instruction.md"
    if not instruction.is_file() or instruction.stat().st_size == 0:
        emit("ERROR", "MISSING_INSTRUCTION", instruction, "缺少非空 instruction.md。")
    configuration = task / "task.toml"
    if configuration.is_file() and not configuration.stat().st_size:
        emit("ERROR", "EMPTY_TASK_CONFIG", configuration, "task.toml 为空，需提供实际任务配置。")
    for name in ("environment", "tests"):
        if not (task / name).is_dir():
            emit("ERROR", "MISSING_HARBOR_DIRECTORY", task / name,
                 f"完整提交包缺少 {name}/ 源码目录。", "预构建镜像可代替 Dockerfile 构建分支，不能代替本次完整题包源码交付。")
    # Reference/evidence schemas are deliberately outside this quick gate.
    if not (root / "workspace/reference").exists():
        emit("WARN", "REFERENCE_NOT_LOCATED", "workspace/reference",
             "未在常见位置找到参考解；前置不阻断，后续按实际位置复核。")
    def configuration_emit(level, code, path, message, fix=""):
        effective = "INFO" if level == "INFO" else "ERROR" if code in BLOCKING_CONFIG_CODES or code.startswith("ARTIFACT") and level == "ERROR" else "WARN"
        emit(effective, code, path, message, fix)
    result = check_task_config(root, task, configuration_emit, task_kind)
    result["preflight_paths"] = check_selected_paths(root, task, result, emit)
    return result


def render_reports(out, report):
    out.mkdir(parents=True, exist_ok=True)
    atomic_report_write(out / "report.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    labels = {"PASS": "前置检查通过", "PASS_WITH_WARNINGS": "前置检查通过，有非阻断提醒",
              "FAIL": "前置检查未通过，存在明确阻断项", "INSPECTION_ERROR": "本次检查未完成"}
    lines = ["提交包格式前置检查", "", "结论：" + labels[report["decision"]],
             "对齐质检3.10可确定的格式/部署配置子集；提醒不阻断。尚未运行 Harbor，不是最终质检结论。",
             "脚本版本：" + VERSION, "输入：" + report["source"]["path"],
             "原包 SHA256：" + report["source"].get("sha256", "目录输入，打包后可再检一次"), ""]
    for level, title in (("ERROR", "需要修复的阻断项"), ("WARN", "非阻断提醒"), ("INFO", "已识别信息")):
        rows = [f for f in report["findings"] if f["level"] == level]
        lines.append(f"{title}（{len(rows)}）")
        for row in rows:
            lines.append(f'- [{row["code"]}] {row["path"]}: {row["message"]}')
            if row["fix"]:
                lines.append("  建议：" + row["fix"])
        if not rows:
            lines.append("无")
        lines.append("")
    lines += ["后续检查：NOP、轨迹、模型、seed、评分与证据有效性由后续质检核对；镜像拉取、构建、候选移交和评分链路由 AIDP 实跑 Harbor 验证。",
              "返修后重新上传 workspace/、expert_evidence/、optimization_evidence/ 三类完整材料；此脚本不上传文件。"]
    body = "\n".join(lines) + "\n"
    atomic_report_write(out / "report.txt", body)
    atomic_report_write(out / "report.md", "# " + lines[0] + "\n\n" + "\n".join(lines[1:]) + "\n")
    errors = [f for f in report["findings"] if f["level"] == "ERROR"]
    if report["decision"] == "INSPECTION_ERROR":
        brief = "本次检查未完成，请查看 report.txt 的读取问题后重试。\n"
    elif not errors:
        brief = "没有发现前置阻断项。提醒见 report.txt，后续进入质检和 AIDP Harbor 实跑；本结果不代表最终验收通过。\n"
    else:
        brief = "请先修复以下阻断项，再自检并重传完整包：\n" + "\n".join(
            f'{i}. {f["path"]}：{f["message"]} {f["fix"]}' for i, f in enumerate(errors, 1)) + "\n"
    atomic_report_write(out / "返修清单.txt", brief)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("submission", type=Path, help="三类目录完整包，支持目录、ZIP、tar.gz")
    parser.add_argument("--out", type=Path, help="报告目录，必须放在待检目录外")
    parser.add_argument("--task-kind", choices=("auto", "cpu", "gpu"), default="auto",
                        help="可选设备类别；CPU/GPU 不代表训练/非训练")
    parser.add_argument("--max-files", type=int, default=200_000, help="检查资源上限，不是交付规则")
    parser.add_argument("--max-unpacked-gib", type=float, default=100, help="展开上限，不是平台包大小限制")
    parser.add_argument("--temp-dir", type=Path, help="可选临时解压位置，结束自动清理")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    if args.max_files < 1 or not math.isfinite(args.max_unpacked_gib) or args.max_unpacked_gib <= 0:
        parser.error("检查资源上限须为正有限值")
    source = args.submission.expanduser().absolute()
    out = args.out.expanduser().absolute() if args.out else source.parent / (
        "前置报告-" + source.name + "-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    if out.resolve() == source.resolve() or (source.is_dir() and out.resolve().is_relative_to(source.resolve())):
        parser.error("报告目录必须放在输入包之外")
    report = {"version": VERSION, "scope": "package_format_and_deployment_preflight", "created_at": datetime.now(timezone.utc).isoformat(),
              "decision": "INSPECTION_ERROR", "harbor_executed": False, "final_acceptance": False,
              "standard": {"skill": "review_skill-0.3.10_1015(1).zip", "format_subset_only": True,
                           "gpu_candidate_rule": "current_tutorial_allows_mixed_if_H20_or_L20_present"},
              "source": {"path": str(source)}, "task_kind": args.task_kind, "findings": [],
              "not_checked": ["NOP", "轨迹内容与八字段", "模型及seed对应关系", "研究质量", "证据有效性", "真实镜像与Harbor运行"]}
    root = None
    seen = set()
    def emit(level, code, path, message, fix=""):
        name = str(path)
        if root is not None:
            try:
                name = Path(path).relative_to(root).as_posix()
            except ValueError:
                pass
        row = {"level": level, "code": code, "path": name, "message": message, "fix": fix}
        key = tuple(row.values())
        if key not in seen:
            seen.add(key)
            report["findings"].append(row)
    try:
        if source.is_symlink() or not source.exists():
            raise InspectionError("输入不存在或是符号链接")
        with tempfile.TemporaryDirectory(prefix="package-preflight-", dir=args.temp_dir) as td:
            if source.is_file():
                report["source"].update(kind="archive", bytes=source.stat().st_size, sha256=file_sha256(source))
                inspected = Path(td).resolve()
                report["source"].update(safe_unpack(source, inspected, args.max_files, int(args.max_unpacked_gib * 1024**3)))
            elif source.is_dir():
                inspected = source.resolve()
                report["source"]["kind"] = "directory"
            else:
                raise InspectionError("输入不是普通文件或目录")
            report["source"].update(scan_directory(inspected, args.max_files, int(args.max_unpacked_gib * 1024**3)))
            root = submission_root(inspected)
            report["source"]["submission_prefix"] = root.relative_to(inspected).as_posix()
            config = check_minimum_package(root, emit, args.task_kind)
            # Keep only the selected branch; invalid TOML values may include
            # dates/NaN and must still produce a normal defect report.
            report["environment_sources"] = {role: value.get("source") for role, value in
                                               config.get("image_selection", {}).items()}
            report["decision"] = "FAIL" if any(f["level"] == "ERROR" for f in report["findings"]) else (
                "PASS_WITH_WARNINGS" if any(f["level"] == "WARN" for f in report["findings"]) else "PASS")
            if any(f["code"] == "CFG_TOML_TOO_LARGE" for f in report["findings"]):
                # A local inspection budget is not a platform format rule.
                report["decision"] = "INSPECTION_ERROR"
    except (OSError, ValueError, zipfile.BadZipFile, NotImplementedError, tarfile.TarError, RecursionError, zlib.error, lzma.LZMAError, EOFError) as exc:
        emit("WARN", "INSPECTION_ERROR", ".", str(exc)[:600])
        report["decision"] = "INSPECTION_ERROR"
    report["counts"] = {level: sum(f["level"] == level for f in report["findings"]) for level in ("ERROR", "WARN", "INFO")}
    for finding in report["findings"]:
        finding["alignment_rule_ids"], finding["skill_check_refs"] = alignment_refs(finding["code"])
    code = 3 if report["decision"] == "INSPECTION_ERROR" else 1 if report["decision"] == "FAIL" else 0
    try:
        render_reports(out, report)
    except (OSError, TypeError, ValueError) as exc:
        print("报告写入失败：" + str(exc), file=sys.stderr)
        return 3
    print(json.dumps({"decision": report["decision"], "counts": report["counts"], "exit_code": code,
                      "report": str(out / "report.txt"), "harbor_executed": False}, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
