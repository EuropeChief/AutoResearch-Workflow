"""W1 规则来源与题目状态合同。

此模块不运行题目代码、训练或质检。外部接口刻意保持为 Registry 与
TaskStore：CLI 和未来 Codex/Pi 薄 Skill 均通过同一接口工作。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import CATALOG_SCHEMA_VERSION, FLOW_VERSION, STATE_DIRNAME, STATE_SCHEMA_VERSION
from .policies import effective_policy, new_policy, policy_status


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT
MANIFEST_PATH = PACKAGE_ROOT / "rules" / "manifest.json"
TASK_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
RULE_ID_RE = re.compile(r"AR-\d{3}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
STAGE_IDS = tuple(str(number) for number in range(1, 7))
STAGE_STATUSES = frozenset({"pending", "in_progress", "passed", "failed", "needs_recheck"})
SUBSTEP_IDS = {str(stage): tuple(f"{stage}.{step}" for step in range(1, count + 1)) for stage, count in enumerate((4, 5, 5, 4, 4, 5), start=1)}


class FlowError(Exception):
    """A user-actionable contract failure, never a task-science judgment."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise FlowError(code, message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), "MISSING_OR_UNSAFE_FILE", f"缺少普通文件或文件是符号链接：{path}")
    _require(path.stat().st_size <= 8 * 1024 * 1024, "FILE_TOO_LARGE", f"状态/规则文件超过 8 MiB：{path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FlowError("INVALID_JSON", f"无法读取 JSON {path}: {exc}") from exc
    _require(isinstance(value, dict), "INVALID_SCHEMA", f"JSON 根必须是对象：{path}")
    return value


def _safe_repository_file(repository_root: Path, relative_path: str) -> Path:
    _require(isinstance(relative_path, str) and relative_path, "INVALID_PATH", "来源路径必须为非空字符串")
    value = Path(relative_path)
    _require(not value.is_absolute() and all(part not in {"", ".", ".."} for part in value.parts), "INVALID_PATH", f"来源路径必须位于仓库内：{relative_path}")
    root = repository_root.resolve(strict=True)
    candidate = repository_root / value
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise FlowError("SOURCE_MISSING", f"来源不存在：{relative_path}") from exc
    _require(resolved.is_relative_to(root), "SOURCE_ESCAPE", f"来源路径越出仓库：{relative_path}")
    _require(resolved.is_file(), "SOURCE_NOT_FILE", f"来源不是普通文件：{relative_path}")
    return resolved


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _source_issues(root: Path, entries: list[dict], invalid_code: str) -> list[dict[str, str]]:
    """Verify a locked source once even when it also belongs to the full bundle."""
    issues: list[dict[str, str]] = []
    checked = set()
    for entry in entries:
        relative_path, expected = entry.get("path"), entry.get("sha256")
        _require(isinstance(relative_path, str) and isinstance(expected, str)
                 and bool(SHA256_RE.fullmatch(expected)), invalid_code, "来源锁含非法路径或哈希")
        identity = (relative_path, expected)
        if identity in checked:
            continue
        checked.add(identity)
        try:
            actual = _sha256(_safe_repository_file(root, relative_path))
        except FlowError as exc:
            issues.append({"code": exc.code, "path": relative_path, "message": exc.message})
            continue
        if actual != expected:
            issues.append({"code": "SOURCE_DRIFT", "path": relative_path,
                           "message": f"锁定 {expected}，当前 {actual}；请核对并恢复锁定原件，不覆盖来源锁"})
    return issues


class Registry:
    """One versioned central rule catalog plus the source files it projects."""

    def __init__(self, package_root: Path = PACKAGE_ROOT) -> None:
        self.package_root = package_root.resolve(strict=True)
        self.repository_root = self.package_root
        self.manifest_path = self.package_root / "rules" / "manifest.json"
        self.manifest = _read_json(self.manifest_path)
        self._validate_manifest()
        catalog_ref = self.manifest["catalog"]
        self.catalog_path = _safe_repository_file(self.repository_root, catalog_ref["path"])
        self.catalog = _read_json(self.catalog_path)
        self._validate_catalog()

    def _validate_manifest(self) -> None:
        data = self.manifest
        _require(data.get("schema_version") == 1, "INVALID_MANIFEST", "规则 manifest schema_version 必须为 1")
        _require(data.get("flow_version") == FLOW_VERSION, "VERSION_MISMATCH", "规则 manifest 与当前 CLI 版本不符")
        catalog = data.get("catalog")
        _require(isinstance(catalog, dict) and isinstance(catalog.get("path"), str) and isinstance(catalog.get("sha256"), str), "INVALID_MANIFEST", "规则 manifest 缺 catalog 路径或哈希")
        _require(bool(SHA256_RE.fullmatch(catalog["sha256"])), "INVALID_MANIFEST", "catalog SHA-256 格式错误")
        sources = data.get("sources")
        _require(isinstance(sources, list) and sources, "INVALID_MANIFEST", "规则 manifest 缺来源清单")
        seen: set[str] = set()
        for source in sources:
            _require(isinstance(source, dict), "INVALID_MANIFEST", "来源条目必须是对象")
            source_id = source.get("id")
            _require(isinstance(source_id, str) and source_id and source_id not in seen, "INVALID_MANIFEST", "来源 ID 缺失或重复")
            seen.add(source_id)
            _require(isinstance(source.get("path"), str) and bool(SHA256_RE.fullmatch(str(source.get("sha256", "")))), "INVALID_MANIFEST", f"来源 {source_id} 路径或哈希不合法")
            _require(source.get("priority") in {1, 2}, "INVALID_MANIFEST", f"来源 {source_id} 权威级别不合法")
            _require(isinstance(source.get("version"), str) and source["version"], "INVALID_MANIFEST", f"来源 {source_id} 缺版本标识")
        _require("tutorial" in seen and "qa_skill" in seen, "INVALID_MANIFEST", "必须包含教程与 QA Skill 两级来源")
        _require(next(item for item in sources if item["id"] == "tutorial")["priority"] == 1, "INVALID_MANIFEST", "教程必须是第一权威")
        _require(all(item["priority"] == 2 for item in sources if item["id"] != "tutorial"), "INVALID_MANIFEST", "QA Skill 与其路由方法必须是第二权威")
        checks = data.get("qa_checks")
        _require(isinstance(checks, list) and checks and all(isinstance(c, str) and re.fullmatch(r"(?:G|B|QA|H)\d{2}", c) for c in checks)
                 and len(set(checks)) == len(checks), "INVALID_MANIFEST", "缺少当前锁定 Skill 的检查项集合")
        bundled = data.get("bundled_files")
        _require(isinstance(bundled, list) and bundled, "INVALID_MANIFEST", "缺少随仓权威资料完整文件索引")
        paths = set()
        for item in bundled:
            _require(isinstance(item, dict) and isinstance(item.get("path"), str)
                     and item["path"] not in paths
                     and bool(SHA256_RE.fullmatch(str(item.get("sha256", "")))),
                     "INVALID_MANIFEST", "随仓资料路径重复或哈希不合法")
            paths.add(item["path"])
        _require(all(source["path"] in paths for source in sources),
                 "INVALID_MANIFEST", "权威来源未纳入完整文件索引")

    def _validate_catalog(self) -> None:
        data = self.catalog
        _require(data.get("schema_version") == CATALOG_SCHEMA_VERSION, "INVALID_CATALOG", "规则目录 schema_version 不匹配")
        rules = data.get("rules")
        _require(isinstance(rules, list) and rules, "INVALID_CATALOG", "规则目录缺规则")
        _require(data.get("rule_count") == len(rules), "INVALID_CATALOG", "规则数量声明与实际不符")
        seen: set[str] = set()
        for rule in rules:
            _require(isinstance(rule, dict), "INVALID_CATALOG", "规则条目必须是对象")
            rule_id = rule.get("id")
            _require(isinstance(rule_id, str) and bool(RULE_ID_RE.fullmatch(rule_id)) and rule_id not in seen, "INVALID_CATALOG", "规则 ID 缺失、非法或重复")
            seen.add(rule_id)
            stages = rule.get("stages")
            _require(isinstance(stages, list) and stages and all(type(stage) is int and 1 <= stage <= 6 for stage in stages) and stages == sorted(set(stages)), "INVALID_CATALOG", f"{rule_id} 阶段非法或重复")
            for field in ("statement", "evidence", "reviewer"):
                _require(isinstance(rule.get(field), str) and rule[field].strip(), "INVALID_CATALOG", f"{rule_id} 缺 {field}")
            refs = rule.get("source_refs")
            _require(isinstance(refs, list) and refs and all(isinstance(ref, str) and (ref.startswith("T:") or ref.startswith("Q:")) for ref in refs), "INVALID_CATALOG", f"{rule_id} 缺权威来源定位")
            timing = rule.get("timing", {})
            steps = {step for values in SUBSTEP_IDS.values() for step in values}
            _require(timing.get("inform_at") in steps
                     and all(isinstance(timing.get(key), list) and timing[key]
                             and all(step in steps for step in timing[key]) for key in ("check_at", "due_at")),
                     "INVALID_CATALOG", f"{rule_id} 缺合法子步骤时机")
            _require(all(timing["inform_at"] <= step for step in timing["check_at"] + timing["due_at"]),
                     "INVALID_CATALOG", f"{rule_id} 提前告知不得晚于检查或到期")
            _require(rule.get("applicability") in {"all", "requires_review"}, "INVALID_CATALOG", f"{rule_id} 适用性说明缺失")
        coverage = data.get("coverage")
        _require(isinstance(coverage, dict), "INVALID_CATALOG", "规则目录缺 QA 覆盖映射")
        expected = set(self.manifest["qa_checks"])
        _require(set(coverage) == expected, "INVALID_CATALOG", "G/B/QA/H 覆盖映射缺项或含未知项")
        for check_id, rule_ids in coverage.items():
            _require(isinstance(rule_ids, list) and rule_ids and all(rule_id in seen for rule_id in rule_ids), "INVALID_CATALOG", f"{check_id} 映射了不存在的规则")
        _require(data.get("skipped_checks") == self.manifest.get("skipped_checks")
                 and set(data["skipped_checks"]) <= expected, "INVALID_CATALOG", "跳过项须与当期 Skill 锁一致")
        notices = data.get("workflow_notices", [])
        _require(isinstance(notices, list), "INVALID_CATALOG", "workflow_notices 须为列表，不属于新增权威来源")
        notice_ids = set()
        for notice in notices:
            _require(isinstance(notice, dict) and isinstance(notice.get("id"), str)
                     and notice["id"] not in notice_ids and notice.get("source_kind") == "user_notice"
                     and isinstance(notice.get("notice_text"), str) and bool(notice["notice_text"].strip())
                     and isinstance(notice.get("decision"), str) and bool(notice["decision"].strip())
                     and isinstance(notice.get("stages"), list) and bool(notice["stages"])
                     and all(type(n) is int and n in range(1, 7) for n in notice["stages"])
                     and isinstance(notice.get("affected_rule_ids"), list)
                     and all(r in seen for r in notice["affected_rule_ids"]),
                     "INVALID_CATALOG", "用户通知缺原话/范围/决策，或引用了未知规则")
            notice_ids.add(notice["id"])

    def show(self, *, rule_id=None, step=None):
        """Read-only obligations, never a claim that their evidence has passed."""
        _require((rule_id is None) != (step is None), "INVALID_RULE_QUERY", "指定规则 ID 或子步骤之一")
        _require(not self.check_sources(), "REGISTRY_DRIFT", "规则来源漂移，先核对锁定原件")
        if step is not None:
            _require(step in {s for values in SUBSTEP_IDS.values() for s in values},
                     "INVALID_RULE_QUERY", "子步骤不合法")
        rows = []
        for rule in self.catalog["rules"]:
            timing = rule["timing"]
            if not (rule["id"] == rule_id if rule_id is not None else
                    step == timing["inform_at"] or step in timing["check_at"] + timing["due_at"]):
                continue
            locations = []
            for ref in rule["source_refs"]:
                filename = ref.split(":", 1)[1].split("#", 1)[0].split("/")[-1]
                for source in self.manifest["sources"]:
                    if (ref.startswith("T:") and source["id"] == "tutorial"
                            or ref.startswith("Q:baseline-quality/") and source["id"].startswith("baseline")
                            and Path(source["path"]).name == filename
                            or ref.startswith("Q:") and not ref.startswith("Q:baseline-quality/")
                            and source["path"].startswith("skills/autoresearch-task-qa/")
                            and Path(source["path"]).name == filename):
                        locations.append({"ref": ref, "path": source["path"], "sha256": source["sha256"]})
            rows.append({**rule, "source_locations": locations, "compliance": "not_evaluated"})
        _require(rule_id is None or rows, "INVALID_RULE_QUERY", "规则 ID 不存在")
        return {"status": "ok", "rules": rows, "step": step,
                "next_action": "按规则准备证据并完成实质审查；适用条件未知时保留待判断，不自动跳过"}

    def check_sources(self) -> list[dict[str, str]]:
        entries = [self.manifest["catalog"], *self.manifest["sources"], *self.manifest["bundled_files"]]
        return _source_issues(self.repository_root, entries, "INVALID_MANIFEST")

    def lock_snapshot(self) -> dict[str, Any]:
        return {
            "manifest_path": str(self.manifest_path.relative_to(self.repository_root)),
            "manifest_sha256": _sha256(self.manifest_path),
            "catalog_sha256": self.manifest["catalog"]["sha256"],
            "catalog_path": self.manifest["catalog"]["path"],
            "sources": self.manifest["sources"],
            "bundled_files": self.manifest["bundled_files"],
            "rule_fingerprints": {rule["id"]: _canonical_digest(rule) for rule in self.catalog["rules"]},
            "rule_stages": {rule["id"]: rule["stages"] for rule in self.catalog["rules"]},
            "rule_source_refs": {rule["id"]: rule["source_refs"] for rule in self.catalog["rules"]},
            "workflow_notices": self.catalog.get("workflow_notices", []),
        }


class TaskStore:
    """Explicit, single-file task state; never guesses a task from the cwd."""

    def __init__(self, task_root: Path, *, repository_root: Path = REPOSITORY_ROOT) -> None:
        _require(task_root.exists() and task_root.is_dir() and not task_root.is_symlink(), "TASK_ROOT_MISSING", f"任务目录须已存在且不是符号链接：{task_root}")
        self.task_root = task_root.resolve(strict=True)
        self.repository_root = repository_root.resolve(strict=True)
        self.state_dir = self.task_root / STATE_DIRNAME
        self.state_path = self.state_dir / "state.json"

    def _load(self) -> dict[str, Any]:
        _require(self.state_dir.is_dir() and not self.state_dir.is_symlink(), "TASK_NOT_INITIALIZED", f"任务状态未初始化：{self.state_dir}")
        data = _read_json(self.state_path)
        self._validate_state(data)
        return data

    @staticmethod
    def _validate_state(data: dict[str, Any]) -> None:
        _require(data.get("schema_version") == STATE_SCHEMA_VERSION and data.get("flow_version") == FLOW_VERSION,
                 "UNSUPPORTED_TASK_VERSION", "只支持本版本新任务及同版本恢复；请用该任务原版本流程继续。不要覆盖、删除旧状态或拼接旧轨迹，本工具不提供跨版本升级。")
        effective_policy(data)
        _require(isinstance(data.get("task_id"), str) and bool(TASK_ID_RE.fullmatch(data["task_id"])), "INVALID_STATE", "task_id 不合法")
        stages = data.get("stages")
        _require(isinstance(stages, dict) and set(stages) == set(STAGE_IDS), "INVALID_STATE", "任务状态须恰好包含六阶段")
        for stage_id in STAGE_IDS:
            item = stages[stage_id]
            _require(isinstance(item, dict) and item.get("status") in STAGE_STATUSES and isinstance(item.get("evidence"), list), "INVALID_STATE", f"阶段 {stage_id} 状态或证据字段不合法")
            substeps = item.get("substeps")
            _require(isinstance(substeps, dict) and set(substeps) == set(SUBSTEP_IDS[stage_id]), "INVALID_STATE", f"阶段 {stage_id} 子步骤缺失或多余")
            for substep_id in SUBSTEP_IDS[stage_id]:
                substep = substeps[substep_id]
                _require(isinstance(substep, dict) and set(substep) == {"status", "inputs", "outputs", "evidence", "reviewer", "depends_on", "rule_ids", "history", "due_stage"}, "INVALID_STATE", f"子步骤 {substep_id} 字段不合法")
                _require(substep["status"] in STAGE_STATUSES | {"awaiting_evidence"}, "INVALID_STATE", f"子步骤 {substep_id} 状态不合法")
                _require(all(isinstance(substep[key], list) and all(isinstance(value, str) for value in substep[key]) for key in ("inputs", "outputs", "evidence", "depends_on", "rule_ids")), "INVALID_STATE", f"子步骤 {substep_id} 引用列表不合法")
                _require(substep["reviewer"] is None or isinstance(substep["reviewer"], str), "INVALID_STATE", f"子步骤 {substep_id} 审查责任不合法")
                _require(isinstance(substep["history"], list), "INVALID_STATE", f"子步骤 {substep_id} 历史不合法")
                _require(substep["due_stage"] is None or substep["due_stage"] in STAGE_IDS, "INVALID_STATE", f"子步骤 {substep_id} 证据截止阶段不合法")
                _require(substep["status"] != "awaiting_evidence" or substep["due_stage"] is not None, "INVALID_STATE", f"子步骤 {substep_id} 待后续证据未给截止阶段")
            _require(item["status"] != "passed" or all(substep["status"] == "passed" for substep in substeps.values()), "INVALID_STATE", f"阶段 {stage_id} 通过但子步骤未全部通过")
        current = data.get("current_stage")
        _require(current in STAGE_IDS or current is None, "INVALID_STATE", "current_stage 必须是 1–6 或 null")
        if current is None:
            _require(all(stages[stage]["status"] == "passed" for stage in STAGE_IDS), "INVALID_STATE", "current_stage=null 但仍有未通过阶段")
        else:
            for stage_id in STAGE_IDS[: int(current) - 1]:
                _require(stages[stage_id]["status"] == "passed", "INVALID_STATE", f"阶段 {stage_id} 未通过却进入阶段 {current}")
        for stage_id in STAGE_IDS[int(current) :] if current is not None else ():
            _require(stages[stage_id]["status"] != "passed", "INVALID_STATE", f"未来阶段 {stage_id} 不能已通过")
        config = data.get("task_config")
        _require(isinstance(config, dict) and config.get("schema_version") == 1 and config.get("task_id") == data["task_id"], "INVALID_STATE", "题目配置 schema 或 task_id 不一致")
        _require(set(config) == {"schema_version", "task_id", "task_type", "adapter"}, "INVALID_STATE", "题目配置含未知字段；不得在状态中放密钥")
        _require(config.get("task_type") in {"undetermined", "S1", "S2", "S3"}, "INVALID_STATE", "task_type 不合法")
        adapter = config.get("adapter")
        _require(isinstance(adapter, dict) and set(adapter) == {"kind", "entrypoint"} and adapter.get("kind") in {"unconfigured", "command-v1"}, "INVALID_STATE", "题目适配合同不合法")
        _require(adapter["kind"] != "unconfigured" or adapter.get("entrypoint") is None, "INVALID_STATE", "未配置适配入口时 entrypoint 必须为空")
        if adapter["kind"] == "command-v1":
            entrypoint = adapter.get("entrypoint")
            _require(isinstance(entrypoint, str) and entrypoint and "\\" not in entrypoint, "INVALID_STATE", "适配入口必须为任务内相对路径")
            entry_path = Path(entrypoint)
            _require(not entry_path.is_absolute() and all(part not in {"", ".", ".."} for part in entry_path.parts), "INVALID_STATE", "适配入口不得越出任务目录")
        _require(isinstance(data.get("exceptions"), list) and isinstance(data.get("history"), list), "INVALID_STATE", "exceptions/history 必须是列表")
        for exception in data["exceptions"]:
            _require(isinstance(exception, dict) and set(exception) == {"notice_text", "recorded_at", "scope", "affected_rule_ids", "decision"}, "INVALID_STATE", "例外记录字段不完整或有额外字段")
            _require(all(isinstance(exception[key], str) and exception[key] for key in ("notice_text", "recorded_at", "scope", "decision")) and isinstance(exception["affected_rule_ids"], list), "INVALID_STATE", "例外记录缺原话、时间、范围、规则或处理结论")
        lock = data.get("rules_lock")
        _require(isinstance(lock, dict) and isinstance(lock.get("sources"), list) and isinstance(lock.get("bundled_files"), list) and isinstance(lock.get("rule_fingerprints"), dict) and isinstance(lock.get("rule_stages"), dict) and isinstance(lock.get("rule_source_refs"), dict), "INVALID_STATE", "规则来源锁缺失")
        _require(isinstance(lock.get("catalog_path"), str) and isinstance(lock.get("manifest_path"), str) and bool(SHA256_RE.fullmatch(str(lock.get("catalog_sha256", "")))) and bool(SHA256_RE.fullmatch(str(lock.get("manifest_sha256", "")))), "INVALID_STATE", "规则来源锁哈希非法")

    def initialize(self, registry: Registry, task_id: str) -> dict[str, Any]:
        _require(isinstance(task_id, str) and bool(TASK_ID_RE.fullmatch(task_id)), "INVALID_TASK_ID", "task_id 仅允许字母、数字、点、下划线和连字符，首字符须为字母或数字")
        legacy_state = self.task_root / ".autoresearch"
        _require(not legacy_state.exists() and not legacy_state.is_symlink(), "LEGACY_STATE_PRESENT", "发现旧流程 .autoresearch；请使用原流程恢复，不迁移或混用旧状态")
        _require(not self.state_dir.exists() and not self.state_dir.is_symlink(), "ALREADY_INITIALIZED", f"新流程状态已存在，不覆盖：{self.state_dir}")
        issues = registry.check_sources()
        _require(not issues, "REGISTRY_DRIFT", "中央规则来源与锁定哈希不符，先修复规则包：" + "; ".join(issue["path"] for issue in issues))
        data: dict[str, Any] = {
            "schema_version": STATE_SCHEMA_VERSION,
            "flow_version": FLOW_VERSION,
            "task_id": task_id,
            "created_at": _utc_now(),
            "current_stage": "1",
            "stages": {
                stage: {
                    "status": "pending",
                    "evidence": [],
                    "substeps": {
                        substep: {
                            "status": "pending", "inputs": [], "outputs": [], "evidence": [],
                            "reviewer": None, "depends_on": [], "rule_ids": [], "history": [],
                            "due_stage": None,
                        }
                        for substep in SUBSTEP_IDS[stage]
                    },
                }
                for stage in STAGE_IDS
            },
            "task_config": {"schema_version": 1, "task_id": task_id, "task_type": "undetermined", "adapter": {"kind": "unconfigured", "entrypoint": None}},
            "workflow_policy": new_policy(),
            "rules_lock": registry.lock_snapshot(),
            "exceptions": [],
            "history": [],
        }
        self.state_dir.mkdir()
        _atomic_json(self.state_path, data)
        return data

    def check(self) -> dict[str, Any]:
        data = self._load()
        lock = data["rules_lock"]
        entries = [
            {"path": lock["manifest_path"], "sha256": lock["manifest_sha256"]},
            {"path": lock["catalog_path"], "sha256": lock["catalog_sha256"]},
            *lock["sources"],
            *lock["bundled_files"],
        ]
        issues = _source_issues(self.repository_root, entries, "INVALID_STATE")
        return {
            "task_id": data["task_id"],
            "current_stage": data["current_stage"],
            "stage_statuses": {stage: data["stages"][stage]["status"] for stage in STAGE_IDS},
            "substep_statuses": {stage: {key: value["status"] for key, value in data["stages"][stage]["substeps"].items()} for stage in STAGE_IDS},
            "issues": issues,
            **{key: value for key, value in policy_status(data).items() if key != "status"},
        }
