"""Six-stage orchestration: durable decisions, live gates and resumable handoff.

Research judgments are attributed to the expert; machine gates consume W2–W4.
This module does not launch training, model calls, or independent QA.
"""
from __future__ import annotations

import fcntl
import re
from contextlib import contextmanager
from pathlib import Path

from .core import (FlowError, Registry, TaskStore, STAGE_IDS, SUBSTEP_IDS, _atomic_json,
                   _canonical_digest, _read_json, _require, _sha256, _utc_now)
from .experiments import ExperimentBook, baseline_check, evidence, score_check
from .runtime import Runtime, TRACKS
from .w4_evidence import DeliveryEvidence
from .w4_package import check_package
from .qa_contract import validate_qa_report
from .pca_contract import check_task, check_execution_receipt, check_stability
from .policies import effective_policy
from .task_git import TaskGit


LABELS = {
    "1": ("锁定来源与题目输入", "审优化面与非纯调参空间", "核可行性和候选原则", "GO/NO-GO"),
    "2": ("构建环境并冒烟", "记录探索", "预先锁定正式协议", "Baseline 正式运行", "Baseline 审查和冻结"),
    "3": ("实现 Reference", "成对正式重复", "关闭跨方法审查", "核评分合同", "Reference/评分同时冻结"),
    "4": ("双路预检及预算确认", "独立启动与计时", "迭代和原会话恢复", "双轨有效性审阅"),
    "5": ("选唯一合法最佳方法", "同协议正式复验", "干净快照重跑", "绑定最终方法和结论"),
    "6": ("组装最小包", "包内格式检查", "独立会话 QA", "返修与独立复检", "本地备齐交付"),
}
REVIEW_REQUIREMENTS = {
    "1.2": {"AR-002": "结合题面、允许修改范围及已有代码审查方法空间；仅宣称允许算法修改不足以通过"},
    "1.3": {"AR-003": "说明 Starter/Baseline/Reference 候选依据；此时只确认方向，不提前冻结未经验证的锚点"},
    "2.2": {"AR-002": "结合已实现接口与实际可修改代码复核优化面，不只复述阶段 1 的设计声明"},
}


def _text(value, name):
    _require(isinstance(value, str) and value.strip(), "INVALID_STAGE_RECORD", f"须填写 {name}")
    return value


