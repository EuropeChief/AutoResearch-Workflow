"""Inspect supplied trajectories/sessions without replaying tools or task code.

Keyword observations are candidates only. The semantic reviewer must establish
policy, action, outcome and affected scores before declaring cheating or leakage.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

import task_fingerprint

MAX_BYTES = 128 * 1024 * 1024
MAX_RECORD_BYTES = 4 * 1024 * 1024
TOOL_TYPES = {"function_call", "custom_tool_call", "tool_call", "tool_use", "web_search_call"}
INFRA_STAGES = {"grader", "hidden_assets", "download", "sandbox_start", "artifact_upload"}


def source_paths(files):
    """Only delivered Agent evidence; never inspect author's own maintenance sessions."""
    selected = []
    for relative in files:
        path = Path(relative)
        if "expert_evidence" not in path.parts or path.suffix.lower() not in (".json", ".jsonl", ".zip", ".gz"):
            continue
        name = path.name.lower()
        if any(word in name for word in ("trajectory", "session", "rollout")):
            selected.append(relative)
    return sorted(selected)


def iter_records(path):
    if path.suffix.lower() not in (".json", ".jsonl"):
        raise ValueError("supplied trajectory/session archive needs safe expansion or an indexed readable copy")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("source exceeds 128 MiB inspection limit; supply indexed chunks")
    if path.suffix.lower() == ".jsonl":
        with path.open("r", encoding="utf-8") as stream:
            for number, raw in enumerate(stream, 1):
                if len(raw.encode("utf-8")) > MAX_RECORD_BYTES:
                    raise ValueError(f"record {number} exceeds 4 MiB")
                if raw.strip():
                    yield f":{number}", json.loads(raw)
    else:
        # Large session files must be JSONL or explicitly split; not silently truncated.
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("JSON source exceeds 16 MiB; supply JSONL or indexed chunks")
        yield "", json.loads(path.read_text(encoding="utf-8"))


def tools_in(node, pointer=""):
    if isinstance(node, list):
        for index, child in enumerate(node):
            yield from tools_in(child, f"{pointer}[{index}]")
    elif isinstance(node, dict):
        kind = node.get("type")
        if kind is not None and not isinstance(kind, str):
            raise ValueError("trajectory/session record type must be a string when supplied")
        function = node.get("function")
        if isinstance(function, dict) and function.get("name"):
            yield pointer, function["name"], function.get("arguments"), node.get("id")
        elif kind in TOOL_TYPES or (node.get("tool_name") and any(k in node for k in ("arguments", "input", "parameters"))):
            name = node.get("name", node.get("tool_name", kind))
            args = node.get("arguments", node.get("input", node.get("parameters")))
            if args is None and kind == "web_search_call" and isinstance(node.get("action"), dict):
                args = node["action"]
            yield pointer, name, args, node.get("call_id", node.get("id"))
        for key, child in node.items():
            if key != "function":
                yield from tools_in(child, f"{pointer}.{key}")


def scan_source(root, relative):
    output = {"path": relative, "status": "readable", "records": 0, "tool_calls": 0,
              "inspectable_tool_calls": 0, "redacted_tool_calls": 0,
              "partial_export": "excerpt" in Path(relative).name.lower(),
              "candidates": [], "error": None}
    try:
        path = task_fingerprint.resolve_file(root, relative)
        for location, record in iter_records(path):
            output["records"] += 1
            for pointer, name, arguments, call_id in tools_in(record):
                output["tool_calls"] += 1
                if arguments is None:
                    output["redacted_tool_calls"] += 1
                    continue
                output["inspectable_tool_calls"] += 1
                text = arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)
                name = str(name)
                hints = []
                if re.search(r"web|search|fetch|browse", name, re.I):
                    hints.append("network_lookup")
                if re.search(r"github\.com|arxiv\.org|git\s+clone|\bcurl\b|\bwget\b|requests\.(?:get|post)|urllib|https?://", text, re.I):
                    hints.append("network_or_download")
                if re.search(r"(?:cat|head|tail|cp|open|read_text|read_bytes|load)\b[^\n]{0,180}(?:/tests/|hidden_assets|reference/)", text, re.I):
                    hints.append("private_asset_access")
                if re.search(r"(?:>|write|unlink|remove|rm\s)[^\n]{0,120}(?:reward\.(?:json|txt)|/tests/)", text, re.I):
                    hints.append("grader_or_reward_write")
                for code in hints:
                    ref = f"{relative}{location}#{pointer or '$'}"
                    output["candidates"].append({"id": f"{ref}:{code}", "code": code, "evidence": [ref],
                                                 "tool": name, "call_id": call_id,
                                                 "summary": "工具调用需要结合任务策略、返回结果和使用方式复核；命中本身不是违规结论。"})
    except (OSError, ValueError, UnicodeError) as exc:
        output.update(status="unreadable", error=str(exc))
    return output


