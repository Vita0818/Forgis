from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Any

from migration_units import MigrationPlan, MigrationUnit, UNIT_STATUSES, sanitize_unit_paths
from repair_report import sanitize_failure_summary, sanitize_text


DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS = 100
MAX_PLAN_EVENT_LOG_MAX_EVENTS = 500
MAX_EVENT_REASON_CHARS = 280
MAX_EVENT_MESSAGE_CHARS = 280
MAX_RESUME_CHANGED_PATHS = 8
SECRET_ID_WORDS = re.compile(r"(?i)(secret|token|credential|password|api[_-]?key|private)")

PLAN_EVENT_TYPES = {
    "plan_loaded",
    "plan_generated",
    "active_unit_selected",
    "active_unit_updated",
    "active_unit_switch_requested",
    "active_unit_switch_succeeded",
    "active_unit_switch_rejected",
    "active_unit_switch_skipped",
    "unit_status_update_requested",
    "unit_status_update_succeeded",
    "unit_status_update_rejected",
    "unit_status_update_skipped",
    "unit_completed",
    "unit_blocked",
    "unit_deferred",
    "plan_write_succeeded",
    "plan_write_failed",
    "resume_summary_generated",
}
BLOCKING_CHECK_STATUSES = {"rejected", "timeout", "blocked"}
FAILED_CHECK_STATUSES = {"failed", "rejected", "timeout", "blocked"}
SUCCESS_CHECK_STATUSES = {"success"}
SKIPPED_CHECK_STATUSES = {"skipped"}
MANUAL_UNIT_STATUSES = {"completed", "blocked", "deferred", "active"}
MANUAL_UNIT_REASON_REQUIRED_STATUSES = {"completed", "blocked", "deferred"}
BLOCKING_STOPPED_REASONS = {
    "blocked",
    "max_attempts_reached",
    "diff_gate_violation",
    "diff gate violation",
}


@dataclasses.dataclass(frozen=True)
class UnitStateUpdateResult:
    update_status: str
    status_before: str
    status_after: str
    reason: str
    event_type: str = "active_unit_updated"
    fields_changed: bool = False
    status_changed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class SwitchDecision:
    status: str
    previous_active_unit_id: str = ""
    requested_active_unit_id: str = ""
    active_unit_id: str = ""
    reason: str = ""
    message: str = ""
    target_status: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class SwitchResult:
    status: str
    previous_active_unit_id: str = ""
    requested_active_unit_id: str = ""
    active_unit_id: str = ""
    reason: str = ""
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class UnitStatusUpdateDecision:
    status: str
    unit_id: str = ""
    previous_status: str = ""
    requested_status: str = ""
    final_status: str = ""
    reason: str = ""
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class UnitStatusUpdateResult:
    status: str
    unit_id: str = ""
    previous_status: str = ""
    requested_status: str = ""
    final_status: str = ""
    reason: str = ""
    message: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def event_log_limit(value: Any) -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS
    return max(0, min(limit, MAX_PLAN_EVENT_LOG_MAX_EVENTS))


def _now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _safe_event_type(value: Any) -> str:
    text = sanitize_text(value or "active_unit_updated", limit=80)
    return text if text in PLAN_EVENT_TYPES else "active_unit_updated"


def _safe_status(value: Any) -> str:
    text = sanitize_text(value or "", limit=40).casefold()
    return text if text in UNIT_STATUSES else ""


def _safe_event_unit_id(value: Any) -> str:
    text = sanitize_text(value or "", limit=120)
    text = SECRET_ID_WORDS.sub("redacted", text)
    return sanitize_text(text, limit=120)


