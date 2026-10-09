"""State-free Harbor 0.23 scoring and read-only inspection of native originals.

Only the child entry imports Harbor. No task ledger, Codex credentials, model
calls or experiment selection; candidate code executes in native containers.
"""
from __future__ import annotations

import datetime as dt
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import stat
import subprocess
import sys
import tomllib

from .common import FlowError, _require, _sha256, _atomic_json, _canonical_digest
from .materials_io import WORK_NAMES, SECRET_NAMES, read_object, bundled, inside

HARBOR_VERSION = "0.23.0"
CANDIDATE_AGENT = "autoresearch_flow.harbor_candidate:CandidateAgent"
TASK_INPUTS = {"instruction.md", "task.toml", "environment", "tests", "solution"}


def inventory(root, *, top_names=None):
    """Hash regular inputs, skipping work directories before walking into them."""
    root = Path(root)
    _require(root.is_dir() and not root.is_symlink(), "HARBOR_INPUT", "输入须为普通目录")
    result = {}
    for base, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d not in WORK_NAMES)
        if Path(base) == root and top_names is not None:
            dirs[:] = [d for d in dirs if d in top_names]
            names = [n for n in names if n in top_names]
        for name in dirs + sorted(names):
            if name in WORK_NAMES:
                continue
            path = Path(base) / name
            _require(name not in SECRET_NAMES, "HARBOR_SECRET", f"不可移交凭据：{path.relative_to(root)}")
            mode = path.lstat().st_mode
            _require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), "HARBOR_INPUT", "不移交链接或特殊文件")
            if stat.S_ISREG(mode):
                result[path.relative_to(root).as_posix()] = {
                    "sha256": _sha256(path), "size": path.stat().st_size,
                    "mode": stat.S_IMODE(mode)}
    _require(bool(result), "HARBOR_INPUT", "输入目录没有可移交文件")
    return result


def snapshot(source, target, *, top_names=None):
    _require(not Path(source).is_symlink(), "HARBOR_INPUT", "源目录不能是链接")
    source, target = Path(source).resolve(), Path(target).absolute()
    _require(not target.exists() and not target.is_symlink(), "HARBOR_EXISTS", "不覆盖已有原件/目录")
    _require(not target.resolve().is_relative_to(source) and not source.is_relative_to(target.resolve()),
             "HARBOR_OVERLAP", "快照不能嵌套源目录或覆盖源目录")
    before = inventory(source, top_names=top_names)
    target.mkdir(parents=True)
    for name in before:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, dest)
    _require(before == inventory(source, top_names=top_names) == inventory(target), "HARBOR_DRIFT", "复制期间输入变化")
    return before


def job_config(task, output, *, candidate=None, gpu_ids=None):
    """One native Trial. Task budgets remain task budgets; no forced 2h aggregate."""
    environment = {"type": "docker"}
    if gpu_ids:
        from .runtime_gpu import normalize_ids
        environment = {"import_path": "autoresearch_flow.harbor_gpu:GpuDockerEnvironment",
                       "kwargs": {"gpu_ids": normalize_ids(gpu_ids), "cpu_only_when_zero": True}}
    agent = {"name": "nop"} if candidate is None else {
        "import_path": CANDIDATE_AGENT, "kwargs": {"candidate_path": str(Path(candidate).resolve())}}
    return {"job_name": "score", "jobs_dir": str(Path(output).resolve() / "jobs"),
            "n_attempts": 1, "n_concurrent_trials": 1, "retry": {"max_retries": 0},
            "environment": environment, "verifier": {"disable": False},
            "agents": [agent], "tasks": [{"path": str(Path(task).resolve())}]}


def _finite_rewards(value):
    _require(isinstance(value, dict) and bool(value), "HARBOR_REWARD", "reward 对象必须非空")
    _require(all(isinstance(k, str) and isinstance(v, (int, float)) and not isinstance(v, bool)
                 and math.isfinite(v) for k, v in value.items()),
             "HARBOR_REWARD", "reward 必须全部为有限数值")
    return value


def _time(value):
    _require(isinstance(value, str), "HARBOR_TIMING", "缺原生完成时间")
    try:
        time = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FlowError("HARBOR_TIMING", "非法原生时间") from exc
    _require(time.tzinfo is not None, "HARBOR_TIMING", "时间须有时区")
    return time


