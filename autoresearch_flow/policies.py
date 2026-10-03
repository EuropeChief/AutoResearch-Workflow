"""Current frozen task policy, distinct from rules and implementation status."""
from copy import deepcopy

REVISION = "2026-10-03.public"
DURATION_SECONDS = {"default_10h": 36000, "non_training_7h": 25200}
DELIVERY_CHECKPOINTS = ("qa_verified", "archives_verified", "form_ready")
DEFAULT_POLICY = {
    "schema_version": 1,
    "revision": REVISION,
    "git_required": True,
    "duration_policy": {"mode": "default_10h", "minimum_effective_seconds": 36000},
    "ui_mode": "exec_json",
    "require_stability_receipt": False,
}


def new_policy():
    return deepcopy(DEFAULT_POLICY)


def validate_duration(value):
    from .core import _require
    _require(isinstance(value, dict) and set(value) == {"mode", "minimum_effective_seconds"},
             "INVALID_POLICY", "duration_policy 必须包含 mode 和 minimum_effective_seconds")
    mode = value["mode"]
    _require(isinstance(mode, str) and mode in DURATION_SECONDS
             and type(value["minimum_effective_seconds"]) is int
             and value["minimum_effective_seconds"] == DURATION_SECONDS[mode],
             "INVALID_POLICY", "时长模式与秒数不匹配；默认 36000 秒，合格非训练例外 25200 秒")


def effective_policy(state):
    from .core import _require
    policy = deepcopy(state.get("workflow_policy"))
    _require(isinstance(policy, dict) and set(policy) == set(DEFAULT_POLICY)
             and policy["schema_version"] == 1
             and isinstance(policy["revision"], str)
             and policy["revision"] == REVISION,
             "INVALID_POLICY", "缺少当前冻结政策或版本不匹配；请用任务原版本流程恢复，不自动补旧默认值")
    validate_duration(policy["duration_policy"])
    _require(policy["git_required"] is True and policy["require_stability_receipt"] is False,
             "INVALID_POLICY", "当前政策要求 Git 检查点，专门稳定性收据非必需；不得静默改动政策")
    _require(policy["ui_mode"] == "exec_json", "POLICY_NOT_IMPLEMENTED", "TUI 尚未验收，不可提前启用")
    if policy["duration_policy"]["mode"] == "non_training_7h":
        _require(isinstance(state.get("duration_assessment"), dict),
                 "DURATION_ASSESSMENT_REQUIRED", "7h 必须先通过 task duration-set 登记证据与确认")
    return policy


def policy_status(state):
    return {"status": "ok", "policy_source": "frozen",
            "workflow_policy": effective_policy(state),
            "planned_delivery_checkpoints": list(DELIVERY_CHECKPOINTS),
            "pending_implementation": {"tui": "未验收", "parallel_dispatch": "未实现",
                                       "three_archives": "未实现", "form_material": "未实现"}}
