"""Small PCA package/receipt checks, not a Harbor implementation or QA verdict."""
from __future__ import annotations

import math
import re
import stat
import tomllib
from datetime import datetime
from pathlib import Path

from .core import FlowError, _canonical_digest, _read_json, _require, _sha256
from .experiments import evidence
from .runtime_evaluate import TreeError, tree_digest


def task_digest(root: Path) -> str:
    try:
        return tree_digest(root)
    except TreeError as exc:
        raise FlowError(exc.code, str(exc)) from exc


def check_task(root: Path) -> dict:
    """Necessary structural checks; Docker/Harbor execution remains a separate gate."""
    root = Path(root)
    digest = task_digest(root)
    for name in ("instruction.md", "task.toml", "environment/Dockerfile", "tests/Dockerfile", "tests/test.sh"):
        path = root / name
        _require(path.is_file() and path.stat().st_size > 0, "WORKSPACE_SCHEMA", f"任务缺非空 {name}")
    starter = root / "environment/starter"
    _require(starter.is_dir() and any(p.is_file() for p in starter.rglob("*")),
             "WORKSPACE_SCHEMA", "缺 environment/starter 中的真实初始化材料")
    try:
        config = tomllib.loads((root / "task.toml").read_text())
    except (ValueError, OSError) as exc:
        raise FlowError("TASK_TOML_INVALID", "task.toml 解析失败") from exc
    _require(config.get("artifacts") == ["/workspace/solution"], "ARTIFACTS_CONTRACT",
             "artifacts 只能移交 /workspace/solution 候选及必要产物")
    verifier = config.get("verifier")
    _require(isinstance(verifier, dict) and verifier.get("environment_mode") == "separate",
             "VERIFIER_NOT_SEPARATE", "verifier.environment_mode 须为 separate")
    _require(isinstance(config.get("environment"), dict) and isinstance(verifier.get("environment"), dict)
             and isinstance(config.get("agent"), dict), "DUAL_ENVIRONMENT", "须分别声明 Agent/Verifier 环境与 Agent 配置")
    for context in ("environment", "tests"):
        dockerfile = (root / context / "Dockerfile").read_text()
        # Conservative detection of an explicitly invalid source. Not a Docker parser.
        logical = dockerfile.replace("\\\n", " ")
        for line in logical.splitlines():
            if re.match(r"\s*(COPY|ADD)\s", line, re.I):
                _require(not re.search(r"(?:^|[\s\"\'])\.\./", line), "DOCKER_CONTEXT_ESCAPE",
                         f"{context}/Dockerfile 不得 COPY/ADD ../")
    return {"status": "structure_checked_not_execution", "task_sha256": digest,
            "contexts": {"agent": "environment", "verifier": "tests"},
            "pending": ["实际构建", "目标 Harbor 字段生效与移交", "候选权限", "真实评分出分"]}