def inspect_trial(trial, *, mode, task_path, expected_files=None, expected_environment=None):
    """Inspect same-Trial originals; success never follows just the CLI exit code."""
    _require(mode in {"nop", "candidate"}, "HARBOR_MODE", "仅 NOP 或明确候选")
    trial = Path(trial)
    config, result = read_object(trial / "config.json"), read_object(trial / "result.json")
    effective = result.get("config", {})
    for cfg in (config, effective):
        _require(cfg.get("task", {}).get("path") == str(Path(task_path).resolve()),
                 "HARBOR_TASK_BINDING", "Trial 不属于指定题包")
        agent = cfg.get("agent", {})
        actual = agent.get("import_path") or agent.get("name")
        _require(actual == ("nop" if mode == "nop" else CANDIDATE_AGENT),
                 "HARBOR_AGENT", "实际 Agent 覆盖不符")
    _require(not result.get("exception_info"), "HARBOR_NATIVE_FAILURE",
             "原生 Trial 失败：" + str(result.get("exception_info")))
    _require(result.get("verifier_environment_mode") == "separate" and
             not effective.get("verifier", {}).get("disable", False) and not effective.get("install_only", False),
             "HARBOR_SEPARATE", "实际评分必须在独立 Verifier 中完成")
    _require(result.get("agent_info", {}).get("name") == ("nop" if mode == "nop" else "autoresearch-candidate"),
             "HARBOR_AGENT", "原生 Agent 身份不符")
    if expected_environment is not None:
        env = effective.get("environment", {})
        for key, value in expected_environment.items():
            _require(env.get(key) == value, "HARBOR_PROVIDER", "实际 provider/参数覆盖不符")
    _require(_time(result.get("started_at")) <= _time(result.get("agent_execution", {}).get("finished_at"))
             <= _time(result.get("verifier", {}).get("started_at")) <= _time(result.get("finished_at")),
             "HARBOR_TIMING", "原生 Agent→Verifier 时序不符")
    rewards = _finite_rewards(result.get("verifier_result", {}).get("rewards"))
    reward_path = trial / "verifier/reward.json"
    if reward_path.exists():
        disk = _finite_rewards(read_object(reward_path))
    else:
        reward_path = trial / "verifier/reward.txt"
        _require(reward_path.is_file() and not reward_path.is_symlink(), "HARBOR_REWARD", "缺真实 reward 原件")
        try:
            disk = _finite_rewards({"reward": float(reward_path.read_text().strip())})
        except ValueError as exc:
            raise FlowError("HARBOR_REWARD", "reward.txt 不是数值") from exc
    _require(disk == rewards, "HARBOR_REWARD", "Harness 接收值与 reward 原件不符")
    originals = [trial / "config.json", trial / "result.json", trial / "trial.log", reward_path]
    logs = [p for p in (trial / "verifier").iterdir() if p.name not in {"reward.txt", "reward.json"}
            and p.is_file() and not p.is_symlink() and p.stat().st_size]
    _require(logs and all(p.is_file() and not p.is_symlink() and p.stat().st_size for p in originals),
             "HARBOR_ORIGINALS", "缺同一 Trial 的配置/结果/reward/日志")
    transferred = trial / "artifacts/workspace/solution"
    actual_files = inventory(transferred)
    if mode == "candidate":
        _require(expected_files is not None and actual_files == expected_files,
                 "HARBOR_ARTIFACTS", "源码、模型或配置未完整原样移交")
        transfer = trial / "agent/candidate_transfer.json"
        _require(read_object(transfer).get("files") == expected_files,
                 "HARBOR_ARTIFACTS", "Agent 实际候选校验与移交产物不符")
        originals.append(transfer)
    return {"status": "native_trial_verified", "mode": mode, "rewards": rewards,
            "coverage": "nop_executed_branch_only" if mode == "nop" else "frozen_candidate_scoring",
            "candidate_files": actual_files, "trial_dir": str(trial.resolve()),
            "originals": {p.relative_to(trial).as_posix(): _sha256(p) for p in originals + logs},
            "verifier_environment_mode": "separate"}


