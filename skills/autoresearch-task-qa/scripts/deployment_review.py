"""Provider capability checks over configuration and cited semantic review only.

Never execute a task or infer a network violation from log keywords. The default
profile describes the current inner-field MASO runner, not all Harbor providers.
"""
import docker_paths

INNERFIELD = "innerfield-maso-v1"
GENERIC = "generic-harbor"
# Execution copy: user-relayed project notice, sources/notices/2026-10-21-gpu.md.
# Submitted target is H20; this does not constrain actual expert hardware.
GPU_TYPES = {"H20"}


def aggregate(statuses):
    return "fail" if "fail" in statuses else "manual" if "manual" in statuses else "pass"


def environments(config):
    cfg = config if isinstance(config, dict) else {}
    agent = cfg.get("environment", {})
    verifier = cfg.get("verifier", {})
    specific = verifier.get("environment") if isinstance(verifier, dict) else None
    return {"agent": agent if isinstance(agent, dict) else {},
            "verifier": specific if isinstance(specific, dict) else agent if isinstance(agent, dict) else {}}


def assess(root, task, config, review, resolve_ref):
    profile = review.get("deployment_profile", INNERFIELD)
    if profile not in (INNERFIELD, GENERIC):
        raise ValueError("deployment_profile must be innerfield-maso-v1 or generic-harbor")
    def cited(value, label):
        if not isinstance(value, dict) or not isinstance(value.get("summary"), str) or not value["summary"].strip():
            raise ValueError(f"{label} requires a semantic summary")
        refs = value.get("evidence")
        if not isinstance(refs, list) or not refs:
            raise ValueError(f"{label} requires existing evidence")
        for ref in refs:
            resolve_ref(root, ref)
        return refs
    basis = review.get("deployment_basis")
    refs = cited(basis, "generic deployment_basis") if profile == GENERIC else []
    cfg = config if isinstance(config, dict) else {}
    envs = environments(config)
    source = (task / "task.toml").relative_to(root.resolve()).as_posix() if task else None
    findings = []
    def finding(code, status, message, category="config", evidence=None):
        findings.append({"code": code, "status": status, "message": message, "category": category,
                         "evidence": evidence if evidence is not None else [source] if source else []})
    if not isinstance(config, dict):
        finding("config_unavailable", "manual", "有效 task.toml 尚未解析，不能确认目标平台能力。")
    selection = docker_paths.image_selection(task, config)
    agent_compose = bool(task and not envs["agent"].get("docker_image")
                         and not (task / "environment/Dockerfile").is_file()
                         and docker_paths.compose_files(task / "environment"))
    compose_review = review.get("compose_review")
    if compose_review is not None:
        compose_refs = cited(compose_review, "compose_review")
        if (compose_review.get("selection") not in ("unused", "selected", "unverified")
                or not isinstance(compose_review.get("roles"), list) or not compose_review["roles"]
                or any(role not in ("agent", "verifier") for role in compose_review["roles"])):
            raise ValueError("compose_review needs selection and agent/verifier roles")
    for role, directory in (("agent", "environment"), ("verifier", "tests")):
        compose_files = docker_paths.compose_files(task / directory) if task else []
        reviewed = compose_review if compose_review and role in compose_review["roles"] else None
        if compose_files:
            finding("compose_unsupported", "fail",
                    f"{role} 正式运行目录含 Compose 文件；默认 implementation 交付禁止 Compose，Dockerfile、预构建镜像或 unused 声明均不豁免。",
                    "compose", [p.relative_to(root.resolve()).as_posix() for p in compose_files])
        elif profile == INNERFIELD and reviewed and reviewed["selection"] == "selected":
            finding("compose_unsupported", "fail", f"{role} 已确认选用 Compose；当前内场 MASO 不支持。", "compose", compose_refs)
    if profile == INNERFIELD:
        for role, env in envs.items():
            if "storage_mb" in env:
                finding("storage_unsupported", "fail", f"{role} 环境声明了内场尚不支持的 storage_mb，不能作为存储限额。", "constraint")
            count = env.get("gpus", 0)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                finding("gpu_count_unresolved", "manual", f"{role} 的有效 gpus 数量无法确定。", "gpu")
            elif count > 0:
                types = env.get("gpu_types")
                if not isinstance(types, list) or not types or not all(isinstance(v, str) and v.strip() for v in types):
                    finding("gpu_types_missing", "manual", f"{role} 申请 GPU 但未明确 gpu_types；最终提交目标须写 H20，实跑设备可自选。", "gpu")
                elif {v.strip().upper() for v in types} != GPU_TYPES:
                    finding("gpu_type_unsupported", "fail", f"{role}.gpu_types={types} 未按项目通知写为 H20；这不是实际用卡限制。", "gpu")
            phase = cfg.get("agent" if role == "agent" else "verifier", {})
            phase = phase if isinstance(phase, dict) else {}
            # Environment startup and the explicit execution phase are separate
            # policy applications; public at run-time does not erase a startup
            # restriction. Do not scan arbitrary env vars or log keywords.
            for stage, policy in (("环境启动", env), ("执行阶段", phase)):
                mode, hosts = policy.get("network_mode"), policy.get("allowed_hosts", [])
                if stage == "环境启动" and mode is None and policy.get("allow_internet") is False:
                    mode = "no-network"  # Known Harbor compatibility field.
                if mode in ("no-network", "allowlist") or hosts:
                    finding("network_constraint_unsupported", "fail", f"{role}{stage}声明禁网/网络白名单，当前内场会 warning 后联网降级，不能声称约束生效。", "constraint")
    capability = review.get("capability_review")
    if capability is None:
        finding("capability_unreviewed", "manual", "尚未语义核对当前交付是否依赖平台未实现约束或仍受 warning/联网降级影响。", "constraint", [])
    else:
        evidence = cited(capability, "capability_review")
        state, outcome = capability.get("status"), capability.get("outcome")
        if state not in ("pass", "manual", "fail") or outcome not in ("effective", "not_required", "unverified", "warning_only", "network_fallback"):
            raise ValueError("capability_review needs status and a supported outcome")
        status = "fail" if state == "fail" or outcome in ("warning_only", "network_fallback") else "pass" if state == "pass" and outcome in ("effective", "not_required") else "manual"
        finding("capability_semantic_review", status, capability["summary"], "constraint", evidence)
    status = aggregate([f["status"] for f in findings])
    config_status = aggregate([f["status"] for f in findings if f["category"] != "compose"])
    constraints = [f for f in findings if f["category"] == "constraint"]
    problem_text = "；".join(f["message"] for f in findings if f["status"] != "pass")
    return {"profile": profile, "status": status, "config_status": config_status,
            "compose_status": aggregate([f["status"] for f in findings if f["category"] == "compose"]),
            "constraint_status": aggregate([f["status"] for f in constraints]),
            "gpu_status": aggregate([f["status"] for f in findings if f["category"] == "gpu"]),
            "innerfield_compliant": profile == INNERFIELD and status == "pass",
            "effective_environments": envs, "image_selection": selection, "agent_compose_selected": agent_compose,
            "config_source": source,
            "compose_review": compose_review,
            "basis": basis, "capability_review": capability, "findings": findings,
            "summary": problem_text or ("当前交付符合内场能力检查；Solver/Verifier 仍须不同 sandbox。" if profile == INNERFIELD else "仅按已声明 provider 复核，不代表内场可交付。"),
            "evidence": list(dict.fromkeys(refs + [r for f in findings for r in f["evidence"]])),
            "remediation": "按所列有效配置移除未支持约束或 Compose；核对现有配置及日志，说明当前仍依赖的限制是否真实生效。历史 warning 已修正时引用现有修正依据。",
            "acceptance_evidence": "当前目标配置及现有说明/日志相互一致；不以 warning 或联网 fallback 作为约束生效证据。"}
