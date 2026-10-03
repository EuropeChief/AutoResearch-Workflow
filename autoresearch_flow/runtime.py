"""W3 Codex-in-Docker runner. Host supervisor owns logs and timing evidence."""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import tomllib
import uuid
from contextlib import contextmanager
from pathlib import Path

from .core import (FlowError, TaskStore, _atomic_json, _canonical_digest, _read_json,
                   _require, _sha256, _utc_now)
from .experiments import evidence
from .runtime_events import EventClock, Redactor, effective_seconds, union
from .runtime_tui import NativeEvents, RolloutTail, TmuxTerminal, codex_command
from .trajectory import raw_public_metric
from .duration import snapshot as duration_snapshot, prompt_text as duration_prompt

TRACKS = ("codex", "seed")
DEFAULT_PROFILE_DIR = Path(__file__).resolve().parents[1] / "local" / "model_profiles"
EVALUATE = "/workspace/evaluate"
CONTINUE_PROMPT = (
    "请在当前同一会话中继续原任务的真实方法迭代。遵守原题面与可修改范围，"
    "使用既定 Public/Dev 入口。每完成一轮，由你向 /expert_evidence/trajectory.jsonl "
    "追加八字段 round、policy_name、method_summary、status、score、failure_reason、retained_best、time。"
    "score 使用公开结果的 raw_metric.value 而非归一化 score；无分为 null，成功 status=ok、原因=null，"
    "失败如实写原因。本轮刷新最佳时 retained_best=true；time 为完成时间 YYYY-MM-DD HH:mm:ss。"
    "中文摘要为 1 至 3 句话。最佳代码更新到 /expert_evidence/best_method/；"
    "结束前重新公开评测并把最佳代码和必需模型/配置恢复到 /workspace/solution。"
    "未提升也应如实记录；不要通过空转、重复无变化评测或等待凑时长。"
)
CLOSE_PROMPT = (
    "当前可核活动时长已达到冻结门槛，请在原会话完成最后收口，不再开启新优化方向。"
    "核对并恢复你记录的最佳代码和必需模型/配置到 /workspace/solution，"
    "单独原样执行 /workspace/evaluate，等待真实结果。"
    "如实补齐 /expert_evidence/trajectory.jsonl 的八字段记录（score 为 raw_metric.value），"
    "确保 /expert_evidence/best_method/ 与恢复的最佳实现一致，再报告结果并结束本次回答。"
    "不得伪造记录或为了收口改写失败结论；不调用 Hidden。"
)


def _relative(value):
    _require(isinstance(value, str) and value and "\\" not in value, "INVALID_PATH", "须使用非空相对路径")
    path = Path(value)
    _require(not path.is_absolute() and ".." not in path.parts and path.parts, "INVALID_PATH", "路径不得越界")
    return path


