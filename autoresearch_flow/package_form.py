"""Seven fields from final package facts and existing prose; never invent prose."""

from __future__ import annotations

import math
import re
from pathlib import Path

from .common import FlowError, _require
from .materials_io import read_object

LABELS = (
    "研究子方向",
    "优化面介绍",
    "Baseline 描述",
    "Baseline 分数",
    "Reference 描述",
    "Reference 分数",
    "小规模试跑结论",
)


def sections(text):
    result = {}
    for match in re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text):
        title = (
            re.sub(r"^(?:\d+[.、)\s]+)", "", match[1])
            .strip()
            .replace(" ", "")
            .casefold()
        )
        end = re.search(r"(?m)^#{1,6}\s+", text[match.end() :])
        body = text[
            match.end() : match.end() + end.start() if end else len(text)
        ].strip()
        for label in LABELS:
            if title == label.replace(" ", "").casefold() and body:
                result[label] = body
    return result


def ordinary_text(path):
    _require(
        path.is_file() and not path.is_symlink() and path.stat().st_size <= 256 * 1024,
        "FORM_NOTES",
        "备注/专家概述须为不超过 256 KiB 的普通 UTF-8 文件",
    )
    return path.read_text(encoding="utf-8")


def read_required_source(root, name):
    p = root / name
    if not p.exists():
        raise FlowError("FORM_SOURCE_CONFLICT", "已通过包缺少必交文件：" + name)
    try:
        return read_object(p)
    except FlowError as exc:
        raise FlowError(
            "FORM_SOURCE_CONFLICT", f"已通过包中的 {name} 无法读取：{exc}"
        ) from exc


def finite(value, label):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    _require(
        valid,
        "FORM_SOURCE_CONFLICT",
        label + " 不是有限数值",
    )
    return value


