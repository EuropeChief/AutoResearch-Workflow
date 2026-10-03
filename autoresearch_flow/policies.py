"""Versioned task policy, separate from authoritative rules and runtime evidence.

OP-2 makes stability optional; OP-3 admits an evidenced non-training duration
exception. Later features stay disabled. Missing legacy fields remain read-only.
"""
from copy import deepcopy

REVISION = "2026-10-03.op03"
OP02_REVISION = "2026-10-03.op02"
OP01_REVISION = "2026-10-03.op01"
DURATION_SECONDS = {"default_10h": 36000, "non_training_7h": 25200}
DELIVERY_CHECKPOINTS = ("qa_verified", "archives_verified", "form_ready")
LEGACY_POLICY = {
    "schema_version": 1,
    "revision": "legacy-0.2.0",
    "git_required": False,
    "duration_policy": {"mode": "default_10h", "minimum_effective_seconds": 36000},
    "ui_mode": "exec_json",
    "require_stability_receipt": True,
}


def new_policy():
    return deepcopy(LEGACY_POLICY) | {"revision": REVISION, "git_required": True,
                                      "require_stability_receipt": False}


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
    policy = deepcopy(state.get("workflow_policy", LEGACY_POLICY))
    _require(isinstance(policy, dict) and set(policy) == set(LEGACY_POLICY)
             and policy["schema_version"] == 1
             and isinstance(policy["revision"], str)
             and policy["revision"] in {"legacy-0.2.0", OP01_REVISION, OP02_REVISION, REVISION},
             "INVALID_POLICY", "未知工作流政策合同；请使用匹配版本或显式升级")
    validate_duration(policy["duration_policy"])
    _require(type(policy["git_required"]) is bool and type(policy["require_stability_receipt"]) is bool,
             "INVALID_POLICY", "Git 与稳定性门禁字段须为布尔值")
    _require(policy["ui_mode"] == "exec_json"
             and (policy["duration_policy"]["mode"] == "default_10h" or policy["revision"] == REVISION),
             "POLICY_NOT_IMPLEMENTED", "TUI 尚未实施；旧政策不能直接改为 7h")
    if policy["duration_policy"]["mode"] == "non_training_7h":
        _require(isinstance(state.get("duration_assessment"), dict),
                 "DURATION_ASSESSMENT_REQUIRED", "7h 必须先通过 task duration-set 登记证据与确认")
    _require(policy["require_stability_receipt"] == (policy["revision"] in {"legacy-0.2.0", OP01_REVISION}),
             "INVALID_POLICY", "稳定性政策须与修订匹配；旧任务请显式升级，不单独改字段")
    _require(policy["git_required"] == (policy["revision"] != "legacy-0.2.0"),
             "INVALID_POLICY", "当前政策修订的 Git 门禁不能单独关闭；旧任务使用旧政策默认值")
    return policy


def policy_status(state):
    return {"status": "ok", "policy_source": "frozen" if "workflow_policy" in state else "legacy_default",
            "workflow_policy": effective_policy(state),
            "planned_delivery_checkpoints": list(DELIVERY_CHECKPOINTS),
            "pending_implementation": {"tui": "OP-4", "parallel_dispatch": "OP-5",
                                       "three_archives": "OP-6", "form_material": "OP-7"}}
