"""Copy explicitly selected material and relocate evidence references, preserving raw Trials."""
from __future__ import annotations

import shutil
from pathlib import Path

from .common import _require, _sha256, _atomic_json
from .materials_io import files, read_object, reference, inside, WORK_NAMES, SECRET_NAMES
from .materials_check import check


def experiment_sources(target, source):
    """Export current LP-2 seed receipts, payloads and failed logs, without its ledger."""
    binding = read_object(source/"experiment.json")
    seeds = binding["protocol"]["seeds"]
    chosen = {}
    for seed in seeds:
        result = source/f"seed_{seed}/result.json"
        if not result.is_file():
            continue
        d = read_object(result)
        _require(d.get("schema_version")=="autoresearch-run.v1", "EXPERIMENT_SOURCE", "实验自动导出只适用于独立 run 原始结果")
        base = target/f"seed_{seed}"
        chosen[base/"result.json"] = result
        method = inside(source,d["method"]["path"],directory=True)
        chosen[base/"method"] = method
        for name, ref in d["artifacts"].items():
            if not isinstance(ref,dict) or "path" not in ref:
                continue
            payload = reference(source,ref)
            dest = (base/"run.log" if name=="log" else
                    base/"measurement.json" if name=="raw_result" else
                    base/"model"/"artifact.json" if name=="model_metadata" else
                    base/"model"/"reload.log" if name=="reload_log" else
                    base/"model"/payload.name if name=="model" else base/"artifacts"/name/payload.name)
            chosen[dest] = payload
        for prior in (source/f"seed_{seed}").glob("attempt_*/result.json"):
            old = read_object(prior)
            if str(old.get("status")).upper() not in {"SUCCEEDED","SUCCESS","COMPLETE"}:
                log = prior.parent/"run.log"
                if log.is_file():
                    chosen[base/"failed_logs"/(prior.parent.name+".log")] = log
    return chosen