def validate_job(path):
    """Run only in the selected Harbor installation; real schemas, no Docker yet."""
    from harbor.models.job.config import JobConfig
    from harbor.models.task.task import Task
    _require(importlib.metadata.version("harbor") == HARBOR_VERSION, "HARBOR_VERSION", "当前接入只验证 Harbor 0.23.0")
    config = JobConfig.model_validate(read_object(path))
    task = Task(config.tasks[0].path)
    for context in ("environment", "tests"):
        _require((Path(config.tasks[0].path) / context / "Dockerfile").is_file(),
                 "HARBOR_CONTEXT", f"缺 {context}/Dockerfile 源码，不仅要求预构建镜像存在")
    _require(not task.has_steps and task.config.verifier.environment_mode.value == "separate",
             "HARBOR_SEPARATE", "需显式双镜像 separate 单题合同")
    declared = tomllib.loads((Path(config.tasks[0].path) / "task.toml").read_text())
    _require(declared.get("agent", {}).get("environment_mode", "separate") == "separate",
             "HARBOR_SEPARATE", "Agent 声明不得与独立评分边界冲突")
    agent_env, verifier_env = task.config.environment, task.config.verifier.environment
    _require(verifier_env is not None, "HARBOR_SEPARATE", "缺独立 Verifier 环境")
    artifacts = [a if isinstance(a, str) else a.source for a in task.config.artifacts]
    _require(all(PurePosixPath(p).is_absolute() and ".." not in PurePosixPath(p).parts
                 and PurePosixPath(p).is_relative_to("/workspace/solution") for p in artifacts)
             and "/workspace/solution" in artifacts, "HARBOR_ARTIFACTS", "需绝对 artifacts，包含 /workspace/solution")
    gpu_ids = config.environment.kwargs.get("gpu_ids", [])
    counts = (agent_env.gpus, verifier_env.gpus)
    _require(max(counts) == len(gpu_ids) and all(c in {0, len(gpu_ids)} for c in counts), "HARBOR_GPU",
             "非零环境 GPU 数须与显式 gpu_ids 相符；零 GPU 阶段不分配设备")
    return {"harbor_version": HARBOR_VERSION, "native_task_schema": "validated",
            "agent_environment": agent_env.model_dump(mode="json"),
            "verifier_environment": verifier_env.model_dump(mode="json"),
            "agent_timeout_sec": task.config.agent.timeout_sec,
            "verifier_timeout_sec": task.config.verifier.timeout_sec,
            "artifacts": artifacts}


