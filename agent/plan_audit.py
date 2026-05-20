from __future__ import annotations

from typing import Any

from migration_state import (
    MAX_PLAN_EVENT_LOG_MAX_EVENTS,
    safe_active_unit_switch_result,
    safe_plan_events,
    safe_resume_summary,
    safe_unit_status_update_result,
)
from migration_units import MigrationPlan
from repair_report import sanitize_text


DEFAULT_MIGRATION_PLAN_AUDIT_MAX_EVENTS = 10
MAX_MIGRATION_PLAN_AUDIT_MAX_EVENTS = 50

MANUAL_STATUS_ACTION_TYPES = {
    "unit_status_update_requested",
    "unit_status_update_succeeded",
    "unit_status_update_rejected",
    "unit_status_update_skipped",
}
SWITCH_ACTION_TYPES = {
    "active_unit_switch_requested",
    "active_unit_switch_succeeded",
    "active_unit_switch_rejected",
    "active_unit_switch_skipped",
}
UNIT_STATUS_ACTION_TYPES = {"unit_completed", "unit_blocked", "unit_deferred"}
PLAN_IO_ACTION_TYPES = {"plan_loaded", "plan_generated", "plan_write_succeeded", "plan_write_failed"}
KEY_PLAN_ACTION_TYPES = (
    MANUAL_STATUS_ACTION_TYPES
    | SWITCH_ACTION_TYPES
    | UNIT_STATUS_ACTION_TYPES
    | PLAN_IO_ACTION_TYPES
    | {"resume_summary_generated", "active_unit_selected", "active_unit_updated"}
)


def audit_event_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_MIGRATION_PLAN_AUDIT_MAX_EVENTS
    return max(0, min(limit, MAX_MIGRATION_PLAN_AUDIT_MAX_EVENTS))


def _safe_unit_id(value: Any) -> str:
    return sanitize_text(value or "", limit=120)


def _safe_status(value: Any) -> str:
    return sanitize_text(value or "", limit=40).casefold()


def _summary_from_plan(plan: MigrationPlan | None, max_events: int) -> dict[str, Any]:
    if plan is None:
        return {}
    return plan.as_summary(max_units=200, max_events=max(max_events, DEFAULT_MIGRATION_PLAN_AUDIT_MAX_EVENTS))


def _counts(plan_summary: dict[str, Any]) -> dict[str, int]:
    nested = plan_summary.get("counts") if isinstance(plan_summary.get("counts"), dict) else {}

    def pick(name: str) -> int:
        try:
            return int(plan_summary.get(f"{name}_count", nested.get(name, 0)) or 0)
        except (TypeError, ValueError):
            return 0

    total = plan_summary.get("unit_count", nested.get("total", 0))
    try:
        total_count = int(total or 0)
    except (TypeError, ValueError):
        total_count = 0
    return {
        "completed": pick("completed"),
        "blocked": pick("blocked"),
        "pending": pick("pending"),
        "deferred": pick("deferred"),
        "active": pick("active"),
        "total": total_count,
    }


def _active_unit(plan_summary: dict[str, Any]) -> dict[str, Any]:
    active = plan_summary.get("active_unit")
    return dict(active) if isinstance(active, dict) else {}


def _active_unit_id(plan_summary: dict[str, Any]) -> str:
    active = _active_unit(plan_summary)
    return _safe_unit_id(plan_summary.get("active_unit_id") or active.get("unit_id") or "")


def _unit_status(plan_summary: dict[str, Any], unit_id: str) -> str:
    clean_id = _safe_unit_id(unit_id)
    if not clean_id:
        return ""
    active = _active_unit(plan_summary)
    if active.get("unit_id") == clean_id:
        return _safe_status(active.get("status"))
    for unit in plan_summary.get("units") or []:
        if isinstance(unit, dict) and _safe_unit_id(unit.get("unit_id")) == clean_id:
            return _safe_status(unit.get("status"))
    return ""