def check_execution_receipt(root: Path, receipt: dict, task_root: Path, *, final=False,
                            frozen_scoring=False, score_contract_sha256=None, best_method=None) -> dict:
    """Expert-located raw execution evidence; never replaces independent review.

Receipt is an internal workflow document. Its filename is not a platform requirement.
"""
    structural = check_task(task_root)
    _require(isinstance(receipt, dict) and receipt.get("kind") == "harbor_end_to_end"
             and receipt.get("task_sha256") == structural["task_sha256"],
             "HARBOR_EVIDENCE_STALE", "Harbor 实跑须绑定当前完整任务版本")
    for field in ("harbor_version", "provider", "trial_id", "reviewer"):
        _require(isinstance(receipt.get(field), str) and receipt[field].strip(),
                 "HARBOR_EVIDENCE", f"缺少真实 {field}")
    for field in ("agent_image", "verifier_image"):
        _require(isinstance(receipt.get(field), str) and
                 re.fullmatch(r"(?:[^\s]+@)?sha256:[0-9a-f]{64}", receipt[field]),
                 "HARBOR_EVIDENCE", f"{field} 须为不可变镜像标识")
    _require(receipt.get("data_scope") in {"authorized_selftest", "official_hidden"},
             "HIDDEN_AUTHORITY", "须区分授权自验和官方 Hidden")
    evidence(root, receipt.get("data_authorization"))
    command = receipt.get("command")
    _require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command),
             "HARBOR_EVIDENCE", "缺真实 Harbor 调用命令")
    observations = receipt.get("observations")
    required = {"dual_build", "agent_finished", "candidate_transferred", "separate_effective",
                "verifier_self_contained", "candidate_permissions", "trusted_reward"}
    if final or frozen_scoring:
        required.add("frozen_scoring")
        _require(isinstance(score_contract_sha256, str) and re.fullmatch(r"[0-9a-f]{64}", score_contract_sha256)
                 and receipt.get("score_contract_sha256") == score_contract_sha256,
                 "SCORING_RECEIPT_STALE", "实跑须绑定当前冻结评分合同摘要")
    if final:
        required.add("best_restored")
        _require(best_method is not None and receipt.get("best_method_sha256") == task_digest(best_method),
                 "CANDIDATE_RECEIPT_STALE", "最终实跑未绑定本次唯一最佳代码")
        manifest = _read_json(evidence(root, receipt.get("candidate_manifest")))
        files = manifest.get("files")
        _require(manifest.get("root") == "/workspace/solution" and isinstance(files, list) and files,
                 "CANDIDATE_MANIFEST", "缺实际移交候选的文件清单")
        by_path = {}
        for item in files:
            _require(isinstance(item, dict) and isinstance(item.get("path"), str),
                     "CANDIDATE_MANIFEST", "候选清单项缺路径")
            path = Path(item["path"])
            _require(path.parts and not path.is_absolute() and ".." not in path.parts
                     and path.as_posix() == item["path"] and "\\" not in item["path"]
                     and item["path"] not in by_path and re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
                     and type(item.get("size_bytes")) is int and item["size_bytes"] >= 0,
                     "CANDIDATE_MANIFEST", "候选清单路径、哈希或大小非法")
            by_path[item["path"]] = item
        for source in Path(best_method).rglob("*"):
            if source.is_file():
                entry = by_path.get(source.relative_to(best_method).as_posix(), {})
                _require(entry.get("sha256") == _sha256(source) and entry.get("size_bytes") == source.stat().st_size,
                         "CANDIDATE_RECEIPT_STALE", "实际移交清单与最佳代码不一致")
    _require(isinstance(observations, dict) and required <= observations.keys(),
             "HARBOR_EVIDENCE", "缺双镜像/移交/权限/评分链路观察证据")
    for name in sorted(required):
        item = observations[name]
        _require(isinstance(item, dict) and item.get("passed") is True
                 and isinstance(item.get("locator"), str) and item["locator"].strip(),
                 "HARBOR_EVIDENCE", f"{name} 缺明确结论和日志定位")
        path = evidence(root, item.get("evidence"))
        _require(path.stat().st_size > 0, "HARBOR_EVIDENCE", f"{name} 原始证据为空")
    reward_path = evidence(root, receipt.get("reward"))
    try:
        reward = _read_json(reward_path) if reward_path.suffix == ".json" else float(reward_path.read_text().strip())
    except (ValueError, OSError) as exc:
        raise FlowError("REWARD_INVALID", "无法解析真实 reward") from exc
    values = list(reward.values()) if isinstance(reward, dict) else [reward]
    _require(bool(values) and all(type(x) in (int, float) and math.isfinite(x) for x in values),
             "REWARD_INVALID", "reward 须为有限标量或非空数值对象")
    return {"status": "evidence_checked_not_platform_approval", "task_sha256": structural["task_sha256"],
            "trial_id": receipt["trial_id"], "data_scope": receipt["data_scope"],
            "agent_image": receipt["agent_image"], "verifier_image": receipt["verifier_image"],
            "official_hidden_pending": receipt["data_scope"] != "official_hidden",
            "receipt_sha256": _canonical_digest(receipt)}


def check_stability(root: Path, receipt: dict, *, expected_image: str) -> dict:
    """Optional diagnostic under OP-2; a skipped test is never a passed test.

    Keep the actual 12h claim strict when evidence is supplied. This function
    does not start containers or replace runtime health/preflight checks.
    """
    _require(isinstance(receipt, dict) and receipt.get("image") == expected_image,
             "STABILITY_IMAGE", "稳定性证据须匹配本题已验证的 Agent 镜像")
    _require(isinstance(receipt, dict) and type(receipt.get("stable_seconds")) in (int, float)
             and math.isfinite(receipt["stable_seconds"]) and receipt["stable_seconds"] >= 43200
             and isinstance(receipt.get("container_id"), str) and receipt["container_id"]
             and isinstance(receipt.get("image"), str) and receipt["image"]
             and receipt.get("oom_killed") is False and receipt.get("unexpected_exit") is False,
             "STABILITY_EVIDENCE", "须有同一容器至少 12h 无异常的真实证据，不相加两条轨迹时长")
    for key in ("started_at", "observed_at", "reviewer"):
        _require(isinstance(receipt.get(key), str) and receipt[key], "STABILITY_EVIDENCE", f"缺 {key}")
    try:
        start = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(receipt["observed_at"].replace("Z", "+00:00"))
        _require(start.tzinfo is not None and end.tzinfo is not None and
                 abs((end - start).total_seconds() - receipt["stable_seconds"]) < 1,
                 "STABILITY_EVIDENCE", "起止时间与稳定秒数不一致或未写时区")
    except ValueError as exc:
        raise FlowError("STABILITY_EVIDENCE", "稳定性时间戳无效") from exc
    path = evidence(root, receipt.get("evidence"))
    _require(path.stat().st_size > 0, "STABILITY_EVIDENCE", "稳定性原始证据为空")
    return {"status": "evidence_checked_not_stress_test", "stable_seconds": receipt["stable_seconds"],
            "image": receipt["image"], "receipt_sha256": _canonical_digest(receipt)}
