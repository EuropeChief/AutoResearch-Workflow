"""W4 trajectory provenance and the single final-method evidence contract."""
from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

from .core import FlowError, TaskStore, _atomic_json, _canonical_digest, _read_json, _require, _sha256, _utc_now
from .experiments import ExperimentBook, evidence
from .runtime import Runtime, TRACKS
from .trajectory import validate_round
from .duration import snapshot as duration_snapshot, validate_roll


def _reject_local_profiles(tree: Path) -> None:
    """The workflow's private account configuration is not submission evidence."""
    _require(not any(p.name == "model_profiles" and p.parent.name == "local"
                     for p in (tree, *tree.rglob("*"))), "LOCAL_CONFIG_LEAK",
             "提交材料包含 local/model_profiles 私有配置；请移出制作期账号配置，不将其作为任务证据")


def _safe_tree(root: Path, value: str) -> Path:
    _require(isinstance(value, str) and value and not Path(value).is_absolute(), "INVALID_PATH", "目录须为任务内相对路径")
    relative = Path(value)
    _require(".." not in relative.parts and not any(part in {"", "."} for part in relative.parts), "INVALID_PATH", "目录路径不能越界")
    path = root / relative
    _require(path.is_dir() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()), "INVALID_DIRECTORY", "目录不存在或越界")
    _require(not any(p.is_symlink() for p in path.rglob("*")), "SYMLINK_IN_TREE", "证据目录不能包含符号链接")
    _reject_local_profiles(path)
    return path


def _files(root: Path, directory: Path) -> list[dict]:
    return [{"path": str(path.relative_to(root)), "sha256": _sha256(path)}
            for path in sorted(directory.rglob("*")) if path.is_file()]


def _copy_tree(source: Path, target: Path) -> None:
    _require(not target.exists(), "TARGET_EXISTS", "目标目录已存在")
    target.mkdir(parents=True)
    for path in sorted(source.rglob("*")):
        _require(not path.is_symlink(), "SYMLINK_IN_TREE", "不能复制符号链接")
        dest = target / path.relative_to(source)
        if path.is_dir():
            dest.mkdir(exist_ok=True)
        elif path.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    for path in sorted((p for p in source.rglob("*") if p.is_dir()), reverse=True):
        shutil.copystat(path, target / path.relative_to(source))


def _score_result(path: Path) -> float:
    result = _read_json(path)
    score = result.get("score")
    _require(result.get("status") == "succeeded" and type(score) in (int, float)
             and math.isfinite(score), "INVALID_CANDIDATE_SCORE", "候选须有真实、有限的成功评分结果")
    return float(score)


