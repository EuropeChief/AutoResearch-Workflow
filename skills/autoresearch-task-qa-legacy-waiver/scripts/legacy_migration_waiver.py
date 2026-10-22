#!/usr/bin/env python3
"""Reviewer-controlled legacy format/config migration waivers; no task execution.

Original v0.3.10 checks remain unchanged. This sidecar verifies report integrity
and explicit coverage, not the historical scientific truth of reviewer claims.
An opt-in worksheet must be outside the submitted artifact.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import tomllib

import audit_collection
import content_gates
import evidence_refs
import implementation_review as strict_qa
import task_fingerprint

PROFILE = "legacy-format-migration-v2"
CAUSE_TARGETS = {
    "target_gpu_record_gap": {"G03", "QA03", "QA13", "QA15"},
    "new_standard_validation_dependency": {"G03", "QA03", "QA13"},
    "new_resource_evidence_gap": {"QA15"},
    "new_trajectory_schema_gap": {"QA18", "QA21"},
    "new_trajectory_run_metadata_gap": {"QA18", "QA21"},
    "new_task_binding_requirement": {"QA21"},
    "unsupported_network_policy_transition": {"QA05", "H02"},
    "internal_image_preparation_pending": {"H03", "H05"},
    "new_current_trial_requirement": {"H05", "H06"},
    "gpu_candidate_list_compatibility": {"H02", "QA15"},
}
CONTEXT_ASSERTIONS = (
    "prepared_by_reviewer_not_submission", "legacy_requirements_met_in_waiver_scope",
    "scope_only_format_config_migration", "historical_results_not_relabelled",
    "no_substantive_faults_in_waiver_scope",
)
PROTECTED_ASSERTIONS = (
    "method_data_metric_and_scoring_unchanged", "historical_scores_not_fabricated_or_relabelled",
    "no_confirmed_cheating_leakage_or_score_failure", "current_delivery_format_checked",
)
MAX_JSON_BYTES = 32 * 1024 * 1024
RUN_METADATA_REQUIREMENTS = {"max_reasoning_level_record", "same_prompt_task_dev_resource_record",
                             "independent_output_start_record", "model_runtime_settings_record"}


def schema_gap_details(report, root):
    """Distinguish missing NEW round fields from already-required old content."""
    found, original_fault = False, False
    for observation in report.get("format_alignment", {}).get("reviewed_trajectories", []):
        issues = observation.get("alignment_issues", [])
        if not issues:
            continue
        try:
            data = load_json(evidence_refs.resolve_ref(root, observation["path"]))
            rounds = data.get("rounds")
            if not isinstance(rounds, list) or not rounds:
                original_fault = True
                continue
            previous = 0
            for row in rounds:
                if (not isinstance(row, dict) or isinstance(row.get("round"), bool)
                        or not isinstance(row.get("round"), int) or row["round"] <= previous
                        or not isinstance(row.get("method_summary"), str) or not row["method_summary"].strip()):
                    original_fault = True
                    break
                previous = row["round"]
            if any(issue.get("code") != "MISSING_TRAJECTORY_FIELDS" for issue in issues):
                original_fault = True
            else:
                found = True
        except (OSError, ValueError, KeyError, UnicodeError):
            original_fault = True
    return found and not original_fault, original_fault


def validation_dependency_present(report):
    harbor = report.get("harbor", {})
    if any(row.get("id") in {"H03", "H05", "H06"} and row.get("status") in {"manual", "fail"}
           for row in harbor.get("checks", [])):
        return True
    if any(row.get("code") in {"capability_unreviewed", "capability_semantic_review"}
           and row.get("status") in {"manual", "fail"}
           for row in harbor.get("deployment_contract", {}).get("findings", [])):
        return True
    return any(row.get("task_binding", {}).get("status") != "pass"
               for row in report.get("trajectory_review", {}).get("trajectories", []))


def candidate_compatibility_present(report):
    for env in report.get("harbor", {}).get("deployment_contract", {}).get("effective_environments", {}).values():
        if not isinstance(env, dict) or not env.get("gpus"):
            continue
        types = env.get("gpu_types")
        if isinstance(types, list) and types and all(isinstance(value, str) and value.strip() for value in types):
            normalized = {value.strip().upper() for value in types}
            if normalized & {"H20", "L20"} and normalized - {"H20", "L20"}:
                return True
    return False


def digest_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def summary_sha256(row):
    return digest_text(row["summary"])


def load_json(path):
    if path.stat().st_size > MAX_JSON_BYTES:
        raise ValueError("JSON exceeds the sidecar reading limit: " + path.name)
    def finite(value):
        raise ValueError("non-finite JSON constant: " + value)
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON key: " + key)
            out[key] = value
        return out
    result = json.loads(path.read_text(encoding="utf-8"), parse_constant=finite, object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("expected a JSON object: " + path.name)
    return result


def evidence(root, refs, label):
    if not isinstance(refs, list) or not refs:
        raise ValueError(label + " requires existing evidence")
    for ref in refs:
        resolved = evidence_refs.resolve_ref(root, ref)
        name = ref.split("#", 1)[0]
        if ":" in name and name.rsplit(":", 1)[1].replace("-", "").isdigit():
            name = name.rsplit(":", 1)[0]
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(label + " has an unsafe evidence path")
        if any((root / part).is_symlink() for part in (relative, *relative.parents) if part != Path(".")):
            raise ValueError(label + " contains a submitted symlink")
        if not resolved.stat().st_size:
            raise ValueError(label + " refers to an empty file")
    return refs


def by_id(rows, target):
    matches = [r for r in rows if isinstance(r, dict) and r.get("id") == target]
    if len(matches) != 1:
        raise ValueError("expected exactly one " + target)
    return matches[0]


def target_row(report, target):
    if target.startswith("QA"):
        return by_id(report["checks"], target)
    if target.startswith("H"):
        return by_id(report["harbor"]["checks"], target)
    return by_id(report["content_gates"]["checks"], target)


def normalize(report):
    result = copy.deepcopy(report)
    for key in ("generated_at", "source", "workspace_root"):
        result.pop(key, None)
    return result


def validate_strict(report, review, root):
    issues = audit_collection.validate_report(report)
    if issues:
        raise ValueError("strict report contract: " + "; ".join(issues[:5]))
    if report.get("inspection_error"):
        raise ValueError("strict input/review inspection did not complete: " + str(report["inspection_error"]))
    if report.get("review", {}).get("stage") != "semantic_review":
        raise ValueError("complete the original semantic review before applying waivers")
    rebuilt = strict_qa.build_report(root, root, strict_qa.inventory(root))
    rebuilt = strict_qa.apply_review(rebuilt, copy.deepcopy(review), root)
    if normalize(rebuilt) != normalize(report):
        raise ValueError("strict report does not match the supplied review and artifact; regenerate the strict report")


def causes_for(target):
    return sorted(code for code, targets in CAUSE_TARGETS.items() if target in targets)


def collect_findings(report, review, root):
    """Produce a stable blocking-atom ledger, including original repair fields.

    A reviewer must account for each owned atom; a whole QA17 waiver is never an
    input option. Protected atoms have no eligible cause and cannot be covered.
    """
    findings = []
    def add(key, owners, status, summary, source=None, codes=None, protected=None):
        if status not in {"fail", "manual", "warn"}:
            return
        allowed = sorted(set(codes if codes is not None else
                             (code for owner in owners for code in causes_for(owner))))
        item = {"key": key, "owners": owners, "status": status, "summary": str(summary),
                "summary_sha256": digest_text(str(summary)), "eligible_causes": [] if protected else allowed,
                "protected_reason": protected}
        if isinstance(source, dict):
            for field in ("evidence", "remediation", "acceptance_evidence"):
                if field in source:
                    item[field] = copy.deepcopy(source[field])
        findings.append(item)
    for group, rows in (("checks", report["checks"]), ("gates", report["content_gates"]["checks"]),
                        ("harbor", report["harbor"]["checks"])):
        for row in rows:
            if row["id"] == "QA17":
                continue  # Derived only after every Harbor child is accounted for.
            protect = None
            if row["id"] == "G03":
                numeric = content_gates.assess_improvement(report["overview"]["baseline_reference"], row.get("assessment"))
                semantic = by_id(review["content_gates"]["checks"], "G03")
                if numeric["status"] != "pass" or semantic["status"] == "fail":
                    protect = "G03 numerical/quality/protocol failure is not a target-GPU record gap"
            if row["id"] in {"QA03", "QA13", "QA18", "QA21"} and by_id(review["checks"], row["id"])["status"] == "fail":
                protect = "original semantic FAIL must be resolved or classified separately; it cannot be hidden by a migration assertion"
            add(group + "/" + row["id"], [row["id"]], row["status"], row["summary"], row, protected=protect)
    harbor = report["harbor"]
    deployment = harbor.get("deployment_contract", {})
    for index, row in enumerate(deployment.get("findings", [])):
        code = row.get("code", "unknown")
        owners = ["QA05", "H02"] if row.get("category") == "constraint" else ["H03"] if row.get("category") == "compose" else ["H02", "QA15"]
        allowed = (["unsupported_network_policy_transition"] if code in {"capability_unreviewed", "capability_semantic_review"} else
                   ["gpu_candidate_list_compatibility"] if code == "gpu_type_unsupported" and candidate_compatibility_present(report) else [])
        add(f"deployment/{index}/{code}", owners, row.get("status"), row.get("message", ""), row,
            codes=allowed, protected=None if allowed else "current unsupported/malformed configuration must be repaired")
    contract = harbor.get("path_contract", {})
    resolved = by_id(harbor["checks"], "H03")["status"] == "pass"
    for index, row in enumerate(contract.get("findings", [])):
        if row.get("status") == "manual" and resolved:
            continue
        code = row.get("code", "unknown")
        allowed = ["internal_image_preparation_pending"] if code in {
            "prebuilt_image", "prebuilt_or_compose_verifier", "verifier_prebuilt_image", "verifier_prebuilt_or_compose_verifier"} else []
        add(f"paths/{index}/{code}", ["H03"], row.get("status"), row.get("message", ""), row, codes=allowed,
            protected=None if allowed and row.get("status") != "fail" else "Dockerfile/context/COPY/entry or unresolved non-image path issue must be repaired")
    for key in ("artifact_contract", "hidden_review"):
        data = harbor.get(key, {})
        add("harbor/" + key, ["H02"] if key == "artifact_contract" else ["H01"], data.get("status", "manual"),
            data.get("summary", "not reviewed"), data, codes=[], protected="submission transfer and Hidden grading requirements remain applicable")
    resource = report.get("resource_review", {})
    add("resource/status", ["QA15"], resource.get("status", "manual"), resource.get("summary", ""), resource)
    hardware = resource.get("hardware_review", {})
    add("resource/hardware/status", ["QA15"], hardware.get("status", "manual"), hardware.get("summary", ""), hardware,
        codes=["target_gpu_record_gap", "new_resource_evidence_gap", "gpu_candidate_list_compatibility"])
    add("resource/hardware/score_status", ["QA15"], hardware.get("score_status", "manual"), hardware.get("summary", ""), hardware,
        codes=["target_gpu_record_gap"])
    for category in ("problems", "gaps", "observation_conflicts", "parse_errors"):
        for index, value in enumerate(resource.get(category, [])):
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
            protected = None
            if category == "parse_errors" and isinstance(value, dict) and isinstance(value.get("path"), str):
                try:
                    source = evidence_refs.resolve_ref(root, value["path"])
                    payload = source.read_text(encoding="utf-8")
                    try:
                        json.loads(payload)
                    except ValueError:
                        # Readable legacy JSONL is a layout difference; broken
                        # JSON/JSONL is an actual input-format repair.
                        lines = [line for line in payload.splitlines() if line.strip()]
                        if not lines:
                            raise ValueError("empty evidence")
                        for line in lines:
                            json.loads(line)
                except (OSError, ValueError, UnicodeError):
                    protected = "existing resource/run summary evidence is corrupt or unreadable"
            add(f"resource/{category}/{index}", ["QA15"], "fail" if category == "problems" else "manual", text,
                codes=["target_gpu_record_gap", "new_resource_evidence_gap", "gpu_candidate_list_compatibility"], protected=protected)
    estimate = resource.get("estimate") or {}
    estimate_type = estimate.get("gpu_type")
    historical_gpu_measurement = (
        hardware.get("task_type") == "gpu" and hardware.get("score_comparability") in {"unverified", "reused_without_validation"}
        and isinstance(estimate_type, str) and estimate_type.strip()
        and not any(model in estimate_type.upper() for model in ("H20", "L20"))
    )
    # Do not turn an old-card observation into a target-card measurement. A
    # concrete current-target estimate outside the limits remains substantive.
    if not historical_gpu_measurement:
        for field, maximum in (("score_seconds", 7200), ("gpu_count", 8), ("cpu_cores", 64)):
            value = estimate.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > maximum:
                add("resource/current_target_estimate/" + field, ["QA15"], "fail",
                    f"current target estimate {field}={value} exceeds {maximum}", resource, codes=[],
                    protected="explicit current-target resource excess is not missing new evidence")
    integrity = report.get("trajectory_review", {})
    add("trajectory/status", ["QA21"], integrity.get("status", "manual"), integrity.get("summary", ""), integrity,
        codes=["new_task_binding_requirement", "new_trajectory_schema_gap", "new_trajectory_run_metadata_gap"])
    add("trajectory/content_status", ["QA18"], integrity.get("content_status", "manual"), integrity.get("content_summary", ""), integrity,
        codes=["new_trajectory_schema_gap", "new_trajectory_run_metadata_gap"], protected="confirmed invalid trajectory content" if integrity.get("content_status") == "fail" else None)
    for index, row in enumerate(integrity.get("trajectories", [])):
        binding = row.get("task_binding", {})
        basis = binding.get("basis")
        protect = None if basis in {"missing", "hash_missing", "unsupported_profile", "task_hash_mismatch", "fingerprint_unavailable"} else "non-task-version trajectory binding defect"
        add(f"trajectory/{index}/task_binding", ["QA21"], binding.get("status"), binding.get("summary", ""), binding,
            codes=["new_task_binding_requirement"], protected=protect)
        if row.get("content_status") == "fail":
            add(f"trajectory/{index}/invalid_content", ["QA18", "QA21"], "fail", row.get("content_summary", ""), row,
                codes=[], protected="confirmed score/content fault cannot be relabelled as migration")
        for j, finding in enumerate(row.get("findings", [])):
            if finding.get("certainty") == "confirmed" and finding.get("score_effect") == "invalid":
                owners = ["QA18", "QA21"] + (["G03", "QA03", "QA13"] if finding.get("affected_formal_runs") else [])
                add(f"trajectory/{index}/confirmed/{j}", owners, "fail", finding.get("summary", ""), finding,
                    codes=[], protected="confirmed leakage/cheating/scoring failure remains a substantive finding")
    for index, error in enumerate(integrity.get("binding_errors", [])):
        add(f"trajectory/binding_parse/{index}", ["QA21"], "manual", str(error), codes=[], protected="existing run_summary parse error is a format fault, not a new hash requirement")
    for index, path in enumerate(integrity.get("unreviewed_sources", [])):
        add(f"trajectory/unreviewed/{index}", ["QA18"], "manual", path, codes=[], protected="supplied evidence still needs original semantic review")
    actual_new_schema_gap, old_schema_fault = schema_gap_details(report, root)
    for index, observation in enumerate(report.get("format_alignment", {}).get("reviewed_trajectories", [])):
        for j, issue in enumerate(observation.get("alignment_issues", [])):
            code = issue.get("code", "unknown")
            protected = None if code == "MISSING_TRAJECTORY_FIELDS" and actual_new_schema_gap and not old_schema_fault else "missing old round/method_summary or malformed existing trajectory still needs format repair"
            add(f"trajectory_format/{index}/{j}/{code}", ["QA18", "QA21"], issue.get("status", "manual"),
                issue.get("message", ""), issue, codes=["new_trajectory_schema_gap"], protected=protected)
    runtime = report.get("runtime_review") or {}
    add("runtime/status", ["QA16"], runtime.get("status", "manual"), runtime.get("summary", ""), runtime,
        codes=[], protected="runtime/content standards outside the finite migration catalog remain applicable")
    # Structural protections use concrete fields, never suspicious-word regexes.
    selected = harbor.get("task_root")
    task = (root / selected).resolve() if isinstance(selected, str) else None
    if task is None or not task.is_relative_to(root):
        add("current/task_root", ["H01", "H03"], "fail", "current task root is unknown or outside the artifact", codes=[], protected="current package format defect")
    else:
        for name in ("instruction.md", "task.toml"):
            path = task / name
            if not path.is_file() or path.is_symlink() or not path.stat().st_size:
                add("current/missing/" + name, ["H01"], "fail", "missing/empty current core file: " + name, codes=[], protected="current missing file")
        try:
            cfg = tomllib.loads((task / "task.toml").read_text(encoding="utf-8"))
            verifier = cfg.get("verifier", {})
            if not isinstance(verifier, dict) or verifier.get("environment_mode") != "separate":
                add("current/separate", ["H02"], "fail", "current verifier must explicitly use separate", codes=[], protected="current separate format requirement")
            environments = deployment.get("effective_environments", {})
            for role, env in environments.items():
                if not isinstance(env, dict):
                    continue
                for field, maximum in (("gpus", 8), ("cpus", 64)):
                    value = env.get(field, 0)
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= maximum:
                        add(f"current/{role}/{field}", ["H02", "QA15"], "fail", f"current {role}.{field} is invalid or outside limit", codes=[], protected="current declared resource defect")
                count = env.get("gpus", 0)
                if isinstance(count, (int, float)) and not isinstance(count, bool) and count > 0:
                    types = env.get("gpu_types")
                    if (not isinstance(types, list) or not types or not all(isinstance(x, str) and x.strip() for x in types)
                            or not any(x.strip().upper() in {"H20", "L20"} for x in types)):
                        add(f"current/{role}/gpu_types", ["H02", "QA15"], "fail", "current target GPU list must be H20/L20", codes=[], protected="current GPU format/configuration still needs repair")
                if hardware.get("task_type") == "cpu" and isinstance(count, (int, float)) and count > 0:
                    add(f"current/{role}/cpu_with_gpu", ["QA15"], "fail", "CPU task currently requests a GPU", codes=[], protected="CPU task must not add a GPU")
        except (OSError, ValueError, UnicodeError) as exc:
            add("current/toml", ["H02"], "fail", str(exc), codes=[], protected="current TOML must be valid")
    return findings


def protected_review(request, codes):
    data = request.get("protected_review", {})
    if any(data.get(key) is not True for key in PROTECTED_ASSERTIONS) or data.get("other_substantive_causes") != []:
        raise ValueError("reviewer must explicitly confirm protected original requirements and no additional substantive cause in this scope")
    extras = set()
    if "unsupported_network_policy_transition" in codes:
        extras |= {"network_change_is_platform_migration_only", "no_confirmed_historical_score_contamination"}
    if "internal_image_preparation_pending" in codes:
        extras |= {"complete_build_materials_present", "platform_internal_image_work_pending"}
    if "new_current_trial_requirement" in codes:
        extras |= {"current_trial_not_legacy_requirement", "no_confirmed_failed_trial"}
    if "gpu_candidate_list_compatibility" in codes:
        extras |= {"target_selection_is_h20_l20", "no_other_gpu_selected"}
    if any(data.get(key) is not True for key in extras):
        raise ValueError("missing per-cause protection review: " + ", ".join(sorted(extras)))


def internal_build_materials(report, root, request):
    selected = report["harbor"].get("task_root")
    if not isinstance(selected, str):
        raise ValueError("internal image preparation needs a known current source task")
    task = (root / selected).resolve()
    path = task / "environment/Dockerfile"
    if not path.is_file() or path.is_symlink() or not path.stat().st_size:
        source = request.get("source_image_review", {})
        image = source.get("source_image")
        if (request["protected_review"].get("valid_prebuilt_source_image_present") is not True
                or not isinstance(image, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@+\-]*", image)
                or (":" not in image and "@" not in image) or "://" in image
                or any(token in image.upper() for token in ("REPLACE_ME", "YOUR_", "PLACEHOLDER"))
                or not isinstance(source.get("summary"), str) or not source["summary"].strip()):
            raise ValueError("internal image waiver needs a valid Dockerfile or explicitly reviewed reproducible source-image plan")
        evidence(root, source.get("evidence"), "existing source image and dependency/assets plan")
    for row in report["harbor"].get("path_contract", {}).get("findings", []):
        if row.get("status") == "fail":
            raise ValueError("internal image waiver cannot cover failed Docker context/COPY/entry checks")


def check_request(request, report, ledger, root):
    target = request.get("target")
    if not isinstance(target, str) or not causes_for(target):
        raise ValueError("unsupported target; QA17 is derived and cannot be requested directly")
    row = target_row(report, target)
    if row["status"] not in {"fail", "manual"}:
        raise ValueError("waivers only apply to original fail/manual findings")
    if request.get("original_status") != row["status"] or request.get("summary_sha256") != summary_sha256(row):
        raise ValueError("stale original row status/summary SHA-256")
    if request.get("all_blocking_reasons_covered") is not True:
        raise ValueError("compound findings need explicit all_blocking_reasons_covered")
    reasons = request.get("causes")
    if not isinstance(reasons, list) or not reasons or any(not isinstance(r, dict) for r in reasons):
        raise ValueError("supply finite-catalog causes with existing evidence")
    codes = [reason.get("code") for reason in reasons]
    if len(set(codes)) != len(codes) or any(target not in CAUSE_TARGETS.get(code, set()) for code in codes):
        raise ValueError("cause is not supported for this target, or is duplicated")
    for reason in reasons:
        if not isinstance(reason.get("summary"), str) or not reason["summary"].strip():
            raise ValueError("each cause needs a concrete reviewer explanation")
        evidence(root, reason.get("evidence"), target + " cause")
    protected_review(request, codes)
    original_review = by_id(report["checks"], target) if target.startswith("QA") else None
    if "target_gpu_record_gap" in codes:
        hardware = report.get("resource_review", {}).get("hardware_review", {})
        if (hardware.get("task_type") != "gpu" or hardware.get("score_comparability") not in {"unverified", "reused_without_validation"}
                or hardware.get("status") not in {"fail", "manual"}):
            raise ValueError("no actual target-GPU hardware-record gap exists for this cause")
        if target in {"G03", "QA03", "QA13"} and hardware.get("score_status") == "pass":
            raise ValueError("formal score was not downgraded by the target-GPU record gap")
    if "new_standard_validation_dependency" in codes:
        if not validation_dependency_present(report):
            raise ValueError("no actual new-platform/network/binding/Trial validation dependency is present")
        gate = by_id(report["content_gates"]["checks"], "G03")
        numeric = content_gates.assess_improvement(report["overview"]["baseline_reference"], gate.get("assessment"))
        if numeric["status"] != "pass":
            raise ValueError("historical numerical/protocol/quality gate is not passing")
    if "new_trajectory_schema_gap" in codes:
        new_gap, old_fault = schema_gap_details(report, root)
        if not new_gap or old_fault:
            raise ValueError("no pure newly-added trajectory-field gap; old round/method_summary and existing JSON must remain valid")
    if "new_trajectory_run_metadata_gap" in codes:
        metadata = request.get("metadata_gaps")
        if not isinstance(metadata, list) or not metadata or any(not isinstance(item, dict) for item in metadata):
            raise ValueError("new run metadata cause needs explicit field-level missing-record review")
        if request["protected_review"].get("historical_runs_genuinely_independent") is not True:
            raise ValueError("historical run independence must remain confirmed")
        for item in metadata:
            if (item.get("requirement") not in RUN_METADATA_REQUIREMENTS or item.get("state") != "missing_evidence_only"
                    or item.get("legacy_required") is not False or not isinstance(item.get("summary"), str) or not item["summary"].strip()):
                raise ValueError("run metadata cause covers newly-required proof only, not actual non-independence or changed execution")
            evidence(root, item.get("evidence"), "existing historical run metadata")
    if "internal_image_preparation_pending" in codes:
        internal_build_materials(report, root, request)
    if "gpu_candidate_list_compatibility" in codes:
        selection = request.get("gpu_selection_review", {})
        if not candidate_compatibility_present(report):
            raise ValueError("there is no mixed candidate list containing an allowed H20/L20 target")
        if (selection.get("selected_gpu_type") not in {"H20", "L20"} or not isinstance(selection.get("summary"), str)
                or not selection["summary"].strip()):
            raise ValueError("existing target-selection review must specify H20/L20, never a different selected GPU")
        evidence(root, selection.get("evidence"), "existing platform GPU selection agreement/configuration")
    owned = {item["key"]: item for item in ledger if target in item["owners"]}
    coverage = request.get("coverage")
    if not isinstance(coverage, list) or any(not isinstance(x, dict) for x in coverage):
        raise ValueError("coverage must list every original blocking atom")
    if len({item.get("key") for item in coverage}) != len(coverage):
        raise ValueError("duplicate finding coverage")
    if {item.get("key") for item in coverage} != set(owned):
        raise ValueError("coverage must match every owned finding exactly; missing or unrelated atom")
    for item in coverage:
        original = owned[item["key"]]
        if original.get("protected_reason"):
            raise ValueError("protected original finding: " + item["key"] + " — " + original["protected_reason"])
        if item.get("status") != original["status"] or item.get("summary_sha256") != original["summary_sha256"]:
            raise ValueError("stale original finding status/summary SHA-256: " + item["key"])
        if item.get("cause") not in codes or item["cause"] not in original["eligible_causes"]:
            raise ValueError("cause does not cover this original finding: " + item["key"])
        if not isinstance(item.get("summary"), str) or not item["summary"].strip():
            raise ValueError("each covered finding needs a factual migration explanation")
        evidence(root, item.get("evidence"), item["key"] + " coverage")
    return {"target": target, "original_status": row["status"], "original_summary": row["summary"],
            "original_evidence": row.get("evidence", []), "summary_sha256": request["summary_sha256"],
            "effective_status": "waived", "causes": reasons, "coverage": coverage,
            "protected_review": request["protected_review"], "metadata_gaps": request.get("metadata_gaps", []),
            "gpu_selection_review": request.get("gpu_selection_review"), "source_image_review": request.get("source_image_review"),
            "semantics_attested_by_reviewer": True}


def assess(report, review, manifest, root, report_sha, review_sha, *, worksheet_outside_artifact=False):
    root = Path(root).resolve()
    result = {"schema_version": 2, "profile": PROFILE, "generated_at": datetime.now(timezone.utc).isoformat(),
              "strict_decision": report.get("summary", {}).get("decision", "UNKNOWN"), "decision": "INCOMPLETE",
              "strict_report_sha256": report_sha, "review_sha256": review_sha,
              "original_report_modified": False, "this_run_executed_task": False,
              "this_run_executed_harbor": False, "target_hardware_revalidated_by_sidecar": False,
              "historical_scientific_truth_automatically_verified": False,
              "waiver_applied": False, "accepted": [], "rejected": [], "remaining_findings": [],
              "platform_followup_pending": [],
              "integrity_issues": [], "scope_note": "本批旧题按新版框架做格式/配置迁移；豁免依据由审核人逐项确认，不代表已重跑或当前内场已通过。"}
    try:
        validate_strict(report, review, root)
        ledger = collect_findings(report, review, root)
        result["remaining_findings"] = ledger
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        result["integrity_issues"].append(str(exc))
        return result
    if not manifest or manifest.get("enabled") is not True:
        result["decision"] = result["strict_decision"]
        result["scope_note"] += " 本次未启用豁免。"
        return result
    try:
        if not worksheet_outside_artifact:
            raise ValueError("waiver worksheet must be explicitly supplied from reviewer workspace outside the submission")
        if manifest.get("schema_version") != 2 or manifest.get("profile") != PROFILE:
            raise ValueError("explicit legacy-format-migration-v2 profile and schema_version=2 are required")
        if manifest.get("strict_report_sha256") != report_sha or manifest.get("review_sha256") != review_sha:
            raise ValueError("stale strict report/review SHA-256")
        context = manifest.get("reviewer_context", {})
        if any(context.get(key) is not True for key in CONTEXT_ASSERTIONS):
            raise ValueError("reviewer must explicitly confirm every scope-limited migration assertion")
        if not isinstance(context.get("summary"), str) or not context["summary"].strip() or not isinstance(manifest.get("reviewer"), str) or not manifest["reviewer"].strip():
            raise ValueError("identified reviewer and concrete scope summary are required")
        evidence(root, context.get("evidence"), "reviewer migration context")
        requests = manifest.get("requests")
        if not isinstance(requests, list) or not requests or any(not isinstance(r, dict) for r in requests):
            raise ValueError("supply a nonempty list of explicit reviewer requests")
        if len({r.get("target") for r in requests}) != len(requests):
            raise ValueError("duplicate request target")
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        result["rejected"].append({"target": "profile", "reason": str(exc)})
        result["decision"] = "FAIL" if result["strict_decision"] == "FAIL" else "INCOMPLETE"
        return result
    covered = set()
    accepted_targets = set()
    for request in requests:
        try:
            accepted = check_request(request, report, ledger, root)
            result["accepted"].append(accepted)
            accepted_targets.add(accepted["target"])
            covered.update(item["key"] for item in accepted["coverage"])
        except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
            result["rejected"].append({"target": request.get("target"), "reason": str(exc)})
    result["remaining_findings"] = [item for item in ledger if item["key"] not in covered]
    harbor = report["harbor"]
    qa17 = by_id(report["checks"], "QA17")
    children_resolved = all(row["status"] in {"pass", "not_applicable"} or row["id"] in accepted_targets for row in harbor["checks"])
    harbor_remaining = [item for item in result["remaining_findings"] if any(owner.startswith("H") for owner in item["owners"])]
    if qa17["status"] in {"fail", "manual"}:
        if children_resolved and not harbor_remaining and any(t.startswith("H") for t in accepted_targets):
            result["accepted"].append({"target": "QA17", "derived": True, "effective_status": "waived",
                "original_status": qa17["status"], "original_summary": qa17["summary"], "original_evidence": qa17.get("evidence", []),
                "causes": [{"code": "derived_from_harbor_children", "summary": "仅由已逐项核对的 Harbor 子项派生，未将运行状态改为通过。", "evidence": []}], "coverage": []})
        else:
            result["remaining_findings"].append({"key": "checks/QA17", "owners": ["QA17"], "status": qa17["status"],
                "summary": qa17["summary"], "summary_sha256": summary_sha256(qa17), "evidence": qa17.get("evidence", []),
                "remediation": qa17.get("remediation", ""), "acceptance_evidence": qa17.get("acceptance_evidence", ""),
                "eligible_causes": [], "protected_reason": "resolve every Harbor child; whole QA17 waivers are forbidden"})
    result["waiver_applied"] = bool(result["accepted"])
    followups = {
        "target_gpu_record_gap": "平台后续按 H20/L20 核对适用性、资源和必要的运行结果；旧卡记录继续保留原标签。",
        "new_standard_validation_dependency": "平台后续验证当前部署、联网或版本迁移后历史成绩的适用性；本次未证明新环境结果。",
        "new_resource_evidence_gap": "平台后续实跑核对实际资源、耗时与稳定性，不要求专家为本批补造新资源记录。",
        "new_trajectory_schema_gap": "本批保留旧版真实轨迹；新八字段规范用于后续新题，不补造历史字段。",
        "new_trajectory_run_metadata_gap": "后续新运行按新要求留存推理档、Prompt/资源及独立输出的运行级记录。",
        "new_task_binding_requirement": "平台后续运行关联当前题包版本；历史绑定缺口不能被描述为本次已复验。",
        "unsupported_network_policy_transition": "平台后续验证联网及外部查表约束在新环境下的适用性；本批豁免不表示防护已经落实。",
        "internal_image_preparation_pending": "字节内部完成镜像构建/上传/实际选择及内场启动验证，专家无需回填内部镜像地址。",
        "new_current_trial_requirement": "平台后续完成当前版本 Trial/NOP 和独立 Verifier 验证；本批不要求专家补跑旧版未要求的 NOP。",
        "gpu_candidate_list_compatibility": "平台按已有选择约定使用 H20/L20；候选列表兼容不表示本次已在该卡上实跑。",
    }
    selected_causes = {cause["code"] for item in result["accepted"] for cause in item.get("causes", [])}
    result["platform_followup_pending"] = [{"cause": code, "status": "pending_not_executed_by_sidecar", "summary": followups[code]}
                                           for code in sorted(selected_causes) if code in followups]
    result["reviewer"] = manifest["reviewer"]
    result["reviewer_context"] = context
    result["decision"] = ("FAIL" if any(item["status"] == "fail" for item in result["remaining_findings"]) else
                          "INCOMPLETE" if result["remaining_findings"] or result["rejected"] else
                          "PASS_WITH_WAIVERS" if result["accepted"] else "PASS")
    return result


def review_template(report, review, root, report_sha, review_sha):
    ledger = collect_findings(report, review, root)
    targets = sorted({owner for item in ledger for owner in item["owners"] if causes_for(owner)})
    requests = []
    for target in targets:
        row = target_row(report, target)
        if row["status"] not in {"fail", "manual"}:
            continue
        requests.append({"target": target, "original_status": row["status"], "summary_sha256": summary_sha256(row),
            "all_blocking_reasons_covered": False, "protected_review": {**{k: False for k in PROTECTED_ASSERTIONS},
                "other_substantive_causes": ["审核人核对后填写，不得因生成模板自动清空"]},
            "causes": [], "available_causes": causes_for(target),
            "coverage": [{"key": item["key"], "status": item["status"], "summary_sha256": item["summary_sha256"],
                          "cause": "", "summary": "", "evidence": [], "original_summary": item["summary"],
                          "eligible_causes": item["eligible_causes"], "protected_reason": item["protected_reason"]}
                         for item in ledger if target in item["owners"]]})
    return {"schema_version": 2, "profile": PROFILE, "enabled": False, "strict_report_sha256": report_sha,
            "review_sha256": review_sha, "reviewer": "", "reviewer_context": {**{k: False for k in CONTEXT_ASSERTIONS},
                "summary": "", "evidence": []}, "requests": requests,
            "template_note": "审核工作底稿，非专家新增交付；默认关闭，原问题与保护项必须逐项核对，模板不能自动证明可豁免。"}


def render(result):
    lines = ["# 旧题格式与配置迁移豁免复核", "", "本轮结论：" + result["decision"],
             "严格原判：" + result["strict_decision"], "", result["scope_note"], "",
             "本次未运行题目、Docker、Harbor 或模型；没有把旧记录改记为新硬件实测。",
             "审核人负责迁移原因的事实判断，脚本只验证输入关联、逐项覆盖和有限保护项。", ""]
    if result.get("strict_report_path"):
        lines += ["原严格报告：" + result["strict_report_path"], ""]
    lines += ["## 认可的豁免", ""]
    if not result["accepted"]:
        lines.append("- 无。")
    for item in result["accepted"]:
        lines += [f"- {item['target']}：原判 [{item['original_status']}] {item['original_summary']}",
                  "  - 原证据：" + "；".join(item.get("original_evidence", []))]
        for cause in item["causes"]:
            lines += ["  - " + cause["code"] + "：" + cause["summary"],
                      "    依据：" + "；".join(cause.get("evidence", []))]
        for covered in item.get("coverage", []):
            lines += ["  - 覆盖 " + covered["key"] + "：" + covered["summary"],
                      "    依据：" + "；".join(covered.get("evidence", []))]
    lines += ["", "## 保留的原问题", ""]
    if not result["remaining_findings"]:
        lines.append("- 无未覆盖的原问题。")
    for item in result["remaining_findings"]:
        lines.append(f"- [{item['status']}] {item['key']}：{item['summary']}")
        if item.get("evidence"):
            lines.append("  原证据：" + "；".join(item["evidence"]))
        for key, label in (("remediation", "原整改要求"), ("acceptance_evidence", "原验收依据")):
            if item.get(key):
                lines.append("  " + label + "：" + item[key])
    lines += ["", "## 审核人尚未完成的豁免核对", "", "这些是审核工作底稿的问题，不是专家新增必交记录。"]
    lines += [f"- {item['target']}：{item['reason']}" for item in result["rejected"]] or ["- 无。"]
    lines += ["", "## 平台后续验证", ""]
    lines += ["- " + item["summary"] for item in result.get("platform_followup_pending", [])] or ["- 本次没有形成新的平台验证豁免事项。"]
    lines += ["", "## 输入核验异常", ""]
    lines += ["- " + item for item in result["integrity_issues"]] or ["- 无。"]
    return "\n".join(lines) + "\n"


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".legacy-waiver-", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_result(result, out):
    atomic_write(out / "waiver_report.json", json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    text = render(result)
    for name in ("waiver_report.md", "waiver_report.txt"):
        atomic_write(out / name, text)
    # The same faithful detail is kept in expert output; reviewer-only problems
    # are clearly labelled so they cannot become new expert rerun requirements.
    atomic_write(out / "waiver_return_to_expert.txt", text)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--waiver", type=Path)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--template-out", type=Path, help="write a disabled reviewer worksheet template outside all inputs")
    args = parser.parse_args(argv)
    root, out = args.artifact_root.expanduser().resolve(), args.out_dir.expanduser().resolve()
    inputs = [p.expanduser().resolve() for p in (args.report, args.review, args.waiver) if p is not None]
    if not root.is_dir() or out == root or out.is_relative_to(root):
        parser.error("artifact-root must exist; out-dir must be outside the artifact")
    if any(out == p.parent or p == out or p.is_relative_to(out) for p in inputs):
        parser.error("out-dir must not contain or overwrite report/review/worksheet inputs")
    template_path = args.template_out.expanduser().resolve() if args.template_out else None
    if template_path and (template_path.is_relative_to(root) or template_path in inputs):
        parser.error("template-out must be outside the artifact and must not overwrite an input")
    try:
        report, review = load_json(args.report), load_json(args.review)
        manifest = load_json(args.waiver) if args.waiver else None
        report_sha, review_sha = task_fingerprint.sha256_file(args.report), task_fingerprint.sha256_file(args.review)
        trusted = bool(args.waiver and not args.waiver.expanduser().resolve().is_relative_to(root))
        result = assess(report, review, manifest, root, report_sha, review_sha, worksheet_outside_artifact=trusted)
        if template_path:
            if result["integrity_issues"]:
                raise ValueError("cannot prepare a worksheet from an unverified strict report")
            template = review_template(report, review, root, report_sha, review_sha)
            atomic_write(template_path, json.dumps(template, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, UnicodeError) as exc:
        result = {"schema_version": 2, "profile": PROFILE, "decision": "INCOMPLETE", "strict_decision": "UNKNOWN",
                  "scope_note": "输入核验未完成，不能形成豁免通过或专家新增返修结论。", "accepted": [], "rejected": [],
                  "remaining_findings": [], "integrity_issues": [str(exc)], "waiver_applied": False,
                  "original_report_modified": False, "this_run_executed_task": False, "this_run_executed_harbor": False,
                  "target_hardware_revalidated_by_sidecar": False, "historical_scientific_truth_automatically_verified": False}
    result["strict_report_path"] = str(args.report.expanduser().resolve())
    write_result(result, out)
    print(json.dumps({"decision": result["decision"], "waiver_report": str(out / "waiver_report.json")}, ensure_ascii=False))
    return 0 if result["decision"] in {"PASS", "PASS_WITH_WAIVERS"} else 2 if result["integrity_issues"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