def collect(root, files, fingerprint=None):
    sources = [scan_source(root, path) for path in source_paths(files)]
    return {"status": "manual", "summary": "等待复核轨迹/sessions 的行为、分数有效性和题包绑定。",
            "sources": sources, "candidate_count": sum(len(s["candidates"]) for s in sources),
            "task_fingerprint": fingerprint or {}, "trajectories": [], "evidence": []}


def summary_bindings(root, files):
    bindings, errors = [], []
    for relative in files:
        if Path(relative).name != "run_summary.json" or "expert_evidence" not in Path(relative).parts:
            continue
        try:
            path = task_fingerprint.resolve_file(root, relative)
            if path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("run_summary exceeds 4 MiB")
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("run_summary must be a JSON object")
            agents = data.get("agent_execution", [])
            if not isinstance(agents, list) or not all(isinstance(row, dict) for row in agents):
                raise ValueError("run_summary.agent_execution must be an array of objects")
            common = data.get("task_binding")
            if isinstance(common, dict):
                bindings.append({"binding": dict(common), "scope": "all", "evidence": f"{relative}#task_binding"})
            for index, row in enumerate(agents):
                if isinstance(row, dict) and isinstance(row.get("task_binding"), dict):
                    binding = dict(row["task_binding"])
                    # A ZIP may add a wrapper directory. Stored references remain
                    # relative to the submitted package, not the extraction root.
                    parts = Path(relative).parts
                    base = Path(*parts[:parts.index("expert_evidence")])
                    for key in ("trajectory_path", "start_record"):
                        ref = binding.get(key)
                        if isinstance(ref, str) and not (root / ref).is_file() and (root / base / ref).is_file():
                            binding[key] = (base / ref).as_posix()
                    bindings.append({"binding": binding, "agent_index": index, "evidence": f"{relative}#agent_execution[{index}].task_binding"})
        except (OSError, ValueError, UnicodeError, AttributeError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    return bindings, errors


def apply_review(current, review, overview, root, files, validate_evidence):
    if review is not None and not isinstance(review, dict):
        raise ValueError("trajectory_review must be an object")
    review = review or {}
    rows = review.get("trajectories", [])
    if not isinstance(rows, list):
        raise ValueError("trajectory_review.trajectories must be an array")
    names = [row.get("source_path") for row in rows if isinstance(row, dict)]
    if len(names) != len(rows) or len(names) != len(set(names)):
        raise ValueError("trajectory_review must have unique source_path entries")
    if any(name not in {r.get("source_path") for r in overview} for name in names):
        raise ValueError("trajectory_review source_path must match an overview trajectory")
    available = {path: scan_source(root, path) for path in source_paths(files)}
    additional = review.get("additional_sources", [])
    if not isinstance(additional, list):
        raise ValueError("additional_sources must be an array of supplied tool-record paths")
    for path in additional:
        task_fingerprint.resolve_file(root, path)
        available[path] = scan_source(root, path)
    # Equivalent overview filenames are inspected even if they lack 'trajectory'.
    for trajectory in overview:
        path = trajectory.get("source_path")
        if path and path not in available:
            available[path] = scan_source(root, path)
    sources = list(available.values())
    bindings, binding_errors = summary_bindings(root, files)
    results, reviewed_sources, resolutions = [], set(), set()
    for agent_index, trajectory in enumerate(overview):
        path = trajectory.get("source_path")
        row = next((r for r in rows if r.get("source_path") == path), {})
        refs = validate_evidence(root, row.get("evidence", []), "trajectory_review")
        inspected = row.get("reviewed_sources", [])
        if not isinstance(inspected, list) or any(p not in available for p in inspected):
            raise ValueError("reviewed_sources must reference collected trajectories/sessions")
        reviewed_sources.update(inspected)
        matched = [b for b in bindings if b["binding"].get("trajectory_path") == path
                   or (b.get("agent_index") == agent_index and not b["binding"].get("trajectory_path"))]
        if not matched:
            matched = [b for b in bindings if b.get("scope") == "all"]
        if len(matched) > 1:
            raise ValueError("multiple run_summary bindings identify the same trajectory")
        binding = task_fingerprint.check_binding(root, current["task_fingerprint"], path,
                    matched[0]["binding"] if matched else None, row.get("binding_review"))
        if matched:
            binding["evidence"].append(matched[0]["evidence"])
        findings = row.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError("trajectory findings must be an array")
        invalid, uncertain = False, False
        for finding in findings:
            if not isinstance(finding, dict) or finding.get("classification") not in ("leakage", "cheating", "infra_bug", "allowed", "suspicious"):
                raise ValueError("finding classification must be leakage/cheating/infra_bug/allowed/suspicious")
            if finding.get("certainty") not in ("confirmed", "suspected") or not finding.get("summary"):
                raise ValueError("finding needs confirmed/suspected certainty and a factual summary")
            validate_evidence(root, finding.get("evidence", []), "trajectory finding", required=True)
            formal_refs = finding.get("affected_formal_runs", [])
            if not isinstance(formal_refs, list):
                raise ValueError("affected_formal_runs must be an array of formal result paths")
            for ref in formal_refs:
                path_parts = Path(ref).parts
                if len(path_parts) < 3 or path_parts[-3] not in ("baseline_runs", "reference_runs") or path_parts[-1] != "result.json":
                    raise ValueError("affected_formal_runs must identify formal B/R result.json")
            validate_evidence(root, formal_refs, "affected_formal_runs")
            if finding["classification"] == "infra_bug" and finding.get("stage") not in INFRA_STAGES:
                raise ValueError("infra_bug needs grader/hidden_assets/download/sandbox_start/artifact_upload stage")
            if finding["classification"] != "allowed" and finding.get("score_effect", "unverified") != "none" and (not finding.get("remediation") or not finding.get("acceptance_evidence")):
                raise ValueError("finding requires actionable repair and acceptance evidence")
            affected = finding.get("affected_rounds", [])
            if not isinstance(affected, list) or any(isinstance(n, bool) or not isinstance(n, int) or n < 1 for n in affected):
                raise ValueError("affected_rounds must contain positive round numbers")
            effect = finding.get("score_effect", "unverified")
            if effect not in ("invalid", "unverified", "none"):
                raise ValueError("score_effect must be invalid/unverified/none")
            if finding["classification"] in ("leakage", "cheating") and finding["certainty"] == "confirmed" and effect != "invalid":
                raise ValueError("confirmed leakage/cheating must invalidate affected scores")
            invalid |= effect == "invalid" and finding["certainty"] == "confirmed"
            uncertain |= effect == "unverified"
            ids = finding.get("candidate_ids", [])
            known = {c["id"] for source in sources for c in source["candidates"]}
            if not isinstance(ids, list) or any(i not in known for i in ids):
                raise ValueError("finding candidate_ids must identify collected observations")
            resolutions.update(ids)
        score = row.get("score_status", "unverified")
        if score not in ("valid", "invalid", "unverified"):
            raise ValueError("score_status must be valid/invalid/unverified")
        if score == "invalid" and (not refs or not row.get("summary")):
            raise ValueError("an invalid score conclusion needs a factual summary and evidence")
        behavior = row.get("behavior_review", {})
        score_review = row.get("score_review", {})
        candidate_ids = {c["id"] for p in inspected for c in available[p]["candidates"]}
        unresolved = candidate_ids - resolutions
        coverage = sum(available[p]["inspectable_tool_calls"] for p in inspected)
        partial = any(available[p]["redacted_tool_calls"] or available[p]["partial_export"] for p in inspected)
        readable = path in inspected and all(available[p]["status"] == "readable" for p in inspected)
        behavior_ok = isinstance(behavior, dict) and behavior.get("status") == "pass" and readable and not unresolved
        if behavior_ok:
            validate_evidence(root, behavior.get("evidence", []), "behavior_review", required=True)
            if not behavior.get("summary"):
                raise ValueError("behavior_review needs policy/action/outcome explanation")
            if partial and not behavior.get("equivalent_evidence"):
                behavior_ok = False  # Supplied but redacted sessions need a targeted explanation.
            elif partial:
                validate_evidence(root, behavior["equivalent_evidence"], "equivalent behavior evidence", required=True)
        score_ok = isinstance(score_review, dict) and score_review.get("status") == "pass" and bool(score_review.get("summary"))
        if score_ok:
            validate_evidence(root, score_review.get("evidence", []), "score_review", required=True)
        content_status = "fail" if invalid or score == "invalid" else "pass" if score == "valid" and behavior_ok and score_ok and not uncertain else "manual"
        if invalid or binding["status"] == "fail":
            score = "invalid"
        elif uncertain or not behavior_ok or not score_ok or binding["status"] != "pass":
            if score != "invalid":
                score = "unverified"
        status = "fail" if score == "invalid" else "pass" if score == "valid" else "manual"
        gaps = []
        if not behavior_ok:
            gaps.append("工具行为未确认")
        if not score_ok:
            gaps.append("评分来源未确认")
        if binding["status"] != "pass":
            gaps.append("run_summary 题包哈希缺失或待确认" if binding["status"] == "manual" else "题包绑定冲突")
        if uncertain:
            gaps.append("评分影响待确认")
        if row.get("score_status", "unverified") == "unverified":
            gaps.append("分数有效性待确认")
        status_summary = "分数无效" if score == "invalid" else "分数有效" if score == "valid" else "、".join(gaps) or "分数有效性待确认"
        content_gaps = [g for g in gaps if g not in ("run_summary 题包哈希缺失或待确认", "题包绑定冲突")]
        content_summary = "所交轨迹内容已审" if content_status == "pass" else "分数存在已确认无效问题" if content_status == "fail" else "、".join(content_gaps)
        results.append({"source_path": path, "name": trajectory["name"], "status": status, "score_status": score,
                        "content_status": content_status,
                        "content_summary": content_summary,
                        "scope_note": "仅审查已交轮次/方法摘要；未提供工具调用或sessions，结论限于这些材料。" if not coverage and not partial else "已审查提供的工具记录及轨迹。",
                        "status_summary": status_summary,
                        "coverage": "partial_tool_calls" if partial else "tool_calls" if coverage else "rounds_only", "reviewed_sources": inspected,
                        "unresolved_candidates": sorted(unresolved), "task_binding": binding,
                        "findings": findings, "behavior_review": behavior, "score_review": score_review,
                        "summary": row.get("summary", "尚未核实行为与可信评分链；缺少工具记录时不能断言无作弊。"),
                        "evidence": list(dict.fromkeys(refs + binding["evidence"]))})
    unused = sorted(set(available) - reviewed_sources)
    excluded = review.get("unrelated_sources", [])
    if not isinstance(excluded, list):
        raise ValueError("unrelated_sources must be an array")
    for row in excluded:
        if not isinstance(row, dict) or row.get("path") not in available or not row.get("summary"):
            raise ValueError("unrelated source exclusions need a known path and semantic reason")
        validate_evidence(root, row.get("evidence", []), "unrelated source", required=True)
        if row["path"] in unused:
            unused.remove(row["path"])
    states = {r["status"] for r in results}
    status = "fail" if "fail" in states else "manual" if "manual" in states or unused or binding_errors or not results else "pass"
    content_states = {r["content_status"] for r in results}
    content_status = "fail" if "fail" in content_states else "manual" if "manual" in content_states or unused or not results else "pass"
    invalid_formal = sorted({ref for row in results for finding in row["findings"]
                            if finding["certainty"] == "confirmed" and finding.get("score_effect") == "invalid"
                            for ref in finding.get("affected_formal_runs", [])})
    actions, acceptance = [], []
    for result in results:
        if result["content_status"] == "pass":
            continue
        affected = [finding for finding in result["findings"] if finding.get("score_effect") != "none"
                    and finding["classification"] != "allowed"]
        for finding in affected:
            rounds = "、".join(str(n) for n in finding.get("affected_rounds", [])) or "所列"
            actions.append(f"{result['name']} 第{rounds}轮：{finding['summary']}；{finding['remediation']}")
            acceptance.append(finding["acceptance_evidence"])
        if not affected and result["content_status"] == "manual":
            actions.append(f"{result['name']}（{result['source_path']}）：{result['content_summary']}；引用该组已有轮次、代码或评分日志解释具体疑点。只核对所交材料，不要求补交未提供的sessions。")
            acceptance.append("所列疑点的代码/日志位置与说明一致；成功分数来源、失败状态和最佳候选能够对应。")
    if unused:
        actions.append("审查已经提供的记录：" + "、".join(unused) + "；无关材料需注明对应关系及排除理由。")
        acceptance.append("提供的记录已审或附有可核对的无关说明。")
    return {**current, "sources": sources, "status": status, "content_status": content_status,
            "content_summary": "；".join(r["name"] + "：" + r["content_summary"] for r in results) + ("；已交记录尚待审查：" + "、".join(unused) if unused else ""),
            "trajectories": results, "unreviewed_sources": unused,
            "invalid_formal_run_paths": invalid_formal,
            "binding_errors": binding_errors, "summary": "；".join(r["name"] + "：" + r["status_summary"] for r in results),
            "evidence": list(dict.fromkeys(ref for r in results for ref in r["evidence"])),
            "remediation": "；".join(actions),
            "acceptance_evidence": "；".join(dict.fromkeys(acceptance))}