class DeliveryEvidence:
    def __init__(self, task_root: Path):
        self.store = TaskStore(Path(task_root))
        self.root = self.store.task_root
        self.directory = self.store.state_dir / "delivery"

    def _ready(self) -> None:
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "先复核已锁定的权威规则")
        self.directory.mkdir(exist_ok=True)

    def _runtime(self, track: str) -> tuple[Runtime, dict]:
        _require(track in TRACKS, "INVALID_TRACK", "只能整理 codex 或 seed 轨迹")
        runtime = Runtime(self.root)
        status = runtime.status(track)
        _require(status["active"] is None and status["thread_id"], "TRAJECTORY_RUNNING", "轨迹尚未完整收口")
        duration = duration_snapshot(self.root)
        minimum = duration["policy"]["minimum_effective_seconds"]
        _require(status["effective_seconds_before_content_review"] >= minimum,
                 "DURATION_SHORT", f"该轨迹可核活动时长不足冻结门槛 {minimum / 3600:g} 小时")
        if duration["policy"]["mode"] == "non_training_7h":
            segments = [s for s in runtime._state(track)["segments"] if s["phase"] == "formal"]
            _require(segments and segments[-1].get("status") == "completed", "TRAJECTORY_RUNNING",
                     "7h轨迹末段尚未正常收口；外部故障需原会话接续，不能只凭计时达标交付")
        return runtime, status

    def finalize_trajectory(self, track: str, changes: dict | None = None) -> dict:
        """Use Agent-authored JSONL; logs are independent corroboration, not source text."""
        self._ready()
        runtime, status = self._runtime(track)
        source = runtime.directory / track / "formal" / "output" / "trajectory.jsonl"
        _require(source.is_file() and not source.is_symlink(), "TRAJECTORY_MISSING", "Agent 未生成 trajectory.jsonl")
        raw = source.read_bytes()
        _require(raw.strip(), "TRAJECTORY_EMPTY", "Agent 轨迹为空")
        source_hash = hashlib.sha256(raw).hexdigest()
        changes = changes or {"source_sha256": source_hash, "corrections": []}
        _require(isinstance(changes, dict) and changes.get("source_sha256") == source_hash
                 and isinstance(changes.get("corrections"), list), "TRAJECTORY_SOURCE_DRIFT", "修订须绑定未改原件哈希")
        corrections: dict[int, dict] = {}
        for item in changes["corrections"]:
            _require(isinstance(item, dict) and set(item) == {"line", "raw_sha256", "replacement", "reason", "evidence"},
                     "INVALID_CORRECTION", "修订须含行号、原行哈希、替换行、理由和证据")
            index = item["line"]
            _require(type(index) is int and index > 0 and index not in corrections
                     and isinstance(item["reason"], str) and item["reason"].strip()
                     and isinstance(item["evidence"], list) and item["evidence"], "INVALID_CORRECTION", "修订行号/理由/证据无效")
            for ref in item["evidence"]:
                evidence(self.root, ref)
            corrections[index] = item
        lines = raw.splitlines()
        _require(set(corrections) <= set(range(1, len(lines) + 1)), "INVALID_CORRECTION", "修订行号不存在于原件")
        rounds = []
        for number, line in enumerate(lines, 1):
            if number in corrections:
                edit = corrections[number]
                _require(hashlib.sha256(line).hexdigest() == edit["raw_sha256"], "CORRECTION_DRIFT", "被修订的原行已变化")
                row = edit["replacement"]
            else:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeError) as exc:
                    raise FlowError("TRAJECTORY_PARSE", f"第 {number} 行无法解析；须提供有证据的修订") from exc
            rounds.append(validate_round(row, number))
        # Read the same source again: an Agent or external process may have modified it mid-read.
        _require(_sha256(source) == source_hash, "TRAJECTORY_SOURCE_DRIFT", "整理过程中 Agent 轨迹已变化")
        version = _canonical_digest({"source_sha256": source_hash, "corrections": changes["corrections"]})[:20]
        target = self.directory / "trajectories" / track / version
        if not target.exists():
            target.mkdir(parents=True)
            (target / "source.jsonl").write_bytes(raw)
            _atomic_json(target / "final.json", {"rounds": rounds})
            _atomic_json(target / "provenance.json", {
                "schema_version": 1, "track": track, "source_sha256": source_hash,
                "source_snapshot_sha256": _sha256(target / "source.jsonl"),
                "final_sha256": _sha256(target / "final.json"), "corrections": changes["corrections"],
                "thread_id": status["thread_id"],
                "effective_seconds_before_content_review": status["effective_seconds_before_content_review"],
                "runtime_segments": [s["segment_id"] for s in runtime._state(track)["segments"] if s["phase"] == "formal"],
                "content_review": "expert_required", "created_at": _utc_now(),
            })
        else:
            existing = _read_json(target / "provenance.json")
            _require(existing["source_sha256"] == source_hash and _sha256(target / "final.json") == existing["final_sha256"]
                     and _sha256(target / "source.jsonl") == existing["source_snapshot_sha256"],
                     "TRAJECTORY_DRIFT", "已有轨迹版本发生变化")
        _atomic_json(self.directory / "trajectories" / track / "current.json",
                     {"version": version, "final_sha256": _sha256(target / "final.json")})
        return {"status": "ready_for_expert_review", "track": track, "rounds": len(rounds),
                "version": version, "final_path": str(target / "final.json"),
                "corrections": len(changes["corrections"])}

    def current_trajectory(self, track: str) -> tuple[Path, dict]:
        _require(track in TRACKS, "INVALID_TRACK", "只能读取 codex 或 seed 轨迹")
        pointer = _read_json(self.directory / "trajectories" / track / "current.json")
        path = self.directory / "trajectories" / track / pointer["version"]
        audit = _read_json(path / "provenance.json")
        _require(_sha256(path / "final.json") == pointer["final_sha256"] == audit["final_sha256"]
                 and _sha256(path / "source.jsonl") == audit["source_snapshot_sha256"],
                 "TRAJECTORY_DRIFT", "轨迹原件/最终版本哈希不一致")
        return path / "final.json", audit

    def review_trajectory(self, track: str, review: dict) -> dict:
        """Bind each Agent-authored round to a located operation/score source."""
        self._ready()
        final, audit = self.current_trajectory(track)
        rounds = _read_json(final)["rounds"]
        _require(isinstance(review, dict) and isinstance(review.get("reviewer"), str)
                 and review["reviewer"].strip() and isinstance(review.get("rounds"), list)
                 and len(review["rounds"]) == len(rounds), "TRAJECTORY_REVIEW", "逐轮审阅记录不完整")
        for number, item in enumerate(review["rounds"], 1):
            _require(isinstance(item, dict) and item.get("round") == number
                     and item.get("consistent") is True and isinstance(item.get("evidence"), list)
                     and item["evidence"], "TRAJECTORY_REVIEW", f"第 {number} 轮缺一致性判断或证据")
            for located in item["evidence"]:
                _require(isinstance(located, dict) and isinstance(located.get("locator"), str)
                         and located["locator"].strip(), "TRAJECTORY_REVIEW", "证据须含可定位的行号/事件/评分 ID")
                evidence(self.root, located.get("ref"))
        duration = duration_snapshot(self.root)
        if duration["policy"]["mode"] == "non_training_7h":
            validate_roll(self.root, rounds, review, duration["assessment"]["decision"]["public_dev_protocol"])
        record = {"schema_version": 1, "track": track, "final_sha256": audit["final_sha256"],
                  "review": review, "reviewed_at": _utc_now(), "duration_sha256": duration["sha256"]}
        target = final.parent / "review.json"
        _atomic_json(target, record)
        return {"status": "reviewed", "track": track, "rounds": len(rounds),
                "review_path": str(target), "review_sha256": _sha256(target)}

    def current_review(self, track: str) -> dict:
        final, audit = self.current_trajectory(track)
        review = _read_json(final.parent / "review.json")
        _require(review.get("track") == track and review.get("final_sha256") == audit["final_sha256"],
                 "TRAJECTORY_REVIEW_DRIFT", "审阅记录与当前轨迹不一致")
        rows = _read_json(final)["rounds"]
        payload = review.get("review")
        _require(isinstance(payload, dict), "TRAJECTORY_REVIEW_DRIFT", "审阅正文丢失")
        items = payload.get("rounds")
        _require(isinstance(items, list) and len(items) == len(rows), "TRAJECTORY_REVIEW_DRIFT", "审阅轮次不完整")
        for number, item in enumerate(items, 1):
            _require(isinstance(item, dict) and item.get("round") == number and item.get("consistent") is True
                     and isinstance(item.get("evidence"), list) and item["evidence"],
                     "TRAJECTORY_REVIEW_DRIFT", "审阅记录被改动或缺逐轮证据")
            for located in item["evidence"]:
                _require(isinstance(located, dict) and isinstance(located.get("locator"), str)
                         and located["locator"].strip(), "TRAJECTORY_REVIEW_DRIFT", "证据定位缺失")
                evidence(self.root, located.get("ref"))
        duration = duration_snapshot(self.root)
        if duration["policy"]["mode"] == "non_training_7h":
            _require(review.get("duration_sha256") == duration["sha256"], "DURATION_DRIFT", "闭环审阅与冻结政策不符")
            validate_roll(self.root, rows, payload, duration["assessment"]["decision"]["public_dev_protocol"])
        return review

    def snapshot_best(self, decision: dict) -> dict:
        self._ready()
        for track in TRACKS:
            self._runtime(track)
            self.current_trajectory(track)
        _require(isinstance(decision, dict) and decision.get("selected_track") in {*TRACKS, "starter"}
                 and isinstance(decision.get("rationale"), str) and decision["rationale"].strip(),
                 "INVALID_SELECTION", "须说明唯一最终方法来源和理由")
        results = decision.get("candidate_results")
        _require(isinstance(results, dict) and set(results) == set(TRACKS), "INVALID_SELECTION", "须记录两条轨迹候选评分或无法评分的理由")
        scores = {}
        for track, item in results.items():
            _require(isinstance(item, dict), "INVALID_SELECTION", "候选记录须为对象")
            if item.get("result") is None:
                _require(isinstance(item.get("invalid_reason"), str) and item["invalid_reason"].strip()
                         and isinstance(item.get("evidence"), list) and item["evidence"], "INVALID_SELECTION", "无效候选须有原因与证据")
                for ref in item["evidence"]:
                    evidence(self.root, ref)
            else:
                scores[track] = _score_result(evidence(self.root, item["result"]))
        chosen = decision["selected_track"]
        if chosen == "starter":
            _require(not scores or max(scores.values()) <= 0, "STARTER_NOT_BEST", "有正向有效候选时不能交 Starter")
            exception = decision.get("starter_exception")
            _require(isinstance(exception, dict) and isinstance(exception.get("reviewer"), str)
                     and exception["reviewer"].strip() and isinstance(exception.get("rationale"), str)
                     and exception["rationale"].strip() and isinstance(exception.get("evidence"), list)
                     and exception["evidence"], "STARTER_EXCEPTION_REQUIRED", "Starter 交付须核当期规则并明确记录 D22 暂定方案")
            for ref in exception["evidence"]:
                evidence(self.root, ref)
            source = _safe_tree(self.root, decision.get("starter_directory"))
        else:
            _require(chosen in scores and scores[chosen] == max(scores.values()) and scores[chosen] > 0,
                     "SELECTION_NOT_BEST", "所选方法须为同口径最高的正向有效候选；无提升按 D22 单独处理")
            runtime = Runtime(self.root)
            source = runtime.directory / chosen / "formal" / "output" / "best_method"
            _require(source.is_dir() and not source.is_symlink() and not any(p.is_symlink() for p in source.rglob("*")),
                     "BEST_METHOD_MISSING", "所选 Agent 未保存完整 best_method 或含符号链接")
        source_refs = _files(self.root, source)
        _require(source_refs, "BEST_METHOD_EMPTY", "最终方法源码目录为空")
        _require(not any(p["path"].endswith((".pt", ".pth", ".ckpt", ".safetensors", ".jsonl")) for p in source_refs),
                 "BEST_METHOD_ARTIFACT", "最终方法不能夹带模型 checkpoint 或轨迹")
        fingerprint = _canonical_digest({"selected_track": chosen, "source": source_refs, "decision": decision})[:20]
        dest = self.directory / "best_versions" / fingerprint
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            _copy_tree(source, dest)
            copied = _files(self.root, dest)
            _require([x["sha256"] for x in copied] == [x["sha256"] for x in source_refs],
                     "BEST_METHOD_DRIFT", "复制时最佳方法发生变化")
            _atomic_json(dest / "selection.json", {"schema_version": 1, "selected_track": chosen,
                         "scores": scores, "decision": decision, "source_files": source_refs,
                         "snapshot_files": copied, "created_at": _utc_now()})
        else:
            old = _read_json(dest / "selection.json")
            for ref in old["snapshot_files"]:
                evidence(self.root, ref)
        _atomic_json(self.directory / "best_current.json", {"version": fingerprint,
                     "selection_sha256": _sha256(dest / "selection.json")})
        return {"status": "snapshot_ready", "selected_track": chosen, "version": fingerprint,
                "snapshot_path": str(dest), "method_files": _read_json(dest / "selection.json")["snapshot_files"]}

    def current_best(self) -> tuple[Path, dict]:
        pointer = _read_json(self.directory / "best_current.json")
        directory = self.directory / "best_versions" / pointer["version"]
        _require(_sha256(directory / "selection.json") == pointer["selection_sha256"],
                 "SELECTION_DRIFT", "最终方法选择记录被改动")
        selection = _read_json(directory / "selection.json")
        for ref in selection["snapshot_files"]:
            evidence(self.root, ref)
        return directory, selection

    def verify_best(self, spec: dict) -> dict:
        self._ready()
        directory, selection = self.current_best()
        protocol_id = spec.get("protocol_id")
        _require(isinstance(protocol_id, str) and protocol_id, "INVALID_VERIFICATION", "须声明正式协议 ID")
        report = ExperimentBook(self.root).report(protocol_id, ("best_method",))
        _require(report["status"] == "ok", "BEST_RETEST_INCOMPLETE", "唯一最终方法尚未完成冻结协议的全部正式 seed")
        expected_method = _canonical_digest(sorted(selection["snapshot_files"], key=lambda x: x["path"]))
        _require(report["groups"]["best_method"]["method_sha256"] == expected_method,
                 "BEST_RETEST_MISMATCH", "正式复验方法与已选源码快照不一致")
        _require(isinstance(spec.get("reviewer"), str) and spec["reviewer"].strip()
                 and isinstance(spec.get("rationale"), str) and spec["rationale"].strip(),
                 "CLEAN_REVIEW_MISSING", "干净快照重跑须给审查人和复现结论")
        result_ref, log_ref = spec.get("clean_result"), spec.get("clean_log")
        result = _read_json(evidence(self.root, result_ref))
        evidence(self.root, log_ref)
        execution = result.get("execution")
        _require(result.get("status") == "succeeded" and result.get("method_sha256") == expected_method
                 and type(result.get("score")) in (int, float) and math.isfinite(result["score"])
                 and isinstance(execution, dict) and execution.get("exit_code") == 0
                 and isinstance(execution.get("command"), list) and execution["command"]
                 and all(isinstance(execution.get(k), str) and execution[k] for k in ("started_at", "finished_at")),
                 "CLEAN_RERUN_INVALID", "干净快照重跑结果须实际成功、绑定方法哈希、命令、起止时间和日志")
        record = {"schema_version": 1, "selection_sha256": _sha256(directory / "selection.json"),
                  "method_sha256": expected_method, "protocol_id": protocol_id,
                  "protocol_sha256": report["protocol_sha256"], "experiment_sha256": report["experiment_sha256"],
                  "formal_mean": report["groups"]["best_method"]["mean"],
                  "clean_result": result_ref, "clean_log": log_ref,
                  "reviewer": spec["reviewer"], "rationale": spec["rationale"], "verified_at": _utc_now()}
        fingerprint = _canonical_digest({key: value for key, value in record.items() if key != "verified_at"})[:20]
        parent = self.directory / "best_verifications"
        parent.mkdir(exist_ok=True)
        target = parent / f"{fingerprint}.json"
        if target.exists():
            existing = _read_json(target)
            _require({key: value for key, value in existing.items() if key != "verified_at"}
                     == {key: value for key, value in record.items() if key != "verified_at"},
                     "BEST_VERIFICATION_DRIFT", "已存在复验版本与当前证据不一致")
        else:
            _atomic_json(target, record)
        _atomic_json(self.directory / "best_verification_current.json",
                     {"version": fingerprint, "sha256": _sha256(target)})
        return {"status": "verified", "method_sha256": expected_method,
                "formal_mean": record["formal_mean"], "clean_score": result["score"]}

    def best_verification(self) -> dict:
        directory, _ = self.current_best()
        pointer = _read_json(self.directory / "best_verification_current.json")
        path = self.directory / "best_verifications" / f"{pointer['version']}.json"
        _require(_sha256(path) == pointer["sha256"], "BEST_VERIFICATION_DRIFT", "复验记录版本哈希不一致")
        record = _read_json(path)
        _require(record["selection_sha256"] == _sha256(directory / "selection.json"), "BEST_VERIFICATION_DRIFT", "复验证据与当前方法不一致")
        evidence(self.root, record["clean_result"])
        evidence(self.root, record["clean_log"])
        report = ExperimentBook(self.root).report(record["protocol_id"], ("best_method",))
        _require(report["status"] == "ok" and report["experiment_sha256"] == record["experiment_sha256"],
                 "BEST_VERIFICATION_DRIFT", "正式复验记录已经变化")
        return record
