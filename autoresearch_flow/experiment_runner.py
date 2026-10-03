"""Small local retest queue for the already selected final method.

Runs a trusted task-specific adapter, not arbitrary Agent code in a new sandbox.
The adapter must wait for all its work and use only the assigned resources. W2
remains the sole result validator/statistician; this module supplies execution.
"""
from __future__ import annotations

import copy
import csv
import fcntl
import hashlib
import os
import shutil
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone

from .core import (FlowError, TASK_ID_RE, _atomic_json, _canonical_digest, _read_json,
                   _require, _sha256)
from .experiments import FAILED_RUN_STATUSES, ExperimentBook, evidence, number
from .w4_evidence import DeliveryEvidence


def _ref(root, path):
    return {"path": str(path.relative_to(root)), "sha256": _sha256(path)}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def nvidia_devices():
    """Read-only host observation, not a grant to use the observed devices."""
    def query(argument):
        try:
            result = subprocess.run(["nvidia-smi", argument, "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=10, check=True)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FlowError("HOST_DEPENDENCY_UNAVAILABLE", "无法读取 NVIDIA 设备；请用户检查 nvidia-smi，不自动安装或改宿主") from exc
        return [[x.strip() for x in row] for row in csv.reader(result.stdout.splitlines()) if row]
    inventory = query("--query-gpu=index,uuid,name,driver_version")
    busy = {row[0] for row in query("--query-compute-apps=gpu_uuid,pid")}
    return [{"id": row[0], "uuid": row[1], "name": row[2], "driver": row[3], "busy": row[1] in busy}
            for row in inventory]


class DevicePool:
    def __init__(self, resources, probe):
        self.resources, self.probe = resources, probe
        self.frozen = None

    def inventory(self):
        found = {d["id"]: d for d in self.probe()}
        _require(all(i in found for i in self.resources["gpu_ids"]), "RESOURCE_POLICY", "授权 GPU 不存在")
        devices = [found[i] for i in self.resources["gpu_ids"]]
        _require(len({d["uuid"] for d in devices}) == len(devices), "RESOURCE_POLICY", "设备 UUID 不得重复")
        _require(not self.resources["hardware_sensitive"] or len({(d["name"], d["driver"]) for d in devices}) == 1,
                 "RESOURCE_POLICY", "硬件敏感指标须使用同型号、同驱动的授权设备池")
        identity = [{k: v for k, v in d.items() if k != "busy"} for d in devices]
        _require(self.frozen is None or identity == self.frozen, "RESOURCE_POLICY", "GPU 索引对应的设备身份发生变化")
        self.frozen = identity
        return devices

    def acquire(self):
        lease = ExitStack()
        count = self.resources["gpus_per_run"]
        if not count:
            return {"lease": lease, "fds": [], "devices": ["cpu"], "inventory": [{"id": "cpu", "logical_cpus": os.cpu_count()}]}
        directory = Path("/tmp") / f"autoresearch-flow-gpu-{os.getuid()}"
        directory.mkdir(mode=0o700, exist_ok=True)
        _require(not directory.is_symlink() and directory.stat().st_uid == os.getuid()
                 and directory.stat().st_mode & 0o077 == 0, "RESOURCE_POLICY", "GPU 互斥目录权限不安全")
        selected, fds = [], []
        try:
            for device in self.inventory():
                if device["busy"]:
                    continue
                name = hashlib.sha256(device["uuid"].encode()).hexdigest() + ".lock"
                try:
                    stream = lease.enter_context(_lock(directory / name))
                except FlowError as exc:
                    if exc.code == "QUEUE_ACTIVE":
                        continue
                    raise
                selected.append(device)
                fds.append(stream.fileno())
                if len(selected) == count:
                    return {"lease": lease, "fds": fds, "devices": [d["uuid"] for d in selected], "inventory": selected}
        except BaseException:
            lease.close()
            raise
        lease.close()
        return None


def _directory(root, relative):
    _require(isinstance(relative, str) and relative and not Path(relative).is_absolute()
             and ".." not in Path(relative).parts and relative != ".",
             "INVALID_QUEUE", "输出目录必须为题目内的独立相对目录")
    target = root / relative
    _require(target.resolve().is_relative_to(root) and not any(p.is_symlink() for p in (target, *target.parents)),
             "INVALID_QUEUE", "输出目录不得使用符号链接或越界")
    return target


@contextmanager
def _lock(path):
    with path.open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise FlowError("QUEUE_ACTIVE", "已有监督进程或作业持锁；不得重复启动") from exc
        yield stream


def _group_alive(pid):
    """Conservative read-only check; never signal a PID recovered from disk."""
    if not isinstance(pid, int):
        return False
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                if fields[0] != "Z" and int(fields[2]) == pid:
                    return True
            except (OSError, ValueError, IndexError):
                continue
    return False


class ExperimentRunner:
    def __init__(self, task_root, *, device_probe=nvidia_devices):
        self.book = ExperimentBook(task_root)
        self.root = self.book.root
        self.device_probe = device_probe

    def _prepare(self, plan):
        _require(isinstance(plan, dict) and plan.get("schema_version") == 1,
                 "INVALID_QUEUE", "复验计划 schema_version 必须为 1")
        _require(isinstance(plan.get("id"), str) and TASK_ID_RE.fullmatch(plan["id"]),
                 "INVALID_QUEUE", "复验计划 ID 无效")
        data = self.book._load()
        _require(plan.get("protocol_id") in data["protocols"], "PROTOCOL_MISSING", "须先冻结正式协议")
        record = data["protocols"][plan["protocol_id"]]
        protocol = self.book._effective(record)
        _require(plan.get("seeds") == protocol["seeds"], "INVALID_QUEUE", "计划 seed 必须与已冻结的完整集合及顺序一致")
        method_root, selection = DeliveryEvidence(self.root).current_best()
        _require(evidence(self.root, plan.get("selection")) == method_root / "selection.json",
                 "METHOD_MISMATCH", "计划须绑定当前唯一最终方法的 selection.json")
        files = plan.get("adapter_files")
        _require(isinstance(files, list) and files and len({x["path"] for x in files}) == len(files),
                 "INVALID_QUEUE", "须绑定完整的可信评测适配器源码索引")
        for ref in files:
            evidence(self.root, ref)
        command = plan.get("command")
        _require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command),
                 "INVALID_QUEUE", "command 须为无 shell 的 argv")
        _require(any("{request}" in x for x in command), "INVALID_QUEUE", "适配器须读取 {request}")
        try:
            [x.format_map({"request": "request.json", "adapter_root": "adapter"}) for x in command]
        except (KeyError, ValueError) as exc:
            raise FlowError("INVALID_QUEUE", "command 仅支持 {request} 和 {adapter_root}") from exc
        resources = plan.get("resources", {})
        _require(isinstance(resources, dict), "INVALID_QUEUE", "须声明授权资源范围")
        evidence(self.root, resources.get("authorization"))
        for name in ("max_parallel", "cpu_threads"):
            _require(type(resources.get(name)) is int and resources[name] > 0, "INVALID_QUEUE", f"{name} 须为正整数")
        for name in ("metric_sensitive", "hardware_sensitive"):
            _require(type(resources.get(name)) is bool, "INVALID_QUEUE", f"须声明 {name}")
        _require(not resources["metric_sensitive"] or resources["max_parallel"] == 1,
                 "RESOURCE_POLICY", "计时/吞吐敏感指标必须串行；本队列不承诺共享主机真正独占")
        ids, count = resources.get("gpu_ids"), resources.get("gpus_per_run")
        _require(isinstance(ids, list) and all(isinstance(i, str) and i.isascii() and i.isdigit() for i in ids)
                 and len(set(ids)) == len(ids) and type(count) is int and 0 <= count <= len(ids)
                 and (count > 0 or not ids), "RESOURCE_POLICY", "须明确授权 GPU 索引和每次 GPU 数；CPU 使用 []/0")
        _require(number(plan.get("timeout_seconds"), "timeout_seconds") > 0, "INVALID_QUEUE", "须有单次运行超时")
        directory = _directory(self.root, plan.get("output_root"))
        state_file = directory / "queue.json"
        frozen = {"plan": plan, "protocol_sha256": record["sha256"], "selection_sha256": plan["selection"]["sha256"]}
        if state_file.exists():
            state = _read_json(state_file)
            _require(state["frozen"] == frozen, "QUEUE_DRIFT", "复验计划或协议漂移；不得覆盖原始记录")
            _require(isinstance(state.get("runs"), dict) and all(k in {str(s) for s in plan["seeds"]}
                     and isinstance(v, str) and TASK_ID_RE.fullmatch(v) for k, v in state["runs"].items()),
                     "INVALID_QUEUE", "队列运行索引损坏")
        else:
            _require(not directory.exists(), "OUTPUT_EXISTS", "输出目录已存在；禁止混入或覆盖旧文件")
            directory.mkdir(parents=True)
            state = {"frozen": copy.deepcopy(frozen), "runs": {}}
            _atomic_json(state_file, state)
        return directory, state, protocol, method_root, selection

    def _launch(self, directory, plan, protocol, method_root, selection, seed, state, allocation, retry=None):
        run_id = f"{plan['id']}-{seed}" if retry is None else retry + "-r"
        output = directory / run_id
        spec = {"run_id": run_id, "protocol_id": plan["protocol_id"], "role": "best_method",
                "seed": seed, "method_files": selection["snapshot_files"], "retry_of": retry}
        _require(not output.exists(), "OUTPUT_EXISTS", "运行目录已存在，先恢复而不是覆盖")
        # Publish the recoverable minimum in one rename. Incomplete preparation
        # directories are not jobs and cannot have started an adapter/W2 run.
        with tempfile.TemporaryDirectory(prefix=".preparing-", dir=directory) as temporary:
            prepared = Path(temporary)
            (prepared / "run.log").touch()
            _atomic_json(prepared / "launch-intent.json", {"spec": spec, "plan_sha256": _canonical_digest(plan)})
            prepared.rename(output)
        copies = []
        for refs, source_root, dest in ((selection["snapshot_files"], method_root, output / "method"),
                                        (plan["adapter_files"], self.root, output / "adapter")):
            for ref in refs:
                source = evidence(self.root, ref)
                target = dest / source.relative_to(source_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                _require(_sha256(target) == ref["sha256"], "EVIDENCE_DRIFT", "复制期间源码改变")
                copies.append(_ref(self.root, target))
        run = self.book.start(spec)
        state["runs"][str(seed)] = run_id
        _atomic_json(directory / "queue.json", state)
        request = {"run": run, "protocol": protocol, "method_directory": str(output / "method"),
                   "output_directory": str(output), "assigned_devices": allocation["devices"],
                   "source_copies": copies, "plan_sha256": _canonical_digest(plan),
                   "resources": plan["resources"]}
        _atomic_json(output / "request.json", request)
        replacements = {"request": str(output / "request.json"), "adapter_root": str(output / "adapter")}
        command = [x.format_map(replacements) for x in plan["command"]]
        environment = {"CUDA_VISIBLE_DEVICES": ",".join(allocation["devices"]) if plan["resources"]["gpus_per_run"] else "",
                       "PYTHONHASHSEED": str(seed % 4294967296), "OMP_NUM_THREADS": str(plan["resources"]["cpu_threads"]),
                       "MKL_NUM_THREADS": str(plan["resources"]["cpu_threads"])}
        env = dict(os.environ, **environment)
        execution = {"command": command, "started_at": _now(), "finished_at": None,
                     "exit_code": None, "devices": allocation["devices"], "device_inventory": allocation["inventory"],
                     "environment": environment}
        item = {"process": None, "run": run, "output": output, "execution": execution,
                "deadline": time.monotonic() + plan["timeout_seconds"], "allocation": allocation}
        log = (output / "run.log").open("wb")
        try:
            # The adapter inherits this lock so a lost supervisor cannot cause a
            # duplicate launch during the Popen -> execution.json write window.
            with _lock(output / "run.lock") as child_lock:
                item["process"] = subprocess.Popen(command, cwd=output, env=env, stdin=subprocess.DEVNULL,
                                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
                                                   pass_fds=(child_lock.fileno(), *allocation["fds"]))
                execution["pid"] = item["process"].pid
        except OSError as exc:
            log.write(str(exc).encode("utf-8"))
            item["launch_error"] = str(exc)
        finally:
            log.close()
        _atomic_json(output / "execution.json", execution)
        return item

    def _finish(self, item, failure=None):
        output, execution = item["output"], item["execution"]
        process = item["process"]
        execution.update(finished_at=None if "missing_reason" in execution else _now(),
                         exit_code=process.returncode if process else None)
        if "launch_error" in item:
            failure = ("infra_error", "启动失败：" + item["launch_error"])
        elif failure is None and execution["exit_code"] != 0:
            failure = ("failed", f"适配器退出码 {execution['exit_code']}；未推断为可重试外部异常")
        _atomic_json(output / "execution.json", execution)
        refs = {"log": _ref(self.root, output / "run.log"), "execution": _ref(self.root, output / "execution.json"),
                "intent": _ref(self.root, output / "launch-intent.json")}
        if (output / "request.json").exists():
            refs["request"] = _ref(self.root, output / "request.json")
        raw_path = output / "adapter-result.json"
        if raw_path.is_file() and not raw_path.is_symlink():
            refs["adapter_result"] = _ref(self.root, raw_path)
        result = {}
        if failure is None:
            try:
                result = _read_json(raw_path)
                for ref in _read_json(output / "request.json")["source_copies"]:
                    evidence(self.root, ref)
                _require(result.get("status") in FAILED_RUN_STATUSES | {"succeeded"}, "INVALID_RESULT", "未知结果状态")
                _require(result["status"] == "succeeded" or isinstance(result.get("error"), str) and result["error"].strip(),
                         "INVALID_RESULT", "失败结果须有清晰 error，缺项不是基础设施异常")
                _require(result.get("devices") == execution["devices"], "DEVICE_MISMATCH", "适配器须记录实际使用的分配设备")
                _require(result.get("status") != "infra_error", "INVALID_RESULT", "适配器不得自行把方法失败认定为可重试的外部异常")
                for name, relative in result.pop("artifacts", {}).items():
                    _require(name in {"model", "artifact", "reload_log"}, "INVALID_RESULT", "未知训练附件")
                    path = _directory(output, relative)
                    _require(path.is_file(), "INVALID_RESULT", "训练附件须为本次输出内的普通文件")
                    refs[name] = _ref(self.root, path)
            except (FlowError, OSError, TypeError, AttributeError) as exc:
                failure = ("format_error", str(exc))
        if failure is not None:
            result = {"status": failure[0], "error": failure[1]}
        result.pop("evidence", None)
        result["execution"] = execution
        _atomic_json(output / "result.receipt.json", result)
        refs["result"] = _ref(self.root, output / "result.receipt.json")
        result["evidence"] = refs
        # A durable receipt allows idempotent import if interruption happens just
        # before W2.finish. A raw adapter result alone is not an observed exit.
        _atomic_json(output / "ledger-result.json", result)
        return self.book.finish(item["run"]["run_id"], result)

    def _recover(self, directory, state, selection):
        active = []
        runs = self.book._load()["runs"]
        plan = state["frozen"]["plan"]
        # Both durable files can survive independently: reconcile launch intents
        # with W2 before consulting the convenience seed -> latest-run index.
        for path in sorted(directory.glob("*/launch-intent.json"), key=lambda p: len(p.parent.name)):
            if path.parent.name.startswith(".preparing-"):
                continue
            intent = _read_json(path)
            spec = intent["spec"]
            _require(intent["plan_sha256"] == _canonical_digest(plan)
                     and spec["run_id"] == path.parent.name and TASK_ID_RE.fullmatch(spec["run_id"])
                     and spec["seed"] in plan["seeds"] and spec["protocol_id"] == plan["protocol_id"]
                     and spec["role"] == "best_method" and spec["method_files"] == selection["snapshot_files"],
                     "QUEUE_DRIFT", "启动意图与冻结计划不符")
            if spec["run_id"] not in runs:
                runs[spec["run_id"]] = self.book.start(spec)
            run = runs[spec["run_id"]]
            _require(all(run[k] == spec[k] for k in ("run_id", "protocol_id", "seed", "role", "method_files", "retry_of")),
                     "QUEUE_DRIFT", "启动意图与原账本不符")
            key = str(spec["seed"])
            if key not in state["runs"] or state["runs"][key] == spec.get("retry_of"):
                state["runs"][key] = spec["run_id"]
        _atomic_json(directory / "queue.json", state)
        for run_id in state["runs"].values():
            _require(run_id in runs, "QUEUE_DRIFT", "队列引用不存在的正式运行")
            run = runs[run_id]
            if run["status"] != "running":
                continue
            output = directory / run_id
            try:
                with _lock(output / "run.lock"):
                    execution_path = output / "execution.json"
                    execution = _read_json(execution_path) if execution_path.exists() else {}
                    if _group_alive(execution.get("pid")):
                        active.append(run_id)
                        continue
                    receipt = output / "ledger-result.json"
                    if receipt.exists():
                        self.book.finish(run_id, _read_json(receipt))
                    else:
                        execution.update(command=execution.get("command"), started_at=execution.get("started_at"),
                                         missing_reason="监督进程已中断；未观测真实退出码/完成时刻，不能由产物反推成功")
                        self._finish({"run": run, "process": None, "output": output, "execution": execution},
                                     ("infra_error", "监督进程丢失退出状态；原始文件保留，须显式决定是否重试"))
            except FlowError as exc:
                if exc.code != "QUEUE_ACTIVE":
                    raise
                active.append(run_id)
        return active

    @staticmethod
    def _stop(item):
        process = item["process"]
        if process is not None and process.poll() is None:
            # Only a process started by this invocation, never an observed user PID.
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()

    def execute(self, plan, *, retry_of=()):
        self.book.store._load()
        with _lock(self.book.store.state_dir / "experiment-execute.lock"):
            return self._execute(plan, retry_of)

    def _execute(self, plan, retry_of):
        directory, state, protocol, method_root, selection = self._prepare(plan)
        inherited = self._recover(directory, state, selection)
        if inherited:
            return {"status": "running", "active": inherited, "launched": [],
                    "next_action": "已有作业仍在运行；稍后用同一计划继续，不补跑活跃 seed"}
        active, launched = [], []
        runs = self.book._load()["runs"]
        retries = {}
        _require(len(retry_of) == len(set(retry_of)), "INVALID_RETRY", "重复的 retry_of")
        for run_id in retry_of:
            run = runs.get(run_id, {})
            _require(state["runs"].get(str(run.get("seed"))) == run_id and run.get("status") == "infra_error",
                     "INVALID_RETRY", "只能显式重试本队列当前已登记的基础设施失败")
            retries[run["seed"]] = run_id
        pending = [s for s in plan["seeds"] if str(s) not in state["runs"] or s in retries]
        pool = DevicePool(plan["resources"], self.device_probe)
        if pending and plan["resources"]["gpus_per_run"]:
            pool.frozen = state.get("device_pool")
            pool.inventory()
            state["device_pool"] = pool.frozen
            _atomic_json(directory / "queue.json", state)
        try:
            while pending or active:
                unavailable = False
                released = False
                while pending and len(active) < plan["resources"]["max_parallel"]:
                    allocation = pool.acquire()
                    if allocation is None:
                        unavailable = True
                        break
                    seed = pending.pop(0)
                    try:
                        item = self._launch(directory, plan, protocol, method_root, selection, seed, state, allocation, retries.get(seed))
                    except BaseException:
                        allocation["lease"].close()
                        raise
                    active.append(item)
                    launched.append(item["run"]["run_id"])
                for item in list(active):
                    if item["process"] is None or item["process"].poll() is not None:
                        active.remove(item)
                        released = True
                        try:
                            self._finish(item)
                        finally:
                            item["allocation"]["lease"].close()
                    elif time.monotonic() >= item["deadline"]:
                        self._stop(item)
                        active.remove(item)
                        released = True
                        try:
                            self._finish(item, ("timeout", "超过预登记单次运行时限"))
                        finally:
                            item["allocation"]["lease"].close()
                if active:
                    time.sleep(0.05)
                elif pending and unavailable and not released:
                    break
        except BaseException:
            for item in active:
                self._stop(item)
                self._finish(item, ("infra_error", "监督进程中断，保留日志；仅允许显式重试"))
                item["allocation"]["lease"].close()
            raise
        report = self.book.report(plan["protocol_id"], ("best_method",))
        return {"status": "waiting_for_resources" if pending else report["status"], "report": report,
                "launched": launched, "pending_seeds": pending,
                "run_directories": {seed: str((directory / run).relative_to(self.root)) for seed, run in state["runs"].items()}}
