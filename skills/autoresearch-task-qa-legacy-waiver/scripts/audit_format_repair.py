#!/usr/bin/env python3
"""Direct current-package format/core-delivery review for legacy task repair.

No full historical QA pass or waiver application is required. Submitted programs,
models, Dockerfiles and shell scripts are read as data and never executed.
"""
from __future__ import annotations

import argparse
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import stat
import tempfile
import tomllib
import unicodedata
import zipfile

import docker_paths

VERSION = "0.3.10-format-repair.3.1"
CHECKS = {
    "F01": "当前必需目录、文件与 TOML 接口",
    "F02": "有效构建或镜像方案、构建上下文及 COPY 来源",
    "F03": "评分入口、独立依赖声明与固定输出路径",
    "F04": "提交物 artifacts 移交契约",
    "F05": "公开 Dev、私有 Hidden 供给与 Agent 隔离",
    "F06": "separate、单容器、无 Compose 与当前目标资源配置",
    "F07": "当前评分实现与冻结面无确证故障或作者泄漏造假",
}
EXCLUDED = ["历史运行字段、资源差异和旧卡记录", "历史轨迹八字段、状态、时间及行为重审",
            "历史运行时长、方法轮次和最高推理档记录", "旧题包指纹、哈希和旧版本重新绑定",
            "历史 Baseline/Reference 成绩重跑与换卡复验", "旧版未要求的当前 Trial/NOP 记录"]
PLATFORM = [
    {"id": "ICM_IMAGE_PREPARATION", "summary": "字节内部准备、构建或导入镜像并配置实际 ICM tag；本轮不要求专家补内部镜像运行记录。"},
    {"id": "BUILD_AND_STARTUP", "summary": "平台实际构建和启动，核对依赖、基础镜像 digest 及 bash/解释器；静态推断不能冒充运行结果。"},
    {"id": "SANDBOX_CONFIGURATION", "summary": "平台核对 root、seccomp、网络及实际分配的沙盒权限设置。"},
    {"id": "CURRENT_TRIAL_NOP", "summary": "平台后续执行当前版本 Harbor Trial/NOP、独立 Verifier 和 reward 收集；其缺口不作为本轮专家返修门槛。"},
    {"id": "RUNTIME_TRANSFER", "summary": "平台实际核对提交物移交及目标 H20/L20（GPU 题）运行；本轮不重算历史资源或成绩。"},
    {"id": "NETWORK_POLICY_TRANSITION", "summary": "移除不支持的禁网字段后，新的联网或外部查表防护尚未落实，列为平台迁移事项，不要求本批专家新增防护实现或补跑；当前确证 Hidden 暴露或假 reward 仍属当前核心缺陷。"},
]
for _item in PLATFORM:
    _item["blocking"] = False
TEXT_LIMIT = 16 * 1024 * 1024
MAX_FILES = 200_000
MAX_UNPACKED = 128 * 1024 ** 3


class ReviewError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def json_object(path):
    if path.stat().st_size > TEXT_LIMIT:
        raise ReviewError("REVIEW_READING_LIMIT", "审核工作文件超过读取预算；请由质检员整理当前七项审查，不要求专家重跑。")
    def finite(value):
        raise ValueError("non-finite JSON constant: " + value)
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result
    value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=finite, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise ReviewError("REVIEW_SHAPE", "七项审核工作文件必须为 JSON 对象；它不是专家新增交付格式。")
    return value


def safe_reference(root, ref):
    """Check only an explicitly used reference; bare array/large logs are valid.

    No history is enumerated, parsed or schema-validated by this function.
    Explicit JSON locators are reviewer conveniences, not required evidence.
    """
    if not isinstance(ref, str) or not ref:
        raise ReviewError("REVIEW_EVIDENCE", "证据引用应为当前包内相对文件路径。")
    name, _, fragment = ref.partition("#")
    line = re.search(r":(\d+)(?:-(\d+))?$", name)
    if line:
        name = name[:line.start()]
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReviewError("REVIEW_EVIDENCE", "证据引用不能越出当前提交包：" + ref)
    path = root / relative
    if not path.resolve().is_relative_to(root) or not path.is_file() or path.is_symlink():
        raise ReviewError("REVIEW_EVIDENCE", "证据不是当前包内可读取的普通文件：" + ref)
    if any((root / parent).is_symlink() for parent in relative.parents if parent != Path(".")):
        raise ReviewError("REVIEW_EVIDENCE", "证据引用经过提交包内链接：" + ref)
    if line or re.fullmatch(r"L\d+(?:-L?\d+)?", fragment):
        match = line if line else re.fullmatch(r"L(\d+)(?:-L?(\d+))?", fragment)
        start, end = int(match[1]), int(match[2] or match[1])
        if not 1 <= start <= end:
            raise ReviewError("REVIEW_EVIDENCE_LOCATION", "证据行号无效：" + ref)
        count = 0
        with path.open(encoding="utf-8-sig") as stream:
            for count, _ in enumerate(stream, 1):
                if count >= end:
                    break
        if count < end:
            raise ReviewError("REVIEW_EVIDENCE_LOCATION", "证据行号越界：" + ref)
    elif fragment.startswith(("/", "field=", "$.")):
        if path.stat().st_size > 64 * 1024 * 1024:
            raise ReviewError("REVIEW_EVIDENCE_LOCATION", "大文件可直接引用路径并在审核说明中定位；无需为本轮改造或重跑历史日志：" + ref)
        node = json.loads(path.read_text(encoding="utf-8-sig"))
        if fragment.startswith("/"):
            tokens = [p.replace("~1", "/").replace("~0", "~") for p in fragment[1:].split("/")]
        else:
            field = fragment[6:] if fragment.startswith("field=") else fragment[2:]
            tokens = re.findall(r"[A-Za-z_][A-Za-z_0-9]*|\d+", field)
        for token in tokens:
            if isinstance(node, dict) and token in node:
                node = node[token]
            elif isinstance(node, list) and token.isdigit() and int(token) < len(node):
                node = node[int(token)]
            else:
                raise ReviewError("REVIEW_EVIDENCE_LOCATION", "证据字段不存在：" + ref)
    return path


