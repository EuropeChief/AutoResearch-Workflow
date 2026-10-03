"""Six submission-form fields from accepted package facts and attributed prose.

The program checks sources/numbers, not whether a Chinese scientific summary is
true. Its named reviewer must inspect the cited final code and documentation.
"""
from __future__ import annotations

import math
import re

from .core import _atomic_json, _read_json, _require, _sha256
from .experiments import evidence


FIELDS = {"research_subdirection": "研究子方向", "optimization_surface": "优化面介绍",
          "baseline_description": "Baseline 描述", "reference_description": "Reference 描述"}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def render(package, archives_path, spec):
    _require(isinstance(spec, dict) and isinstance(spec.get("reviewer"), str) and spec["reviewer"].strip(),
             "FORM_SPEC", "须有核对最终代码/说明的填表责任人")
    texts, sources = {}, set()
    for key in FIELDS:
        item = spec.get(key)
        _require(isinstance(item, dict) and isinstance(item.get("text"), str)
                 and re.search(r"[\u4e00-\u9fff]", item["text"])
                 and not any(c in item["text"] for c in "\r\n"),
                 "FORM_SPEC", f"{key} 须为有依据的单段中文概述，不附虚构试跑")
        refs = item.get("sources")
        _require(isinstance(refs, list) and refs, "FORM_SOURCE_MISSING", f"{key} 缺包内依据")
        paths = [evidence(package, ref) for ref in refs]
        if key in {"baseline_description", "reference_description"}:
            scope = package / "workspace" / ("harbor_task" if key == "baseline_description" else "reference")
            _require(any(p.is_relative_to(scope) for p in paths), "FORM_SOURCE_MISSING",
                     f"{key} 须引用对应最终代码，不得拿 Agent best_method 代替 Reference")
        sources.update(ref["path"] for ref in refs)
        texts[key] = item["text"].strip()
    annotation = _read_json(package / "expert_evidence/expert_annotation.json")
    score = annotation["score_contract"]
    comparison = _read_json(package / "optimization_evidence/comparison_summary.json")
    aggregate = comparison.get("formal_aggregates")
    _require(isinstance(aggregate, dict), "FORM_SOURCE_MISSING", "缺正式聚合证据 formal_aggregates")
    _require(all(aggregate.get(k) == score[k] for k in ("protocol", "metric", "direction", "split")),
             "FORM_SOURCE_CONFLICT", "正式聚合与评分合同的协议/指标/方向/数据划分不一致")
    seeds = comparison["evaluation_protocol"]["seeds"]
    _require(aggregate.get("seeds") == seeds, "FORM_SOURCE_CONFLICT", "正式聚合 seed 与冻结协议不一致")
    for role in ("baseline", "reference"):
        row = aggregate.get(role)
        _require(isinstance(row, dict) and type(row.get("n")) is int and row["n"] == len(seeds)
                 and _number(row.get("mean")) and abs(row["mean"] - score[role]["raw_value"]) <= 1e-6,
                 "FORM_SOURCE_CONFLICT", f"{role} 正式均值/次数与评分锚点不一致")
        if role + "_mean" in comparison:
            mean = comparison[role + "_mean"]
            _require(_number(mean) and abs(mean - row["mean"]) <= 1e-6,
                     "FORM_SOURCE_CONFLICT", f"{role} comparison_summary 存在矛盾均值")
        direction = "越大越好" if score["direction"] == "maximize" else "越小越好"
        texts[role + "_score"] = (f'原始指标 `{score["metric"]}`：{row["mean"]:.10g}（{direction}）；'
            f'归一化分数：{score[role]["normalized_score"]:.10g}（越大越好）；'
            f'split=`{score["split"]}`，同协议重复 n={row["n"]}，seeds={seeds}。')
    body = ["# 填表信息", ""]
    for key, label in [("research_subdirection", "研究子方向"), ("optimization_surface", "优化面介绍"),
                       ("baseline_description", "Baseline 描述"), ("baseline_score", "Baseline 分数"),
                       ("reference_description", "Reference 描述"), ("reference_score", "Reference 分数")]:
        body.extend(["## " + label, "", texts[key], ""])
    manifest = _read_json(archives_path)
    sources.update(("expert_evidence/expert_annotation.json", "optimization_evidence/comparison_summary.json"))
    body.extend(["---", "", f'来源与版本：提交包 `{manifest["package_sha256"]}`；归档清单 `{_sha256(archives_path)}`。',
                 "包内依据：" + "、".join(f"`{p}`" for p in sorted(sources)) + "。",
                 f'方法概述核对人：{spec["reviewer"]}。程序仅核数值、引用及绑定，不代替方法实质审查。', ""])
    return "\n".join(body)


def write(package, archives_path, spec):
    text = render(package, archives_path, spec)
    path, receipt = archives_path.parent / "填表信息.md", archives_path.parent / "form.json"
    if path.exists():
        _require(not path.is_symlink() and path.read_text(encoding="utf-8") == text,
                 "FORM_EDITED", "已有填表文件不同（可能含人工修订），禁止静默覆盖")
    else:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    record = {"schema_version": 1, "archives_sha256": _sha256(archives_path),
              "form_sha256": _sha256(path), "spec": {k: v for k, v in spec.items() if k != "checks"}}
    if receipt.exists():
        _require(_read_json(receipt) == record, "FORM_EDITED", "已有填表绑定不同，禁止覆盖")
    else:
        _atomic_json(receipt, record)
    return verify(package, archives_path)


def verify(package, archives_path):
    path, receipt = archives_path.parent / "填表信息.md", archives_path.parent / "form.json"
    _require(receipt.is_file() and not receipt.is_symlink(), "FORM_INCOMPLETE", "缺少填表核验记录")
    record = _read_json(receipt)
    _require(record.get("archives_sha256") == _sha256(archives_path), "FORM_STALE", "填表文件未绑定当前三包")
    _require(path.is_file() and not path.is_symlink() and record.get("form_sha256") == _sha256(path),
             "FORM_EDITED", "填表文件丢失或已有人工修订，须核实，不自动覆盖")
    _require(path.read_text(encoding="utf-8") == render(package, archives_path, record.get("spec")),
             "FORM_STALE", "填表数值/来源或版本绑定不一致")
    return {"status": "form_ready", "path": str(path), "sha256": _sha256(path),
            "archives_sha256": record["archives_sha256"]}