def migration_plan_recommended_next_action(
    *,
    migration_scheduler_enabled: bool,
    plan_summary: dict[str, Any] | None = None,
) -> str:
    summary = plan_summary if isinstance(plan_summary, dict) else {}
    if not migration_scheduler_enabled:
        return "Enable migration_scheduler_enabled with plan persistence/resume to use plan audit."
    if not summary:
        return "Generate or resume a migration plan before auditing units."

    counts = _counts(summary)
    active = _active_unit(summary)
    active_status = _safe_status(active.get("status"))

    if counts["total"] > 0 and counts["completed"] == counts["total"]:
        return "Review the final diff and run full CI."
    if active_status == "active":
        return "Continue the current active unit or run configured build/test."
    if active_status == "blocked":
        return "Inspect the blocked reason; explicitly switch to a pending unit or mark it deferred."
    if active_status == "deferred":
        return "Resolve the deferred condition, reactivate it, or explicitly switch to a pending unit."
    if active_status == "completed":
        return "Manually switch to the next pending unit; Forgis will not advance automatically."
    if counts["pending"] > 0:
        return "Set migration_plan_requested_active_unit_id to the next pending unit."
    return "Review the migration plan state and choose the next explicit manual action."


def _event_action_status(event: dict[str, Any]) -> str:
    event_type = sanitize_text(event.get("event_type") or "", limit=80)
    if event_type.endswith("_succeeded"):
        return "succeeded"
    if event_type.endswith("_rejected"):
        return "rejected"
    if event_type.endswith("_skipped"):
        return "skipped"
    if event_type.endswith("_requested"):
        return "requested"
    if event_type == "unit_completed":
        return "completed"
    if event_type == "unit_blocked":
        return "blocked"
    if event_type == "unit_deferred":
        return "deferred"
    if event_type == "plan_loaded":
        return "loaded"
    if event_type == "plan_generated":
        return "generated"
    if event_type == "plan_write_succeeded":
        return "written"
    if event_type == "plan_write_failed":
        return "failed"
    if event_type == "resume_summary_generated":
        return "generated"
    return _safe_status(event.get("status_after")) or "recorded"


def _event_priority(event_type: str) -> int:
    if event_type in MANUAL_STATUS_ACTION_TYPES:
        return 20
    if event_type in SWITCH_ACTION_TYPES:
        return 30
    if event_type in UNIT_STATUS_ACTION_TYPES:
        return 40
    if event_type == "resume_summary_generated":
        return 50
    if event_type in PLAN_IO_ACTION_TYPES:
        return 60
    return 70


def _event_unit_id(event: dict[str, Any]) -> str:
    return _safe_unit_id(
        event.get("unit_id")
        or event.get("requested_unit_id")
        or event.get("active_unit_id")
        or event.get("previous_active_unit_id")
    )


def _event_unit_status(event: dict[str, Any]) -> str:
    return _safe_status(event.get("final_status") or event.get("status_after") or event.get("requested_status"))


def _event_record(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "order": int(event.get("order") or 0),
        "timestamp": sanitize_text(event.get("timestamp") or "", limit=40),
        "action_type": sanitize_text(event.get("event_type") or "unknown", limit=80),
        "action_status": _event_action_status(event),
        "unit_id": _event_unit_id(event),
        "unit_status": _event_unit_status(event),
        "reason": sanitize_text(event.get("reason") or "", limit=180),
        "message": sanitize_text(event.get("short_message") or "", limit=180),
    }


def _recent_key_events(events: list[dict[str, Any]], *, max_events: int) -> list[dict[str, Any]]:
    limit = audit_event_limit(max_events)
    if limit <= 0:
        return []
    key_events = [
        event
        for event in safe_plan_events(events, max_events=MAX_PLAN_EVENT_LOG_MAX_EVENTS)
        if sanitize_text(event.get("event_type") or "", limit=80) in KEY_PLAN_ACTION_TYPES
    ]
    key_events.sort(
        key=lambda event: (
            _event_priority(sanitize_text(event.get("event_type") or "", limit=80)),
            -int(event.get("order") or 0),
        )
    )
    return [_event_record(event) for event in key_events[:limit]]