def validate_config(config, root):
    _require(isinstance(config, dict) and config.get("schema_version") == 2, "INVALID_RUNTIME", "PCA runtime schema_version 必须为 2；旧配置须显式适配")
    allowed = {"schema_version", "image", "codex_version", "public_files", "starter_files",
               "prompt", "evaluation", "boundaries", "resources", "tracks", "silence_seconds", "log_limit_bytes", "docker_security", "harness"}
    _require(set(config) <= allowed, "INVALID_RUNTIME", "配置有未知字段；密钥只能经 auth_ref 引用")
    _require(bool(re.fullmatch(r"(?:[\w./:-]+@)?sha256:[0-9a-f]{64}", str(config.get("image", "")))), "IMAGE_NOT_PINNED", "镜像须为 sha256 ID 或带 digest 的引用")
    _require(bool(re.fullmatch(r"\d+\.\d+\.\d+", str(config.get("codex_version", "")))), "INVALID_RUNTIME", "须锁定 Codex 版本")
    evidence(root, config["prompt"])
    if "docker_security" in config:
        security = config["docker_security"]
        _require(isinstance(security, dict) and set(security) == {"apparmor", "seccomp", "approval"},
                 "INVALID_SECURITY", "安全例外须同时声明 AppArmor、限定 seccomp 文件和用户授权证据")
        _require(isinstance(security["apparmor"], str) and
                 bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", security["apparmor"])),
                 "INVALID_SECURITY", "AppArmor 仅接受明确的 profile 名称")
        evidence(root, security["approval"])
        profile = _read_json(evidence(root, security["seccomp"]))
        _require(profile.get("defaultAction") == "SCMP_ACT_ERRNO" and isinstance(profile.get("syscalls"), list),
                 "INVALID_SECURITY", "seccomp 必须保留默认拒绝；安全适用性还须专家审阅")
    denied = {"tests", "reference", "optimization_evidence", "expert_evidence", "hidden_assets", ".autoresearch", ".autoresearch-flow", ".codex", ".git"}
    destinations = set()
    for group in ("public_files", "starter_files"):
        _require(isinstance(config.get(group), list) and config[group], "INVALID_RUNTIME", f"{group} 不能为空")
        for item in config[group]:
            _require(isinstance(item, dict) and set(item) == {"source", "destination"}, "INVALID_RUNTIME", "文件映射须含 source 和 destination")
            source = evidence(root, item["source"])
            target = _relative(item["destination"])
            _require(not (set(target.parts) | set(Path(item["source"]["path"]).parts)) & denied, "PRIVATE_ASSET", "禁止将参考解、证据、Hidden 或宿主配置映入 Agent")
            _require(group != "public_files" or target.parts[0] not in {"solution", "starter", "evaluate", "boundary_probe.py", "_segment_exec.py", "_evaluate.py", "_public_command.json"}, "RESERVED_PATH", "public 目标与底座保留路径冲突")
            key = (group, str(target))
            _require(key not in destinations, "DUPLICATE_PATH", "文件目标重复")
            destinations.add(key)
    evaluation = config.get("evaluation", {})
    _require(isinstance(evaluation, dict) and set(evaluation) <= {"command", "smoke_args", "timeout_seconds"}, "INVALID_EVALUATOR", "评测配置字段不合法")
    command = evaluation.get("command")
    _require(isinstance(command, list) and command and all(isinstance(v, str) and v for v in command), "INVALID_EVALUATOR", "评测入口必须为参数数组")
    executable = Path(command[0])
    _require(executable.is_absolute() and ".." not in executable.parts
             and not any(executable.is_relative_to(p) for p in ("/workspace/solution", "/expert_evidence", "/codex", "/tmp"))
             and (not executable.is_relative_to("/workspace") or executable.is_relative_to("/workspace/public_eval")),
             "INVALID_EVALUATOR", "入口须来自固定镜像/只读 public_eval，不能来自候选写入区")
    # A fixed grader may legitimately receive --candidate /workspace/solution.
    # Interpreter scripts themselves must remain on the trusted side.
    if executable.name.startswith(("python", "pypy")) or executable.name in {"sh", "bash", "node"}:
        _require(len(command) > 1 and command[1].startswith("/") and ".." not in Path(command[1]).parts
                 and not any(Path(command[1]).is_relative_to(p) for p in
                             ("/workspace/solution", "/expert_evidence", "/codex", "/tmp")),
                 "INVALID_EVALUATOR", "解释器须直接运行固定只读评分脚本，不接受候选脚本或 -c/-m 间接入口")
    _require(isinstance(evaluation.get("smoke_args", []), list) and all(isinstance(v, str) for v in evaluation.get("smoke_args", [])), "INVALID_EVALUATOR", "smoke_args 必须为字符串数组")
    _require(type(evaluation.get("timeout_seconds")) is int and evaluation["timeout_seconds"] > 0, "INVALID_EVALUATOR", "须提供冒烟超时")
    boundaries = config.get("boundaries")
    _require(isinstance(boundaries, dict) and set(boundaries) == {"readable", "readonly", "unreadable"}, "INVALID_BOUNDARY", "须声明可读、只读和不可读路径")
    for paths in boundaries.values():
        _require(isinstance(paths, list) and all(isinstance(v, str) and v.startswith("/") for v in paths), "INVALID_BOUNDARY", "边界路径必须为容器内绝对路径")
    resources = config.get("resources", {})
    _require(isinstance(resources, dict) and set(resources) == {"cpus", "memory", "gpus"}, "INVALID_RESOURCES", "资源须包含 cpus/memory/gpus")
    _require(type(resources["cpus"]) in (int, float) and math.isfinite(resources["cpus"]) and resources["cpus"] > 0, "INVALID_RESOURCES", "cpus 必须为正数")
    _require(isinstance(resources["memory"], str) and bool(re.fullmatch(r"[1-9][0-9]*[mMgG]", resources["memory"])), "INVALID_RESOURCES", "memory 使用如 16g")
    _require(isinstance(resources["gpus"], dict) and set(resources["gpus"]) == set(TRACKS), "INVALID_RESOURCES", "每条轨迹须指定 GPU 或 null")
    for gpu in resources["gpus"].values():
        _require(gpu is None or isinstance(gpu, str) and bool(re.fullmatch(r"\d+(?:,\d+)*", gpu)), "INVALID_RESOURCES", "GPU 使用索引字符串或 null")
    _require(isinstance(config.get("tracks"), dict) and set(config["tracks"]) == set(TRACKS), "INVALID_RUNTIME", "须恰好配置 codex 和 seed 两组")
    for track in config["tracks"].values():
        _require(isinstance(track, dict) and set(track) <= {"model", "reasoning_effort", "base_url", "auth_ref", "context_window", "auto_compact_token_limit", "max_output_tokens"}, "INVALID_MODEL", "模型配置含未知字段")
        _require(isinstance(track.get("model"), str) and track["model"].strip(), "INVALID_MODEL", "须提供准确模型 ID")
        _require(track.get("reasoning_effort") in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}, "INVALID_MODEL", "须显式指定推理档位")
        auth = track.get("auth_ref")
        _require(isinstance(auth, dict) and set(auth) <= {"kind", "path", "key"} and auth.get("kind") in {"api_key_json", "codex_login"} and isinstance(auth.get("path"), str) and Path(auth["path"]).is_absolute(), "INVALID_AUTH", "auth_ref 须引用绝对路径凭据文件，不含凭据值")
        if auth["kind"] == "api_key_json":
            _require(isinstance(auth.get("key"), str) and auth["key"], "INVALID_AUTH", "API key JSON 须声明字段名")
            _require(isinstance(track.get("base_url"), str) and track["base_url"].startswith("https://") and "@" not in track["base_url"] and "?" not in track["base_url"], "INVALID_PROVIDER", "API base_url 须为不含凭据或查询参数的 HTTPS 地址")
        else:
            _require(not track.get("base_url"), "INVALID_PROVIDER", "登录凭据使用 Codex 默认 provider")
        if any(key in track for key in ("context_window", "auto_compact_token_limit", "max_output_tokens")):
            _require(all(type(track.get(key)) is int and track[key] > 0 for key in ("context_window", "auto_compact_token_limit", "max_output_tokens")), "INVALID_CONTEXT", "上下文配置须同时提供 window/compact/output 三个正整数")
            _require(track["auto_compact_token_limit"] + track["max_output_tokens"] < track["context_window"], "INVALID_CONTEXT", "压缩阈值须为输出与协议开销保留空间")
    for key, default in (("silence_seconds", 300), ("log_limit_bytes", 268435456)):
        _require(type(config.get(key, default)) is int and config.get(key, default) > 0, "INVALID_RUNTIME", f"{key} 必须为正整数")


def public_evaluation(item, exact):
    """Accept the fixed public command, optionally after a literal workspace cd."""
    if item.get('type') != 'command_execution' or item.get('exit_code') != 0:
        return None
    try:
        text = item.get('command', '')
        command = shlex.split(text)
        if len(command) == 3 and Path(command[0]).name in {'bash', 'sh'} and command[1] in {'-lc', '-c'}:
            text = command[2]
        # Native Codex commonly adds this harmless working-directory prefix.
        # Strip only the two literal public directories; do not accept arbitrary
        # shell composition, substitutions, pipes or result-producing suffixes.
        text = re.sub(r'^cd[ \t]+/workspace(?:/solution)?[ \t]*&&[ \t]*', '', text, count=1)
        command = shlex.split(text)
        if command != exact:
            return None
        value = json.loads(item.get('aggregated_output', item.get('output', '')).strip().splitlines()[-1])
        if (value.get('status') == 'succeeded' and type(value.get('score')) in (int, float)
                and math.isfinite(value['score']) and raw_public_metric(value) is not None):
            return value
    except (ValueError, IndexError, TypeError, AttributeError, FlowError):
        return None
    return None