def _safe_order(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _next_event_order(plan: MigrationPlan) -> int:
    orders = [_safe_order(event.get("order")) for event in plan.events if isinstance(event, dict)]
    return (max(orders) if orders else 0) + 1


def safe_plan_event(event: Any) -> dict[str, Any] | None:
    if not isinstance(event, dict):
        return None
    event_type = _safe_event_type(event.get("event_type"))
    timestamp = sanitize_text(event.get("timestamp") or "", limit=40)
    return {
        "event_type": event_type,
        "unit_id": _safe_event_unit_id(event.get("unit_id")),
        "requested_unit_id": _safe_event_unit_id(event.get("requested_unit_id")),
        "previous_active_unit_id": _safe_event_unit_id(event.get("previous_active_unit_id")),
        "active_unit_id": _safe_event_unit_id(event.get("active_unit_id")),
        "status_before": _safe_status(event.get("status_before")),
        "status_after": _safe_status(event.get("status_after")),
        "previous_status": _safe_status(event.get("previous_status") or event.get("status_before")),
        "requested_status": sanitize_text(event.get("requested_status") or "", limit=40).casefold(),
        "final_status": _safe_status(event.get("final_status") or event.get("status_after")),
        "reason": sanitize_text(event.get("reason") or "", limit=MAX_EVENT_REASON_CHARS),
        "short_message": sanitize_text(event.get("short_message") or "", limit=MAX_EVENT_MESSAGE_CHARS),
        "order": _safe_order(event.get("order")),
        "timestamp": timestamp,
    }


def safe_plan_events(events: Any, *, max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS) -> list[dict[str, Any]]:
    if not isinstance(events, list):
        return []
    limit = event_log_limit(max_events)
    if limit <= 0:
        return []
    selected = events[-limit:]
    safe: list[dict[str, Any]] = []
    for event in selected:
        clean = safe_plan_event(event)
        if clean is not None:
            safe.append(clean)
    return safe


def append_plan_event(
    plan: MigrationPlan,
    event_type: str,
    *,
    unit_id: str = "",
    requested_unit_id: str = "",
    previous_active_unit_id: str = "",
    active_unit_id: str = "",
    status_before: str = "",
    status_after: str = "",
    previous_status: str = "",
    requested_status: str = "",
    final_status: str = "",
    reason: str = "",
    short_message: str = "",
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> dict[str, Any]:
    event = {
        "event_type": event_type,
        "unit_id": unit_id,
        "requested_unit_id": requested_unit_id,
        "previous_active_unit_id": previous_active_unit_id,
        "active_unit_id": active_unit_id,
        "status_before": status_before,
        "status_after": status_after,
        "previous_status": previous_status or status_before,
        "requested_status": requested_status,
        "final_status": final_status or status_after,
        "reason": reason,
        "short_message": short_message,
        "order": _next_event_order(plan),
        "timestamp": _now_iso(),
    }
    clean = safe_plan_event(event) or {
        "event_type": "active_unit_updated",
        "unit_id": "",
        "requested_unit_id": "",
        "previous_active_unit_id": "",
        "active_unit_id": "",
        "status_before": "",
        "status_after": "",
        "previous_status": "",
        "requested_status": "",
        "final_status": "",
        "reason": "",
        "short_message": "",
        "order": _next_event_order(plan),
        "timestamp": _now_iso(),
    }
    plan.events.append(clean)
    limit = event_log_limit(max_events)
    if limit <= 0:
        plan.events = []
    elif len(plan.events) > limit:
        del plan.events[: len(plan.events) - limit]
    return clean


def _switch_result_dict(
    *,
    status: str = "skipped",
    requested_active_unit_id: str = "",
    previous_active_unit_id: str = "",
    active_unit_id: str = "",
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    return {
        "status": sanitize_text(status or "skipped", limit=40),
        "requested_active_unit_id": _safe_event_unit_id(requested_active_unit_id),
        "previous_active_unit_id": _safe_event_unit_id(previous_active_unit_id),
        "active_unit_id": _safe_event_unit_id(active_unit_id),
        "reason": sanitize_text(reason or "", limit=MAX_EVENT_REASON_CHARS),
        "message": sanitize_text(message or "", limit=MAX_EVENT_MESSAGE_CHARS),
    }


def safe_active_unit_switch_result(value: Any) -> dict[str, Any]:
    if isinstance(value, SwitchResult):
        value = value.as_dict()
    if not isinstance(value, dict):
        return _switch_result_dict()
    status = sanitize_text(value.get("status") or "skipped", limit=40).casefold()
    if status not in {"switched", "skipped", "rejected"}:
        status = "skipped"
    return _switch_result_dict(
        status=status,
        requested_active_unit_id=value.get("requested_active_unit_id") or value.get("requested_unit_id") or "",
        previous_active_unit_id=value.get("previous_active_unit_id") or "",
        active_unit_id=value.get("active_unit_id") or "",
        reason=value.get("reason") or "",
        message=value.get("message") or value.get("short_message") or "",
    )


def _unit_status_update_result_dict(
    *,
    status: str = "skipped",
    unit_id: str = "",
    previous_status: str = "",
    requested_status: str = "",
    final_status: str = "",
    reason: str = "",
    message: str = "",
) -> dict[str, Any]:
    clean_status = sanitize_text(status or "skipped", limit=40).casefold()
    if clean_status not in {"updated", "skipped", "rejected"}:
        clean_status = "skipped"
    requested = sanitize_text(requested_status or "", limit=40).casefold()
    return {
        "status": clean_status,
        "unit_id": _safe_event_unit_id(unit_id),
        "previous_status": _safe_status(previous_status),
        "requested_status": requested if requested in MANUAL_UNIT_STATUSES else sanitize_text(requested, limit=40),
        "final_status": _safe_status(final_status),
        "reason": sanitize_text(reason or "", limit=MAX_EVENT_REASON_CHARS),
        "message": sanitize_text(message or "", limit=MAX_EVENT_MESSAGE_CHARS),
    }


def safe_unit_status_update_result(value: Any) -> dict[str, Any]:
    if isinstance(value, (UnitStatusUpdateResult, UnitStatusUpdateDecision)):
        value = value.as_dict()
    if not isinstance(value, dict):
        return _unit_status_update_result_dict()
    return _unit_status_update_result_dict(
        status=value.get("status") or "skipped",
        unit_id=value.get("unit_id") or value.get("requested_unit_id") or "",
        previous_status=value.get("previous_status") or value.get("status_before") or "",
        requested_status=value.get("requested_status") or "",
        final_status=value.get("final_status") or value.get("status_after") or "",
        reason=value.get("reason") or "",
        message=value.get("message") or value.get("short_message") or "",
    )


def _requested_switch_id(value: Any) -> str:
    return sanitize_text(value or "", limit=120).strip()


def _requested_status(value: Any) -> str:
    return sanitize_text(value or "", limit=40).casefold().strip()


def _status_update_reason(config: Any, reason: str = "", requested_status: str = "") -> str:
    configured = getattr(config, "migration_plan_requested_unit_status_reason", "")
    clean = sanitize_text(reason or configured or "", limit=MAX_EVENT_REASON_CHARS)
    if clean:
        return clean
    if requested_status == "active":
        return "Manual migration unit activation requested by configuration."
    return ""


def _allow_manual_status_update(config: Any, requested_status: str) -> bool:
    if requested_status == "completed":
        return bool(getattr(config, "migration_plan_allow_manual_complete", True))
    if requested_status == "blocked":
        return bool(getattr(config, "migration_plan_allow_manual_block", True))
    if requested_status == "deferred":
        return bool(getattr(config, "migration_plan_allow_manual_defer", True))
    if requested_status == "active":
        return bool(getattr(config, "migration_plan_allow_manual_activate", True))
    return False


def _manual_status_allow_name(requested_status: str) -> str:
    return {
        "completed": "migration_plan_allow_manual_complete",
        "blocked": "migration_plan_allow_manual_block",
        "deferred": "migration_plan_allow_manual_defer",
        "active": "migration_plan_allow_manual_activate",
    }.get(requested_status, "migration_plan_allow_manual_*")


def validate_manual_unit_status_update(
    plan: MigrationPlan | None,
    unit_id: str,
    requested_status: str,
    config: Any,
    reason: str = "",
    *,
    resume_loaded: bool = False,
) -> UnitStatusUpdateDecision:
    requested_unit_id = _requested_switch_id(unit_id)
    target_status = _requested_status(requested_status)
    clean_reason = _status_update_reason(config, reason, target_status)
    if not requested_unit_id or not target_status:
        return UnitStatusUpdateDecision(
            status="skipped",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason or "No manual migration unit status update was requested.",
            message="Manual unit status update requires both unit id and requested status.",
        )
    if target_status not in MANUAL_UNIT_STATUSES:
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason,
            message="Requested migration unit status must be one of: active, blocked, completed, deferred.",
        )
    if not bool(getattr(config, "migration_scheduler_enabled", False)):
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason,
            message="Manual unit status update requires migration_scheduler_enabled=true.",
        )
    if plan is None:
        return UnitStatusUpdateDecision(
            status="skipped",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason,
            message="No migration plan is available for manual unit status update.",
        )
    if not isinstance(plan, MigrationPlan):
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason,
            message="Manual unit status update requires a valid migration plan.",
        )
    if bool(getattr(config, "migration_plan_status_update_requires_resume", True)) and not resume_loaded:
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason,
            message="Manual unit status update requires a successfully loaded resumed migration plan.",
        )
    target: MigrationUnit | None = None
    for unit in plan.units:
        if unit.unit_id == requested_unit_id:
            target = unit
            break
    if target is None:
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            requested_status=target_status,
            reason=clean_reason,
            message="Requested migration unit id was not found in the plan.",
        )
    if target_status in MANUAL_UNIT_REASON_REQUIRED_STATUSES and not clean_reason:
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            previous_status=target.status,
            requested_status=target_status,
            final_status=target.status,
            reason=clean_reason,
            message=f"Manual status update to {target_status} requires a non-empty reason.",
        )
    if not _allow_manual_status_update(config, target_status):
        return UnitStatusUpdateDecision(
            status="rejected",
            unit_id=requested_unit_id,
            previous_status=target.status,
            requested_status=target_status,
            final_status=target.status,
            reason=clean_reason,
            message=f"{_manual_status_allow_name(target_status)} is false for requested status {target_status}.",
        )
    active_id = _current_active_id(plan)
    reason_matches = (clean_reason == target.reason) or (target_status == "active" and not reason and bool(target.reason))
    active_already_selected = target_status != "active" or active_id == target.unit_id
    if target.status == target_status and reason_matches and active_already_selected:
        return UnitStatusUpdateDecision(
            status="skipped",
            unit_id=target.unit_id,
            previous_status=target.status,
            requested_status=target_status,
            final_status=target.status,
            reason=clean_reason or target.reason,
            message="Requested migration unit already has this status and reason.",
        )
    return UnitStatusUpdateDecision(
        status="allowed",
        unit_id=target.unit_id,
        previous_status=target.status,
        requested_status=target_status,
        final_status=target_status,
        reason=clean_reason,
        message="Requested manual migration unit status update is allowed.",
    )