def _process(command, *, env, log, cwd, timeout=None):
    """Native owns lifecycle. Interrupt only this process group on bounded tests."""
    with Path(log).open("w", encoding="utf-8") as output:
        process = subprocess.Popen(command, env=env, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        try:
            return process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise


def run(task, output, *, harbor_python, candidate=None, gpu_ids=None, allow_live=False, timeout=None):
    _require(allow_live, "HARBOR_PERMISSION", "实际 Docker/评分须明确 --allow-live，并在已有资源授权内执行")
    _require(not Path(task).is_symlink() and (candidate is None or not Path(candidate).is_symlink()),
             "HARBOR_INPUT", "题包与候选须为实际目录，不经链接解析")
    task, output = Path(task).resolve(), Path(output).absolute()
    _require(not output.exists() and not output.is_symlink() and not output.resolve().is_relative_to(task)
             and not task.is_relative_to(output.resolve()), "HARBOR_OUTPUT", "用全新独立输出目录；不覆盖题包/原件")
    if candidate is not None:
        source = Path(candidate).resolve()
        _require(not output.resolve().is_relative_to(source) and not source.is_relative_to(output.resolve()),
                 "HARBOR_OUTPUT", "输出不能与候选嵌套")
    _require(timeout is None or timeout > 0, "HARBOR_TIMEOUT", "短验收上限须为正数；正式评分默认沿题包时限")
    declared = tomllib.loads((task / "task.toml").read_text())
    paths = bundled("docker_paths").inspect(task.parent, task.name, declared,
                {"profile": "harbor-environment-v1"}, require_separate=True)
    _require(not any(f.get("status") == "fail" for f in paths.get("findings", [])),
             "HARBOR_CONTEXT", "构建路径存在确定错误：" + str(paths.get("findings")))
    # Resolving a venv's python symlink selects the base interpreter instead.
    python = Path(harbor_python).absolute()
    _require(python.is_file() and os.access(python, os.X_OK), "HARBOR_PYTHON", "指定已安装 Harbor 的 Python")
    output.mkdir(parents=True)
    task_snapshot = output / "task" / task.name
    task_files = snapshot(task, task_snapshot, top_names=TASK_INPUTS)
    candidate_files = snapshot(candidate, output / "candidate") if candidate is not None else None
    job = job_config(task_snapshot, output, candidate=output / "candidate" if candidate is not None else None, gpu_ids=gpu_ids)
    _atomic_json(output / "job.json", job)
    source = Path(__file__).resolve().parents[1]
    program_names = ("__init__.py", "harbor_native.py", "harbor_candidate.py", "common.py", "materials_io.py")
    if gpu_ids:
        program_names += ("harbor_gpu.py", "runtime_gpu.py")
    implementation = output / "implementation"
    (implementation / "autoresearch_flow").mkdir(parents=True)
    for name in program_names:
        shutil.copy2(source / "autoresearch_flow" / name, implementation / "autoresearch_flow" / name)
    program_files = inventory(implementation)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(implementation)  # No importing task modules on the host.
    command = [str(python), "-m", "autoresearch_flow.harbor_native"]
    report = {"status": "native_trial_failed", "mode": "nop" if candidate is None else "candidate",
              "task_snapshot": task_snapshot.relative_to(output).as_posix(),
              "task_files": task_files, "frozen_candidate_files": candidate_files, "native": {},
              "started_at": dt.datetime.now(dt.timezone.utc).isoformat(), "path_review": paths,
              "program_files": program_files,
              "job_sha256": _sha256(output / "job.json"), "task_digest": _canonical_digest(task_files)}
    _atomic_json(output / "report.json", report)
    try:
        with (output / "validation.log").open("w") as stderr, (output / "validation.json").open("w") as stdout:
            validate = subprocess.run(command + ["validate", str(output / "job.json")], env=env,
                                      cwd=implementation, stdout=stdout, stderr=stderr, timeout=30)
        _require(validate.returncode == 0, "HARBOR_CONFIG", "目标 Harbor 校验失败，查看 validation.log")
        report["native"] = read_object(output / "validation.json")
        code = _process(command + ["execute", str(output / "job.json")], env=env,
                        log=output / "harbor.log", cwd=implementation, timeout=timeout)
        report["harbor_exit_code"] = code
        _require(code == 0, "HARBOR_EXIT", f"Harbor 命令失败，退出码 {code}")
        trials = list((output / "jobs/score").glob("*/result.json"))
        _require(len(trials) == 1, "HARBOR_ORIGINALS", "需一个且仅一个真实 Trial 原件")
        report["trial_dir"] = str(trials[0].parent.resolve())
        _require(inventory(task_snapshot) == task_files, "HARBOR_DRIFT", "运行期间题包变化")
        report.update(inspect_trial(trials[0].parent, mode=report["mode"], task_path=task_snapshot,
                                    expected_files=candidate_files, expected_environment=job["environment"]))
    except (FlowError, OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        report["error"] = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
    report["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _atomic_json(output / "report.json", report)
    return report


def inspect_run(output, *, task=None, candidate=None):
    """Reuse intact raw evidence; never execute Harbor or silently rerun scoring."""
    output = Path(output).resolve()
    recorded = read_object(output / "report.json")
    task_snapshot = inside(output, recorded.get("task_snapshot"), directory=True)
    _require(recorded.get("native", {}).get("harbor_version") == HARBOR_VERSION,
             "HARBOR_VERSION", "需实际 Harbor 版本绑定")
    _require(_sha256(output / "job.json") == recorded.get("job_sha256"), "HARBOR_DRIFT", "原生 Job 配置变化")
    _require(inventory(task_snapshot) == recorded.get("task_files") and
             inventory(output / "implementation") == recorded.get("program_files"),
             "HARBOR_DRIFT", "原题包或运行程序快照变化")
    if task is not None:
        _require(inventory(task, top_names=TASK_INPUTS) == recorded["task_files"],
                 "HARBOR_DRIFT", "当前题包不再对应原 Trial；只对改变路径定向重验")
    expected = recorded.get("frozen_candidate_files")
    if recorded["mode"] == "candidate":
        _require(inventory(output / "candidate") == expected, "HARBOR_DRIFT", "冻结候选变化")
        if candidate is not None:
            _require(inventory(candidate) == expected, "HARBOR_DRIFT", "指定方法不是这次评分的候选")
    else:
        _require(candidate is None, "HARBOR_MODE", "NOP 不证明最终候选评分")
    trials = list((output / "jobs/score").glob("*/result.json"))
    _require(len(trials) == 1, "HARBOR_ORIGINALS", "需唯一同次 Trial")
    job = read_object(output / "job.json")
    actual = inspect_trial(trials[0].parent, mode=recorded["mode"], task_path=task_snapshot,
                           expected_files=expected, expected_environment=job["environment"])
    _require(actual["originals"] == recorded.get("originals"), "HARBOR_DRIFT", "Trial 原件变化")
    return {**actual, "harbor_version": HARBOR_VERSION,
            "source_binding": "frozen_implementation_verified_not_current_source_claim"}


if __name__ == "__main__":
    action, config_path = sys.argv[1:]
    validated = validate_job(Path(config_path))
    if action == "validate":
        print(json.dumps(validated))
    elif action == "execute":
        from harbor.cli.main import app
        sys.argv = ["harbor", "run", "--config", config_path]
        app()
    else:
        raise ValueError("unknown native action")