def model_config(track):
    q = lambda value: json.dumps(value, ensure_ascii=False)
    lines = [f"model = {q(track['model'])}", f"model_reasoning_effort = {q(track['reasoning_effort'])}",
             'approval_policy = "never"', 'default_permissions = "autoresearch"',
             'cli_auth_credentials_store = "file"']
    for field, name in (("context_window", "model_context_window"), ("auto_compact_token_limit", "model_auto_compact_token_limit")):
        if field in track:
            lines.append(f"{name} = {track[field]}")
    if track["auth_ref"]["kind"] == "api_key_json":
        lines.extend(['model_provider = "autoresearch"', '[model_providers.autoresearch]',
                      'name = "AutoResearch configured provider"', f"base_url = {q(track['base_url'])}",
                      'wire_api = "responses"', 'env_key = "AUTORESEARCH_MODEL_KEY"'])
    # The runtime owns this exact container workspace. Native TUI must not
    # prompt again on resume; project trust does not replace sandbox permissions.
    lines.extend(['[projects."/workspace/solution"]', 'trust_level = "trusted"',
                  '[shell_environment_policy]', 'inherit = "all"',
                  'include_only = ["PATH", "LANG", "LC_ALL", "TERM", "CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES", "NVIDIA_DRIVER_CAPABILITIES"]',
                  '[permissions.autoresearch.filesystem]', '"/" = "read"', '"/codex/auth.json" = "deny"',
                  '"/workspace/solution" = "write"', '"/expert_evidence" = "write"', '"/tmp" = "write"',
                  '[permissions.autoresearch.network]', 'enabled = false'])
    return "\n".join(lines) + "\n"


BOUNDARY_PROBE = """import json, os, pathlib, sys, uuid
spec=json.loads(sys.argv[1]); problems=[]
for name in ('readable','readonly','unreadable'):
    for value in spec[name]:
        path=pathlib.Path(value)
        if name=='unreadable':
            try:
                if path.is_dir(): list(path.iterdir())
                else:
                    with path.open('rb'): pass
            except (OSError, PermissionError): pass
            else: problems.append('unexpected read access: '+value)
        else:
            try:
                if path.is_dir(): list(path.iterdir())
                else:
                    with path.open('rb'): pass
            except OSError: problems.append('missing read access: '+value)
            if name=='readonly':
                probe = path / ('.w3-readonly-'+uuid.uuid4().hex) if path.is_dir() else path
                created = False
                try:
                    with probe.open('x' if path.is_dir() else 'ab'): pass
                    created = probe != path
                except OSError: pass
                else: problems.append('unexpected write access: '+value)
                finally:
                    if created: probe.unlink()
for base in ('/workspace/solution','/expert_evidence'):
    path=pathlib.Path(base)/('.w3-probe-'+str(os.getpid()))
    try:
        with path.open('x') as stream: stream.write('probe')
        path.unlink()
    except OSError: problems.append('not writable: '+base)
print(json.dumps({'status':'ok' if not problems else 'blocked','issues':problems}))
sys.exit(0 if not problems else 2)
"""


class DockerBackend:
    def command(self, runtime, track, phase, container, command, use_auth=False):
        config = runtime.config
        base = runtime.directory / track / phase
        _require(os.getuid() != 0, "NONROOT_REQUIRED", "运行底座须由非 root 专家用户调用")
        args = ["docker", "run", "--rm", "-i", "--init", "--name", container, "--read-only",
                "--user", f"{os.getuid()}:{os.getgid()}", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges", "--cpus", str(config["resources"]["cpus"]),
                "--memory", config["resources"]["memory"], "--tmpfs", "/tmp:rw,nosuid,size=1g",
                "--workdir", "/workspace/solution", "--env", "CODEX_HOME=/codex"]
        if "docker_security" in config:
            args.extend(["--security-opt", "apparmor=" + config["docker_security"]["apparmor"],
                         "--security-opt", "seccomp=" + str(runtime.directory / "security/seccomp.json")])
        mounts = [(p, "/workspace/" + p.name, True)
                  for p in sorted((runtime.directory / "public").iterdir())]
        mounts.extend((
            (base / "solution", "/workspace/solution", False),
            (base / "output", "/expert_evidence", False),
            (base / "codex_home", "/codex", False),
            (runtime.directory / track / "config.toml", "/codex/config.toml", True),
        ))
        for source, destination, readonly in mounts:
            _require("," not in str(source) and "\n" not in str(source), "INVALID_MOUNT", "挂载路径不能包含逗号或换行")
            args.extend(["--mount", f"type=bind,src={source},dst={destination}" + (",readonly" if readonly else "")])
        gpu = config["resources"]["gpus"][track]
        if gpu:
            args.extend(["--gpus", f'"device={gpu}"'])
        if use_auth and config["tracks"][track]["auth_ref"]["kind"] == "api_key_json":
            args.extend(["--env", "AUTORESEARCH_MODEL_KEY"])
        if not use_auth:
            args.extend(["--network", "none"])
        args.extend([config["image"], *command])
        return args

    def check(self, runtime, track):
        try:
            result = subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", runtime.config["image"]], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise FlowError("HOST_DEPENDENCY_UNAVAILABLE",
                            "无法调用 Docker；请由用户核对 PATH、docker --version 与 docker ps，补齐已有环境；流程不自动安装或改权限") from exc
        _require(result.returncode == 0, "DOCKER_UNAVAILABLE", "镜像不可用或 Docker 权限不足；请核对镜像与 docker ps 权限")
        image_id = result.stdout.strip()
        command = self.command(runtime, track, "preflight", "ar-check-" + uuid.uuid4().hex[:12], ["codex", "--version"])
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        _require(result.returncode == 0 and runtime.config["codex_version"] in result.stdout, "CODEX_VERSION", "镜像中的 Codex 版本不符或入口无法执行 codex --version")
        return {"image_id": image_id, "codex_version_output": result.stdout.strip(), "status": "ok"}

    def boundary(self, runtime, track):
        probe = ["python3", "/workspace/boundary_probe.py", json.dumps(runtime.config["boundaries"])]
        report = {"at": _utc_now(), "probes": []}
        sandbox_probe = ["/bin/sh", "-c",
                         'exec codex sandbox -P autoresearch -- "$(command -v python3)" "$@"',
                         "ar-boundary", *probe[1:]]
        for layer, inner in (("container", probe), ("codex_sandbox", sandbox_probe)):
            name = "ar-boundary-" + uuid.uuid4().hex[:12]
            command = self.command(runtime, track, "preflight", name, inner)
            try:
                result = subprocess.run(command, capture_output=True, text=True, timeout=60)
                report["probes"].append({"layer": layer, "exit_code": result.returncode,
                                        "stdout": result.stdout, "stderr": result.stderr})
                _atomic_json(runtime.directory / track / "boundary.json", report)
                code = "SANDBOX_FAILED" if layer == "codex_sandbox" else "BOUNDARY_FAILED"
                _require(result.returncode == 0, code,
                         "容器或 Codex 沙箱不可用；尚未调用模型。查看 boundary.json；不要关闭沙箱绕过")
            finally:
                self.stop(name)
        return json.dumps(report, ensure_ascii=False)

    def stop(self, name):
        result = subprocess.run(["docker", "inspect", "--format", "{{.State.Running}}", name], capture_output=True, text=True, timeout=15)
        if result.returncode != 0:
            _require("No such" in result.stderr or "no such" in result.stderr, "CLEANUP_UNCONFIRMED", "不能确认专属容器已退出")
            return
        if result.stdout.strip() == "true":
            result = subprocess.run(["docker", "stop", "--time", "5", name], capture_output=True, text=True, timeout=15)
            _require(result.returncode == 0, "CLEANUP_UNCONFIRMED", "专属容器停止失败")