def _manual_status_candidate(update: dict[str, Any]) -> dict[str, Any] | None:
    status = sanitize_text(update.get("status") or "skipped", limit=40).casefold()
    has_request = bool(update.get("unit_id") or update.get("requested_status") or status in {"updated", "rejected"})
    if not has_request:
        return None
    return {
        "priority": 0,
        "order": 0,
        "latest_action_type": "manual_unit_status_update",
        "latest_action_status": status or "skipped",
        "latest_unit_id": _safe_unit_id(update.get("unit_id")),
        "latest_unit_status": _safe_status(update.get("final_status") or update.get("requested_status")),
        "latest_reason": sanitize_text(update.get("reason") or "", limit=220),
        "latest_message": sanitize_text(update.get("message") or "", limit=220),
    }


def _switch_candidate(switch: dict[str, Any], plan_summary: dict[str, Any]) -> dict[str, Any] | None:
    status = sanitize_text(switch.get("status") or "skipped", limit=40).casefold()
    has_request = bool(switch.get("requested_active_unit_id") or status in {"switched", "rejected"})
    if not has_request:
        return None
    unit_id = _safe_unit_id(switch.get("active_unit_id") or switch.get("requested_active_unit_id"))
    return {
        "priority": 1,
        "order": 0,
        "latest_action_type": "active_unit_switch",
        "latest_action_status": status or "skipped",
        "latest_unit_id": unit_id,
        "latest_unit_status": _unit_status(plan_summary, unit_id),
        "latest_reason": sanitize_text(switch.get("reason") or "", limit=220),
        "latest_message": sanitize_text(switch.get("message") or "", limit=220),
    }


def _resume_candidate(resume_summary: dict[str, Any]) -> dict[str, Any] | None:
    if not resume_summary:
        return None
    next_step = sanitize_text(resume_summary.get("next_step") or "", limit=220)
    return {
        "priority": 50,
        "order": 0,
        "latest_action_type": "resume_summary",
        "latest_action_status": "generated",
        "latest_unit_id": _safe_unit_id(resume_summary.get("active_unit_id")),
        "latest_unit_status": _safe_status(resume_summary.get("last_active_unit_status")),
        "latest_reason": next_step,
        "latest_message": sanitize_text(resume_summary.get("summary_short") or "", limit=220),
    }


def _event_candidate(event: dict[str, Any]) -> dict[str, Any]:
    record = _event_record(event)
    return {
        "priority": _event_priority(record["action_type"]),
        "order": -int(record.get("order") or 0),
        "latest_action_type": record["action_type"],
        "latest_action_status": record["action_status"],
        "latest_unit_id": record["unit_id"],
        "latest_unit_status": record["unit_status"],
        "latest_reason": record["reason"],
        "latest_message": record["message"],
    }


