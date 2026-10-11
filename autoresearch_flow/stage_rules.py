"""轻量六阶段规则矩阵及派生视图的一致性检查。

本模块只检查流程包自身的规则映射。它不读取题目目录、不记录题目状态，
也不会根据 ``depends_on`` 自动重开阶段或触发训练。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .task_workspace import GATES


FLOW_ROOT = Path(__file__).resolve().parents[1]
MATRIX_RELATIVE = Path("rules/stage_matrix.json")
RULES_RELATIVE = Path("rules/README.md")
OBLIGATION_RE = re.compile(r"^### ([MC]\d{2}-S\d+)\s+[—-]", re.MULTILINE)
RULE_HEADING_RE = re.compile(r"^## ([MC]\d{2})\s*$", re.MULTILINE)
RULE_IDS = {f"M{i:02d}" for i in range(1, 14)} | {f"C{i:02d}" for i in range(1, 8)}
CHECK_TYPES = {"mechanical", "review", "mixed"}
SEVERITIES = {"hard", "review", "advisory"}
REQUIRED_OBLIGATION_FIELDS = {
    "id", "source_rule", "stage", "title", "action", "evidence", "check_type",
    "severity", "blocking_before", "depends_on", "consumes", "produces",
    "recheck_on_change", "source_anchor",
}


def _issue(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **extra}


class StageRules:
    """加载并验证 ``stage_matrix.json`` 与其六个 Markdown 派生视图。"""

    def __init__(self, root: Path | str = FLOW_ROOT) -> None:
        self.root = Path(root).resolve()
        self.matrix_path = self.root / MATRIX_RELATIVE
        self.rules_path = self.root / RULES_RELATIVE
        self.matrix: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        if self.matrix is None:
            with self.matrix_path.open(encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("stage_matrix.json 顶层必须是对象")
            self.matrix = payload
        return self.matrix

    def canonical_rule_ids(self) -> set[str]:
        if not self.rules_path.is_file():
            return set()
        return set(RULE_HEADING_RE.findall(self.rules_path.read_text(encoding="utf-8")))

    def stages(self) -> list[dict[str, Any]]:
        value = self.load().get("stages", [])
        return value if isinstance(value, list) else []

    def obligations(self) -> list[dict[str, Any]]:
        value = self.load().get("obligations", [])
        return value if isinstance(value, list) else []

    def stage_for(self, stage_id: int) -> dict[str, Any] | None:
        return next((stage for stage in self.stages() if stage.get("id") == stage_id), None)

    def obligations_for(self, stage_id: int) -> list[dict[str, Any]]:
        return [item for item in self.obligations() if item.get("stage") == stage_id]

    def render_stage(self, stage_id: int) -> str:
        stage = self.stage_for(stage_id)
        if stage is None:
            raise ValueError(f"未知阶段: {stage_id}")
        lines = [
            "<!-- generated-from: rules/stage_matrix.json; do not edit manually -->",
            f"<!-- stage: {stage_id} -->",
            f"# 阶段 {stage_id}：{stage['title']}",
            "",
            f"阶段标识：`{stage['slug']}`；阶段门提示：`{stage['gate']}`。",
            "本页由 `rules/stage_matrix.json` 派生，仅列当前阶段行动、所需证据和受影响的前置义务。",
            "规则正文仍以 [rules/README.md](../README.md) 为唯一来源；本页不是题目状态账本。",
            "",
        ]
        required = stage.get("required_confirmations", [])
        if required:
            lines.extend([f"相关动作前读取已确认决定：{', '.join(f'`{gate}`' for gate in required)}。", ""])
        if stage.get("expert_confirmation"):
            lines.extend([f"`{stage['gate']}` 需要专家明确确认；程序检查通过不等于批准。",
                          f"确认绑定已有证据：{', '.join(f'`{role}`' for role in stage['confirmation_evidence'])}。",
                          "确认前可继续准备，不启动对应正式动作；收到真实确认后才追加 `.autoresearch/decision-log.md`。", ""])
        else:
            lines.extend(["本阶段不新增人工批准；相关检查和已有授权满足即可连续推进。", ""])
        lines.extend(["## 阶段义务", ""])
        obligations = self.obligations_for(stage_id)
        if not obligations:
            lines.append("当前没有登记的阶段义务。")
            return "\n".join(lines) + "\n"
        for item in obligations:
            lines.extend(
                [
                    f"### {item['id']} — {item['title']}",
                    "",
                    f"- 规则来源：`{item['source_rule']}`（`{item['source_anchor']}`）",
                    f"- 当前行动：{item['action']}",
                    f"- 所需证据：{', '.join(f'`{value}`' for value in item['evidence'])}",
                    f"- 检查性质：`{item['check_type']}`；严重性：`{item['severity']}`",
                    f"- 阶段门前阻断：{', '.join(f'`{value}`' for value in item['blocking_before']) or '无'}",
                    f"- 读取前置：{', '.join(f'`{value}`' for value in item['depends_on']) or '无'}",
                    f"- 消费证据：{', '.join(f'`{value}`' for value in item['consumes']) or '无'}",
                    f"- 产生证据：{', '.join(f'`{value}`' for value in item['produces']) or '无'}",
                    f"- 影响性变更后复核：`{'是' if item['recheck_on_change'] else '否'}`",
                    "",
                ]
            )
            for gate, evidence in item.get("pre_action", {}).items():
                lines.extend([f"- `{gate}` 前先核准备证据：{', '.join(f'`{value}`' for value in evidence)}", ""])
            if item.get("deferred_before"):
                lines.extend([f"- 以下动作前不要求运行后结果：{', '.join(f'`{value}`' for value in item['deferred_before'])}；阶段退出时再核。", ""])
        return "\n".join(lines)

    def validate(self, *, check_views: bool = True) -> list[dict[str, Any]]:
        """返回问题列表；空列表表示矩阵、来源和视图一致。"""

        issues: list[dict[str, Any]] = []
        try:
            matrix = self.load()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            return [_issue("MATRIX_LOAD", f"无法读取阶段矩阵: {exc}")]

        if matrix.get("schema_version") != 1:
            issues.append(_issue("MATRIX_SCHEMA", "stage_matrix.json 的 schema_version 必须为 1"))
        if not isinstance(matrix.get("workflow_revision"), str) or not matrix["workflow_revision"]:
            issues.append(_issue("MATRIX_REVISION", "workflow_revision 必须是非空字符串"))

        stages = self.stages()
        stage_ids = [stage.get("id") for stage in stages if isinstance(stage, dict)]
        if stage_ids != list(range(1, 7)):
            issues.append(_issue("STAGE_SET", "必须按 1..6 顺序定义六个阶段", actual=stage_ids))
        if len(stage_ids) != len(set(stage_ids)):
            issues.append(_issue("STAGE_DUPLICATE", "阶段 id 不能重复"))
        for stage in stages:
            if not isinstance(stage, dict):
                issues.append(_issue("STAGE_TYPE", "每个阶段必须是对象"))
                continue
            for field in ("id", "slug", "title", "gate", "view_path"):
                if not stage.get(field):
                    issues.append(_issue("STAGE_FIELD", f"阶段缺少非空字段: {field}", stage=stage.get("id")))
            if stage.get("view_path") and not str(stage["view_path"]).startswith("rules/stages/"):
                issues.append(_issue("STAGE_VIEW_PATH", "阶段视图必须位于 rules/stages/", stage=stage.get("id")))

        canonical = self.canonical_rule_ids()
        if canonical != RULE_IDS:
            missing = sorted(RULE_IDS - canonical)
            extra = sorted(canonical - RULE_IDS)
            issues.append(_issue("CANONICAL_RULE_SET", "规则正文的 M/C 标题集合不完整", missing=missing, extra=extra))

        obligations = self.obligations()
        if not obligations:
            issues.append(_issue("OBLIGATION_EMPTY", "obligations 不能为空"))
        by_id: dict[str, dict[str, Any]] = {}
        for item in obligations:
            if not isinstance(item, dict):
                issues.append(_issue("OBLIGATION_TYPE", "每项阶段义务必须是对象"))
                continue
            item_id = item.get("id")
            if not isinstance(item_id, str) or not item_id:
                issues.append(_issue("OBLIGATION_ID", "阶段义务缺少非空 id"))
                continue
            if item_id in by_id:
                issues.append(_issue("OBLIGATION_DUPLICATE", f"阶段义务 id 重复: {item_id}"))
            by_id[item_id] = item
            missing_fields = sorted(REQUIRED_OBLIGATION_FIELDS - set(item))
            if missing_fields:
                issues.append(_issue("OBLIGATION_FIELDS", f"{item_id} 缺少字段", fields=missing_fields))
                continue
            source = item["source_rule"]
            stage_id = item["stage"]
            if source not in RULE_IDS or source not in canonical:
                issues.append(_issue("OBLIGATION_SOURCE", f"{item_id} 引用了未知规则: {source}"))
            if not isinstance(stage_id, int) or self.stage_for(stage_id) is None:
                issues.append(_issue("OBLIGATION_STAGE", f"{item_id} 引用了未知阶段: {stage_id}"))
            if not isinstance(item["title"], str) or not item["title"].strip():
                issues.append(_issue("OBLIGATION_TITLE", f"{item_id} title 不能为空"))
            if not isinstance(item["action"], str) or not item["action"].strip():
                issues.append(_issue("OBLIGATION_ACTION", f"{item_id} action 不能为空"))
            for field in ("evidence", "blocking_before", "depends_on", "consumes", "produces"):
                if not isinstance(item[field], list) or not all(isinstance(value, str) and value for value in item[field]):
                    issues.append(_issue("OBLIGATION_LIST", f"{item_id}.{field} 必须是非空字符串数组（blocking/depends 可为空）"))
            if item["check_type"] not in CHECK_TYPES:
                issues.append(_issue("OBLIGATION_CHECK_TYPE", f"{item_id} check_type 无效: {item['check_type']}"))
            if item["severity"] not in SEVERITIES:
                issues.append(_issue("OBLIGATION_SEVERITY", f"{item_id} severity 无效: {item['severity']}"))
            if not isinstance(item["recheck_on_change"], bool):
                issues.append(_issue("OBLIGATION_RECHECK", f"{item_id}.recheck_on_change 必须是布尔值"))
            preparation = item.get("pre_action", {})
            gates = {stage.get("gate") for stage in stages if isinstance(stage, dict)}
            if not isinstance(preparation, dict) or any(gate not in gates or not isinstance(refs, list)
                    or not refs or not all(isinstance(ref, str) and ref for ref in refs)
                    for gate, refs in preparation.items()):
                issues.append(_issue("OBLIGATION_PRE_ACTION", f"{item_id}.pre_action 须为动作到准备证据数组的映射"))
            deferred = item.get("deferred_before", [])
            if not isinstance(deferred, list) or any(gate not in gates for gate in deferred):
                issues.append(_issue("OBLIGATION_DEFERRED", f"{item_id}.deferred_before 含未知动作"))
            if "conditional" in item and type(item["conditional"]) is not bool:
                issues.append(_issue("OBLIGATION_CONDITIONAL", f"{item_id}.conditional 须为布尔值"))
            expected_anchor = f"rules/README.md#{source}"
            if item["source_anchor"] != expected_anchor:
                issues.append(_issue("OBLIGATION_ANCHOR", f"{item_id} source_anchor 与 source_rule 不一致"))

        referenced = {item.get("source_rule") for item in obligations if isinstance(item, dict)}
        uncovered = sorted(RULE_IDS - referenced)
        if uncovered:
            issues.append(_issue("RULE_COVERAGE", "矩阵没有覆盖全部 M/C 规则", missing=uncovered))

        for item_id, item in by_id.items():
            if not isinstance(item, dict) or "stage" not in item:
                continue
            stage_id = item.get("stage")
            for dependency in item.get("depends_on", []):
                target = by_id.get(dependency)
                if target is None:
                    issues.append(_issue("DEPENDENCY_UNKNOWN", f"{item_id} 引用了未知前置义务: {dependency}"))
                elif isinstance(stage_id, int) and isinstance(target.get("stage"), int) and target["stage"] > stage_id:
                    issues.append(_issue("DEPENDENCY_FORWARD", f"{item_id} 不能依赖后续阶段 {dependency}"))
            for value in item.get("blocking_before", []):
                if not isinstance(value, str) or not value:
                    issues.append(_issue("BLOCKING_VALUE", f"{item_id}.blocking_before 含无效值"))

        # Three explicit expert decisions, not a new gate for every operation.
        gate_stages = {s.get("gate"): s for s in stages if isinstance(s, dict)}
        for stage in stages:
            if not isinstance(stage, dict):
                continue
            gate = stage.get("gate")
            confirmation = stage.get("expert_confirmation", False)
            if type(confirmation) is not bool or confirmation != (gate in GATES):
                issues.append(_issue("EXPERT_GATE", "只有研究合同、锚点冻结、双轨启动需要专家确认", stage=stage.get("id")))
            refs = stage.get("confirmation_evidence", [])
            known_refs = {role for o in obligations if isinstance(o, dict) and isinstance(o.get("evidence"), list)
                          and o.get("stage") == stage.get("id")
                          for role in o.get("evidence", [])}
            if (not isinstance(refs, list) or any(not isinstance(role, str) or role not in known_refs for role in refs)
                    or confirmation and not refs):
                issues.append(_issue("CONFIRMATION_EVIDENCE", "专家确认须引用本阶段已有证据 ID", stage=stage.get("id")))
            previous = stage.get("required_confirmations", [])
            if not isinstance(previous, list) or any(not isinstance(g, str) or g not in GATES
                    or g not in gate_stages or gate_stages[g].get("id", 99) >= stage.get("id", 0) for g in previous):
                issues.append(_issue("CONFIRMATION_DEPENDENCY", "前置确认须为较早阶段的已知专家决定", stage=stage.get("id")))
            expected = [s["gate"] for s in stages if isinstance(s, dict) and s.get("gate") in GATES
                        and isinstance(s.get("id"), int) and isinstance(stage.get("id"), int)
                        and s["id"] < stage["id"] <= 4]
            if previous != expected:
                issues.append(_issue("CONFIRMATION_DEPENDENCY", "正式实现/锚点冻结/双轨启动应读取对应前置确认；复验和交付不追补审批", stage=stage.get("id")))

        # 这是矩阵自身的静态一致性检查，不是运行时状态传播。
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(item_id: str, path: tuple[str, ...] = ()) -> None:
            if item_id in visiting:
                cycle = " -> ".join((*path, item_id))
                issues.append(_issue("DEPENDENCY_CYCLE", f"阶段义务依赖形成环: {cycle}"))
                return
            if item_id in visited or item_id not in by_id:
                return
            visiting.add(item_id)
            for dependency in by_id[item_id].get("depends_on", []):
                visit(dependency, (*path, item_id))
            visiting.remove(item_id)
            visited.add(item_id)

        for item_id in by_id:
            visit(item_id)

        if check_views:
            issues.extend(self._validate_views(by_id))
        return issues

    def _validate_views(self, by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        for stage in self.stages():
            if not isinstance(stage, dict) or not stage.get("view_path"):
                continue
            path = self.root / str(stage["view_path"])
            if not path.is_file():
                issues.append(_issue("VIEW_MISSING", f"缺少阶段视图: {stage['view_path']}", stage=stage.get("id")))
                continue
            text = path.read_text(encoding="utf-8")
            if "generated-from: rules/stage_matrix.json" not in text:
                issues.append(_issue("VIEW_MARKER", f"阶段视图缺少生成标记: {stage['view_path']}"))
            found = set(OBLIGATION_RE.findall(text))
            expected = {item_id for item_id, item in by_id.items() if item.get("stage") == stage.get("id")}
            for item_id in sorted(expected - found):
                issues.append(_issue("VIEW_MISSING_OBLIGATION", f"阶段视图缺少义务: {item_id}", path=str(path)))
            for item_id in sorted(found - expected):
                issues.append(_issue("VIEW_UNKNOWN_OBLIGATION", f"阶段视图包含错误阶段义务: {item_id}", path=str(path)))
            for item_id in sorted(expected):
                item = by_id[item_id]
                if item["source_anchor"] not in text:
                    issues.append(_issue("VIEW_SOURCE_ANCHOR", f"阶段视图缺少来源锚点: {item_id}", path=str(path)))
        return issues


def check_stage_rules(root: Path | str = FLOW_ROOT, *, check_views: bool = True) -> list[dict[str, Any]]:
    """便捷入口，供工具和测试调用。"""

    return StageRules(root).validate(check_views=check_views)