def render(root, report, notes=None):
    issues = []
    texts = {}
    expert = root / "expert_evidence/专家作业说明文档.md"
    if expert.is_file():
        if expert.stat().st_size <= 256 * 1024:
            texts.update(sections(ordinary_text(expert)))
        else:
            issues.append("专家说明较大，未自动提取正文；可补简短备注，不阻塞压缩")
    if notes is not None:
        texts.update(sections(ordinary_text(Path(notes))))
    annotation = read_required_source(root, "expert_evidence/expert_annotation.json")
    comparison = read_required_source(
        root, "optimization_evidence/comparison_summary.json"
    )
    for label, key in (
        ("研究子方向", "research_subdirection"),
        ("优化面介绍", "optimization_surface"),
    ):
        value = annotation.get(key)
        if key == "research_subdirection" and value is None:
            value = annotation.get("research_direction")
        if isinstance(value, str) and value.strip():
            texts.setdefault(label, value.strip())
    overview = report.get("overview", {})
    methods = overview.get("baseline_reference", {})
    if isinstance(methods, dict):
        for role in ("baseline", "reference"):
            value = methods.get(role + "_method")
            if isinstance(value, str) and value.strip():
                texts.setdefault(role.capitalize() + " 描述", value.strip())
    surface = overview.get("optimization_surface", {})
    if (
        isinstance(surface, dict)
        and isinstance(surface.get("summary"), str)
        and surface["summary"].strip()
    ):
        texts.setdefault("优化面介绍", surface["summary"].strip())

    score = annotation.get("score_contract", {})
    _require(isinstance(score, dict), "FORM_SOURCE_CONFLICT", "score_contract 类型错误")
    metric = score.get("metric")
    direction = score.get("direction")
    split = score.get("split")
    cm = comparison.get("metric")
    if isinstance(cm, dict):
        _require(
            not metric or not cm.get("name") or cm["name"] == metric,
            "FORM_SOURCE_CONFLICT",
            "正式汇总与 annotation 的指标不一致",
        )
        _require(
            not direction or not cm.get("direction") or cm["direction"] == direction,
            "FORM_SOURCE_CONFLICT",
            "正式汇总与 annotation 的方向不一致",
        )
    elif isinstance(cm, str):
        _require(
            not metric or cm == metric, "FORM_SOURCE_CONFLICT", "正式汇总指标不一致"
        )
    _require(
        not split or not comparison.get("split") or comparison["split"] == split,
        "FORM_SOURCE_CONFLICT",
        "正式汇总与 annotation 的 split 不一致",
    )
    stats = comparison.get("statistics", {})
    groups = comparison.get("groups", {})
    aggregate = comparison.get("formal_aggregates", {})
    _require(
        all(isinstance(x, dict) for x in (stats, groups, aggregate)),
        "FORM_SOURCE_CONFLICT",
        "正式汇总嵌套统计类型错误",
    )
    for key in ("metric", "direction", "split", "protocol"):
        if key in aggregate and key in score:
            _require(
                aggregate[key] == score[key],
                "FORM_SOURCE_CONFLICT",
                "formal_aggregates." + key + " 与评分合同不一致",
            )
    protocol = comparison.get("evaluation_protocol", {})
    _require(
        isinstance(protocol, dict),
        "FORM_SOURCE_CONFLICT",
        "evaluation_protocol 类型错误",
    )
    declarations = [
        obj["seeds"]
        for obj in (comparison, protocol, aggregate)
        if obj.get("seeds") is not None
    ]
    for declared in declarations:
        _require(
            isinstance(declared, list)
            and declared
            and all(type(s) is int and s >= 0 for s in declared)
            and len(set(declared)) == len(declared),
            "FORM_SOURCE_CONFLICT",
            "正式 seed 类型/唯一性错误",
        )
    seeds = declarations[0] if declarations else None
    _require(
        all(d == seeds for d in declarations),
        "FORM_SOURCE_CONFLICT",
        "正式 seed 声明矛盾",
    )
    means = {}
    for role in ("baseline", "reference"):
        label = role.capitalize() + " 分数"
        # Numeric notes do not override structured formal facts.
        texts.pop(label, None)
        rows = [
            container[role]
            for container in (aggregate, groups, score)
            if role in container
        ]
        _require(
            all(isinstance(x, dict) for x in rows),
            "FORM_SOURCE_CONFLICT",
            role + " 汇总对象类型错误",
        )
        values = [
            container[role]["mean"]
            for container in (aggregate, groups)
            if role in container and "mean" in container[role]
        ]
        values += [
            container[role + "_mean"]
            for container in (comparison, stats)
            if role + "_mean" in container
        ]
        if not values:
            issues.append(role + " 缺可识别的正式聚合均值")
            continue
        values = [finite(v, role + " mean") for v in values]
        raw = values[0]
        _require(
            all(math.isclose(raw, v, rel_tol=1e-9, abs_tol=1e-6) for v in values),
            "FORM_SOURCE_CONFLICT",
            role + " 多处正式均值矛盾",
        )
        anchor = score.get(role, {})
        if anchor.get("raw_value") is not None:
            _require(
                math.isclose(
                    raw,
                    finite(anchor["raw_value"], role + " anchor"),
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                ),
                "FORM_SOURCE_CONFLICT",
                role + " 正式均值与 annotation 锚点矛盾",
            )
        norm = anchor.get("normalized_score")
        if norm is not None:
            finite(norm, role + " normalized")
        if not (
            isinstance(metric, str)
            and metric
            and direction in {"minimize", "maximize"}
            and isinstance(split, str)
            and split
        ):
            issues.append(role + " 缺指标/方向/split")
            continue
        means[role] = raw
        unit = cm.get("unit", "") if isinstance(cm, dict) else ""
        texts[label] = (
            f"原始指标 `{metric}`：{raw:.10g}"
            + (f" {unit}" if unit else "")
            + ("（越小越好）" if direction == "minimize" else "（越大越好）")
            + f"；split=`{split}`；归一化分数："
            + (f"{norm:.10g}" if norm is not None else "待补")
            + (
                f"；正式 seeds={seeds}，n={len(seeds)}。"
                if isinstance(seeds, list)
                else "；正式重复次数待补。"
            )
        )
    upper = score.get("upper_bound", {})
    if (
        all(role in means for role in ("baseline", "reference"))
        and isinstance(upper, dict)
        and upper.get("raw_value") is not None
    ):
        b = means["baseline"]
        u = finite(upper["raw_value"], "upper_bound")
        _require(
            (u > b if direction == "maximize" else u < b),
            "FORM_SOURCE_CONFLICT",
            "U 与原始指标方向矛盾",
        )
        for role in ("baseline", "reference"):
            norm = score.get(role, {}).get("normalized_score")
            if norm is not None:
                _require(
                    math.isclose(
                        norm, (means[role] - b) / (u - b), rel_tol=1e-9, abs_tol=1e-6
                    ),
                    "FORM_SOURCE_CONFLICT",
                    role + " 归一化数值与 B/U 矛盾",
                )
    missing = [
        label for label in LABELS if label not in texts or "待补" in texts[label]
    ]
    body = ["# 填表信息", ""]
    for label in LABELS:
        body += [
            "## " + label,
            "",
            texts.get(label, "待补：未找到可直接引用的真实概述/正式数值。"),
            "",
        ]
    body += [
        "---",
        "",
        "分数取自当前最终包的正式汇总与 expert_annotation；备注不能覆盖结构化数值。",
        "小规模试跑结论仅总结已有双轨前期真实记录，不表示另做独立试跑；缺资料保持待补。",
        "文字按已有专家材料/可选备注整理，方法与试跑叙述仍须据实核对。",
        "",
    ]
    return "\n".join(body), {
        "status": "pending" if missing else "complete",
        "missing": missing,
        "notes": issues,
    }
