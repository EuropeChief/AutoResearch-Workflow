"""Scoped project notice; a warning records an unverified fact, never a PASS."""
NOTICE = "qa-relaxation-20261021"
REVISION = "v0.3.10+project-notices.20261021"
SCOPES = {
    "TASK_FINGERPRINT": {"QA21"},
    "NOP_EVIDENCE": {"H06", "QA17"},
    "HARDWARE_RECHECK": {"G02", "G03", "QA03", "QA13", "QA15"},
}


def advisory(value, code):
    if code not in SCOPES:
        raise ValueError("unknown project advisory")
    return {**value, "status": "warn", "advisory_code": code, "policy_notice": NOTICE}


def allowed(row, check_id=None):
    return (row.get("status") == "warn" and row.get("policy_notice") == NOTICE
            and (check_id or row.get("id")) in SCOPES.get(row.get("advisory_code"), set()))


def aggregate(rows):
    states = {r["status"] for r in rows}
    return next((s for s in ("fail", "manual", "warn") if s in states), "pass")