def _latest_action(
    *,
    plan_summary: dict[str, Any],
    events: list[dict[str, Any]],
    resume_summary: dict[str, Any],
    active_unit_switch: dict[str, Any],
    manual_unit_status_update: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for candidate in (
        _manual_status_candidate(manual_unit_status_update),
        _switch_candidate(active_unit_switch, plan_summary),
        _resume_candidate(resume_summary),
    ):
        if candidate is not None:
            candidates.append(candidate)
    candidates.extend(
        _event_candidate(event)
        for event in safe_plan_events(events, max_events=MAX_PLAN_EVENT_LOG_MAX_EVENTS)
        if sanitize_text(event.get("event_type") or "", limit=80) in KEY_PLAN_ACTION_TYPES
    )
    if not candidates:
        return {
            "latest_action_type": "none",
            "latest_action_status": "none",
            "latest_unit_id": "",
            "latest_unit_status": "",
            "latest_reason": "",
            "latest_message": "",
        }
    def sort_key(item: dict[str, Any]) -> tuple[int, int]:
        priority = item.get("priority")
        try:
            clean_priority = int(priority if priority is not None else 99)
        except (TypeError, ValueError):
            clean_priority = 99
        try:
            clean_order = int(item.get("order") or 0)
        except (TypeError, ValueError):
            clean_order = 0
        return clean_priority, clean_order

    selected = sorted(candidates, key=sort_key)[0]
    return {
        "latest_action_type": sanitize_text(selected.get("latest_action_type") or "none", limit=80),
        "latest_action_status": sanitize_text(selected.get("latest_action_status") or "none", limit=40),
        "latest_unit_id": _safe_unit_id(selected.get("latest_unit_id")),
        "latest_unit_status": _safe_status(selected.get("latest_unit_status")),
        "latest_reason": sanitize_text(selected.get("latest_reason") or "", limit=220),
        "latest_message": sanitize_text(selected.get("latest_message") or "", limit=220),
    }


def _summary_short(summary: dict[str, Any]) -> str:
    return sanitize_text(
        (
            f"Audit latest {summary['latest_action_type']} status {summary['latest_action_status']} "
            f"unit {summary['latest_unit_id'] or 'none'} active {summary['active_unit_id'] or 'none'} "
            f"counts completed={summary['completed_units_count']} blocked={summary['blocked_units_count']} "
            f"deferred={summary['deferred_units_count']}. "
            f"Next: {summary['recommended_next_action']}"
        ),
        limit=500,
    )


def build_migration_plan_audit_summary(
    *,
    migration_scheduler_enabled: bool,
    plan: MigrationPlan | None = None,
    plan_summary: dict[str, Any] | None = None,
    plan_events: list[dict[str, Any]] | None = None,
    resume_summary: dict[str, Any] | None = None,
    active_unit_switch: dict[str, Any] | None = None,
    manual_unit_status_update: dict[str, Any] | None = None,
    max_events: int = DEFAULT_MIGRATION_PLAN_AUDIT_MAX_EVENTS,
    enabled: bool = True,
) -> dict[str, Any]:
    event_limit = audit_event_limit(max_events)
    summary = dict(plan_summary) if isinstance(plan_summary, dict) else _summary_from_plan(plan, event_limit)
    events = plan_events if isinstance(plan_events, list) else summary.get("events") if isinstance(summary.get("events"), list) else []
    safe_events = safe_plan_events(events, max_events=MAX_PLAN_EVENT_LOG_MAX_EVENTS)
    resume = safe_resume_summary(resume_summary or {})
    switch = safe_active_unit_switch_result(active_unit_switch or {})
    status_update = safe_unit_status_update_result(manual_unit_status_update or {})
    counts = _counts(summary)
    active_id = _active_unit_id(summary)
    recommendation = migration_plan_recommended_next_action(
        migration_scheduler_enabled=bool(migration_scheduler_enabled),
        plan_summary=summary,
    )

    if not enabled:
        output = {
            "enabled": False,
            "status": "disabled",
            "latest_action_type": "none",
            "latest_action_status": "none",
            "latest_unit_id": "",
            "latest_unit_status": "",
            "latest_reason": "",
            "latest_message": "",
            "blocked_units_count": counts["blocked"],
            "deferred_units_count": counts["deferred"],
            "completed_units_count": counts["completed"],
            "active_unit_id": active_id,
            "recommended_next_action": "Enable migration_plan_audit_summary_enabled to generate plan audit.",
            "recent_events": [],
        }
        output["summary_short"] = _summary_short(output)
        return output

    if not migration_scheduler_enabled:
        output = {
            "enabled": True,
            "status": "skipped",
            "latest_action_type": "none",
            "latest_action_status": "none",
            "latest_unit_id": "",
            "latest_unit_status": "",
            "latest_reason": "",
            "latest_message": "",
            "blocked_units_count": 0,
            "deferred_units_count": 0,
            "completed_units_count": 0,
            "active_unit_id": "",
            "recommended_next_action": recommendation,
            "recent_events": [],
        }
        output["summary_short"] = _summary_short(output)
        return output

    latest = _latest_action(
        plan_summary=summary,
        events=safe_events,
        resume_summary=resume,
        active_unit_switch=switch,
        manual_unit_status_update=status_update,
    )
    output = {
        "enabled": True,
        "status": "generated" if summary else "skipped",
        **latest,
        "blocked_units_count": counts["blocked"],
        "deferred_units_count": counts["deferred"],
        "completed_units_count": counts["completed"],
        "active_unit_id": active_id,
        "recommended_next_action": recommendation,
        "recent_events": _recent_key_events(safe_events, max_events=event_limit),
    }
    output["summary_short"] = _summary_short(output)
    return output