def _append_unit_status_update_event(
    plan: MigrationPlan,
    event_type: str,
    *,
    result: UnitStatusUpdateResult | UnitStatusUpdateDecision,
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> None:
    append_plan_event(
        plan,
        event_type,
        unit_id=result.unit_id,
        requested_unit_id=result.unit_id,
        active_unit_id=_current_active_id(plan),
        status_before=result.previous_status,
        status_after=result.final_status,
        previous_status=result.previous_status,
        requested_status=result.requested_status,
        final_status=result.final_status,
        reason=result.reason,
        short_message=result.message,
        max_events=max_events,
    )


def request_unit_status_update(
    plan: MigrationPlan | None,
    unit_id: str,
    requested_status: str,
    config: Any,
    reason: str = "",
    *,
    resume_loaded: bool = False,
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> UnitStatusUpdateResult:
    requested_unit_id = _requested_switch_id(unit_id)
    target_status = _requested_status(requested_status)
    clean_reason = _status_update_reason(config, reason, target_status)
    has_request = bool(requested_unit_id or target_status)

    if plan is not None and has_request:
        requested_event = UnitStatusUpdateDecision(
            status="requested",
            unit_id=requested_unit_id,
            requested_status=target_status,
            final_status="",
            reason=clean_reason,
            message="Manual migration unit status update requested.",
        )
        _append_unit_status_update_event(
            plan,
            "unit_status_update_requested",
            result=requested_event,
            max_events=max_events,
        )

    decision = validate_manual_unit_status_update(
        plan,
        requested_unit_id,
        target_status,
        config,
        reason=reason,
        resume_loaded=resume_loaded,
    )

    if plan is None:
        return UnitStatusUpdateResult(
            status=decision.status,
            unit_id=decision.unit_id,
            previous_status=decision.previous_status,
            requested_status=decision.requested_status,
            final_status=decision.final_status,
            reason=decision.reason,
            message=decision.message,
        )

    if decision.status == "skipped":
        result = UnitStatusUpdateResult(
            status="skipped",
            unit_id=decision.unit_id,
            previous_status=decision.previous_status,
            requested_status=decision.requested_status,
            final_status=decision.final_status or decision.previous_status,
            reason=decision.reason,
            message=decision.message,
        )
        if has_request:
            _append_unit_status_update_event(
                plan,
                "unit_status_update_skipped",
                result=result,
                max_events=max_events,
            )
        return result

    if decision.status == "rejected":
        result = UnitStatusUpdateResult(
            status="rejected",
            unit_id=decision.unit_id,
            previous_status=decision.previous_status,
            requested_status=decision.requested_status,
            final_status=decision.final_status or decision.previous_status,
            reason=decision.reason,
            message=decision.message,
        )
        _append_unit_status_update_event(
            plan,
            "unit_status_update_rejected",
            result=result,
            max_events=max_events,
        )
        return result

    target = plan.unit_by_id(decision.unit_id)
    previous_status = target.status
    target.status = decision.requested_status
    if decision.reason:
        target.reason = decision.reason
    if decision.requested_status == "active":
        plan.active_unit_id = target.unit_id
    result = UnitStatusUpdateResult(
        status="updated",
        unit_id=target.unit_id,
        previous_status=previous_status,
        requested_status=decision.requested_status,
        final_status=target.status,
        reason=target.reason,
        message="Manual migration unit status update applied.",
    )
    _append_unit_status_update_event(
        plan,
        "unit_status_update_succeeded",
        result=result,
        max_events=max_events,
    )
    return result


def _switch_reason(config: Any, reason: str = "") -> str:
    configured = getattr(config, "migration_plan_switch_reason", "")
    clean = sanitize_text(reason or configured or "", limit=MAX_EVENT_REASON_CHARS)
    return clean or "Manual active migration unit switch requested by configuration."


def _current_active_id(plan: MigrationPlan | None) -> str:
    if plan is None:
        return ""
    active = plan.active_unit
    return active.unit_id if active is not None else sanitize_text(plan.active_unit_id or "", limit=120)


def _allow_switch_for_status(config: Any, status: str) -> bool:
    if status == "blocked":
        return bool(getattr(config, "migration_plan_allow_switch_from_blocked", True))
    if status == "deferred":
        return bool(getattr(config, "migration_plan_allow_switch_from_deferred", True))
    if status == "completed":
        return bool(getattr(config, "migration_plan_allow_switch_from_completed", False))
    return True


def validate_active_unit_switch(
    plan: MigrationPlan | None,
    requested_unit_id: str,
    config: Any,
    *,
    resume_loaded: bool = False,
    reason: str = "",
) -> SwitchDecision:
    requested = _requested_switch_id(requested_unit_id)
    previous = _current_active_id(plan)
    clean_reason = _switch_reason(config, reason)
    if not requested:
        return SwitchDecision(
            status="skipped",
            previous_active_unit_id=previous,
            requested_active_unit_id="",
            active_unit_id=previous,
            reason="No active migration unit switch was requested.",
            message="No requested active unit id was configured.",
        )
    if not bool(getattr(config, "migration_scheduler_enabled", False)):
        return SwitchDecision(
            status="rejected",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message="Active unit switch requires migration_scheduler_enabled=true.",
        )
    if plan is None:
        return SwitchDecision(
            status="skipped",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message="No migration plan is available for active unit switching.",
        )
    if not isinstance(plan, MigrationPlan):
        return SwitchDecision(
            status="rejected",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message="Active unit switch requires a valid migration plan.",
        )
    if bool(getattr(config, "migration_plan_switch_requires_resume", True)) and not resume_loaded:
        return SwitchDecision(
            status="rejected",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message="Active unit switch requires a successfully loaded resumed migration plan.",
        )
    target: MigrationUnit | None = None
    for unit in plan.units:
        if unit.unit_id == requested:
            target = unit
            break
    if target is None:
        return SwitchDecision(
            status="rejected",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message="Requested active migration unit id was not found in the plan.",
        )
    if previous == target.unit_id:
        return SwitchDecision(
            status="skipped",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message="Requested migration unit is already the active unit.",
            target_status=target.status,
        )
    if not _allow_switch_for_status(config, target.status):
        return SwitchDecision(
            status="rejected",
            previous_active_unit_id=previous,
            requested_active_unit_id=requested,
            active_unit_id=previous,
            reason=clean_reason,
            message=f"Switching to a {target.status} migration unit is not allowed by configuration.",
            target_status=target.status,
        )
    return SwitchDecision(
        status="allowed",
        previous_active_unit_id=previous,
        requested_active_unit_id=requested,
        active_unit_id=target.unit_id,
        reason=clean_reason,
        message="Requested active migration unit switch is allowed.",
        target_status=target.status,
    )


def _append_switch_event(
    plan: MigrationPlan,
    event_type: str,
    *,
    result: SwitchResult | SwitchDecision,
    unit_id: str = "",
    status_before: str = "",
    status_after: str = "",
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> None:
    append_plan_event(
        plan,
        event_type,
        unit_id=unit_id or result.requested_active_unit_id,
        requested_unit_id=result.requested_active_unit_id,
        previous_active_unit_id=result.previous_active_unit_id,
        active_unit_id=result.active_unit_id,
        status_before=status_before,
        status_after=status_after,
        reason=result.reason,
        short_message=result.message,
        max_events=max_events,
    )


def request_active_unit_switch(
    plan: MigrationPlan | None,
    requested_unit_id: str,
    config: Any,
    reason: str = "",
    *,
    resume_loaded: bool = False,
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> SwitchResult:
    requested = _requested_switch_id(requested_unit_id)
    previous = _current_active_id(plan)
    if plan is None:
        decision = validate_active_unit_switch(
            plan,
            requested,
            config,
            resume_loaded=resume_loaded,
            reason=reason,
        )
        return SwitchResult(
            status=decision.status,
            previous_active_unit_id=decision.previous_active_unit_id,
            requested_active_unit_id=decision.requested_active_unit_id,
            active_unit_id=decision.active_unit_id,
            reason=decision.reason,
            message=decision.message,
        )

    requested_event = SwitchDecision(
        status="requested",
        previous_active_unit_id=previous,
        requested_active_unit_id=requested,
        active_unit_id=previous,
        reason=_switch_reason(config, reason) if requested else "No active migration unit switch was requested.",
        message="Active migration unit switch requested." if requested else "No active migration unit switch requested.",
    )
    _append_switch_event(
        plan,
        "active_unit_switch_requested",
        result=requested_event,
        unit_id=requested,
        status_after=(plan.active_unit.status if plan.active_unit is not None else ""),
        max_events=max_events,
    )

    decision = validate_active_unit_switch(
        plan,
        requested,
        config,
        resume_loaded=resume_loaded,
        reason=reason,
    )
    if decision.status == "skipped":
        result = SwitchResult(
            status="skipped",
            previous_active_unit_id=decision.previous_active_unit_id,
            requested_active_unit_id=decision.requested_active_unit_id,
            active_unit_id=decision.active_unit_id,
            reason=decision.reason,
            message=decision.message,
        )
        _append_switch_event(
            plan,
            "active_unit_switch_skipped",
            result=result,
            unit_id=requested,
            status_before=decision.target_status,
            status_after=decision.target_status,
            max_events=max_events,
        )
        return result
    if decision.status == "rejected":
        result = SwitchResult(
            status="rejected",
            previous_active_unit_id=decision.previous_active_unit_id,
            requested_active_unit_id=decision.requested_active_unit_id,
            active_unit_id=decision.active_unit_id,
            reason=decision.reason,
            message=decision.message,
        )
        _append_switch_event(
            plan,
            "active_unit_switch_rejected",
            result=result,
            unit_id=requested,
            status_before=decision.target_status,
            status_after=decision.target_status,
            max_events=max_events,
        )
        return result

    target = plan.unit_by_id(decision.requested_active_unit_id)
    status_before = target.status
    if target.status != "completed":
        target.transition_to("active", reason=decision.reason)
    elif decision.reason:
        target.reason = decision.reason
    plan.active_unit_id = target.unit_id
    result = SwitchResult(
        status="switched",
        previous_active_unit_id=decision.previous_active_unit_id,
        requested_active_unit_id=decision.requested_active_unit_id,
        active_unit_id=target.unit_id,
        reason=decision.reason,
        message="Active migration unit switched by explicit request.",
    )
    _append_switch_event(
        plan,
        "active_unit_switch_succeeded",
        result=result,
        unit_id=target.unit_id,
        status_before=status_before,
        status_after=target.status,
        max_events=max_events,
    )
    return result


def _normalized_status(value: Any) -> str:
    return sanitize_text(value or "", limit=80).casefold()


def _failure_message(runtime_state: dict[str, Any]) -> str:
    summary = sanitize_failure_summary(runtime_state.get("last_failure_summary"))
    if not summary:
        return ""
    return sanitize_text(summary.get("message") or summary.get("error_type") or "failure", limit=160)


def _runtime_changed_paths(runtime_state: dict[str, Any], unit: MigrationUnit) -> list[str]:
    return sanitize_unit_paths([*(unit.changed_paths or []), *(runtime_state.get("changed_paths") or [])])


def update_active_unit_runtime_fields(
    plan: MigrationPlan,
    runtime_state: dict[str, Any],
    *,
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
    record_event: bool = True,
) -> UnitStateUpdateResult:
    unit = plan.active_unit
    if unit is None:
        return UnitStateUpdateResult(
            update_status="no_active_unit",
            status_before="",
            status_after="",
            reason="No active migration unit is available.",
        )

    before = unit.as_summary()
    unit.changed_paths = _runtime_changed_paths(runtime_state, unit)
    unit.build_status = sanitize_text(runtime_state.get("last_build_status") or unit.build_status, limit=80)
    unit.test_status = sanitize_text(runtime_state.get("last_test_status") or unit.test_status, limit=80)
    summary = sanitize_failure_summary(runtime_state.get("last_failure_summary"))
    if summary:
        unit.last_failure_summary = summary

    fields_changed = unit.as_summary() != before
    reason = "Active unit runtime evidence was refreshed." if fields_changed else "Active unit runtime evidence was unchanged."
    if fields_changed and record_event:
        append_plan_event(
            plan,
            "active_unit_updated",
            unit_id=unit.unit_id,
            status_before=before.get("status", ""),
            status_after=unit.status,
            reason=reason,
            short_message="Runtime changed paths/build/test/failure metadata updated.",
            max_events=max_events,
        )
    return UnitStateUpdateResult(
        update_status="updated" if fields_changed else "unchanged",
        status_before=str(before.get("status") or unit.status),
        status_after=unit.status,
        reason=reason,
        fields_changed=fields_changed,
    )


def _transition_active_unit(
    *,
    plan: MigrationPlan,
    unit: MigrationUnit,
    status_after: str,
    reason: str,
    max_events: int,
) -> UnitStateUpdateResult:
    status_before = unit.status
    clean_reason = sanitize_text(reason, limit=MAX_EVENT_REASON_CHARS)
    if status_after in {"completed", "blocked", "deferred"} and not clean_reason:
        clean_reason = f"Runtime evidence selected status={status_after}."
    if status_after != status_before:
        unit.transition_to(status_after, reason=clean_reason)
    else:
        unit.reason = clean_reason or unit.reason
    event_type = {
        "completed": "unit_completed",
        "blocked": "unit_blocked",
        "deferred": "unit_deferred",
    }.get(status_after, "active_unit_updated")
    append_plan_event(
        plan,
        event_type,
        unit_id=unit.unit_id,
        status_before=status_before,
        status_after=unit.status,
        reason=unit.reason,
        short_message=f"Active unit state is {unit.status}.",
        max_events=max_events,
    )
    return UnitStateUpdateResult(
        update_status="updated" if status_after != status_before or clean_reason else "unchanged",
        status_before=status_before,
        status_after=unit.status,
        reason=unit.reason,
        event_type=event_type,
        status_changed=status_after != status_before,
    )


def update_active_unit_state(
    plan: MigrationPlan,
    runtime_state: dict[str, Any],
    *,
    auto_complete_on_success: bool = False,
    normal_tool_loop_end: bool = False,
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> UnitStateUpdateResult:
    field_result = update_active_unit_runtime_fields(
        plan,
        runtime_state,
        max_events=max_events,
        record_event=False,
    )
    unit = plan.active_unit
    if unit is None:
        return field_result
    if unit.status != "active":
        return UnitStateUpdateResult(
            update_status=field_result.update_status,
            status_before=unit.status,
            status_after=unit.status,
            reason=unit.reason or f"Active unit id points to a {unit.status} unit; preserving existing status.",
            fields_changed=field_result.fields_changed,
        )

    deferred_reason = sanitize_text(runtime_state.get("migration_unit_deferred_reason") or "", limit=MAX_EVENT_REASON_CHARS)
    if deferred_reason:
        return _transition_active_unit(
            plan=plan,
            unit=unit,
            status_after="deferred",
            reason=deferred_reason,
            max_events=max_events,
        )
    if "migration_unit_deferred_reason" in runtime_state and not deferred_reason:
        reason = "Deferred status was requested without a specific reason; keeping unit active."
        unit.reason = reason
        return UnitStateUpdateResult(
            update_status="updated",
            status_before="active",
            status_after="active",
            reason=reason,
            fields_changed=True,
        )

    fatal_reason = sanitize_text(runtime_state.get("fatal_failure_reason") or runtime_state.get("fatal_failure") or "", limit=MAX_EVENT_REASON_CHARS)
    if fatal_reason:
        return _transition_active_unit(
            plan=plan,
            unit=unit,
            status_after="blocked",
            reason=f"Fatal runtime failure: {fatal_reason}",
            max_events=max_events,
        )

    build_status = _normalized_status(runtime_state.get("last_build_status") or unit.build_status)
    test_status = _normalized_status(runtime_state.get("last_test_status") or unit.test_status)
    stopped_reason = _normalized_status(runtime_state.get("stopped_reason"))
    failure_message = _failure_message(runtime_state)

    if stopped_reason in BLOCKING_STOPPED_REASONS:
        return _transition_active_unit(
            plan=plan,
            unit=unit,
            status_after="blocked",
            reason=f"Repair loop stopped with {stopped_reason}: {failure_message or 'manual review required.'}",
            max_events=max_events,
        )
    if any(status in BLOCKING_CHECK_STATUSES for status in (build_status, test_status)):
        check_status = build_status if build_status in BLOCKING_CHECK_STATUSES else test_status
        return _transition_active_unit(
            plan=plan,
            unit=unit,
            status_after="blocked",
            reason=f"Verification was {check_status}: {failure_message or 'runtime cannot continue safely.'}",
            max_events=max_events,
        )
    if any(status == "failed" for status in (build_status, test_status)) and stopped_reason == "max_attempts_reached":
        return _transition_active_unit(
            plan=plan,
            unit=unit,
            status_after="blocked",
            reason=f"Build/test failed and repair loop reached max_attempts_reached: {failure_message or 'manual review required.'}",
            max_events=max_events,
        )

    has_changes = bool(unit.changed_paths)
    verification_success = build_status in SUCCESS_CHECK_STATUSES or test_status in SUCCESS_CHECK_STATUSES
    checks_skipped = build_status in SKIPPED_CHECK_STATUSES and test_status in SKIPPED_CHECK_STATUSES
    has_failure = bool(sanitize_failure_summary(unit.last_failure_summary))
    completed_evidence = has_changes and (
        verification_success
        or (checks_skipped and normal_tool_loop_end and not has_failure and not stopped_reason)
    )
    if completed_evidence:
        if auto_complete_on_success:
            return _transition_active_unit(
                plan=plan,
                unit=unit,
                status_after="completed",
                reason="Runtime evidence shows target changes and verification passed.",
                max_events=max_events,
            )
        reason = "Verification passed with target changes; keeping active until explicit completion because auto_complete_on_success=false."
        unit.reason = sanitize_text(reason, limit=MAX_EVENT_REASON_CHARS)
        append_plan_event(
            plan,
            "active_unit_updated",
            unit_id=unit.unit_id,
            status_before="active",
            status_after="active",
            reason=unit.reason,
            short_message="Verification passed; auto-complete is disabled.",
            max_events=max_events,
        )
        return UnitStateUpdateResult(
            update_status="updated",
            status_before="active",
            status_after="active",
            reason=unit.reason,
            fields_changed=True,
        )

    if has_changes:
        reason = "Target changes exist but completion evidence is incomplete; keeping unit active for verification."
    elif bool(runtime_state.get("read_files")) or bool(runtime_state.get("searched_text")):
        reason = "Relevant files were read or searched but no target changes are verified yet; keeping unit active."
    elif build_status in SKIPPED_CHECK_STATUSES or test_status in SKIPPED_CHECK_STATUSES:
        reason = "Build/test was skipped and completion cannot be proven; keeping unit active."
    else:
        reason = "No runtime evidence is sufficient to complete, block, or defer this unit; keeping unit active."
    previous_reason = unit.reason
    unit.reason = sanitize_text(reason, limit=MAX_EVENT_REASON_CHARS)
    reason_changed = previous_reason != unit.reason
    if field_result.fields_changed or reason_changed:
        append_plan_event(
            plan,
            "active_unit_updated",
            unit_id=unit.unit_id,
            status_before="active",
            status_after="active",
            reason=unit.reason,
            short_message="Active unit remains active after conservative state review.",
            max_events=max_events,
        )
    return UnitStateUpdateResult(
        update_status="updated" if field_result.fields_changed or reason_changed else "unchanged",
        status_before="active",
        status_after="active",
        reason=unit.reason,
        fields_changed=field_result.fields_changed or reason_changed,
    )


def _last_stopped_reason(plan: MigrationPlan, active: MigrationUnit | None) -> str:
    for event in reversed(safe_plan_events(plan.events, max_events=MAX_PLAN_EVENT_LOG_MAX_EVENTS)):
        reason = sanitize_text(event.get("reason") or event.get("short_message") or "", limit=160)
        if reason:
            return reason
    if active is not None:
        if active.reason:
            return sanitize_text(active.reason, limit=160)
        summary = sanitize_failure_summary(active.last_failure_summary)
        if summary:
            return sanitize_text(summary.get("message") or summary.get("error_type") or "", limit=160)
    return ""


def _resume_next_step(plan: MigrationPlan, active: MigrationUnit | None) -> str:
    if active is not None and active.status == "active":
        return "Continue the current active unit."
    if active is not None and active.status == "blocked":
        return "Review the blocked reason manually or switch units explicitly."
    if plan.units and plan.completed_count == len(plan.units):
        return "All units are completed; review the final diff and run full CI."
    if active is None:
        return "Select the next pending unit."
    if active.status == "deferred":
        return "Review the deferred reason before continuing or explicitly select another unit."
    return "Continue with the current plan conservatively."


def _switch_manual_guidance(switch: dict[str, Any]) -> str:
    if switch.get("status") != "rejected":
        return ""
    return (
        "Check that the requested unit id exists, the blocked/deferred/completed switch policy allows it, "
        "migration_plan_resume_enabled is true when required, and migration_scheduler_enabled is true."
    )


def _status_update_manual_guidance(update: dict[str, Any]) -> str:
    if update.get("status") != "rejected":
        return ""
    return (
        "Check that the requested unit id exists, requested status is active/completed/blocked/deferred, "
        "reason is filled for completed/blocked/deferred, resume is enabled and loaded when required, "
        "and the matching allow_manual_* setting permits the update."
    )


def generate_resume_summary(
    plan: MigrationPlan,
    active_unit_switch: SwitchResult | dict[str, Any] | None = None,
    manual_unit_status_update: UnitStatusUpdateResult | dict[str, Any] | None = None,
) -> dict[str, Any]:
    active = plan.active_unit
    counts = plan.counts()
    changed_paths = sanitize_unit_paths(active.changed_paths if active is not None else [], limit=MAX_RESUME_CHANGED_PATHS)
    next_step = _resume_next_step(plan, active)
    status = active.status if active is not None else "none"
    active_id = active.unit_id if active is not None else plan.active_unit_id or ""
    switch = safe_active_unit_switch_result(active_unit_switch)
    status_update = safe_unit_status_update_result(manual_unit_status_update)
    switch_suffix = ""
    if switch.get("requested_active_unit_id") or switch.get("status") in {"switched", "rejected"}:
        switch_suffix = (
            f" Switch requested_unit {switch.get('requested_active_unit_id') or 'none'} "
            f"result {switch.get('status') or 'skipped'}."
        )
        guidance = _switch_manual_guidance(switch)
        if guidance:
            next_step = f"{next_step} {guidance}"
    status_update_suffix = ""
    if status_update.get("unit_id") or status_update.get("status") in {"updated", "rejected"}:
        status_update_suffix = (
            f" Status update unit {status_update.get('unit_id') or 'none'} "
            f"requested {status_update.get('requested_status') or 'none'} "
            f"result {status_update.get('status') or 'skipped'}."
        )
        guidance = _status_update_manual_guidance(status_update)
        if guidance:
            next_step = f"{next_step} {guidance}"
    summary_short = sanitize_text(
        (
            f"Resume plan {plan.plan_id}: active_unit={active_id or 'none'} "
            f"status={status}; completed={counts['completed']} blocked={counts['blocked']} "
            f"deferred={counts['deferred']} pending={counts['pending']} active={counts['active']}. "
            f"Next: {next_step}{switch_suffix}{status_update_suffix}"
        ),
        limit=500,
    )
    return {
        "plan_id": sanitize_text(plan.plan_id, limit=120),
        "active_unit_id": sanitize_text(active_id, limit=120),
        "last_active_unit_status": status,
        "counts": counts,
        "last_stopped_reason": _last_stopped_reason(plan, active),
        "changed_paths": changed_paths,
        "next_step": next_step,
        "summary_short": summary_short,
        "active_unit_switch": switch,
        "switch_manual_guidance": _switch_manual_guidance(switch),
        "manual_unit_status_update": status_update,
        "unit_status_update_manual_guidance": _status_update_manual_guidance(status_update),
    }


def safe_resume_summary(summary: Any) -> dict[str, Any]:
    if not isinstance(summary, dict):
        return {}
    counts = summary.get("counts") if isinstance(summary.get("counts"), dict) else {}
    return {
        "plan_id": sanitize_text(summary.get("plan_id") or "", limit=120),
        "active_unit_id": sanitize_text(summary.get("active_unit_id") or "", limit=120),
        "last_active_unit_status": _safe_status(summary.get("last_active_unit_status")) or "none",
        "counts": {
            "completed": int(counts.get("completed") or 0),
            "blocked": int(counts.get("blocked") or 0),
            "pending": int(counts.get("pending") or 0),
            "deferred": int(counts.get("deferred") or 0),
            "active": int(counts.get("active") or 0),
            "total": int(counts.get("total") or 0),
        },
        "last_stopped_reason": sanitize_text(summary.get("last_stopped_reason") or "", limit=200),
        "changed_paths": sanitize_unit_paths(summary.get("changed_paths") or [], limit=MAX_RESUME_CHANGED_PATHS),
        "next_step": sanitize_text(summary.get("next_step") or "", limit=240),
        "summary_short": sanitize_text(summary.get("summary_short") or "", limit=500),
        "active_unit_switch": safe_active_unit_switch_result(summary.get("active_unit_switch")),
        "switch_manual_guidance": sanitize_text(summary.get("switch_manual_guidance") or "", limit=300),
        "manual_unit_status_update": safe_unit_status_update_result(summary.get("manual_unit_status_update")),
        "unit_status_update_manual_guidance": sanitize_text(
            summary.get("unit_status_update_manual_guidance") or "",
            limit=360,
        ),
    }