def assemble(sources, best_method, output_dir, *, source_root=None):
    """sources maps package-relative destinations to actual files/directories."""
    _require(isinstance(sources, dict) and sources, "MATERIAL_SOURCES", "sources 须为目的相对路径到实际来源的对象")
    output = Path(output_dir)
    _require(not output.exists(), "OUTPUT_EXISTS", "使用新输出目录，不能覆盖已有提交包")
    base = Path(source_root or ".").resolve()
    entries, lookup_roots = [], []
    selected = dict(sources)
    _require("expert_evidence/best_method" not in selected, "BEST_DUPLICATE", "唯一方法通过 best_method 输入，不从其他材料默选")
    selected["expert_evidence/best_method"] = str(Path(best_method).resolve())
    expanded = {}
    for target, source in selected.items():
        rel = Path(target)
        _require(isinstance(target, str) and rel.parts and not rel.is_absolute() and ".." not in rel.parts
                 and rel.parts[0] in {"workspace", "expert_evidence", "optimization_evidence"},
                 "MATERIAL_TARGET", f"目的须在三个标准目录内：{target}")
        src = base/source if isinstance(source, str) else None
        _require(src is not None and src.exists() and not src.is_symlink(), "MATERIAL_SOURCE", f"来源缺失/是链接：{target}")
        src = src.resolve()
        if src.is_dir():
            lookup_roots.append(src)
        resolved = output.resolve()
        _require(not resolved.is_relative_to(src) and not src.is_relative_to(resolved),
                 "OUTPUT_OVERLAP", f"输出不能包含或位于来源：{target}")
        if src.is_dir() and (src/"experiment.json").is_file() and rel.name in {"baseline_runs","reference_runs","best_retest"}:
            expanded.update(experiment_sources(rel,src))
        else:
            expanded[rel] = src
    for rel,src in expanded.items():
        inventory = files(src) if src.is_dir() else [src]
        for path in inventory:
            relative = path.relative_to(src) if src.is_dir() else Path(path.name)
            if any(x in WORK_NAMES for x in relative.parts):
                continue
            if rel==Path("expert_evidence") and relative.parts[:1]==("best_method",):
                continue
            if any(x in SECRET_NAMES or x.endswith(".key") for x in relative.parts):
                _require(False, "SECRET_SOURCE", f"来源含凭据，不能复制：{rel}/{relative}")
        entries.append((rel, src, inventory))
    targets = [x[0] for x in entries]
    for i, rel in enumerate(targets):
        _require(not any((rel==other or rel.is_relative_to(other) or other.is_relative_to(rel))
                         and {rel,other}!={Path("expert_evidence"),Path("expert_evidence/best_method")} for other in targets[i+1:]),
                 "MATERIAL_OVERLAP", f"映射目标重叠：{rel}；分开指定 expert_evidence 中的文件或目录")
    output.mkdir(parents=True)
    copied, excluded, relocated = {}, [], []
    # No guessed recursive data collection: only explicitly supplied source roots are copied.
    for target, source, inventory in entries:
        for path in inventory:
            relative = path.relative_to(source) if source.is_dir() else Path()
            if target==Path("expert_evidence") and relative.parts[:1]==("best_method",):
                excluded.append(str(target/relative))
                continue
            if any(x in WORK_NAMES for x in relative.parts) or path.suffix in {".pyc", ".pyo"}:
                excluded.append(str(target/relative))
                continue
            dest = output/target/relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
            copied[path.resolve()] = dest
    # Raw Harbor Trial config/result/log/reward retain original bytes and runtime paths.
    trial_dirs = {p.parent for p in output.rglob("config.json") if (p.parent/"result.json").is_file()
                  and (p.parent/"verifier").is_dir()}

    def destination(raw, parent):
        if not isinstance(raw, str):
            return None
        p = Path(raw)
        owners = [s for s in lookup_roots if parent.is_relative_to(s)]
        selected_roots = [max(owners,key=lambda s:len(s.parts))] if owners else lookup_roots
        candidates = [p.resolve()] if p.is_absolute() else [
            (root/p).resolve() for root in (parent,*parent.parents,base,*selected_roots)]
        found = {copied[x] for x in candidates if x in copied}
        # Directory references (method source) are selected explicitly, not inferred from names.
        for _, src, _ in entries:
            if not src.is_dir():
                continue
            for candidate in candidates:
                if candidate==src:
                    found.add(output/next(t for t,s,_ in entries if s==src))
                elif candidate.is_relative_to(src):
                    dest = output/next(t for t,s,_ in entries if s==src)/candidate.relative_to(src)
                    if dest.exists(): found.add(dest)
        _require(len(found)<=1, "AMBIGUOUS_REFERENCE", f"来源路径映射不唯一：{raw}")
        return next(iter(found), None)

    def rewrite(value, original_parent):
        if isinstance(value, dict):
            obj = {key: rewrite(item, original_parent) for key,item in value.items()}
            if isinstance(obj.get("path"), str):
                dest = destination(obj["path"], original_parent)
                if dest is not None:
                    obj["path"] = dest.relative_to(output).as_posix()
                    if "sha256" in obj and dest.is_file():
                        original = original_by_destination.get(dest)
                        _require(original is not None and value["sha256"]==_sha256(original),
                                 "SOURCE_HASH", f"来源证据哈希不符，不自动修正：{obj['path']}")
                        obj["sha256"] = _sha256(dest)
            return obj
        if isinstance(value, list):
            return [rewrite(x, original_parent) for x in value]
        return value

    structured = []
    for src, dest in copied.items():
        if dest.suffix!=".json" or any(dest.is_relative_to(t) for t in trial_dirs):
            continue
        rel = dest.relative_to(output)
        metadata_scope = rel.parts[0] in {"expert_evidence","optimization_evidence"} and not any(
            x in {"best_method","method","method_sources"} for x in rel.parts[1:-1])
        if not metadata_scope and rel.as_posix()!="workspace/qa_exposure_manifest.json":
            continue
        # Only metadata documents with references are rewritten, not arbitrary method/data JSON.
        if dest.name in {"result.json", "comparison_summary.json", "artifact.json", "evidence_index.json", "timing.json", "duration_evidence.json", "qa_exposure_manifest.json"}:
            structured.append((src,dest))
    original_by_destination = {dest: src for src,dest in copied.items()}
    metadata_targets = {dest for _,dest in structured}
    for src,dest in structured:
        value = read_object(dest)
        updated = rewrite(value, src.parent)
        if updated!=value:
            _atomic_json(dest, updated)
            relocated.append(dest.relative_to(output).as_posix())
    # Refresh only metadata rewritten by this copy, after checking original bindings.
    def refresh(value):
        if isinstance(value, dict):
            obj = {k: refresh(v) for k,v in value.items()}
            target = output/obj["path"] if isinstance(obj.get("path"), str) and not Path(obj["path"]).is_absolute() else None
            if target in metadata_targets and "sha256" in obj:
                obj["sha256"] = _sha256(target)
            return obj
        if isinstance(value, list):
            return [refresh(x) for x in value]
        return value
    ordered = sorted(structured, key=lambda pair: pair[1].name=="comparison_summary.json")
    for _,dest in ordered:
        value = read_object(dest)
        updated = refresh(value)
        if updated!=value:
            _atomic_json(dest, updated)
    report = check(output)
    return {"status": "assembled", "package_root": str(output.resolve()), "copied_files": len(copied),
            "excluded_work_files": excluded, "relocated_metadata": relocated, "format_check": report,
            "note": "按明确来源组装；仍须处理格式问题及独立 QA，不自动压缩或重跑实验"}