class Runtime:
    def __init__(self, task_root, backend=None, profiles_dir=None, terminal_factory=TmuxTerminal):
        self.store = TaskStore(Path(task_root))
        self.root = self.store.task_root
        self.directory = self.store.state_dir / "runtime"
        self.backend = backend or DockerBackend()
        self.profile_dir = Path(profiles_dir) if profiles_dir is not None else DEFAULT_PROFILE_DIR
        self.config = None
        self.terminal_factory = terminal_factory

    def _resolve_config(self, requested):
        _require(isinstance(requested, dict), "INVALID_RUNTIME", "运行配置须为 JSON 对象")
        _require("tracks" not in requested, "INLINE_MODEL_CONFIG_UNSUPPORTED",
                 "题目配置不接受 tracks；请在流程根 local/model_profiles/codex.toml 和 seed.toml 配置模型与鉴权引用")
        resolved = copy.deepcopy(requested)
        resolved["tracks"] = {}
        sources = {}
        for name in TRACKS:
            path = self.profile_dir / f"{name}.toml"
            _require(path.is_file(), "PROFILE_MISSING",
                     f"缺少 {name} 模型配置：{path}；从 model_profiles/{name}.example.toml 复制并填写，不覆盖已有文件")
            try:
                raw = path.read_bytes()
                profile = tomllib.loads(raw.decode("utf-8"))
            except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
                raise FlowError("PROFILE_INVALID", f"无法读取 {name} TOML 配置：{path}") from exc
            _require(profile.pop("schema_version", None) == 1, "PROFILE_INVALID", f"{name} TOML 须声明 schema_version = 1")
            resolved["tracks"][name] = profile
            sources[name] = {"path": str(path.resolve()), "sha256": hashlib.sha256(raw).hexdigest()}
        return resolved, sources

    def _load(self):
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "任务规则来源漂移")
        config = _read_json(self.directory / "config.json")
        manifest = _read_json(self.directory / "manifest.json")
        _require(manifest.get('runtime_mode') == 'native_tui', 'RUNTIME_MODE',
                 '该运行不是当前原生 TUI 快照；旧任务请使用其原版本，不自动切换或迁移轨迹')
        _require(_canonical_digest(config) == manifest["config_sha256"], "RUNTIME_DRIFT", "运行配置发生变化；不得把改配置后的会话拼接")
        _require(_canonical_digest(self.store._load()["rules_lock"]) == manifest["rules_lock_sha256"], "RUNTIME_DRIFT", "运行来源锁不一致；须使用冻结版本")
        for ref in manifest["files"]:
            evidence(self.directory, ref)
        current = duration_snapshot(self.root)
        _require(manifest.get("duration_snapshot") == current, "DURATION_DRIFT",
                 "缺少当前冻结时长快照，或准备后政策/资格证据发生变化；不使用旧运行兼容默认值")
        for track in TRACKS:
            _require(self._state(track).get("duration_sha256") == current["sha256"],
                     "DURATION_DRIFT", "双轨冻结的时长政策不一致")
        self.config = config
        return manifest

    def minimum_seconds(self):
        return duration_snapshot(self.root)["policy"]["minimum_effective_seconds"]

    def continuation_prompt(self):
        return CONTINUE_PROMPT + "\n" + duration_prompt(duration_snapshot(self.root))

    def prepare(self, config):
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "先核对规则来源")
        config, profile_sources = self._resolve_config(config)
        validate_config(config, self.root)
        NativeEvents(config['codex_version'])  # Reject unsupported protocols before auth or model calls.
        duration = duration_snapshot(self.root)
        harbor_task = None
        if 'harness' in config:
            from .harbor_runtime import validate_harness
            harbor_task = validate_harness(config, self.root)['task_sha256']
        _require(not self.directory.exists(), "RUNTIME_EXISTS", "运行目录已存在，不覆盖历史轨迹")
        temporary = Path(tempfile.mkdtemp(prefix=".runtime-", dir=self.store.state_dir))
        try:
            public = temporary / "public"
            public.mkdir()
            (public / "starter").mkdir()
            for item in config["starter_files"]:
                self._copy(item, public / "starter", readonly=True)
            for item in config["public_files"]:
                self._copy(item, public, readonly=True)
            (public / "evaluate").write_text('#!/bin/sh\nexec python3 -I /workspace/_evaluate.py "$@"\n')
            (public / "evaluate").chmod(0o555)
            shutil.copyfile(Path(__file__).with_name('runtime_evaluate.py'), public/'_evaluate.py')
            (public/'_evaluate.py').chmod(0o444)
            _atomic_json(public/'_public_command.json', config['evaluation']['command'])
            (public/'_public_command.json').chmod(0o444)
            (public / "boundary_probe.py").write_text(BOUNDARY_PROBE)
            (public / "boundary_probe.py").chmod(0o444)
            if harbor_task:
                from .harbor_runtime import SEGMENT_EXEC
                (public / '_segment_exec.py').write_text(SEGMENT_EXEC)
                (public / '_segment_exec.py').chmod(0o444)
            prompt = evidence(self.root, config["prompt"]).read_text(encoding="utf-8")
            marker = "{{DURATION_REQUIREMENT}}"
            if duration["policy"]["mode"] == "non_training_7h":
                _require(marker in prompt and not re.search(r"(?:10\s*(?:小时|h)|36000)", prompt),
                         "DURATION_PROMPT", "7h Prompt须使用时长占位符，不能残留10h指令")
            prompt = prompt.replace(marker, duration_prompt(duration)) if marker in prompt else prompt + "\n" + duration_prompt(duration)
            (temporary / "prompt.md").write_text(prompt, encoding="utf-8")
            if "docker_security" in config:
                (temporary / "security").mkdir()
                for key in ("seccomp", "approval"):
                    ref = config["docker_security"][key]
                    target = temporary / "security" / ("seccomp.json" if key == "seccomp" else "approval.md")
                    shutil.copyfile(evidence(self.root, ref), target)
                    _require(_sha256(target) == ref["sha256"], "SECURITY_DRIFT", "安全配置复制期间发生变化")
                    target.chmod(0o444)
            # config.json freezes validated non-secret fields; raw private TOML
            # (including comments) is never copied into an evidence snapshot.
            for source in profile_sources.values():
                _require(_sha256(Path(source["path"])) == source["sha256"],
                         "PROFILE_DRIFT", "准备过程中模型配置已改变")
            for name in TRACKS:
                track_root = temporary / name
                track_root.mkdir()
                (track_root / "config.toml").write_text(model_config(config["tracks"][name]))
                (track_root / "config.toml").chmod(0o444)
                for phase in ("preflight", "formal"):
                    base = track_root / phase
                    for directory in ("solution", "output", "codex_home"):
                        (base / directory).mkdir(parents=True)
                    for item in config["starter_files"]:
                        self._copy(item, base / "solution", readonly=False)
                _atomic_json(track_root / "state.json", {"schema_version": 1, "thread_id": None, "segments": [], "exclusions": [], "active": None, "preflight": None, "duration_sha256": duration["sha256"]})
            _atomic_json(temporary / "config.json", config)
            refs = [{"path": str(p.relative_to(temporary)), "sha256": _sha256(p)}
                    for p in sorted(temporary.rglob("*")) if p.is_file() and (p.is_relative_to(public) or p.is_relative_to(temporary / "security") or p.name == "config.toml" or p.name == "prompt.md")]
            _atomic_json(temporary / "manifest.json", {"runtime_mode": "native_tui", "config_sha256": _canonical_digest(config), "rules_lock_sha256": _canonical_digest(self.store._load()["rules_lock"]), "files": refs, "profile_sources": profile_sources, "harbor_task_sha256": harbor_task, "starter_sha256": self._tree_hash(temporary / "codex" / "formal" / "solution"), "duration_snapshot": duration})
            temporary.rename(self.directory)
        except BaseException:
            # Staging contains only new tool-owned copies, never existing task files.
            shutil.rmtree(temporary)
            raise
        self.config = copy.deepcopy(config)
        return {"status": "prepared", "tracks": list(TRACKS), "runtime": str(self.directory), "profile_sources": profile_sources}

    def _copy(self, item, root, readonly):
        source = evidence(self.root, item["source"])
        destination = root / _relative(item["destination"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        destination.chmod((0o555 if readonly else 0o755) if source.stat().st_mode & 0o111 else (0o444 if readonly else 0o644))

    def _state(self, track):
        _require(track in TRACKS, "INVALID_TRACK", "轨迹只接受 codex/seed")
        return _read_json(self.directory / track / "state.json")

    def _save(self, track, state):
        _atomic_json(self.directory / track / "state.json", state)

    @contextmanager
    def _lock(self, track):
        self._load()
        _require(track in TRACKS, "INVALID_TRACK", "轨迹只接受 codex/seed")
        with (self.directory / track / "supervisor.lock").open("a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise FlowError("ALREADY_RUNNING", "该轨迹已有运行监督进程") from exc
            yield
            fcntl.flock(lock, fcntl.LOCK_UN)

    def check(self, track):
        self._load()
        result = self.backend.check(self, track)
        return {"status": "ok", "track": track, "backend": result,
                "note": "静态镜像/接口检查；鉴权和真实 Public/Dev 尚需 preflight --allow-live"}

    def _auth(self, track, phase):
        model = self.config["tracks"][track]
        ref = model["auth_ref"]
        secrets = []
        env = {key: value for key, value in os.environ.items() if key in {"PATH", "LANG", "LC_ALL", "DOCKER_HOST", "DOCKER_CONTEXT", "XDG_RUNTIME_DIR"}}
        if ref["kind"] == "api_key_json":
            data = _read_json(Path(ref["path"]))
            value = data.get(ref["key"])
            _require(isinstance(value, str) and value, "AUTH_MISSING", "凭据文件缺配置的 API key 字段")
            secrets.append(value)
            env["AUTORESEARCH_MODEL_KEY"] = value
        else:
            target = self.directory / track / phase / "codex_home" / "auth.json"
            if not target.exists():
                refreshed = self.directory / track / "preflight" / "codex_home" / "auth.json"
                source = refreshed if phase == "formal" and refreshed.exists() else Path(ref["path"])
                data = _read_json(source)
                _atomic_json(target, data)
                target.chmod(0o600)
            data = _read_json(target)
            def collect(value):
                if isinstance(value, dict):
                    for key, child in value.items():
                        if key in {"access_token", "refresh_token", "id_token", "OPENAI_API_KEY"} and isinstance(child, str):
                            secrets.append(child)
                        else:
                            collect(child)
            collect(data)
            _require(secrets, "AUTH_MISSING", "登录文件中未找到可用凭据字段")
        return env, Redactor(secrets)

    def _segment(self, track, phase, state, prompt, budget, thread=None):
        env, redact = self._auth(track, phase)
        segment_id = uuid.uuid4().hex
        directory = self.directory / track / "logs" / segment_id
        directory.mkdir(parents=True)
        name = "ar-" + track + "-" + segment_id[:12]
        clock = EventClock(thread, self.config.get("silence_seconds", 300))
        command = self.backend.command(self, track, phase, name, codex_command(prompt, thread), use_auth=True, tty=True)
        terminal = None
        origin, monotonic = time.time(), time.monotonic()
        now = lambda: origin + time.monotonic() - monotonic
        start = now()
        tail = None
        status, error, returncode, total = "failed", None, None, 0
        error_code = None
        state["active"] = {"segment_id": segment_id, "container": getattr(self.backend, 'container', name),
                           "phase": phase, "started_at": _utc_now(), "mode": "native_tui"}
        self._save(track, state)
        completed_items = []
        cleanup_confirmed, screen_error = True, None
        streams = {key: (directory / filename).open("x", encoding="utf-8")
                   for key, filename in (("native", "native.jsonl"), ("events", "events.jsonl"))}
        closing = phase == "formal" and self._seconds(state) >= self.minimum_seconds()
        turn_results = []
        closure = None
        def send(text, kind):
            streams['events'].write(json.dumps({'at': now(), 'source': 'supervisor',
                'kind': kind, 'text': text}, ensure_ascii=False)+'\n')
            streams['events'].flush()
            terminal.send(text)
        try:
            home = self.directory / track / phase / 'codex_home'
            tail = RolloutTail(home, self.config['codex_version'], thread)
            terminal = self.terminal_factory()
            terminal.start(command, {**env, 'TERM': 'xterm-256color'})
            state['active']['terminal_socket'] = str(terminal.socket)
            self._save(track, state)
            while True:
                _require(now() - start < budget, "BUDGET_EXHAUSTED", "本次运行时间预算已用尽")
                observations = tail.poll()
                for observation in observations:
                    received = now()
                    record = redact.value(observation['native'])
                    text = json.dumps(record, ensure_ascii=False)+'\n'
                    total += len(text.encode('utf-8'))
                    _require(total <= self.config.get('log_limit_bytes', 268435456), 'LOG_LIMIT', '日志达到预算，已暂停')
                    streams['native'].write(text)
                    at = observation['native_at']
                    if record['type'] == 'session_meta':
                        at = max(start, at)  # Historical resume header is identity, not new work.
                    else:
                        _require(start <= at <= received + 2, 'CLOCK_ORDER', '新增原生事件超出本分段时间范围')
                    for event in observation['events']:
                        safe = redact.value(event)
                        streams['events'].write(json.dumps({'received_at': received, 'at': at,
                            'source': 'native_rollout', 'event': safe}, ensure_ascii=False)+'\n')
                        clock.event(safe, at)
                        if phase == 'formal' and state['thread_id'] is None and clock.saw_thread:
                            state['thread_id'] = clock.thread_id
                            self._save(track, state)
                        if safe['type'] == 'item.completed':
                            item = safe.get('item', {})
                            if phase == 'preflight':
                                completed_items.append(item)
                            result = public_evaluation(item, [EVALUATE])
                            if result is not None:
                                turn_results.append(result)
                        _require(safe['type'] not in {'error', 'turn.failed'}, 'TUI_FAILED',
                                 '原生记录报告外部异常；暂停并排查后恢复原会话')
                for stream in streams.values():
                    stream.flush()
                if observations:
                    state['active'].update(last_event_at=clock.last, waiting_input=tail.adapter.idle,
                        observed_active_seconds=clock.summary()['observed_active_seconds'], event_counts=dict(clock.counts))
                    self._save(track, state)
                _require(terminal.status()['alive'], 'TUI_EXITED', 'TUI 提前退出；不能按进程退出推断方法已完成')
                if tail.adapter.idle:
                    if tail.adapter.processes:
                        send('仍有后台工具进程未确认终态。请在原会话中等待并核查这些进程的结果，'
                             '不要启动新的优化方向；记录实际结果后再结束本回合。', 'await_background')
                        tail.adapter.state = 'awaiting_start'
                        continue
                    if phase == 'preflight' or closing:
                        if closing:
                            _require(turn_results, 'CLOSURE_INCOMPLETE', '收口回合缺成功的真实公开复测')
                            from .harbor_runtime import candidate_snapshot
                            closure = candidate_snapshot(self, track)
                            binding = turn_results[-1].get('evaluation_binding', {})
                            _require(binding.get('candidate_before_sha256') == binding.get('candidate_after_sha256')
                                     == closure['candidate_sha256'], 'CLOSURE_SOURCE_DRIFT',
                                     '收口复测的可信源码哈希与最终候选不一致；须恢复后重新公开评测')
                            rows = (self.directory/track/phase/'output/trajectory.jsonl').read_text().splitlines()
                            last = json.loads(rows[-1])
                            _require(last['status'] == 'ok' and last['score'] == turn_results[-1]['raw_metric']['value'],
                                     'CLOSURE_INCOMPLETE', 'Agent 收口记录须对应最后一次真实公开复测原始指标')
                            closure['public_result'] = turn_results[-1]
                        send('/quit', 'terminal_quit')
                        end = time.monotonic() + 10
                        while terminal.status()['alive'] and time.monotonic() < end:
                            time.sleep(.1)
                        returncode = terminal.status()['exit_code']
                        _require(not terminal.status()['alive'] and returncode == 0,
                                 'TUI_EXITED', '正常回合后 TUI 未正常退出，不能标记完成')
                        status = 'completed'
                        break
                    elapsed = effective_seconds(
                        [i for s in state['segments'] if s['phase'] == 'formal' for i in s['intervals']] + clock.intervals,
                        [[e['start'], e['end']] for e in state['exclusions']])
                    closing = elapsed >= self.minimum_seconds()
                    send(CLOSE_PROMPT if closing else self.continuation_prompt(), 'closure' if closing else 'continue')
                    tail.adapter.state = 'awaiting_start'
                    turn_results = []
                time.sleep(.1)
        except KeyboardInterrupt:
            status, error = "interrupted", "用户中断；保留原会话"
        except (FlowError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            error_code = exc.code if isinstance(exc, FlowError) else type(exc).__name__
            status = "budget_exhausted" if isinstance(exc, FlowError) and exc.code == "BUDGET_EXHAUSTED" else "failed"
            error = redact.text(str(exc))
        finally:
            # An unfinished tool/turn is not evidence for the unobserved crash tail.
            if clock.last is not None:
                clock.stop(clock.last)
            if terminal is not None and terminal.started:
                try:
                    (directory/'screen.txt').write_text(redact.text(terminal.capture()))
                except (FlowError, OSError, subprocess.SubprocessError) as exc:
                    screen_error = redact.text(str(exc))  # Optional diagnostic must not block cleanup.
            try:
                self.backend.stop(name)
            except (FlowError, OSError, subprocess.SubprocessError):
                cleanup_confirmed = False
                error = (error or "") + "；容器清理未确认，恢复前须确认该容器已停止"
                status = "cleanup_unconfirmed"
            if terminal is not None:
                try:
                    terminal.close()
                except (FlowError, OSError, subprocess.SubprocessError):
                    cleanup_confirmed = False
                    status, error = 'cleanup_unconfirmed', (error or '')+'；专属终端清理未确认'
            for stream in streams.values():
                stream.close()
        summary = {**clock.summary(), "segment_id": segment_id, "phase": phase, "status": status,
                   "error": error, "error_code": error_code, "exit_code": returncode, "wall_seconds": now() - start,
                   "prompt_sha256": _canonical_digest(prompt), "mode": "native_tui",
                   "closure_completed": phase == 'formal' and closing and status == 'completed',
                   "closure": closure,
                   "screen_error": screen_error,
                   "logs": [{"path": str(p.relative_to(self.directory)), "sha256": _sha256(p)}
                            for p in sorted(directory.iterdir())]}
        if status == "failed" and error_code in {'THREAD_MISSING', 'THREAD_MISMATCH', 'CODEX_VERSION'}:
            summary["intervals"] = []
            summary["observed_active_seconds"] = 0
        _atomic_json(directory / "summary.json", summary)
        if cleanup_confirmed:
            state["active"] = None
        state["segments"].append(summary)
        self._save(track, state)
        return summary, completed_items

    def preflight(self, track, allow_live=False):
        _require(allow_live, "LIVE_CONFIRMATION_REQUIRED", "真实预检会调用模型与 Public/Dev；须显式 --allow-live")
        if type(self.backend) is DockerBackend:
            self._load()
            if 'harness' in self.config:
                from .harbor_runtime import launch
                return launch(self, track, 'preflight', self.config['evaluation']['timeout_seconds'])
        with self._lock(track):
            state = self._state(track)
            _require(state['active'] is None, 'UNCLOSED_SEGMENT', '先 recover 未收口分段，不能覆盖活动状态')
            _require(state["thread_id"] is None, "FORMAL_ALREADY_STARTED", "正式会话开始后不能重建 preflight")
            self.backend.check(self, track)
            boundary = self.backend.boundary(self, track)
            _atomic_json(self.directory / track / "boundary.json", {"at": _utc_now(), "output": boundary})
            exact = [EVALUATE, *self.config["evaluation"].get("smoke_args", [])]
            prompt = ("这是独立的环境预检会话，不计入正式轨迹。请只运行下面这条命令一次，"
                      "不要修改代码，不要改写或伪造结果；完成后简要报告。命令：\n" + shlex.join(exact))
            solution = self.directory / track / "preflight" / "solution"
            before = self._tree_hash(solution)
            previous = [s for s in state['segments'] if s['phase'] == 'preflight']
            summary, items = self._segment(track, "preflight", state, prompt,
                                           self.config["evaluation"]["timeout_seconds"],
                                           previous[-1]['thread_id'] if previous else None)
            results = []
            for item in items:
                value = public_evaluation(item, exact)
                if value is not None:
                    results.append(value)
            ready = summary["status"] == "completed" and len(results) == 1 and before == self._tree_hash(solution)
            state["preflight"] = {"ready": ready, "segment_id": summary["segment_id"], "config_sha256": _canonical_digest(self.config),
                                  "evaluation_results": results, "at": _utc_now()}
            self._save(track, state)
            return {"status": "ready" if ready else "blocked", "track": track, "preflight": state["preflight"],
                    "note": "预检会话/耗时独立；正式轨迹从新会话开始"}

    @staticmethod
    def _tree_hash(root):
        _require(not any(p.is_symlink() for p in root.rglob("*")), "SYMLINK_IN_SNAPSHOT", "快照不能含符号链接")
        return _canonical_digest([{"path": str(p.relative_to(root)), "sha256": _sha256(p)}
                                  for p in sorted(root.rglob("*")) if p.is_file()])

    def run(self, track, budget_seconds, *, resume=False, confirm_cost=False):
        _require(confirm_cost, "COST_CONFIRMATION_REQUIRED", "正式运行须显式 --confirm-cost 并声明本次预算")
        _require(type(budget_seconds) is int and budget_seconds > 0, "INVALID_BUDGET", "预算为正整数秒")
        if type(self.backend) is DockerBackend:
            self._load()
            if 'harness' in self.config:
                from .harbor_runtime import launch
                return launch(self, track, 'run', budget_seconds, resume)
        _require(not isinstance(self.backend, DockerBackend), "HARBOR_DRIVER_REQUIRED",
                 "PCA 正式轨迹须接入项目指定 Harbor；当前 Docker 后端仅供组件预检，不能冒充正式 Harness。请先完成目标版本适配。")
        with self._lock(track):
            state = self._state(track)
            _require(state["active"] is None, "UNCLOSED_SEGMENT", "上次监督进程未收口；须先 recover，不能推定停滞时间")
            _require(state["preflight"] and state["preflight"]["ready"] and state["preflight"]["config_sha256"] == _canonical_digest(self.config), "PREFLIGHT_REQUIRED", "该组尚未通过当前版本的真实预检")
            _require(bool(state["thread_id"]) == resume, "RESUME_REQUIRED", "已有会话只能 resume；没有会话不能 resume")
            if not resume:
                manifest = _read_json(self.directory / "manifest.json")
                _require(self._tree_hash(self.directory / track / "formal" / "solution") == manifest["starter_sha256"], "STARTER_CHANGED", "正式首次启动前 Starter 已改变")
            formal = [s for s in state['segments'] if s['phase'] == 'formal']
            finish_pending = bool(resume and formal and formal[-1]['status'] != 'completed')
            if self._seconds(state) < self.minimum_seconds() or finish_pending:
                prompt = (CLOSE_PROMPT if self._seconds(state) >= self.minimum_seconds() else
                          self.continuation_prompt() if state['thread_id'] else (self.directory/'prompt.md').read_text())
                self._segment(track, 'formal', state, prompt, budget_seconds, state['thread_id'])
            return self.status(track)

    def finalize(self, track, confirm_final_score=False):
        _require(confirm_final_score, 'FINAL_CONFIRMATION_REQUIRED',
                 '须先专家核对真实合法迭代、净时长及最佳候选，再显式确认唯一一次最终评分')
        self._load()
        _require('harness' in self.config, 'HARBOR_DRIVER_REQUIRED', '最终评分须通过 Harbor')
        from .harbor_runtime import launch
        return launch(self, track, 'finalize', self.config['evaluation']['timeout_seconds'])

    def _seconds(self, state):
        intervals = [interval for segment in state["segments"] if segment["phase"] == "formal" for interval in segment["intervals"]]
        return effective_seconds(intervals, [[entry["start"], entry["end"]] for entry in state["exclusions"]])

    def status(self, track):
        self._load()
        state = self._state(track)
        for segment in state["segments"]:
            for ref in segment["logs"]:
                evidence(self.directory, ref)
        for entry in state["exclusions"]:
            for ref in entry["evidence"]:
                evidence(self.root, ref)
        seconds = self._seconds(state)
        minimum = self.minimum_seconds()
        return {"status": "duration_reached" if seconds >= minimum else "in_progress" if state["active"] else "not_ready_or_paused",
                "track": track, "thread_id": state["thread_id"], "effective_seconds_before_content_review": seconds,
                "minimum_seconds": minimum, "duration_sha256": duration_snapshot(self.root)["sha256"], "active": state["active"], "preflight": state["preflight"],
                "formal_segments": sum(s["phase"] == "formal" for s in state["segments"]),
                "unverified_seconds": sum(s["unverified_seconds"] for s in state["segments"] if s["phase"] == "formal"),
                "note": "有效性还须核真实方法迭代与合法操作；计时达标不代表整条轨迹通过"}

    def attach(self, track):
        self._load()
        active = self._state(track)['active']
        _require(active and active.get('terminal_socket'), 'TERMINAL_UNAVAILABLE',
                 '当前没有已就绪的原生终端；先查 status，不创建新会话')
        return {'track': track, **TmuxTerminal.existing(active['terminal_socket']).observe()}

    def recover(self, track):
        with self._lock(track):
            state = self._state(track)
            active = state["active"]
            _require(active is not None, "NO_RECOVERY_NEEDED", "没有未收口的运行")
            self.backend.stop(active["container"])
            socket = active.get('terminal_socket')
            if socket and Path(socket).exists():
                TmuxTerminal.existing(socket).close()
            if not any(s["segment_id"] == active["segment_id"] for s in state["segments"]):
                directory = self.directory / track / "logs" / active["segment_id"]
                path = directory / "events.jsonl"
                clock = EventClock(state["thread_id"] if active["phase"] == "formal" else None,
                                   self.config.get("silence_seconds", 300))
                incomplete_tail = False
                with path.open() as stream:
                    for line in stream:
                        if not line.endswith("\n"):
                            incomplete_tail = True
                            break
                        observation = json.loads(line)
                        if observation["source"] in {"codex", "native_rollout"}:
                            clock.event(observation["event"], observation["at"])
                        elif re.search(r"Reconnecting|Total tokens.*exceed|context length.*exceed|rate limit", observation.get("text", ""), re.I):
                            clock.event({"type": "error"}, observation["at"])
                if clock.last is not None:
                    clock.stop(clock.last)
                if active["phase"] == "formal" and clock.saw_thread:
                    state["thread_id"] = clock.thread_id
                summary = {**clock.summary(), "segment_id": active["segment_id"], "phase": active["phase"],
                           "status": "recovered_interruption", "exit_code": None,
                           "error": "只计到最后可核事件，退出时间未知；中断尾部全部未计",
                           "incomplete_tail": incomplete_tail,
                           "logs": [{"path": str(p.relative_to(self.directory)), "sha256": _sha256(p)}
                                    for p in sorted(directory.iterdir()) if p.name != "summary.json"]}
                _atomic_json(directory / "summary.json", summary)
                state["segments"].append(summary)
            state["active"] = None
            self._save(track, state)
        return self.status(track)

    def exclude(self, track, entry):
        with self._lock(track):
            state = self._state(track)
            _require(state["active"] is None, "RUNNING", "请在会话暂停后补扣时证据")
            _require(isinstance(entry, dict) and isinstance(entry.get("reason"), str) and entry["reason"].strip(), "INVALID_EXCLUSION", "扣时须有理由")
            union([[entry.get("start"), entry.get("end")]])
            _require(isinstance(entry.get("evidence"), list) and entry["evidence"], "INVALID_EXCLUSION", "扣时须引用实际证据")
            for ref in entry["evidence"]:
                evidence(self.root, ref)
            state["exclusions"].append({**entry, "recorded_at": _utc_now()})
            self._save(track, state)
        return self.status(track)
