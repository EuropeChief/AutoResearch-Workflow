"""Read-only stage preflight over existing evidence; no task state machine.

Reports are checked, not replayed. Semantic conclusions remain attributable
reviews. A missing file cannot turn into PASS merely by declaring a conclusion.
"""
from __future__ import annotations

import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from .common import FlowError, _canonical_digest, _read_json, _require, _sha256
from .stage_rules import StageRules
from .task_workspace import TaskWorkspace

SUCCESS = {"PASS", "PASSED", "OK", "COMPLETE", "FORMAT_CHECKED_NOT_QA",
           "NATIVE_TRIAL_VERIFIED", "EVIDENCE_CHECKED_NOT_INDEPENDENT_REPLAY"}
RESOLVED = {"PASS", "WAIVED", "NOT_APPLICABLE"}


class Preflight:
    def __init__(self, task_root: Path | str, *, rules: StageRules | None = None):
        candidate = Path(task_root)
        _require(candidate.is_dir() and not candidate.is_symlink(), "TASK_ROOT", "指定已有普通题目目录")
        self.root = candidate.resolve()
        self.rules = rules or StageRules()
        issues = self.rules.validate()
        _require(not issues, "RULE_MATRIX_INVALID", f"先修复流程包规则/视图：{issues}")
        self.version = _canonical_digest({"matrix": self.rules.load(),
            "rules_sha256": _sha256(self.rules.rules_path),
            "manifest_sha256": _sha256(self.rules.root / "rules/manifest.json")})
        self.by_id = {item["id"]: item for item in self.rules.obligations()}

    def _reference(self, value: Any) -> dict:
        ref = {"path": value} if isinstance(value, str) else value
        _require(isinstance(ref, dict) and isinstance(ref.get("path"), str), "EVIDENCE_REF", "证据须为相对路径或 path/sha256 引用")
        raw = ref["path"]
        path = Path(raw)
        _require(raw and not path.is_absolute() and ".." not in path.parts and "\\" not in raw,
                 "EVIDENCE_BOUNDARY", "证据须为题目根内的 POSIX 相对路径")
        target = self.root / path
        _require(target.resolve().is_relative_to(self.root) and not any(
            part.is_symlink() for part in (target, *target.parents) if part != self.root.parent),
            "EVIDENCE_BOUNDARY", "不读取越界或符号链接证据")
        _require(target.is_file() and target.stat().st_size > 0, "EVIDENCE_MISSING", f"缺少非空普通证据：{raw}（目录请引用已有清单文件）")
        digest = _sha256(target)
        if "sha256" in ref:
            _require(ref["sha256"] == digest, "EVIDENCE_CHANGED", f"证据哈希变化，需复核：{raw}")
        # Parse machine-readable inputs, but never infer scientific validity.
        value = None
        if target.suffix in {".json", ".jsonl", ".toml"}:
            _require(target.stat().st_size <= 8 * 1024 * 1024, "EVIDENCE_TOO_LARGE", "结构化检查文件不得超过 8 MiB；大日志引用既有清单")
            text = target.read_text(encoding="utf-8")
            reject = lambda value: (_ for _ in ()).throw(ValueError(f"非有限值 {value}"))
            if target.suffix == ".json":
                value = json.loads(text, parse_constant=reject)
            elif target.suffix == ".jsonl":
                value = []
                for line in text.splitlines():
                    if line.strip():
                        value.append(json.loads(line, parse_constant=reject))
            else:
                value = tomllib.loads(text)
        validator = ref.get("validator")
        _require(validator in {None, "protocol", "trajectory"}, "EVIDENCE_VALIDATOR", "内置校验只支持 protocol/trajectory；不运行任意命令")
        if validator == "protocol":
            from .experiment_data import protocol
            protocol(value)
        if validator == "trajectory":
            from .materials_trajectory import check_rounds
            if target.suffix == ".jsonl":
                value = {"rounds": value}
            findings = check_rounds(value, path.as_posix())
            _require(not findings, "TRAJECTORY_FORMAT", f"轨迹结构需修正或审阅：{findings}")
        return {"path": path.as_posix(), "sha256": digest}

    def _reports(self, inputs: dict, field: str) -> dict[str, list[dict]]:
        rows = inputs.get(field, [])
        _require(isinstance(rows, list), "PREFLIGHT_INPUT", f"{field} 须为数组")
        mapped: dict[str, list[dict]] = {}
        for row in rows:
            _require(isinstance(row, dict) and isinstance(row.get("obligations"), list)
                     and row["obligations"] and all(isinstance(key, str) and key in self.by_id for key in row["obligations"]),
                     "PREFLIGHT_INPUT", f"{field} 须明确引用已知阶段义务")
            for key in row["obligations"]:
                mapped.setdefault(key, []).append(row)
        return mapped

    def _assessment(self, row: dict, required: list[str], refs: dict, *, review: bool) -> tuple[str, str]:
        report_ref = self._reference(row.get("report"))
        bindings = row.get("bindings")
        _require(isinstance(bindings, dict) and all(
            key in bindings and bindings[key] == refs[key]["sha256"] for key in required),
            "ASSESSMENT_CHANGED", "检查/审查未绑定全部当前证据；需定向复核，不能沿用旧 PASS")
        if review:
            _require(all(isinstance(row.get(key), str) and row[key].strip()
                         for key in ("reviewer", "summary", "conclusion")),
                     "REVIEW_PENDING", "人工结论须有责任人、依据摘要和明确 conclusion")
            _require(row["conclusion"] in {"PASS", "BLOCKED", "PENDING", "NOT_APPLICABLE"},
                     "REVIEW_PENDING", "人工 conclusion 须为明确预检状态")
            return row["conclusion"], row["summary"]
        report = _read_json(self.root / report_ref["path"])
        _require(isinstance(report.get("status"), str), "CHECK_REPORT", "机械检查输出须有 status")
        if report["status"].upper() not in SUCCESS:
            return "BLOCKED", "已有检查输出未通过；先修复其实际失败项"
        findings = report.get("issues", [])
        _require(isinstance(findings, list), "CHECK_REPORT", "检查输出 issues 须为数组")
        if any(not isinstance(item, dict) or item.get("level", "error") == "error" for item in findings):
            return "BLOCKED", "检查输出仍有错误，不能以顶层 status 覆盖"
        if report.get("pending") or findings:
            return "PENDING", "已有检查仍有待审内容；不把结构/局部通过视为完整通过"
        return "PASS", "已有机械检查输出及其当前证据绑定已核；未重新执行实跑"

    def _exceptions(self, before: str | None, decisions: dict) -> tuple[dict, list]:
        effective, warnings = {}, list(decisions["issues"])
        for row in decisions.get("exceptions", []):
            targets = [key.strip() for key in row.get("scope", "").split(",") if key.strip()]
            try:
                _require(not row.get("parse_issues"), "EXCEPTION_RECORD", "例外记录存在重复字段")
                _require(targets and all(key in self.by_id for key in targets), "EXCEPTION_SCOPE", "例外 scope 须为逗号分隔的明确阶段义务 ID")
                _require(row.get("rule_version") == self.version and all(
                    isinstance(row.get(field), str) and row[field].strip()
                    for field in ("reason", "approver", "limits")), "EXCEPTION_AUTHORITY",
                         "例外须有当前规则版本、专家确认人、原因和适用限制")
                _require(not before or row.get("before") in {before, "all"}, "EXCEPTION_SCOPE", "例外不适用于当前动作")
                self._reference(row.get("evidence"))
                status = row.get("status")
                _require(status in {"waived", "not_applicable", "rejected"}, "EXCEPTION_STATUS", "例外状态无效")
                for key in targets:
                    if status == "not_applicable":
                        _require(self.by_id[key].get("conditional") is True, "EXCEPTION_SCOPE", "无条件规则只能申请 WAIVED，不得改为不适用")
                    effective[key] = {"status": status, "entry": row}
            except (FlowError, ValueError, OSError) as exc:
                warnings.append(f"第 {row['line']} 行例外不生效：{exc}")
                # A later rejected/invalid amendment must not revive an older waiver.
                for key in targets:
                    effective.pop(key, None)
        return effective, warnings

    def _confirmation(self, stage: dict, evidence: dict, entry: dict | None) -> dict:
        """Check the recorded decision, not the identity of a human approver."""
        refs, missing, issues = {}, [], []
        bindings = {}
        if entry and entry.get("bindings"):
            try:
                bindings = json.loads(entry["bindings"])
                _require(isinstance(bindings, dict), "CONFIRMATION_BINDING", "bindings 须为证据 ID 到 path/sha256 的对象")
            except (ValueError, FlowError) as exc:
                bindings = {}
                issues.append(str(exc))
        for role in stage["confirmation_evidence"]:
            value = evidence.get(role, bindings.get(role))
            if value is None:
                missing.append(role)
                continue
            try:
                refs[role] = self._reference(value)
            except (FlowError, ValueError, OSError, UnicodeError) as exc:
                issues.append(f"{role}: {exc}")
        paths = sorted({ref["path"] for ref in refs.values()})
        proposal = {"gate": stage["gate"], "status": "pending", "scope": stage["title"],
                    "rule_version": self.version, "evidence": "; ".join(paths),
                    "bindings": refs}
        status, reason = "PENDING", "需要专家明确确认；程序通过不等于批准"
        if entry:
            try:
                _require(not entry.get("parse_issues"), "CONFIRMATION_RECORD", "确认记录存在重复字段")
                _require(all(isinstance(entry.get(field), str) and entry[field].strip()
                         for field in ("scope", "approver", "limits", "evidence")),
                         "CONFIRMATION_RECORD", "确认须有实际范围、确认人、依据和限制")
                _require(entry.get("status") in {"approved", "waived", "pending", "rejected"},
                         "CONFIRMATION_RECORD", "确认状态无效")
                if entry["status"] == "rejected":
                    status, reason = "BLOCKED", "最新决定已拒绝或撤回，不能沿用旧批准"
                elif entry["status"] == "pending":
                    reason = "最新决定尚待确认"
                else:
                    _require(entry.get("rule_version") == self.version, "CONFIRMATION_VERSION", "规则版本已变化，先定向复核再确认")
                    _require(not missing and not issues and all(
                        bindings.get(role) == refs.get(role) for role in stage["confirmation_evidence"]),
                        "CONFIRMATION_BINDING", "确认证据缺失、改变或不属于当前范围；旧批准不生效")
                    _require({value.strip() for value in entry["evidence"].split(";") if value.strip()} == set(paths),
                             "CONFIRMATION_BINDING", "确认 evidence 与实际绑定文件不一致")
                    if entry["status"] == "waived":
                        _require(bool(entry.get("reason", "").strip()), "CONFIRMATION_RECORD", "豁免阶段确认须有明确理由")
                    status = "PASS" if entry["status"] == "approved" else "WAIVED"
                    reason = "已核当前规则和证据对应的专家决定；不认证人身份、不豁免费用或权限"
            except FlowError as exc:
                status, reason = "BLOCKED", str(exc)
                issues.append(str(exc))
        elif issues:
            status, reason = "BLOCKED", "待确认的核心证据无效，先修复再请求确认"
        return {"gate": stage["gate"], "status": status, "reason": reason,
                "record": entry, "proposal": proposal, "missing": missing, "issues": issues}

    def _confirmations(self, stage: int, evidence: dict, decisions: dict, *, before: str | None,
                       phase: str) -> list[dict]:
        current = self.rules.stage_for(stage)
        gates = current.get("required_confirmations", [])[:]
        if current.get("expert_confirmation"):
            gates.append(current["gate"])
        stages = {item["gate"]: item for item in self.rules.stages()}
        rows = []
        for gate in gates:
            row = self._confirmation(stages[gate], evidence, decisions["latest"].get(gate))
            # An exit audit is not a second launch authorization or a hot runtime gate.
            row["due"] = bool(before) if gate != current["gate"] else before == gate
            if phase == "exit" and stage != 4:
                row["due"] = True
            rows.append(row)
        return rows

    def check(self, stage: int, inputs: dict | None = None, *, before: str | None = None,
              phase: str = "enter", changed: list[str] | None = None) -> dict:
        _require(self.rules.stage_for(stage) is not None and phase in {"enter", "exit"}, "STAGE_INPUT", "指定阶段 1..6 与 enter/exit")
        gates = {item["gate"]: item["id"] for item in self.rules.stages()}
        _require(before is None or before in gates and gates[before] == stage,
                 "STAGE_INPUT", "--before 须为当前阶段动作；退出检查不要同时指定 before")
        _require(before is None or phase == "enter", "STAGE_INPUT", "--before 不与 --phase exit 混用")
        if inputs is None:
            inputs = {}
        _require(isinstance(inputs, dict) and set(inputs) <= {"evidence", "checks", "reviews"},
                 "PREFLIGHT_INPUT", "输入只包含已有 evidence/checks/reviews；不接受声明的 PASS 状态表")
        evidence = inputs.get("evidence", {})
        _require(isinstance(evidence, dict), "PREFLIGHT_INPUT", "evidence 须为证据 ID 到已有引用的映射")
        checks, reviews = self._reports(inputs, "checks"), self._reports(inputs, "reviews")
        current = {item["id"] for item in self.rules.obligations_for(stage)}
        selected = set(current)
        if before:
            selected.update(item["id"] for item in self.by_id.values()
                            if item["stage"] < stage and before in item["blocking_before"])
        # Read previous conclusions; no cascade or task status is persisted.
        queue = list(selected)
        while queue:
            for key in self.by_id[queue.pop()]["depends_on"]:
                if key not in selected:
                    selected.add(key)
                    queue.append(key)
        decisions = TaskWorkspace(self.root).read_decisions()
        exceptions, warnings = self._exceptions(before, decisions)
        rows = []
        for item in self.by_id.values():
            key = item["id"]
            if key not in selected:
                continue
            deferred = bool(before and before in item.get("deferred_before", []))
            due = item["severity"] != "advisory" and not deferred and (phase == "exit" or bool(before and (
                item["stage"] < stage or before in item["blocking_before"])))
            required = item.get("pre_action", {}).get(before, item["evidence"])
            refs, problems, missing = {}, [], []
            for role in required:
                if role not in evidence:
                    missing.append(role)
                    continue
                try:
                    refs[role] = self._reference(evidence[role])
                except (FlowError, ValueError, OSError, UnicodeError) as exc:
                    problems.append({"code": getattr(exc, "code", "EVIDENCE_FORMAT"), "message": str(exc)})
            status, reason = "PENDING", "尚无覆盖当前范围的检查或人工结论"
            if deferred:
                reason = "这是动作后的结果义务；当前不阻断，退出阶段时再核"
            elif problems:
                status, reason = "BLOCKED", "已有证据无效或已变化，需修复/复核"
            elif missing:
                status, reason = ("BLOCKED" if due else "PENDING"), "到期证据缺失" if due else "当前准备尚未齐全"
            else:
                outcomes = []
                for field, mapping in (("mechanical", checks), ("review", reviews)):
                    if item["check_type"] not in {field, "mixed"}:
                        continue
                    records = mapping.get(key, [])
                    if not records:
                        outcomes.append(("PENDING", f"缺{'人工实质审查' if field == 'review' else '既有机械检查输出'}"))
                    else:
                        try:
                            outcomes.append(self._assessment(records[-1], required, refs, review=field == "review"))
                        except (FlowError, ValueError, OSError, UnicodeError) as exc:
                            outcomes.append(("BLOCKED", str(exc)))
                if any(s == "BLOCKED" for s, _ in outcomes):
                    status = "BLOCKED"
                elif any(s == "NOT_APPLICABLE" for s, _ in outcomes):
                    status = "NOT_APPLICABLE" if item.get("conditional") and all(
                        s in {"PASS", "NOT_APPLICABLE"} for s, _ in outcomes) else "BLOCKED"
                else:
                    status = "PENDING" if any(s != "PASS" for s, _ in outcomes) else "PASS"
                reason = "；".join(text for _, text in outcomes)
            exception = exceptions.get(key)
            if exception and not deferred and exception["status"] != "rejected":
                status = "WAIVED" if exception["status"] == "waived" else "NOT_APPLICABLE"
                reason = "专家显式确认的题目/版本内例外；不是原要求已通过"
            rows.append({"id": key, "source_rule": item["source_rule"], "stage": item["stage"],
                         "status": status, "due": due, "title": item["title"],
                         "action": item["action"], "source_anchor": item["source_anchor"],
                         "check_type": item["check_type"], "severity": item["severity"],
                         "required_evidence": required, "evidence": refs, "missing": missing,
                         "issues": problems, "reason": reason,
                         "exception": exception["entry"] if exception and status in {"WAIVED", "NOT_APPLICABLE"} else None})
        changed = changed or []
        _require(all(key in self.by_id or key in self.rules.canonical_rule_ids() for key in changed),
                 "CHANGED_RULE", "--changed 使用受影响的规则或阶段义务 ID；普通文字修改不必填写")
        affected = {key for key, item in self.by_id.items() if key in changed or item["source_rule"] in changed}
        while True:
            following = {key for key, item in self.by_id.items() if set(item["depends_on"]) & affected}
            expanded = affected | following
            if expanded == affected:
                break
            affected = expanded
        confirmations = self._confirmations(stage, evidence, decisions, before=before, phase=phase)
        checks_ready = all(row["status"] in RESOLVED for row in rows if row["due"])
        confirmations_ready = all(row["status"] in RESOLVED for row in confirmations if row["due"])
        ready = checks_ready and confirmations_ready
        aggregate = "BLOCKED" if any(row["status"] == "BLOCKED" for row in rows) else "PENDING" if any(
            row["status"] == "PENDING" for row in rows) else "WAIVED" if any(row["status"] == "WAIVED" for row in rows) else "PASS"
        due_statuses = {row["status"] for row in confirmations if row["due"]}
        if "BLOCKED" in due_statuses:
            aggregate = "BLOCKED"
        elif "PENDING" in due_statuses and aggregate != "BLOCKED":
            aggregate = "PENDING"
        elif "WAIVED" in due_statuses and aggregate == "PASS":
            aggregate = "WAIVED"
        return {"status": aggregate, "stage": stage, "phase": phase, "before": before,
                "task_root": str(self.root), "rule_version": self.version,
                "ready": ready if before or phase == "exit" else None,
                "checks_ready": checks_ready if before or phase == "exit" else None,
                "confirmations_ready": confirmations_ready if before or phase == "exit" else None,
                "confirmations": confirmations,
                "counts": dict(Counter(row["status"] for row in rows)), "obligations": rows,
                "decision_log_issues": warnings,
                "recheck": {"changed": changed, "obligations": sorted(affected),
                            "stages": sorted({self.by_id[key]["stage"] for key in affected}),
                            "mode": "targeted_review_hint_only_no_cascade"},
                "next_action": ("检查就绪，但需按 confirmations 向专家请求当前范围确认，真实答复后才记录" if
                                before and checks_ready and not confirmations_ready else
                                "按到期缺口补证/审查；例外须有专家确认") +
                               "。预检不批准费用、不运行训练、不代替独立 QA"}