class StageFlow:
    def __init__(self, task_root: Path):
        self.store = TaskStore(Path(task_root))
        self.root = self.store.task_root

    @contextmanager
    def _edit(self):
        self.store._load()
        with (self.store.state_dir / "stages.lock").open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            _require(not self.store.check()["issues"], "SOURCE_DRIFT", "先核对并恢复任务锁定的权威原件")
            state = self.store._load()
            yield state
            self.store._validate_state(state)
            _atomic_json(self.store.state_path, state)

    def _step(self, state, step):
        _require(isinstance(step, str) and step.split(".")[0] in SUBSTEP_IDS
                 and step in SUBSTEP_IDS[step.split(".")[0]], "INVALID_STEP", "子步骤须为 1.1–6.5 内的有效编号")
        return state["stages"][step.split(".")[0]]["substeps"][step]

    def _check_refs(self, value):
        if isinstance(value, dict):
            if set(value) == {"path", "sha256"}:
                evidence(self.root, value)
            else:
                for item in value.values():
                    self._check_refs(item)
        elif isinstance(value, list):
            for item in value:
                self._check_refs(item)

    def _receipt(self, state, step):
        substep = self._step(state, step)
        records = [r for r in substep["history"] if r.get("action") == "record"]
        _require(records, "MISSING_STEP_RECORD", f"{step} 没有可核登记记录")
        ref = records[-1]["receipt"]
        record = _read_json(evidence(self.root, ref))
        _require(record["rules_lock_sha256"] == _canonical_digest(state["rules_lock"]),
                 "STALE_STEP_RECORD", f"{step} 记录使用旧规则锁，须重验")
        self._check_refs(record["spec"])
        self._check_refs(record["gate"])
        return record

    def _package(self, checks):
        value = checks.get("package_root")
        _text(value, "package_root")
        path = Path(value)
        _require(not path.is_absolute() and ".." not in path.parts, "INVALID_PATH", "package_root 须为任务内相对目录")
        target = (self.root / path).resolve()
        _require(target.is_relative_to(self.root), "INVALID_PATH", "提交包越出任务根")
        return check_package(target)

    def _approval(self, ref, expected):
        value = _read_json(evidence(self.root, ref))
        _text(value.get("approved_by"), "approved_by")
        _text(value.get("decision"), "decision")
        _require(value.get("approved") is True and value.get("scope") == expected and isinstance(value.get("evidence"), list)
                 and value["evidence"], "CONFIRMATION_MISSING", f"缺少范围为 {expected} 的用户确认及引用")
        self._check_refs(value)
        return {"scope": expected, "approved_by": value["approved_by"], "sha256": ref["sha256"]}

    @staticmethod
    def _qa_coverage(report, dispositions):
        reported = {}
        def collect(value):
            if isinstance(value, dict):
                identifier = value.get("id", value.get("check_id"))
                if isinstance(identifier, str) and re.fullmatch(r"(?:QA|B|G|H)\d{2}", identifier):
                    reported.setdefault(identifier, set()).add(value.get("status"))
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(report)
        _require(reported, "QA_REPORT_SCHEMA", "独立报告未提供可识别检查项，须核其格式")
        actual = [d.get("id") for d in dispositions]
        _require(len(actual) == len(set(actual)) and set(reported) <= set(actual),
                 "QA_REVIEW_INCOMPLETE", "逐项处置遗漏独立报告检查项或存在重复")
        for item in dispositions:
            if item.get("status") == "pass":
                _require(item["id"] in reported
                         and reported[item["id"]] <= {"pass", "passed", "通过"},
                         "QA_UNRESOLVED", "不得把独立报告的未通过项手动改写为通过；返修后重新独立质检")
            if item.get("status") in {"skip", "not_applicable"}:
                allowed = {"QA15"} if item["status"] == "skip" else {"QA04", "QA15", "QA19", "H05", "H06"}
                _require(item["id"] in allowed and item["id"] in reported
                         and reported[item["id"]] == {"not_applicable"},
                         "QA_UNRESOLVED", "不适用须与当前 Skill 及独立报告一致")
            _require(item.get("status") in {"pass", "skip", "not_applicable"},
                     "QA_UNRESOLVED", "旧口头例外或 platform_only 不能关闭适用 QA 项")

    def _statistical_review(self, book, protocol, checks):
        """3σ–5σ is conditional, not an invented universal 5σ release threshold."""
        report = book.report(protocol)
        _require(report["status"] == "needs_review" and report.get("seed_extensions"),
                 "STATISTICAL_REVIEW_REQUIRED", "3σ–5σ 时须先追加正式 seed 并完成两侧结果")
        ref = checks.get("statistical_review")
        value = _read_json(evidence(self.root, ref))
        _require(value.get("protocol_sha256") == report["protocol_sha256"]
                 and value.get("experiment_sha256") == report["experiment_sha256"]
                 and value.get("platform_review_required") is True,
                 "STATISTICAL_REVIEW_REQUIRED", "统计复核须绑定补充后的实际结果并标记平台复核")
        _text(value.get("reviewer"), "统计复核责任人")
        _text(value.get("rationale"), "追加重复后仍在 3σ–5σ 的解释")
        _require(isinstance(value.get("evidence"), list) and value["evidence"],
                 "STATISTICAL_REVIEW_REQUIRED", "缺少统计复核引用")
        self._check_refs(value)
        return {"status": "conditional_platform_review", "source": ref}

    def _gate(self, step, checks):
        """Recompute just the module gate relevant to this step (no expensive actions)."""
        _require(isinstance(checks, dict), "INVALID_STAGE_RECORD", "checks 须为对象")
        book = ExperimentBook(self.root)
        protocol = checks.get("protocol_id")
        if step == "1.1" and effective_policy(self.store._load())["git_required"]:
            result = TaskGit(self.root).status()
            _require(result["ready"], "GIT_NOT_READY",
                     "阶段 1.1 须完成 Git 范围确认及首个真实检查点；先执行 task git-status")
            return result
        if step == "2.1":
            return check_execution_receipt(self.root,
                _read_json(evidence(self.root, checks.get("harbor_execution"))), self._harbor_path(checks))
        if step in {"2.3", "2.4", "2.5", "3.2", "3.3", "3.4", "3.5", "5.2"}:
            _text(protocol, "protocol_id")
        if step == "2.3":
            data = book._load()
            _require(protocol in data["protocols"], "PROTOCOL_MISSING", "先执行 experiment lock")
            return {"status": "locked", "protocol_sha256": data["protocols"][protocol]["sha256"]}
        if step in {"2.4", "3.2", "5.2"}:
            roles = ("baseline",) if step == "2.4" else ("best_method",) if step == "5.2" else ("baseline", "reference")
            result = book.report(protocol, roles)
            _require(result["status"] in {"ok", "needs_review"}, "STAGE_GATE_BLOCKED", "; ".join(result["issues"]))
            return result
        if step in {"2.5", "3.3", "3.5"}:
            review = _read_json(evidence(self.root, checks.get("baseline_review")))
            result = baseline_check(book, protocol, review, 2 if step == "2.5" else 3)
            if result["status"] != "ready_for_expert_confirmation":
                report = book.report(protocol)
                _require(step != "2.5" and report["status"] == "needs_review"
                         and result["issues"] == report["issues"],
                         "STAGE_GATE_BLOCKED", "; ".join(result["issues"]))
                result["statistical_review"] = self._statistical_review(book, protocol, checks)
                result["status"] = "conditional_platform_review"
            if step != "3.5":
                return result
        if step in {"3.4", "3.5"}:
            contract = _read_json(evidence(self.root, checks.get("score_contract")))
            result = score_check(book, protocol, contract)
            if result["status"] == "needs_review":
                result["statistical_review"] = self._statistical_review(book, protocol, checks)
                result["status"] = "conditional_platform_review"
            else:
                _require(result["status"] == "ok", "STAGE_GATE_BLOCKED", "; ".join(result["issues"]))
            if step == "3.5":
                result["harbor_execution"] = check_execution_receipt(self.root,
                    _read_json(evidence(self.root, checks.get("harbor_execution"))),
                    self._harbor_path(checks), frozen_scoring=True,
                    score_contract_sha256=_canonical_digest(contract))
            return result
        if step == "4.1":
            from .duration import snapshot as duration_snapshot
            duration = duration_snapshot(self.root)
            execution = check_execution_receipt(self.root,
                _read_json(evidence(self.root, checks.get("harbor_execution"))), self._harbor_path(checks))
            statuses = {t: Runtime(self.root).status(t) for t in TRACKS}
            _require(all(s["preflight"] and s["preflight"]["ready"] for s in statuses.values()),
                     "PREFLIGHT_REQUIRED", "两组都须完成当前配置的真实 Public/Dev 预检")
            return {"tracks": statuses, "harbor_execution": execution, "duration_snapshot": duration,
                    "approval": self._approval(checks.get("approval"), "stage-4-start")}
        if step == "4.4":
            delivery = DeliveryEvidence(self.root)
            for track in TRACKS:
                delivery._runtime(track)
                delivery.current_review(track)
            statuses = {t: Runtime(self.root).status(t) for t in TRACKS}
            _require(len({v["thread_id"] for v in statuses.values()}) == 2, "TRAJECTORY_INDEPENDENCE", "双轨须为不同会话")
            return {"status": "reviewed", "tracks": statuses}
        if step == "5.1":
            _, decision = DeliveryEvidence(self.root).current_best()
            return {"selected_track": decision["selected_track"], "method_files": decision["snapshot_files"]}
        if step in {"5.3", "5.4"}:
            return DeliveryEvidence(self.root).best_verification()
        if step.startswith("6."):
            result = self._package(checks)
            if step == "6.5":
                # Final evidence must be contained in the final package, not rescued from working files.
                package = Path(result["package_path"])
                receipt_path = evidence(self.root, checks.get("harbor_execution"))
                _require(receipt_path.is_relative_to(package),
                         "PACKAGE_EVIDENCE_BOUNDARY", "交付阶段只接受最终包内实跑记录")
                result["harbor_execution"] = check_execution_receipt(package,
                    _read_json(receipt_path),
                    package / "workspace/harbor_task", final=True,
                    score_contract_sha256=_canonical_digest(_read_json(package / "expert_evidence/expert_annotation.json")["score_contract"]),
                    best_method=package / "expert_evidence/best_method")
                stability_required = effective_policy(self.store._load())["require_stability_receipt"]
                result["stability"] = {"status": "not_run", "required": False}
                if stability_required or "stability" in checks:
                    stability_path = evidence(self.root, checks.get("stability"))
                    _require(stability_path.is_relative_to(package), "PACKAGE_EVIDENCE_BOUNDARY",
                             "提交的稳定性记录也须在最终包内，不得越界取证")
                    result["stability"] = check_stability(package,
                        _read_json(stability_path), expected_image=result["harbor_execution"]["agent_image"])
                    result["stability"]["required"] = stability_required
            if step in {"6.3", "6.4", "6.5"}:
                pointer = _read_json(self.store.state_dir / "delivery" / "qa_binding_current.json")
                _require(pointer["package_sha256"] == result["package_sha256"], "QA_PACKAGE_DRIFT", "QA 绑定不是当前包")
                path = self.store.state_dir / "delivery" / "qa" / pointer["package_sha256"] / "reports" / (pointer["report_sha256"] + ".json")
                _require(path.is_file() and _sha256(path) == pointer["binding_sha256"], "QA_REPORT_DRIFT", "QA 绑定被改动")
                binding = _read_json(path)
                report = Path(binding["report_path"])
                _require(report.is_file() and _sha256(report) == binding["report_sha256"], "QA_REPORT_DRIFT", "独立报告被改动")
                qa = _read_json(report)
                validate_qa_report(qa, require_pass=step in {"6.4", "6.5"})
                result["report_sha256"] = binding["report_sha256"]
                if step in {"6.4", "6.5"}:
                    review = _read_json(evidence(self.root, checks.get("qa_review")))
                    _require(review.get("package_sha256") == result["package_sha256"]
                             and review.get("report_sha256") == result["report_sha256"]
                             and review.get("unresolved_local_items") == [], "QA_UNRESOLVED", "QA 尚有本地问题或审阅未绑定当前包/报告")
                    _text(review.get("reviewer"), "reviewer")
                    _text(review.get("conclusion"), "conclusion")
                    _require(isinstance(review.get("dispositions"), list) and review["dispositions"],
                             "QA_UNRESOLVED", "须逐项记录独立报告的结论/处置")
                    for item in review["dispositions"]:
                        _require(isinstance(item, dict) and item.get("status") in {"pass", "not_applicable", "skip"},
                                 "QA_UNRESOLVED", "每项处置须与新版 Skill 报告的通过或不适用一致")
                        _text(item.get("id"), "QA 检查项编号")
                        _text(item.get("rationale"), "QA 处置理由")
                    self._qa_coverage(_read_json(report), review["dispositions"])
                    result["qa_review_sha256"] = checks["qa_review"]["sha256"]
            if step == "6.5":
                from .w4_package import DeliveryPackage
                result.update(DeliveryPackage(self.root).delivery_state(result))
            return result
        return {"status": "not_applicable", "note": "本步骤无额外机器门禁；不代表科研审查通过"}

    def _reviews(self, step, spec):
        """Validate attributed decisions, not the truth of scientific reasoning."""
        required = REVIEW_REQUIREMENTS.get(step, {})
        if not required:
            return {"status": "handled_by_module" if step in {"2.5", "3.3", "3.5"}
                    else "not_required", "scientific_conclusion_certified": False}
        reviews = spec.get("reviews", [])
        _require(isinstance(reviews, list) and all(isinstance(r, dict) for r in reviews),
                 "INVALID_STAGE_RECORD", "reviews 须为审查记录数组")
        ids = [r.get("rule_id") for r in reviews]
        _require(len(ids) == len(set(ids)) and set(ids) == set(required),
                 "SCIENTIFIC_REVIEW_REQUIRED", "须逐项完成当前实质审查：" + ", ".join(required))
        for review in reviews:
            _text(review.get("rationale"), "实质审查结论及理由")
            _require(isinstance(review.get("evidence"), list) and review["evidence"],
                     "SCIENTIFIC_REVIEW_REQUIRED", "审查不能仅凭声明，须引用实际题面、接口、代码或研究证据")
            for ref in review["evidence"]:
                evidence(self.root, ref)
            _require(review.get("status") == "pass" and review.get("unresolved") == [],
                     "SCIENTIFIC_REVIEW_REQUIRED", "尚待补证或未决的实质审查不能通过；记录待补证并保留到期阶段")
        return {"status": "recorded", "reviews": reviews, "scientific_conclusion_certified": False}

    def _resolve_checks(self, state, step, supplied):
        """Reuse explicit, still-valid earlier inputs; never invent file locations."""
        _require(isinstance(supplied, dict), "INVALID_STAGE_RECORD", "checks 须为对象")
        checks = dict(supplied)
        needed = set(self.template(step)["spec"]["checks"]) - {"approval", "stability"}
        if step in {"3.3", "3.4", "3.5"}:
            needed.add("statistical_review")
        ordered = [s for steps in SUBSTEP_IDS.values() for s in steps]
        for earlier in reversed(ordered[:ordered.index(step)]):
            if needed <= checks.keys():
                break
            if self._step(state, earlier)["status"] != "passed":
                continue
            record = self._receipt(state, earlier)
            for key, value in record["spec"].get("checks", {}).items():
                if key in needed and key not in checks:
                    checks[key] = value
        return checks

    def check(self, step, spec=None):
        """Read-only check of existing facts; does not record or approve a step."""
        state = self.store._load()
        sub = self._step(state, step)
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "先恢复任务锁定的权威原件")
        if spec is None:
            spec = self._receipt(state, step)["spec"] if sub["status"] == "passed" else {"step": step}
        _require(isinstance(spec, dict) and spec.get("step", step) == step,
                 "INVALID_STAGE_RECORD", "检查输入须对应指定子步骤")
        issues = []
        checks = {}
        try:
            self._check_refs(spec)
            checks = self._resolve_checks(state, step, spec.get("checks", {}))
            result = self._gate(step, checks)
            machine = {"status": "passed", "result": result}
        except FlowError as exc:
            machine = {"status": "blocked", "code": exc.code, "message": exc.message}
            issues.append({"code": exc.code, "message": exc.message})
        try:
            semantic = self._reviews(step, spec)
        except FlowError as exc:
            semantic = {"status": "awaiting_evidence", "code": exc.code, "message": exc.message}
            issues.append({"code": exc.code, "message": exc.message})
        return {"status": "blocked" if issues else "checked", "step": step,
                "machine_check": machine, "semantic_review": semantic, "issues": issues,
                "resolved_checks": checks,
                "scientific_conclusion_certified": False,
                "next_action": "完成实质审查和实际工作后再登记；检查本身不推进状态"}

    def _harbor_path(self, checks):
        value = checks.get("harbor_task")
        _text(value, "harbor_task")
        path = Path(value)
        _require(not path.is_absolute() and ".." not in path.parts
                 and (self.root / path).resolve().is_relative_to(self.root),
                 "INVALID_PATH", "harbor_task 须为题目内相对目录")
        return self.root / path

    def template(self, step):
        state = self.store._load()
        self._step(state, step)
        stage = step.split(".")[0]
        checks = {}
        if step in {"2.1", "3.5", "4.1"}:
            checks["harbor_task"] = "workspace/harbor_task"
        if step in {"2.1", "3.5", "4.1", "6.5"}:
            checks["harbor_execution"] = {"path": "<任务内真实 Harbor 记录 JSON；6.5 须位于最终包内>", "sha256": "<SHA-256>"}
        if step == "6.5" and effective_policy(state)["require_stability_receipt"]:
            checks["stability"] = {"path": "<任务内最终包中的 12h 稳定性记录 JSON>", "sha256": "<SHA-256>"}
        if step in {"2.3", "2.4", "2.5", "3.2", "3.3", "3.4", "3.5", "5.2"}:
            checks["protocol_id"] = "<正式协议 ID>"
        if step in {"2.5", "3.3", "3.5"}:
            checks["baseline_review"] = {"path": "<B01–B08 审阅 JSON>", "sha256": "<SHA-256>"}
        if step in {"3.4", "3.5"}:
            checks["score_contract"] = {"path": "<评分合同 JSON>", "sha256": "<SHA-256>"}
        if step == "4.1":
            checks["approval"] = {"path": "<双轨预算批准 JSON>", "sha256": "<SHA-256>"}
        if stage == "6":
            checks["package_root"] = "<任务内最终包目录>"
            if step in {"6.4", "6.5"}:
                checks["qa_review"] = {"path": "<独立报告逐项处置 JSON>", "sha256": "<SHA-256>"}
        reviews = [{"rule_id": rule, "status": "awaiting_evidence", "rationale": hint,
                    "evidence": [], "unresolved": ["<实际未决事项，解决后清空>"], "due_stage": int(stage)}
                   for rule, hint in REVIEW_REQUIREMENTS.get(step, {}).items()]
        return {"status": "template", "spec": {"step": step, "status": "passed", "reviewer": "<专家>",
                "summary": "<实际完成的工作和结论>", "inputs": [], "outputs": [],
                "evidence": [{"path": "<任务内证据相对路径>", "sha256": "<SHA-256>"}], "checks": checks,
                **({"reviews": reviews} if reviews else {})}}

    def status(self):
        checked = self.store.check()
        state = self.store._load()
        issues = list(checked["issues"])
        for stage, item in state["stages"].items():
            for step, sub in item["substeps"].items():
                if sub["status"] == "passed":
                    try:
                        self._receipt(state, step)
                    except FlowError as exc:
                        issues.append({"code": exc.code, "step": step, "message": exc.message})
        for stage, item in state["stages"].items():
            completed = [h for h in state["history"] if h.get("action") == "stage_finish" and h.get("stage") == stage]
            if item["status"] == "passed" and completed:
                try:
                    self._check_refs(completed[-1]["spec"])
                    if stage == "6":
                        last = self._receipt(state, "6.5")
                        checked_package = self._gate("6.5", last["spec"]["checks"])
                        _require(checked_package["package_sha256"] == last["gate"]["package_sha256"],
                                 "QA_PACKAGE_DRIFT", "已完成交付包发生变化")
                except FlowError as exc:
                    issues.append({"code": exc.code, "stage": stage, "message": exc.message})
        current = state["current_stage"]
        next_step = next((s for s, v in state["stages"][current]["substeps"].items() if v["status"] != "passed"), None) if current else None
        rows = Registry(self.store.repository_root).show(step=next_step)["rules"] if next_step and not checked["issues"] else []
        rules = [r["id"] for r in rows]
        prepare = [{"rule_id": r["id"], "evidence": r["evidence"], "due_at": r["timing"]["due_at"],
                    "applicability": r["applicability"]} for r in rows if r["timing"]["inform_at"] == next_step]
        pending = []
        for item in state["stages"].values():
            for sub in item["substeps"].values():
                records = [r for r in sub["history"] if r.get("action") == "record"]
                if records and sub["status"] == "passed":
                    try:
                        record = _read_json(evidence(self.root, records[-1]["receipt"]))
                        for name in record["gate"].get("deferred", []):
                            if state["stages"]["3"]["status"] != "passed":
                                pending.append({"check": name, "due_stage": 3})
                    except FlowError:
                        pass  # Already reported above; no silent success.
        git_setup = next_step == "1.1" and effective_policy(state)["git_required"]
        return {"status": "blocked" if issues else "ready", "task_id": state["task_id"],
                "current_stage": current, "stage_statuses": checked["stage_statuses"],
                "next_step": next_step, "next_step_label": LABELS[current][int(next_step.split(".")[1])-1] if next_step else None,
                "next_action": "先处理证据/来源漂移，必要时 stage reopen" if issues else
                    "先 task git-status / git-setup / git-preview / git-checkpoint，再登记 1.1 的来源与输入" if git_setup else
                    f"rules show --step {next_step}；stage check --step {next_step}；完成实际工作和实质审查后 stage record" if next_step else
                    f"stage finish --stage {current}，重核证据并登记结论及必要确认" if current else "本地备齐；等待平台反馈",
                "rule_ids": rules, "required_rules": [{key: r[key] for key in ("id", "timing", "applicability", "source_refs")}
                                                        for r in rows],
                "prepare_evidence": prepare,
                "semantic_review_requirements": [{"rule_id": key, "guidance": value}
                                                 for key, value in REVIEW_REQUIREMENTS.get(next_step, {}).items()],
                "scientific_conclusion_certified": False,
                "pending_cross_method_checks": pending, "issues": issues}

    def record(self, spec):
        _require(isinstance(spec, dict), "INVALID_STAGE_RECORD", "登记须为 JSON 对象")
        step = spec.get("step")
        with self._edit() as state:
            sub = self._step(state, step)
            stage = step.split(".")[0]
            _require(state["current_stage"] == stage, "STAGE_ORDER", "只能登记当前阶段；返修先显式 reopen")
            earlier = SUBSTEP_IDS[stage][:SUBSTEP_IDS[stage].index(step)]
            _require(all(state["stages"][stage]["substeps"][s]["status"] == "passed" for s in earlier),
                     "STEP_ORDER", "须先完成本阶段前置子步骤")
            _require(sub["status"] != "passed", "STEP_FROZEN", "已通过记录不可覆盖；返修先 reopen")
            _require(spec.get("status") in {"in_progress", "passed", "failed", "awaiting_evidence"},
                     "INVALID_STAGE_RECORD", "记录状态非法")
            _text(spec.get("reviewer"), "reviewer")
            _text(spec.get("summary"), "summary")
            refs = spec.get("evidence")
            _require(isinstance(refs, list) and refs, "MISSING_EVIDENCE", "阶段记录须有证据引用")
            for key in ("inputs", "outputs", "evidence"):
                _require(isinstance(spec.get(key, []), list), "INVALID_STAGE_RECORD", f"{key} 须为引用数组")
                for ref in spec.get(key, []):
                    evidence(self.root, ref)
            if spec["status"] == "awaiting_evidence":
                _require(str(spec.get("due_stage")) == stage, "INVALID_DEFERRAL",
                         "整个未完成子步骤不能跨阶段通过；B03/B07 跨方法部分由 baseline-check 专门登记")
            self._check_refs(spec)
            spec = {**spec, "checks": self._resolve_checks(state, step, spec.get("checks", {}))}
            gate = self._gate(step, spec.get("checks", {})) if spec["status"] == "passed" else {"status": spec["status"]}
            if step == "6.5" and spec["status"] == "passed":
                _require(gate.get("delivery_phase") == "form_ready", "DELIVERY_INCOMPLETE",
                         "先完成独立 QA、三包核验及填表文件，再登记 6.5 完成")
            semantic = self._reviews(step, spec) if spec["status"] == "passed" else {"status": "awaiting_evidence"}
            record = {"schema_version": 1, "rules_lock_sha256": _canonical_digest(state["rules_lock"]),
                      "spec": spec, "gate": gate, "semantic_review": semantic, "at": _utc_now()}
            directory = self.store.state_dir / "stage_records"
            directory.mkdir(exist_ok=True)
            path = directory / (step + "-" + _canonical_digest(record) + ".json")
            _atomic_json(path, record)
            ref = {"path": str(path.relative_to(self.root)), "sha256": _sha256(path)}
            sub.update(status=spec["status"], reviewer=spec["reviewer"], evidence=[ref["path"]],
                       inputs=[r["path"] for r in spec.get("inputs", [])], outputs=[r["path"] for r in spec.get("outputs", [])],
                       depends_on=list(earlier), rule_ids=[r["id"] for r in Registry(self.store.repository_root).show(step=step)["rules"]],
                       due_stage=stage if spec["status"] == "awaiting_evidence" else None)
            sub["history"].append({"action": "record", "at": _utc_now(), "receipt": ref})
            state["stages"][stage]["status"] = "failed" if spec["status"] == "failed" else "in_progress"
            state["history"].append({"action": "stage_record", "step": step, "receipt": ref, "at": _utc_now()})
        return {"status": "failed" if spec["status"] == "failed" else "recorded", "step": step,
                "step_status": spec["status"], "receipt": ref, "gate": gate,
                "semantic_review": semantic, "scientific_conclusion_certified": False}

    def finish(self, stage, spec):
        with self._edit() as state:
            _require(stage == state["current_stage"], "STAGE_ORDER", "只能完成当前阶段")
            _require(all(s["status"] == "passed" for s in state["stages"][stage]["substeps"].values()),
                     "STAGE_INCOMPLETE", "本阶段仍有未通过子步骤")
            _text(spec.get("reviewer"), "reviewer")
            _text(spec.get("conclusion"), "conclusion")
            source = spec.get("source_review")
            if source is not None:
                _require(isinstance(source, dict), "INVALID_STAGE_RECORD", "原文疑义记录须为对象")
                _text(source.get("findings"), "实际发现的原文疑义/遗漏")
                _text(source.get("resolution"), "原文疑义/遗漏的处理依据")
                _require(isinstance(source.get("evidence"), list) and source["evidence"],
                         "MISSING_EVIDENCE", "原文疑义处置须有可核引用")
                for ref in source["evidence"]:
                    evidence(self.root, ref)
            approvals = self._approval(spec.get("approval"), "stage-" + stage) if stage in {"1", "2", "3", "6"} else None
            gates = {}
            for step in SUBSTEP_IDS[stage]:
                record = self._receipt(state, step)
                gates[step] = self._gate(step, record["spec"].get("checks", {}))
                self._reviews(step, record["spec"])
            if stage in {"2", "3"}:
                protocol_ids = {self._receipt(state, s)["spec"]["checks"]["protocol_id"]
                                for s in SUBSTEP_IDS[stage]
                                if s in {"2.3", "2.4", "2.5", "3.2", "3.3", "3.4", "3.5"}}
                _require(len(protocol_ids) == 1, "PROTOCOL_MISMATCH", "同阶段必须冻结同一个已执行协议")
                if stage == "3":
                    baseline_protocol = self._receipt(state, "2.5")["spec"]["checks"]["protocol_id"]
                    _require(protocol_ids == {baseline_protocol}, "PROTOCOL_MISMATCH",
                             "Reference 须使用已冻结 Baseline 的同一协议；变更须回退阶段 2")
                _require(state["task_config"]["task_type"] != "undetermined"
                         and state["task_config"]["adapter"]["kind"] == "command-v1",
                         "CONFIG_MISSING", "冻结 Baseline 前须 task configure 登记类型和已实现适配入口")
                configs = [e for e in state["history"] if e.get("action") == "task_configure"]
                _require(configs, "CONFIG_MISSING", "缺少题目适配登记")
                self._check_refs(configs[-1]["spec"])
            if stage == "6":
                _require(gates["6.5"].get("delivery_phase") == "form_ready", "DELIVERY_INCOMPLETE",
                         "交付产物尚未全部完成或绑定已过期")
                _require(len({g["package_sha256"] for g in gates.values()}) == 1,
                         "PACKAGE_VERSION_MISMATCH", "阶段 6 各步骤必须对应同一个最终包；返修后从 6.1 重验")
            state["stages"][stage]["status"] = "passed"
            state["history"].append({"action": "stage_finish", "stage": stage, "at": _utc_now(),
                                     "spec": spec, "gates": gates, "approval": approvals,
                                     "rules_lock_sha256": _canonical_digest(state["rules_lock"])})
            state["current_stage"] = str(int(stage)+1) if stage != "6" else None
        return {"status": "stage_completed", "stage": stage, "current_stage": state["current_stage"],
                "note": "专家本地阶段结论；不代表平台审核通过"}

    def reopen(self, step, spec):
        with self._edit() as state:
            self._step(state, step)
            _text(spec.get("reason"), "返修原因")
            _text(spec.get("reviewer"), "返修责任人")
            all_steps = [s for group in SUBSTEP_IDS.values() for s in group]
            start = all_steps.index(step)
            current = state["current_stage"]
            _require(current is None or int(step.split(".")[0]) <= int(current), "STAGE_ORDER", "不能跳到未来阶段返修")
            for key in all_steps[start:]:
                sub = self._step(state, key)
                if sub["status"] != "pending":
                    sub["status"] = "needs_recheck"
                    sub["history"].append({"action": "reopen", "reason": spec["reason"], "at": _utc_now()})
            first = step.split(".")[0]
            for stage in STAGE_IDS[int(first)-1:]:
                if state["stages"][stage]["status"] != "pending":
                    state["stages"][stage]["status"] = "needs_recheck"
            state["current_stage"] = first
            state["history"].append({"action": "stage_reopen", "step": step, "spec": spec, "at": _utc_now()})
        return {"status": "reopened", "step": step, "current_stage": first,
                "note": "保留历史与训练结果；只重验受影响结论，内容修订不自动要求重跑训练"}

    def configure(self, spec):
        with self._edit() as state:
            _require(state["current_stage"] in {"1", "2"}
                     and state["stages"]["2"]["substeps"]["2.1"]["status"] != "passed",
                     "CONFIG_FROZEN", "只能在环境验收前配置；后续变更先 stage reopen 2.1")
            _require(spec.get("task_type") in {"S1", "S2", "S3"}, "INVALID_TASK_CONFIG", "task_type 须为 S1/S2/S3")
            path = evidence(self.root, spec.get("adapter"))
            state["task_config"] = {"schema_version": 1, "task_id": state["task_id"], "task_type": spec["task_type"],
                                    "adapter": {"kind": "command-v1", "entrypoint": str(path.relative_to(self.root))}}
            state["history"].append({"action": "task_configure", "spec": spec, "at": _utc_now()})
        return {"status": "configured", "task_config": state["task_config"]}

    def reference(self, paths):
        self.store._load()
        refs = []
        for value in paths:
            path = Path(value)
            _require(not path.is_absolute() and ".." not in path.parts, "INVALID_PATH", "使用任务内相对文件路径")
            actual = self.root / path
            _require(actual.is_file() and not actual.is_symlink() and actual.resolve().is_relative_to(self.root),
                     "INVALID_PATH", "引用文件不存在、含符号链接或越界")
            refs.append({"path": str(path), "sha256": _sha256(actual)})
        return {"status": "referenced", "evidence": refs}
