"""Run a concrete method/protocol; no TaskStore, selection, approvals or GPU leases."""
from __future__ import annotations

import csv
import json
import fcntl
import os
import platform
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from .common import FlowError, _require, _sha256, _canonical_digest, _read_json, _atomic_json
from .experiment_data import protocol, raw_value, quality_passed, record_evidence, number

SUCCESS = "SUCCESS"


def nvidia_devices():
    """Read-only observation; it is not an exclusive reservation or authorization."""
    def query(argument):
        try:
            r = subprocess.run(["nvidia-smi", argument, "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FlowError("HOST_DEPENDENCY_UNAVAILABLE", "无法读取 nvidia-smi；不自动安装或修改宿主") from exc
        return [[v.strip() for v in row] for row in csv.reader(r.stdout.splitlines()) if row]
    inventory = query("--query-gpu=index,uuid,name,driver_version")
    busy = {row[0] for row in query("--query-compute-apps=gpu_uuid,pid")}
    return [{"id": r[0], "uuid": r[1], "name": r[2], "driver": r[3], "busy": r[1] in busy} for r in inventory]


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _sources(method):
    path = Path(method).resolve(strict=True)
    base = path if path.is_dir() else path.parent
    candidates = sorted(path.rglob("*")) if path.is_dir() else [path]
    files = {}
    for p in candidates:
        relative = p.relative_to(base)
        if any(part in {".git", "__pycache__"} for part in relative.parts) or p.suffix in {".pyc", ".pyo"}:
            continue
        _require(not p.is_symlink(), "METHOD_SYMLINK", f"方法目录不能有符号链接：{relative}")
        if p.is_file():
            _require(p.name not in {"auth.json", ".env"} and not p.name.endswith(".key"),
                     "PRIVATE_SOURCE", "方法目录包含凭据型文件，请仅指定方法源码/配置")
            files[relative.as_posix()] = _sha256(p)
    _require(bool(files), "EMPTY_METHOD", "方法没有源码文件")
    return base, files


def _ref(root, path):
    path = Path(path)
    _require(path.resolve().is_relative_to(root) and path.is_file() and not path.is_symlink(),
             "ARTIFACT_ESCAPE", f"产物须为本组输出内普通文件：{path.name}")
    return {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}


def _terminate(process):
    # Only processes launched in this invocation, never PIDs taken from disk.
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


def _finish(item, root, p, failure=None):
    process, record, attempt = item["process"], item["record"], item["attempt"]
    record["execution"].update(finished_at=_now(), exit_code=process.returncode if process else None,
                               duration_seconds=time.monotonic() - item["started"])
    refs = {"log": _ref(root, attempt / "run.log")}
    raw = attempt / "measurement.json"
    if raw.is_file() and not raw.is_symlink():
        refs["raw_result"] = _ref(root, raw)
    errors = []
    if failure:
        errors.append(failure)
    elif not process or process.returncode != 0:
        errors.append(f"执行失败，exit_code={record['execution']['exit_code']}")
    else:
        try:
            measured = _read_json(raw)
            json.dumps(measured, allow_nan=False)
            _require(str(measured.get("status")).upper() in {"SUCCESS", "SUCCEEDED", "OK", "VALID", "COMPLETE"},
                     "RUN_INVALID", "方法没有返回成功状态")
            for key, value in (("seed", record["seed"]), ("role", record["role"])):
                if key in measured:
                    _require(measured[key] == value, "RESULT_MISMATCH", f"方法结果 {key} 不符")
            value = raw_value(measured, p["metric"])
            _require(quality_passed(measured), "QUALITY_FAILED", "质量门失败或未提供")
            record["metrics"] = {**p["metric"], "raw": value}
            record["quality_gate"] = measured.get("quality_gate", {"passed": measured.get("quality_passed")})
            record["training"] = measured.get("training", {"status": "NOT_APPLICABLE"} if not p["training"] else {})
            record["execution"]["actual_budget"] = measured.get("actual_budget")
            for name, bound in p["budget"].items():
                if isinstance(bound, dict) and bound.get("mode") in {"exact", "maximum"}:
                    used = number((measured.get("actual_budget") or {}).get(name), f"actual_budget.{name}")
                    limit = number(bound.get("value"), f"budget.{name}")
                    _require(used >= 0 and (used == limit if bound["mode"] == "exact" else used <= limit),
                             "BUDGET_MISMATCH", f"实际 {name} 不符合共同预算")
            for name, relative in measured.get("artifacts", {}).items():
                _require(name not in {"log", "raw_result", "model_metadata"}, "ARTIFACT_NAME", "产物名称保留给执行器")
                _require(isinstance(relative, str) and not Path(relative).is_absolute(), "ARTIFACT_ESCAPE", "产物须为本次输出相对路径")
                target = attempt / relative
                _require(target.resolve().is_relative_to(attempt), "ARTIFACT_ESCAPE", "产物越出本次输出")
                refs[name] = _ref(root, target)
            if p["training"]:
                train = record["training"]
                model = root / refs["model"]["path"]
                reload = train.get("reload", {})
                metadata = {"seed": record["seed"], "role": record["role"],
                            "method_sha256": record["method"]["sha256"],
                            "sha256": _sha256(model), "size_bytes": model.stat().st_size,
                            "format": train.get("model_format"), "reload_passed": reload.get("passed"),
                            "reload_metric": reload.get("raw_metric"),
                            "source_result": (attempt / "result.json").relative_to(root).as_posix()}
                metadata_path = model.parent / "artifact.json"
                _require(metadata_path != model, "MODEL_MISMATCH", "模型不能占用 artifact.json 元信息路径")
                if metadata_path.exists():
                    supplied = _read_json(metadata_path)
                    _require(all(supplied.get(k) == v for k, v in metadata.items()),
                             "MODEL_MISMATCH", "已有模型元信息与本轮不符；未覆盖原件")
                else:
                    _atomic_json(metadata_path, metadata)
                refs["model_metadata"] = _ref(root, metadata_path)
            _, after = _sources(attempt / "method")
            _require(after == record["method"]["files"], "METHOD_DRIFT", "运行时方法源码被改变")
        except (FlowError, OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            errors.append(str(exc))
    record["artifacts"] = refs
    if not errors:
        errors.extend(record_evidence(record, root, p))
    record["status"] = "INVALID" if errors else SUCCESS
    record["failure_reason"] = "; ".join(errors) if errors else None
    # Keep raw candidate bytes untouched even when malformed/non-finite.
    _atomic_json(attempt / "result.json", record)
    _atomic_json(attempt.parent / "result.json", record)
    return record


def _launch(root, method_base, files, method_hash, p, command, role, seed, devices, threads, timeout, lock_fd):
    seed_root = root / f"seed_{seed}"
    seed_root.mkdir(exist_ok=True)
    n = 1
    while (seed_root / f"attempt_{n:03}").exists():
        n += 1
    attempt = seed_root / f"attempt_{n:03}"
    attempt.mkdir()
    snapshot = attempt / "method"
    for relative, expected in files.items():
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(method_base / relative, target)
        _require(_sha256(target) == expected, "METHOD_DRIFT", "复制期间方法改变")
    request = attempt / "request.json"
    _atomic_json(request, {"protocol": p, "role": role, "seed": seed, "assigned_devices": devices,
                           "method_directory": str(snapshot), "output_directory": str(attempt)})
    substitutions = {"seed": str(seed), "method": str(snapshot), "output_dir": str(attempt),
                     "result": str(attempt / "measurement.json"), "request": str(request),
                     "protocol": str(root / "protocol.json"), "devices": ",".join(d["uuid"] for d in devices)}
    expanded = []
    for argument in command:
        for name, value in substitutions.items():
            argument = argument.replace("{" + name + "}", value)
        expanded.append(argument)
    env_values = {"CUDA_VISIBLE_DEVICES": substitutions["devices"], "PYTHONHASHSEED": str(seed % 4294967296),
                  "AUTORESEARCH_SEED": str(seed), "AUTORESEARCH_RESULT": substitutions["result"],
                  "AUTORESEARCH_OUTPUT_DIR": str(attempt), "AUTORESEARCH_PROTOCOL": substitutions["protocol"]}
    if threads:
        env_values.update(OMP_NUM_THREADS=str(threads), MKL_NUM_THREADS=str(threads))
    record = {"schema_version": "autoresearch-run.v1", "status": "RUNNING", "role": role, "seed": seed,
              "task_type": "training" if p["training"] else "non_training",
              "method": {"path": str(snapshot.relative_to(root)), "sha256": method_hash, "files": files},
              "protocol": p, "training": {}, "execution": {"command": expanded, "cwd": str(snapshot),
              "started_at": _now(), "finished_at": None, "exit_code": None, "duration_seconds": None,
              "devices": devices, "environment": env_values,
              "host": {"python": platform.python_version(), "platform": platform.platform(), "logical_cpus": os.cpu_count()}},
              "metrics": {}, "quality_gate": {}, "artifacts": {}}
    _atomic_json(attempt / "result.json", record)
    _atomic_json(seed_root / "result.json", record)
    item = {"process": None, "record": record, "attempt": attempt, "started": time.monotonic(),
            "timeout": timeout, "devices": devices}
    with (attempt / "run.log").open("wb") as log:
        log.write(("[runner] started " + record["execution"]["started_at"] + "\n").encode())
        log.flush()
        try:
            # The inherited local output lock prevents duplicate resume while this command lives.
            item["process"] = subprocess.Popen(expanded, cwd=snapshot, env={**os.environ, **env_values},
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                pass_fds=(lock_fd,))
            record["execution"]["pid"] = item["process"].pid
        except OSError as exc:
            log.write((str(exc) + "\n").encode())
            item["launch_error"] = str(exc)
    _atomic_json(attempt / "result.json", record)
    _atomic_json(seed_root / "result.json", record)
    return item


def run(method, protocol_value, output_dir, command, *, role="exploration", resume=False,
        gpu_ids=(), gpus_per_run=1, jobs=1, cpu_threads=None, timeout_seconds=None):
    p = protocol(protocol_value)
    _require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command),
             "INVALID_COMMAND", "command 须为非空参数数组，不经 shell 拼接")
    _require(bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", role)), "INVALID_ROLE", "role 不合法")
    _require(type(jobs) is int and jobs > 0 and type(gpus_per_run) is int and gpus_per_run > 0,
             "INVALID_RESOURCES", "jobs/gpus_per_run 须为正整数")
    _require(cpu_threads is None or type(cpu_threads) is int and cpu_threads > 0,
             "INVALID_RESOURCES", "cpu_threads 须为正整数")
    _require(timeout_seconds is None or number(timeout_seconds, "timeout_seconds") > 0,
             "INVALID_RESOURCES", "单次超时须为正数")
    ids = [str(x) for x in gpu_ids]
    _require(len(ids) == len(set(ids)), "INVALID_RESOURCES", "GPU 不得重复")
    base, files = _sources(method)
    root = Path(output_dir).resolve()
    source = Path(method).resolve()
    _require(not root.is_relative_to(source) and not source.is_relative_to(root),
             "OUTPUT_OVERLAP", "输出目录须与方法源码分开")
    binding = {"method_sha256": _canonical_digest(files), "method_files": files, "protocol": p,
               "role": role, "command": command, "cpu_threads": cpu_threads,
               "gpus_per_run": gpus_per_run if ids else 0, "timeout_seconds": timeout_seconds}
    exists = root.exists() and any(root.iterdir())
    _require(not exists or resume, "OUTPUT_EXISTS", "结果已存在；同协议续跑用 --resume，变化实验用新目录")
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FlowError("RUN_ACTIVE", "本输出仍有执行器或健康作业运行；不会重复启动") from exc
        if exists:
            _require(_read_json(root / "experiment.json") == binding, "EXPERIMENT_DRIFT", "方法/命令/协议/单次预算改变，不能复用本组")
            _require(_read_json(root / "protocol.json") == p, "PROTOCOL_DRIFT", "输出协议快照被改动")
        else:
            _atomic_json(root / "experiment.json", binding)
            _atomic_json(root / "protocol.json", p)
        pending, completed, reused, active, resource_issues = [], [], [], [], []
        for seed in p["seeds"]:
            existing = root / f"seed_{seed}" / "result.json"
            if existing.exists():
                record = _read_json(existing)
                if record.get("status") == SUCCESS:
                    _require(record.get("seed") == seed and record.get("role") == role
                             and record.get("protocol") == p and record.get("method", {}).get("sha256") == binding["method_sha256"],
                             "RESULT_DRIFT", "完成结果身份或协议改变")
                    errors = record_evidence(record, root, p)
                    _require(not errors, "EVIDENCE_DRIFT", "完成结果证据不完整，须人工核查，不覆盖重跑：" + "; ".join(errors))
                    raw = _read_json(root / record["artifacts"]["raw_result"]["path"])
                    _require(raw_value(raw, p["metric"]) == raw_value(record, p["metric"]) and quality_passed(raw),
                             "RESULT_DRIFT", "完成结果与原始测量矛盾")
                    reused.append(seed)
                    continue
                if record.get("status") == "RUNNING":
                    # An inherited output lock would still be held by a healthy foreground job.
                    # No observed exit receipt: never infer its return code or success from raw output.
                    attempt = (root / record["method"]["path"]).parent
                    _require(attempt.resolve().is_relative_to(existing.parent), "RESULT_DRIFT", "旧 attempt 越界")
                    record.update(status="INTERRUPTED", failure_reason="执行器退出且无真实终态收据；原日志保留")
                    record["execution"]["missing_reason"] = "未观测退出码与结束时间，不反推"
                    _atomic_json(attempt / "result.json", record)
                    _atomic_json(existing, record)
            pending.append(seed)
        try:
            while pending or active:
                while pending and len(active) < jobs:
                    devices = []
                    if ids:
                        inventory = nvidia_devices()
                        allowed = [d for d in inventory if d["id"] in ids or d["uuid"] in ids]
                        _require(len(allowed) == len(ids), "INVALID_RESOURCES", "指定 GPU 不存在或同一卡被重复指定")
                        occupied = {d["uuid"] for item in active for d in item["devices"]}
                        devices = [d for d in allowed if not d["busy"] and d["uuid"] not in occupied][:gpus_per_run]
                        if len(devices) < gpus_per_run:
                            if not active:
                                resource_issues.append("授权设备当前不足；未启动剩余 seed，可空闲后 --resume")
                            break
                    seed = pending.pop(0)
                    active.append(_launch(root, base, files, binding["method_sha256"], p, command, role,
                                          seed, devices, cpu_threads, timeout_seconds, lock.fileno()))
                if not active:
                    break
                for item in list(active):
                    process = item["process"]
                    timed_out = item["timeout"] is not None and time.monotonic() - item["started"] > item["timeout"]
                    if process and process.poll() is None and not timed_out:
                        continue
                    failure = item.get("launch_error")
                    if process and process.poll() is None and timed_out:
                        _terminate(process)
                        failure = "TIMEOUT：超过声明的单次预算"
                    completed.append(_finish(item, root, p, failure))
                    active.remove(item)
                if active:
                    time.sleep(0.05)
        except BaseException:
            for item in active:
                if item["process"]:
                    _terminate(item["process"])
                _finish(item, root, p, "INTERRUPTED：本次执行器中断")
            raise
    good = reused + [r["seed"] for r in completed if r["status"] == SUCCESS]
    return {"status": "COMPLETE" if len(good) == len(p["seeds"]) else "PARTIAL",
            "output_dir": str(root), "succeeded_seeds": good, "reused_seeds": reused,
            "failed_seeds": [r["seed"] for r in completed if r["status"] != SUCCESS],
            "pending_seeds": pending, "resource_issues": resource_issues}