def read_current(path):
    if path.stat().st_size > TEXT_LIMIT:
        raise ReviewError("CURRENT_SOURCE_READING_LIMIT", "当前入口文件超过静态读取预算，质检员需选择可审阅入口；这不是历史记录或专家补跑要求：" + str(path))
    return path.read_text(encoding="utf-8-sig")


def direct_execution_paths(path):
    """Recognize literal executable calls, never infer dependencies from names.

    Dynamic adapter use still needs F01 source review. This narrow safeguard
    prevents an 'inactive' note from hiding a concrete existing literal call.
    """
    raw = read_current(path)
    commands = []
    if path.suffix == ".py":
        try:
            tree = ast.parse(raw)
        except SyntaxError:
            return set()
        modules, functions = {name: name for name in ("subprocess", "runpy", "os")}, {}
        allowed = {"subprocess." + name for name in ("run", "call", "check_call", "check_output", "Popen")} | {"runpy.run_path", "os.system"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update({alias.asname or alias.name: alias.name for alias in node.names if alias.name in modules})
            elif isinstance(node, ast.ImportFrom) and node.module in {"subprocess", "runpy", "os"}:
                functions.update({alias.asname or alias.name: node.module + "." + alias.name for alias in node.names})
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                name = modules.get(node.func.value.id, "") + "." + node.func.attr
            else:
                name = functions.get(node.func.id, "") if isinstance(node.func, ast.Name) else ""
            if name not in allowed:
                continue
            try:
                command = ast.literal_eval(node.args[0])
            except (ValueError, TypeError, SyntaxError):
                continue
            commands.append(command)
    elif path.suffix in {".sh", ".bash"}:
        commands = raw.splitlines()
    found = set()
    for command in commands:
        try:
            tokens = shlex.split(command, comments=True) if isinstance(command, str) else command
        except ValueError:
            continue
        if (not isinstance(tokens, list) or not tokens or not all(isinstance(item, str) for item in tokens)
                or tokens[0] in {"echo", "printf", "cat", "#"} or "=" in tokens[0]):
            continue
        # Only executable/script positions establish a literal dependency.
        # Arguments are data: python -c/-m and later argv can mention an old
        # path as a label. Option-bearing/indirect invocations stay in the
        # existing F01 semantic review instead of guessing their script path.
        found.add(tokens[0].removeprefix("./"))
        executable = PurePosixPath(tokens[0]).name
        interpreter = re.fullmatch(r"python(?:\d+(?:\.\d+)*)?|bash|sh|zsh|node|perl|ruby|source|\.", executable)
        if interpreter and len(tokens) > 1 and not tokens[1].startswith("-"):
            found.add(tokens[1].removeprefix("./"))
    return found


def unpack(source, destination):
    """Stream safe ZIP members; no compression-ratio rejection of valid logs."""
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES or sum(item.file_size for item in infos) > MAX_UNPACKED:
            raise ReviewError("INPUT_READING_LIMIT", "归档超过当前工具展开预算；请在有空间的环境安全解包后以目录检查，不是题目质量判退。")
        if sum(item.file_size for item in infos) > shutil.disk_usage(destination).free:
            raise ReviewError("INPUT_DISK_SPACE", "空间不足以展开完整包；可清理缓存或在其他环境以目录检查，不要求专家补跑。")
        seen = set()
        for item in infos:
            name = item.filename
            if not item.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("utf-8")
                except (UnicodeError, ValueError):
                    pass
            pure = PurePosixPath(name)
            mode = stat.S_IFMT((item.external_attr >> 16) & 0xFFFF)
            key = unicodedata.normalize("NFC", name).casefold().rstrip("/")
            if (not name or "\x00" in name or "\\" in name or pure.is_absolute() or ".." in pure.parts
                    or mode not in (0, stat.S_IFREG, stat.S_IFDIR) or item.flag_bits & 1 or key in seen):
                raise ReviewError("INPUT_UNSAFE_ARCHIVE", "归档无法安全读取，含越界、链接、特殊/加密文件或重名条目：" + name)
            seen.add(key)
            target = destination.joinpath(*pure.parts)
            if item.is_dir() or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, target.open("xb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)


def package_root(root):
    if (root / "workspace").is_dir() or (root / "expert_evidence").is_dir() or (root / "optimization_evidence").is_dir():
        return root
    candidates = []
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink() and child.name != "__MACOSX":
            if any((child / name).is_dir() for name in ("workspace", "expert_evidence", "optimization_evidence")):
                candidates.append(child)
    if len(candidates) == 1:
        return candidates[0]
    return root


def current_task(root, bundle, review):
    if review and review.get("task_root") is not None:
        requested = review["task_root"]
        if not isinstance(requested, str) or Path(requested).is_absolute() or ".." in Path(requested).parts:
            raise ReviewError("REVIEW_TASK_ROOT", "task_root 应指向当前包内的任务目录。")
        return root / requested
    for candidate in (bundle / "workspace/harbor_task", bundle / "harbor_task", root):
        if candidate.is_dir() and not candidate.is_symlink() and (candidate / "task.toml").is_file():
            return candidate
    candidates = []
    pruned = {"expert_evidence", "optimization_evidence", "history", "docs", ".git", "__MACOSX"}
    for base, dirs, files in os.walk(root, followlinks=False):
        relative = Path(base).relative_to(root)
        dirs[:] = [name for name in dirs if name not in pruned and not (Path(base) / name).is_symlink()]
        if len(relative.parts) >= 4:
            dirs[:] = []
        if "task.toml" in files:
            candidates.append(Path(base))
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ReviewError("INPUT_AMBIGUOUS_TASK_ROOT", "存在多个当前任务候选；质检员需在 task_root 指明本轮任务，不把历史快照当当前包。")
    for candidate in (bundle / "workspace/harbor_task", bundle / "harbor_task", root):
        if candidate.is_dir() and not candidate.is_symlink() and any((candidate / name).exists() for name in ("instruction.md", "environment", "tests")):
            return candidate
    return bundle / "workspace/harbor_task"


def inventory(root, review=None):
    root = root.resolve()
    bundle = package_root(root)
    issues, observations, notes = [], [], []
    def reference(path):
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return str(path)
    def emit(owner, code, message, paths=(), *, semantic=False, platform=False):
        data = {"owner": owner, "code": code, "summary": message,
                "evidence": [reference(Path(p)) for p in paths if p is not None]}
        if semantic:
            identity = json.dumps(data, ensure_ascii=False, sort_keys=True)
            data["observation_id"] = owner + ":" + code + ":" + hashlib.sha256(identity.encode()).hexdigest()[:12]
            # A multi-source COPY can produce the same helper observation for
            # each source on the same line. One stable observation must have one
            # template resolution, otherwise our own template is invalid.
            if not any(item["observation_id"] == data["observation_id"] for item in observations):
                observations.append(data)
        elif platform:
            data["blocking"] = False
            notes.append(data)
        else:
            issues.append(data)
    # Equivalent outer layouts are valid; historical research/evidence folder
    # names are neither required nor retroactively audited in this stage.
    task = current_task(root, bundle, review)
    if not task.resolve().is_relative_to(root) or task.is_symlink():
        raise ReviewError("INPUT_TASK_ROOT", "当前任务根目录越界或为链接。")
    for name in ("environment", "tests"):
        path = task / name
        if not path.is_dir() or path.is_symlink():
            emit("F01", "TASK_DIRECTORY_MISSING", "当前任务缺少目录：" + name, [path])
    cfg = None
    for name in ("instruction.md", "task.toml"):
        path = task / name
        if not path.is_file() or path.is_symlink() or not path.stat().st_size:
            emit("F01", "CORE_FILE_MISSING", "当前任务缺少或为空：" + name, [path])
    config_path = task / "task.toml"
    if config_path.is_file() and not config_path.is_symlink():
        try:
            cfg = tomllib.loads(read_current(config_path))
        except tomllib.TOMLDecodeError as exc:
            emit("F01", "TOML_PARSE", "当前 task.toml 不能解析：" + str(exc), [config_path])
    cfg = cfg if isinstance(cfg, dict) else {}
    original_config = copy.deepcopy(cfg)
    adapter = review.get("config_adapter") if review else None
    if adapter is not None:
        if (not isinstance(adapter, dict) or not isinstance(adapter.get("summary"), str)
                or not adapter["summary"].strip() or not isinstance(adapter.get("evidence"), list)
                or not adapter["evidence"] or not adapter.get("entrypoint") or not adapter.get("effective_task")):
            raise ReviewError("REVIEW_CONFIG_ADAPTER", "config_adapter 应引用包内已有适配入口、目标原生 task.toml、调用/映射依据和具体说明；不是专家新增交付 schema 或运行记录。")
        adapter_entry = safe_reference(root, adapter["entrypoint"])
        effective_task = safe_reference(root, adapter["effective_task"])
        for ref in adapter["evidence"]:
            safe_reference(root, ref)
        # This narrow branch reads an existing native configuration at the
        # same delivered task root. It never executes a submitted adapter or
        # guesses the configuration it might produce at runtime.
        if effective_task.parent != task or effective_task == config_path or adapter_entry == effective_task:
            raise ReviewError("REVIEW_CONFIG_ADAPTER", "适配分支需引用同一当前任务根内已有的另一份原生 TOML 目标配置及独立适配入口；另一套已生成任务应直接用 task_root 定位。")
        try:
            cfg = tomllib.loads(read_current(effective_task))
        except tomllib.TOMLDecodeError as exc:
            emit("F01", "ADAPTER_TARGET_TOML_PARSE", "已有适配目标原生 TOML 不能解析：" + str(exc), [effective_task])
            cfg = {}
        emit("F01", "CONFIG_ADAPTER_MAPPING", "核对已有适配入口的实际调用、旧字段到目标原生配置的映射及目标环境目录；仅声称存在适配器不能证明接口生效。",
             [config_path, adapter_entry, effective_task] + [safe_reference(root, ref) for ref in adapter["evidence"]], semantic=True)
        config_path = effective_task
    known_legacy_resources = {"cpu_cores", "memory_mb", "gpu_count", "gpu_type", "gpu_types", "network_access", "storage_mb"}
    legacy_resources = original_config.get("resources")
    if isinstance(legacy_resources, dict) and known_legacy_resources.intersection(legacy_resources):
        native_env = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
        native_verifier = cfg.get("verifier") if isinstance(cfg.get("verifier"), dict) else {}
        native_venv = native_verifier.get("environment") if isinstance(native_verifier.get("environment"), dict) else {}
        native_fields = {"cpus", "gpus", "memory_mb", "gpu_types"}
        if not any(native_fields.intersection(values) for values in (native_env, native_venv)):
            emit("F01", "LEGACY_RESOURCE_SCHEMA_UNMAPPED", "当前仍只有旧 [resources] 资源表，缺少原生资源配置或已有真实适配目标；旧字段不会自动成为 Harbor 生效配置。",
                 [task / "task.toml", config_path])
        elif adapter is None:
            emit("F01", "LEGACY_RESOURCE_TABLE_ROLE", "当前存在原生资源配置及旧 [resources] 表；核对原生字段为实际配置，旧表仅历史说明且没有其他仍生效的旧调用，不把旧字段当作已落实约束。",
                 [task / "task.toml"], semantic=True)
    # An explicit old entrypoint remains a live declaration until the reviewer
    # identifies its replacement using the existing native wrapper. If an
    # actual adapter still invokes old paths they must remain checked.
    inactive_entrypoint = review.get("legacy_entrypoint_inactive") if review else None
    if inactive_entrypoint is not None:
        if (not isinstance(inactive_entrypoint, dict) or not isinstance(inactive_entrypoint.get("summary"), str)
                or not inactive_entrypoint["summary"].strip() or not isinstance(inactive_entrypoint.get("evidence"), list)
                or not inactive_entrypoint["evidence"]):
            raise ReviewError("REVIEW_LEGACY_ENTRYPOINT", "legacy_entrypoint_inactive 需据已有原生配置和实际 tests 入口填写说明与证据，不是专家新增文件。")
        refs = [safe_reference(root, ref) for ref in inactive_entrypoint["evidence"]]
        if not isinstance(cfg.get("environment"), dict) or not (task / "tests/test.sh").is_file():
            emit("F01", "LEGACY_ENTRYPOINT_REPLACEMENT_MISSING", "旧 entrypoint 的替代需有当前原生 environment 和真实 tests/test.sh，不能仅用底稿声明移除旧入口。", [task / "task.toml", task / "tests/test.sh"])
        else:
            emit("F01", "LEGACY_ENTRYPOINT_REPLACED", "核实当前原生配置和 tests/test.sh 已替代旧 [entrypoint]，实际调用不再依赖旧入口；旧表仅保留历史信息。", [task / "task.toml", task / "tests/test.sh"] + refs, semantic=True)
            cfg = copy.deepcopy(cfg)
            cfg.pop("entrypoint", None)
            if adapter is not None and isinstance(original_config.get("entrypoint"), dict):
                adapter_sources = {adapter_entry, *(safe_reference(root, ref) for ref in adapter["evidence"]), *refs}
                calls = set().union(*(direct_execution_paths(path) for path in adapter_sources if path.suffix in {".py", ".sh", ".bash"}))
                active = {name: value for name, value in original_config["entrypoint"].items()
                          if isinstance(value, str) and value.removeprefix("./") in calls}
                if active:
                    cfg["entrypoint"] = active
                    emit("F01", "LEGACY_ENTRYPOINT_STILL_USED", "已有适配源码/调用仍明确使用部分旧入口；这些实际路径保留检查，不能用整表历史说明掩盖当前依赖。", [adapter_entry] + refs, semantic=True)
    elif adapter is not None and isinstance(original_config.get("entrypoint"), dict):
        # The real adapter can still invoke these paths. Preserve their physical
        # source checks instead of silently discarding old current entrypoints.
        cfg = copy.deepcopy(cfg)
        cfg["entrypoint"] = copy.deepcopy(original_config["entrypoint"])
    shape_ok = True
    for field in ("environment", "agent", "verifier"):
        if field in cfg and not isinstance(cfg[field], dict):
            shape_ok = False
            emit("F01", "TABLE_SHAPE", field + " 必须为 TOML table。", [config_path])
    verifier = cfg.get("verifier") if isinstance(cfg.get("verifier"), dict) else {}
    if "environment" in verifier and not isinstance(verifier["environment"], dict):
        shape_ok = False
        emit("F01", "TABLE_SHAPE", "verifier.environment 必须为 TOML table。", [config_path])
    if verifier.get("environment_mode") != "separate":
        emit("F06", "SEPARATE_REQUIRED", '当前 [verifier] 必须显式设置 environment_mode = "separate"。', [config_path])
    env = cfg.get("environment") if isinstance(cfg.get("environment"), dict) else {}
    venv = verifier.get("environment") if isinstance(verifier.get("environment"), dict) else env
    if review and review.get("task_type") == "gpu" and not any(isinstance(values.get("gpus"), int) and not isinstance(values.get("gpus"), bool) and values["gpus"] > 0 for values in (env, venv)):
        emit("F06", "GPU_REQUEST_MISSING", "当前 GPU 题缺少原生 gpus 申请；旧 resources.gpu_count 不会自动生效，应补当前配置或已有真实适配目标。", [config_path])
    for role, values in (("agent", env), ("verifier", venv)):
        for field, maximum in (("gpus", 8), ("cpus", 64)):
            value = values.get(field, 0 if field == "gpus" else 1)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum or (field == "cpus" and value == 0):
                emit("F06", "RESOURCE_CONFIG", f"当前 {role}.{field} 必须为有效整数，且不超过 {maximum}。", [config_path])
        count = values.get("gpus", 0)
        if isinstance(count, int) and not isinstance(count, bool) and count > 0:
            types = values.get("gpu_types")
            if (not isinstance(types, list) or not types or not all(isinstance(x, str) and x.strip() for x in types)
                    or not any(x.strip().upper() in {"H20", "L20"} for x in types)):
                emit("F06", "GPU_TARGET", f"当前 {role} GPU 目标须包含 H20/L20；历史卡型记录不在本轮重审。", [config_path])
            elif any(x.strip().upper() not in {"H20", "L20"} for x in types):
                emit("F06", "GPU_CANDIDATE_SELECTION", "候选列表含其他卡型；本项需确认本轮内场目标选择 H20/L20，实际分配由平台验证。", [config_path], semantic=True)
            if review and review.get("task_type") == "cpu":
                emit("F06", "CPU_WITH_GPU", "当前 CPU 题不能新增 GPU 申请。", [config_path])
        phase = cfg.get("agent" if role == "agent" else "verifier", {})
        for stage, policy in (("environment", values), ("execution", phase if isinstance(phase, dict) else {})):
            if "storage_mb" in policy:
                emit("F06", "STORAGE_UNSUPPORTED", f"当前 {role}.{stage} 的 storage_mb 尚不支持，需移除。", [config_path])
            if (policy.get("network_mode") in {"no-network", "allowlist"} or policy.get("allowed_hosts")
                    or policy.get("allow_internet") is False or policy.get("network_access") is False):
                emit("F06", "NETWORK_UNSUPPORTED", f"当前 {role}.{stage} 仍声明不支持的禁网/白名单配置，需移除；历史网络行为不倒查。", [config_path])
    for directory in (task / "environment", task / "tests"):
        for name in docker_paths.COMPOSE_NAMES:
            path = directory / name
            if path.is_file() or path.is_symlink():
                emit("F06", "COMPOSE_UNSUPPORTED", "当前正式运行目录仍含 Compose，需按每 sandbox 单容器交付。", [path])
    # A source build or an existing source image is sufficient. Internal tags,
    # actual image availability, shell inference and runtime are platform work.
    agent_image = env.get("docker_image")
    agent_df = task / "environment/Dockerfile"
    if not agent_image and not agent_df.is_file():
        emit("F02", "AGENT_ENVIRONMENT_MISSING", "当前缺少 Agent Dockerfile 或有效源镜像方案。", [agent_df, config_path])
    for role, image in (("agent", agent_image), ("verifier", venv.get("docker_image") if isinstance(verifier.get("environment"), dict) else None)):
        if image is not None and not isinstance(image, str):
            emit("F02", "IMAGE_TYPE", role + " 的 docker_image 应为字符串。", [config_path])
        elif image:
            if any(symbol in image for symbol in ("\n", "[", "]", "(", ")")) or "://" in image:
                emit("F02", "IMAGE_FORMAT", role + " 的源镜像标识应是镜像引用，不能填写网页或 Markdown 链接。", [config_path])
            else:
                emit("F02", "IMAGE_PLATFORM_PREPARATION", role + " 源镜像内容、内部导入和最终 tag 由平台核对；不要求当前运行记录。", [config_path], platform=True)
    test = task / "tests/test.sh"
    dedicated_image = isinstance(verifier.get("environment"), dict) and verifier["environment"].get("docker_image")
    tests_df = task / "tests/Dockerfile"
    if not test.is_file() or not test.stat().st_size:
        if not dedicated_image and not tests_df.is_file():
            emit("F03", "TEST_ENTRY_MISSING", "复用 Agent 镜像时需提供可上传的非空 tests/test.sh。", [test])
        else:
            emit("F03", "BAKED_TEST_ENTRY", "评分入口由专用镜像或构建生成，本项需核对其入口、依赖和固定输出供给。", [config_path, tests_df if tests_df.is_file() else None], semantic=True)
    path_contract = None
    if shape_ok and task.is_dir():
        declaration = review.get("path_contract") if review else None
        # Current delivery uses the native context even when a legacy teaching
        # profile is retained for history. A generic reviewer declaration cannot
        # make task-root COPY sources valid in the current inner-field build.
        native_declaration = copy.deepcopy(declaration) if isinstance(declaration, dict) else {}
        invalid_context = native_declaration.get("profile") == docker_paths.TEACHING
        for name, expected in (("build_context", task / "environment"), ("dockerfile", task / "environment/Dockerfile")):
            value = native_declaration.get(name)
            if value is not None:
                if not isinstance(value, str) or (root / value).resolve() != expected.resolve():
                    invalid_context = True
        if invalid_context and not agent_image:
            emit("F02", "NATIVE_BUILD_CONTEXT_REQUIRED", "当前 Agent 构建上下文必须为 environment/，专用 Verifier 为 tests/；旧 task-root 教学或 generic custom 声明不能替代最新版格式，公开 Dev 来源应迁入 environment/ 内并更新实际入口。", [task / "task.toml", agent_df])
        elif invalid_context:
            emit("F02", "UNUSED_LEGACY_BUILD_RECIPE", "当前明确选择源镜像，旧 task-root Dockerfile 构建声明不作为本次生效构建路径；源镜像内容和内部准备仍由平台核对。", [task / "task.toml"], platform=True)
        native_declaration["profile"] = docker_paths.NATIVE
        native_declaration.pop("build_context", None)
        native_declaration.pop("dockerfile", None)
        path_contract = docker_paths.inspect(root, reference(task), cfg, native_declaration, require_separate=True)
        platform_codes = {"runtime_unverified", "prebuilt_image", "prebuilt_or_compose_verifier", "runtime_declared"}
        soft_runtime_codes = {"runtime_entry_unmapped", "runtime_command_unmapped", "runtime_command_parse", "dynamic_entry", "dynamic_runtime_command"}
        for item in path_contract.get("findings", []):
            code = item["code"].removeprefix("verifier_")
            if item["status"] in {"pass", "not_applicable"}:
                continue
            paths = [root / p.split(":", 1)[0] for p in item.get("evidence", [])]
            if code in platform_codes:
                emit("F03", "PLATFORM_" + code.upper(), item["message"], paths, platform=True)
            elif code == "private_copy_source":
                emit("F05", "PRIVATE_COPY_REVIEW", "实际复制的材料需确认是公开 Dev/共享实现还是私有 Hidden/Reference；不按文件名直接判退。", paths, semantic=True)
            elif item["status"] == "fail" and code not in soft_runtime_codes:
                owner = "F03" if code in {"uploaded_test_entry_missing", "entry_missing", "runtime_command_missing", "agent_final_test_entry"} else "F02"
                emit(owner, "PATH_" + code.upper(), item["message"], paths)
            else:
                owner = "F03" if code in soft_runtime_codes else "F02"
                emit(owner, "PATH_" + code.upper(), item["message"], paths, semantic=True)
        # The helper reports conventional recipe paths even when an explicit
        # image is selected. Audit FROM only for actual source builds, and once
        # when the independent Verifier reuses the Agent's resulting image.
        build_fields = ["dockerfile"] if not agent_image else []
        if path_contract.get("image_selection", {}).get("source") == "tests_dockerfile":
            build_fields.append("verifier_dockerfile")
        selected_recipes = {path_contract[field] for field in build_fields if isinstance(path_contract.get(field), str)}
        for value in sorted(selected_recipes):
            path = root / value
            if path.is_file() and not path.is_symlink():
                raw = read_current(path)
                if not any(command == "FROM" for _, command, _ in docker_paths.instructions(raw)):
                    emit("F02", "DOCKERFILE_FROM", "有效 Dockerfile 需要 FROM 构建阶段。", [path])
    # Explicit source objects and Harbor's default /logs/artifacts are legal.
    artifacts = cfg.get("artifacts", [])
    definite, uncertain = ["/logs/artifacts"], []
    if not isinstance(artifacts, list):
        emit("F04", "ARTIFACTS_TYPE", "顶层 artifacts 应为数组，可省略或为空以保留默认 /logs/artifacts。", [config_path])
        artifacts = []
    for index, item in enumerate(artifacts):
        source = item.get("source") if isinstance(item, dict) else item
        if not isinstance(source, str) or not source.startswith("/") or ".." in PurePosixPath(source).parts or "\\" in source:
            emit("F04", "ARTIFACTS_SOURCE", f"artifacts[{index}] 应为绝对源路径或含绝对 source 的对象。", [config_path])
        elif re.search(r"[$*?\[{}]", source) or (isinstance(item, dict) and (item.get("exclude") or item.get("service", "main") != "main")):
            uncertain.append(source)
            emit("F04", "ARTIFACTS_DYNAMIC", "移交规则含变量、glob、exclude 或 service，需要核对当前候选路径是否被覆盖；无需历史运行记录。", [config_path], semantic=True)
        else:
            definite.append(source.rstrip("/") or "/")
    requested = []
    if review and review.get("submission_paths") is not None:
        requested = copy.deepcopy(review["submission_paths"])
        if not isinstance(requested, list) or any(not isinstance(p, str) or not p.startswith("/") or ".." in PurePosixPath(p).parts for p in requested):
            raise ReviewError("REVIEW_SUBMISSION_PATHS", "submission_paths 应据当前 Verifier 填写绝对读取路径，不是专家新增字段。")
    adapter = cfg.get("adapter", {})
    if isinstance(adapter, dict) and isinstance(adapter.get("agent_submission_dir"), str):
        requested.append(adapter["agent_submission_dir"])
    if test.is_file():
        raw = read_current(test)
        # A single ordinary invocation is a concrete contract; do not infer
        # runtime branches, variables or historical logs from keywords.
        if not re.search(r"(?m)^\s*(?:if|for|while|case|function|exit|return)\b|&&|\|\||[;`]|\$\(", raw):
            for line in raw.splitlines():
                try:
                    tokens = shlex.split(line, comments=True)
                except ValueError:
                    continue
                if not tokens or tokens[0] in {"echo", "printf", "cat"}:
                    continue
                for i, token in enumerate(tokens):
                    flag, sep, inline = token.partition("=")
                    if flag in {"--submission", "--submission-dir", "--candidate", "--solution"}:
                        value = inline if sep else tokens[i + 1] if i + 1 < len(tokens) else ""
                        if value.startswith("/") and not re.search(r"[$*?\[{}]", value):
                            requested.append(value)
    for path in sorted(set(requested)):
        if not any(path == s or path.startswith(s.rstrip("/") + "/") for s in definite):
            emit("F04", "ARTIFACTS_UNCOVERED", "当前提交物移交未覆盖 Verifier 读取路径：" + path,
                 [config_path, test if test.is_file() else None], semantic=bool(uncertain))
    return {"bundle_root": reference(bundle), "task_root": reference(task), "issues": issues,
            "semantic_observations": observations, "platform_observations": notes,
            "path_contract": path_contract, "artifact_contract": {"definite_sources": definite,
                "uncertain_sources": uncertain, "submission_paths": sorted(set(requested))},
            "config": cfg, "source_config": original_config}


def review_template(scan):
    return {"schema_version": 1, "stage": "format_repair", "task_root": scan["task_root"], "task_type": "gpu" if any(
                isinstance(scan["config"].get(key), dict) and scan["config"][key].get("gpus", 0) for key in ("environment",)) else "cpu",
            "checks": [{"id": key, "status": None, "summary": "", "evidence": [], "remediation": "", "acceptance_evidence": "",
                        "resolutions": [{"observation_id": item["observation_id"], "summary": "", "evidence": []}
                                        for item in scan["semantic_observations"] if item["owner"] == key]}
                       for key in CHECKS],
            "review_note": "本文件由质检员据当前材料核实七项后填写，不是专家新增交付或补跑要求；status 只填 pass/fail。平台事项和历史记录不要求填写通过证明。"}


def assess(root, review=None):
    root = Path(root).resolve()
    result = {"schema_version": 1, "version": VERSION, "stage": "format_repair",
              "generated_at": datetime.now(timezone.utc).isoformat(), "decision": "ERROR", "code": None,
              "is_task_rejection": False, "checks": [], "current_findings": [], "semantic_observations": [],
              "platform_followup_pending": copy.deepcopy(PLATFORM), "platform_runtime_status": "not_executed",
              "historical_rules_not_checked": [{"summary": item, "blocking": False} for item in EXCLUDED], "task_code_executed": False,
              "review_diagnostics": [],
              "input_and_review_errors": [], "scope_note": "本批只审当前格式与核心交付语义；历史记录与平台实跑事项不作为本轮门槛。"}
    try:
        scan = inventory(root, review)
        result.update({key: scan[key] for key in ("task_root", "bundle_root", "semantic_observations", "platform_observations", "artifact_contract")})
        result["current_findings"] = scan["issues"]
        result["review_template"] = review_template(scan)
        if review is None:
            raise ReviewError("REVIEW_NOT_PROVIDED", "当前七项核心语义尚未由质检员填写；已生成审核模板。这是审核流程未完成，不是专家返修或补跑要求。")
        if review.get("schema_version") != 1 or review.get("stage") != "format_repair" or review.get("task_type") not in {"cpu", "gpu"}:
            raise ReviewError("REVIEW_SCHEMA", "质检员应使用 schema_version=1、stage=format_repair 并据当前题目判明 cpu/gpu。")
        rows = review.get("checks")
        if (not isinstance(rows, list) or len(rows) != len(CHECKS) or any(not isinstance(item, dict) for item in rows)
                or {item.get("id") for item in rows} != set(CHECKS)):
            raise ReviewError("REVIEW_CHECKS", "质检员应完成 F01–F07，恰好各一项。")
        for key in CHECKS:
            original = next(item for item in rows if item["id"] == key)
            row = copy.deepcopy(original)
            if row.get("status") not in {"pass", "fail"} or not isinstance(row.get("summary"), str) or not row["summary"].strip():
                raise ReviewError("CORE_REVIEW_NOT_FINISHED", key + " 需完成实际审阅并填写 pass/fail 和具体原因；不可把平台未知或旧记录欠缺写成当前失败。")
            refs = row.get("evidence")
            if not isinstance(refs, list) or not refs:
                raise ReviewError("REVIEW_EVIDENCE", key + " 应引用当前核实的文件或 @current_inventory，不要求新增专家记录。")
            files = []
            for ref in refs:
                if ref == "@current_inventory":
                    continue
                try:
                    files.append(safe_reference(root, ref))
                except ReviewError as exc:
                    name = ref.split("#", 1)[0] if isinstance(ref, str) else ""
                    candidate = Path(name)
                    if (scan["issues"] and exc.code == "REVIEW_EVIDENCE" and name and not candidate.is_absolute()
                            and ".." not in candidate.parts and (root / candidate).resolve().is_relative_to(root)
                            and not (root / candidate).exists()):
                        result["review_diagnostics"].append({"owner": key, "code": "MISSING_CURRENT_EVIDENCE_LOCATION",
                            "summary": "当前引用文件已缺失，已有确定格式问题保持 FAIL；该定位供质检员核对：" + ref, "blocking": False})
                        continue
                    raise
            if row["status"] == "pass" and not files:
                if scan["issues"]:
                    result["review_diagnostics"].append({"owner": key, "code": "REVIEW_EVIDENCE_NOT_READ",
                        "summary": "已有确定格式问题，保留该问题；本项未以空引用证明通过。", "blocking": False})
                else:
                    raise ReviewError("REVIEW_EVIDENCE", key + " 的 pass 不能仅引用目录清单，应实际审阅对应内容。")
            if row["status"] == "fail" and (not row.get("remediation") or not row.get("acceptance_evidence")):
                raise ReviewError("REVIEW_ACTION", key + " 的实际返修问题需给出具体整改与验收依据。")
            observations = [item for item in scan["semantic_observations"] if item["owner"] == key]
            resolutions = row.get("resolutions", [])
            if not isinstance(resolutions, list) or any(not isinstance(item, dict) for item in resolutions):
                raise ReviewError("REVIEW_RESOLUTION", key + " resolutions 应为质检员对当前语义项的逐项解释。")
            if len({item.get("observation_id") for item in resolutions}) != len(resolutions):
                raise ReviewError("REVIEW_RESOLUTION", key + " 的语义解释重复。")
            known = {item["observation_id"] for item in observations}
            if any(item.get("observation_id") not in known for item in resolutions):
                raise ReviewError("REVIEW_RESOLUTION", key + " 的解释引用了非当前观察。")
            for observation in observations:
                resolution = next((item for item in resolutions if item.get("observation_id") == observation["observation_id"]), None)
                if row["status"] == "fail" and resolution is None:
                    continue
                if not resolution or not resolution.get("summary") or not isinstance(resolution.get("evidence"), list) or not resolution["evidence"]:
                    if scan["issues"] or any(item.get("status") == "fail" for item in rows):
                        result["review_diagnostics"].append({"owner": key, "code": "CURRENT_SEMANTIC_REVIEW_REQUIRED",
                            "summary": "已有确定的当前缺陷，本观察另供质检员核对，不遮盖该缺陷：" + observation["summary"], "blocking": False})
                        continue
                    raise ReviewError("CURRENT_SEMANTIC_REVIEW_REQUIRED", key + " 尚需质检员核实当前表达：" + observation["summary"])
                for ref in resolution["evidence"]:
                    safe_reference(root, ref)
                if resolution.get("confirmed_private_exposure") is True:
                    scan["issues"].append({"owner": "F05", "code": "CONFIRMED_CURRENT_PRIVATE_EXPOSURE",
                        "summary": resolution["summary"], "evidence": resolution["evidence"]})
            automatic = [item for item in scan["issues"] if item["owner"] == key]
            row.update(title=CHECKS[key], review_status=original["status"], status="fail" if automatic else row["status"], automatic_findings=automatic)
            result["checks"].append(row)
        result["current_findings"] = scan["issues"]
        for row in result["checks"]:
            automatic = [item for item in scan["issues"] if item["owner"] == row["id"]]
            if automatic:
                row.update(status="fail", automatic_findings=automatic)
                if not row.get("remediation"):
                    row["remediation"] = "修正本项列出的当前目录、文件、配置或路径错误。"
                    row["acceptance_evidence"] = "修正后的当前完整包与本项引用的入口、文件及配置一致。"
        result["decision"] = "FAIL" if any(item["status"] == "fail" for item in result["checks"]) else "PASS_WITH_WAIVERS"
        result["is_task_rejection"] = result["decision"] == "FAIL"
        result["code"] = "CURRENT_FORMAT_FAULTS" if result["decision"] == "FAIL" else "FORMAT_REPAIR_ACCEPTED"
    except ReviewError as exc:
        result["decision"], result["code"] = "ERROR", exc.code
        result["input_and_review_errors"].append(str(exc))
    except (OSError, ValueError, KeyError, TypeError, UnicodeError) as exc:
        result["decision"], result["code"] = "ERROR", "INPUT_OR_REVIEW_ERROR"
        result["input_and_review_errors"].append(str(exc))
    return result


def render(result):
    lines = ["# 旧题格式返修检查", "", "本轮结论：" + result["decision"], "阶段：format_repair", "",
             result["scope_note"], "平台运行状态：not_executed；本次未运行模型、题目代码、Docker 或 Harbor。", ""]
    if result["decision"] == "ERROR":
        lines += ["这是工具输入或质检流程状态，不是题目判退。", "原因代码：" + str(result.get("code")), ""]
        lines += ["- " + item for item in result.get("input_and_review_errors", [])]
    lines += ["", "## 本轮七项核心检查", ""]
    for row in result.get("checks", []):
        lines.append(f"- {row['id']} [{row['status']}] {row['title']}：{row['summary']}")
        lines.append("  审阅证据：" + "；".join(row.get("evidence", [])))
        for item in row.get("automatic_findings", []):
            lines += ["  已确认格式问题：" + item["summary"], "  定位：" + "；".join(item.get("evidence", []))]
        if row["status"] == "fail" and row.get("remediation"):
            lines += ["  整改：" + row["remediation"], "  验收：" + row.get("acceptance_evidence", "")]
    lines += ["", "## 平台后续事项（不阻断本轮）", ""]
    lines += ["- " + item["summary"] for item in result.get("platform_followup_pending", [])]
    lines += ["", "## 本轮不复查的历史事项", ""]
    lines += ["- " + (item["summary"] if isinstance(item, dict) else item) for item in result.get("historical_rules_not_checked", [])]
    return "\n".join(lines) + "\n"


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".format-repair-", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_report(result, out):
    output = copy.deepcopy(result)
    template = output.pop("review_template", None)
    serialized = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    atomic_write(out / "format_report.json", serialized)
    atomic_write(out / "report.json", serialized)  # Compatibility alias only.
    text = render(output)
    for name in ("format_report.md", "format_report.txt", "report.md", "report.txt"):
        atomic_write(out / name, text)
    if output["decision"] == "PASS_WITH_WAIVERS":
        expert = "本轮结论：PASS_WITH_WAIVERS。无需当前格式返修。\n"
    elif output["decision"] == "FAIL":
        lines = ["本轮结论：FAIL。以下为当前格式或核心交付问题：", ""]
        for row in output.get("checks", []):
            if row["status"] != "fail":
                continue
            lines.append(row["id"] + "：" + row["title"])
            if row.get("review_status") == "fail":
                lines.append("问题：" + row["summary"])
            for item in row.get("automatic_findings", []):
                lines += ["问题：" + item["summary"], "定位：" + "；".join(item.get("evidence", []))]
            if row.get("remediation"):
                lines += ["整改：" + row["remediation"], "验收：" + row.get("acceptance_evidence", "")]
            lines.append("")
        expert = "\n".join(lines) + "\n"
    else:
        expert = "本次未形成可发送给专家的当前格式返修项。\n"
    atomic_write(out / "return_to_expert.txt", expert)
    if template is not None:
        atomic_write(out / "review_template.json", json.dumps(template, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, epilog=(
        "Current native contexts are environment/ for Agent and tests/ for a dedicated Verifier. "
        "Old [resources]/[entrypoint] do not automatically become effective Harbor settings. "
        "Reviewer-only optional config_adapter={entrypoint,effective_task,summary,evidence} cites an existing adapter, "
        "an existing native TOML in the same current task directory and its actual invocation/mapping evidence; no adapter is executed. "
        "legacy_entrypoint_inactive={summary,evidence} may identify old entrypoint notes replaced by existing native environment and tests/test.sh. "
        "Both branches require F01 semantic resolutions based on current source, not new expert logs or a new expert schema."))
    parser.add_argument("source", type=Path)
    parser.add_argument("--review", type=Path, help="reviewer's current seven-item review; not a new expert submission schema")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    source, out = args.source.expanduser().resolve(), args.out_dir.expanduser().resolve()
    if out == source or (source.is_dir() and out.is_relative_to(source)):
        parser.error("out-dir must be outside the submitted artifact")
    output_names = {"format_report.json", "format_report.md", "format_report.txt", "report.json", "report.md", "report.txt", "return_to_expert.txt", "review_template.json"}
    if any(source == out / name for name in output_names):
        parser.error("an output file must not overwrite the submitted input")
    if args.review:
        review_path = args.review.expanduser().resolve()
        if review_path == out or any(review_path == out / name for name in output_names):
            parser.error("a generated output file must not overwrite the review input; save the worksheet as format_review.json")
    try:
        review = json_object(args.review) if args.review else None
        if source.is_dir():
            result = assess(source, review)
        elif source.is_file() and zipfile.is_zipfile(source):
            with tempfile.TemporaryDirectory(prefix="format-repair-") as directory:
                root = Path(directory).resolve()
                unpack(source, root)
                result = assess(root, review)
        else:
            raise ReviewError("INPUT_UNREADABLE", "输入应为可读取的当前完整包目录或 ZIP；工具未执行题目判定。")
    except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, NotImplementedError) as exc:
        result = {"schema_version": 1, "version": VERSION, "stage": "format_repair", "decision": "ERROR",
                  "code": getattr(exc, "code", "INPUT_OR_REVIEW_ERROR"), "is_task_rejection": False,
                  "input_and_review_errors": [str(exc)], "checks": [], "current_findings": [],
                  "platform_runtime_status": "not_executed", "platform_followup_pending": copy.deepcopy(PLATFORM),
                  "historical_rules_not_checked": [{"summary": item, "blocking": False} for item in EXCLUDED], "scope_note": "输入或审核工作文件未完成读取，不构成题目判退。"}
    result["source"] = str(source)
    write_report(result, out)
    print(json.dumps({"decision": result["decision"], "code": result.get("code"), "report": str(out / "format_report.json")}, ensure_ascii=False))
    return 0 if result["decision"] == "PASS_WITH_WAIVERS" else 1 if result["decision"] == "FAIL" else 2


if __name__ == "__main__":
    raise SystemExit(main())
