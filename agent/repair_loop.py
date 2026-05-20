from __future__ import annotations

import dataclasses
from typing import Any

from forgis_config import ResolvedConfig
from repair_report import sanitize_failure_summary, sanitize_paths, sanitize_text


CHECK_TOOLS = {
    "run_build": "build",
    "run_tests": "tests",
}
WRITE_REPAIR_TOOLS = {
    "mkdir",
    "write_file",
    "append_file",
    "delete_file",
    "edit_file",
    "apply_patch",
}
FAILURE_STATUSES = {"failed", "rejected", "timeout"}
DEFAULT_REPAIR_EVENT_LIMIT = 200


@dataclasses.dataclass(frozen=True)
class RepairEvent:
    event_id: int
    event_type: str
    attempt_index: int
    check_type: str
    status: str
    short_message: str
    affected_paths: list[str] = dataclasses.field(default_factory=list)
    failure_summary: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "attempt_index": self.attempt_index,
            "check_type": self.check_type,
            "status": self.status,
            "short_message": self.short_message,
            "affected_paths": list(self.affected_paths),
            "failure_summary": self.failure_summary,
        }


@dataclasses.dataclass
class RepairLoopController:
    """State-only controller plus bounded v3.3 event log for repair loop runs."""

    enabled: bool
    max_attempts: int
    requires_diff_check: bool = True
    requires_build_or_test: bool = True
    stop_on_success: bool = True
    current_attempt: int = 0
    last_check_type: str | None = None
    last_check_status: str | None = None
    last_failure_summary: dict[str, Any] | None = None
    modified_after_failure: bool = False
    diff_checked_after_modification: bool = False
    stopped_reason: str | None = None
    event_log_limit: int = DEFAULT_REPAIR_EVENT_LIMIT
    events: list[RepairEvent] = dataclasses.field(default_factory=list)
    _failure_seen: bool = dataclasses.field(default=False, repr=False)
    _next_event_id: int = dataclasses.field(default=1, repr=False)

    @classmethod
    def from_config(cls, config: ResolvedConfig) -> "RepairLoopController":
        return cls(
            enabled=config.repair_loop_enabled,
            max_attempts=config.max_repair_attempts,
            requires_diff_check=config.repair_requires_diff_check,
            requires_build_or_test=config.repair_requires_build_or_test,
            stop_on_success=config.repair_stop_on_success,
        )

    @property
    def repair_allowed(self) -> bool:
        return (
            self.enabled
            and self._failure_seen
            and self.stopped_reason is None
            and self.current_attempt < self.max_attempts
        )

    def _attempt_index_for_event(self) -> int:
        if self._failure_seen and self.stopped_reason is None and self.current_attempt < self.max_attempts:
            return self.current_attempt + 1
        return self.current_attempt

    def record_event(
        self,
        *,
        event_type: str,
        status: str,
        short_message: str,
        check_type: str | None = None,
        attempt_index: int | None = None,
        affected_paths: list[str] | None = None,
        failure_summary: dict[str, Any] | None = None,
    ) -> None:
        event = RepairEvent(
            event_id=self._next_event_id,
            event_type=sanitize_text(event_type, limit=80),
            attempt_index=self._attempt_index_for_event() if attempt_index is None else max(0, int(attempt_index)),
            check_type=sanitize_text(check_type or "none", limit=40) or "none",
            status=sanitize_text(status, limit=40) or "unknown",
            short_message=sanitize_text(short_message, limit=240),
            affected_paths=sanitize_paths(affected_paths or []),
            failure_summary=sanitize_failure_summary(failure_summary),
        )
        self._next_event_id += 1
        self.events.append(event)
        limit = max(1, int(self.event_log_limit))
        if len(self.events) > limit:
            del self.events[: len(self.events) - limit]

    def events_as_dict(self) -> list[dict[str, Any]]:
        return [event.as_dict() for event in self.events]

    def observe_tool_started(self, *, name: str) -> None:
        if not self.enabled:
            return
        if name not in CHECK_TOOLS:
            return
        check_type = CHECK_TOOLS[name]
        if self._failure_seen and self.modified_after_failure:
            self.record_event(
                event_type="repair_recheck_started",
                check_type=check_type,
                status="success",
                short_message=f"{check_type} recheck started after repair edit.",
            )
        self.record_event(
            event_type=f"{check_type}_started",
            check_type=check_type,
            status="success",
            short_message=f"{check_type} check started.",
        )

    def block_reason_for_tool(self, name: str) -> str | None:
        if not self.enabled:
            return None

        if self.stopped_reason == "max_attempts_reached":
            if name in CHECK_TOOLS:
                return (
                    "repair loop is stopped because max_repair_attempts was reached; "
                    "do not run another build/test repair attempt."
                )
            if name in WRITE_REPAIR_TOOLS:
                return (
                    "repair loop is stopped because max_repair_attempts was reached; "
                    "no further repair edits are allowed."
                )

        if (
            name in CHECK_TOOLS
            and self.requires_diff_check
            and self._failure_seen
            and self.stopped_reason is None
            and self.modified_after_failure
            and not self.diff_checked_after_modification
        ):
            return "repair loop requires git_diff after repair edits before running build/tests again."

        return None

    def final_summary_block_reason(self) -> str | None:
        if not self.enabled or self.stopped_reason is not None:
            return None
        if not self._failure_seen or not self.modified_after_failure:
            return None
        if self.requires_diff_check and not self.diff_checked_after_modification:
            return "repair loop requires git_diff after repair edits before final_summary."
        if self.requires_build_or_test:
            return "repair loop requires run_build or run_tests after repair edits before final_summary."
        return None

    def observe_final_summary_blocked(self, reason: str) -> None:
        self.record_event(
            event_type="repair_blocked",
            status="blocked",
            short_message=self._blocked_event_message(reason),
        )

    def observe_tool_result(self, *, name: str, result: dict[str, Any]) -> None:
        if not self.enabled:
            return
        if name in CHECK_TOOLS:
            self._observe_check(name=name, result=result)
            return
        if name in WRITE_REPAIR_TOOLS and result.get("ok"):
            self._observe_modification(result)
            return
        if name == "git_diff" and result.get("ok"):
            self._observe_diff()

    def _observe_check(self, *, name: str, result: dict[str, Any]) -> None:
        status = str(result.get("status", "unknown"))
        self.last_check_type = CHECK_TOOLS[name]
        self.last_check_status = status
        summary = result.get("summary")
        safe_summary = summary if isinstance(summary, dict) else None
        self.record_event(
            event_type=f"{self.last_check_type}_finished",
            check_type=self.last_check_type,
            status=status,
            short_message=f"{self.last_check_type} check finished with status={status}.",
            failure_summary=safe_summary if status in FAILURE_STATUSES else None,
        )

        if status == "success":
            if self._failure_seen and self.modified_after_failure:
                self.current_attempt = min(self.max_attempts, self.current_attempt + 1)
            if self._failure_seen and self.stop_on_success:
                self.stopped_reason = "success"
                self.record_event(
                    event_type="repair_success",
                    check_type=self.last_check_type,
                    status="success",
                    short_message="repair recheck succeeded.",
                    attempt_index=self.current_attempt,
                )
            return

        if status not in FAILURE_STATUSES:
            return

        self.last_failure_summary = safe_summary
        self.record_event(
            event_type="failure_recorded",
            check_type=self.last_check_type,
            status=status,
            short_message=f"{self.last_check_type} failure recorded.",
            failure_summary=safe_summary,
        )

        if not self._failure_seen:
            self._failure_seen = True
            self.modified_after_failure = False
            self.diff_checked_after_modification = False
            if self.max_attempts <= 0:
                self.stopped_reason = "max_attempts_reached"
                self.record_event(
                    event_type="max_attempts_reached",
                    check_type=self.last_check_type,
                    status="blocked",
                    short_message="max_repair_attempts reached before repair edits.",
                    attempt_index=0,
                    failure_summary=safe_summary,
                )
            elif self.enabled:
                self.record_event(
                    event_type="repair_allowed",
                    check_type=self.last_check_type,
                    status="success",
                    short_message="repair attempt is allowed after failure.",
                    failure_summary=safe_summary,
                )
            else:
                self.record_event(
                    event_type="repair_blocked",
                    check_type=self.last_check_type,
                    status="skipped",
                    short_message="repair_loop_disabled.",
                    attempt_index=0,
                    failure_summary=safe_summary,
                )
            return

        self.current_attempt = min(self.max_attempts, self.current_attempt + 1)
        self.modified_after_failure = False
        self.diff_checked_after_modification = False
        if self.current_attempt >= self.max_attempts:
            self.stopped_reason = "max_attempts_reached"
            self.record_event(
                event_type="max_attempts_reached",
                check_type=self.last_check_type,
                status="blocked",
                short_message="max_repair_attempts reached.",
                attempt_index=self.current_attempt,
                failure_summary=safe_summary,
            )
        elif self.enabled:
            self.record_event(
                event_type="repair_allowed",
                check_type=self.last_check_type,
                status="success",
                short_message="another repair attempt is allowed after failed recheck.",
                failure_summary=safe_summary,
            )

    def _observe_modification(self, result: dict[str, Any]) -> None:
        if not self.repair_allowed:
            return
        self.modified_after_failure = True
        self.diff_checked_after_modification = False
        self.record_event(
            event_type="edit_after_failure",
            check_type=self.last_check_type,
            status="success",
            short_message="target file changed after a failed check.",
            affected_paths=sanitize_paths([result.get("path")]),
        )

    def _observe_diff(self) -> None:
        if not self.repair_allowed or not self.modified_after_failure:
            return
        self.diff_checked_after_modification = True
        self.record_event(
            event_type="diff_checked",
            check_type=self.last_check_type,
            status="success",
            short_message="git_diff inspected after repair edit.",
        )

    def _blocked_event_message(self, reason: str) -> str:
        if "requires git_diff" in reason:
            return "diff_check_required: repair loop requires git_diff before continuing."
        if "max_repair_attempts" in reason:
            return "max_attempts_reached: repair loop is stopped."
        return reason

    def blocked_tool_result(self, name: str, reason: str) -> dict[str, Any]:
        error_type = "diff_check_required" if "requires git_diff" in reason else "repair_loop_blocked"
        if "max_repair_attempts" in reason:
            error_type = "max_attempts_reached"
        self.record_event(
            event_type="repair_blocked",
            check_type=CHECK_TOOLS.get(name, self.last_check_type or "none"),
            status="blocked",
            short_message=self._blocked_event_message(reason),
        )
        return {
            "ok": False,
            "tool": name,
            "status": "blocked",
            "error": reason,
            "summary": {
                "error_type": error_type,
                "status": "blocked",
                "exit_code": None,
                "message": reason,
                "tail": "",
            },
            "repair_loop": self.as_dict(),
        }

    def as_dict(self, *, include_events: bool = False) -> dict[str, Any]:
        data = {
            "repair_loop_enabled": self.enabled,
            "max_repair_attempts": self.max_attempts,
            "repair_attempts_used": self.current_attempt,
            "repair_allowed": self.repair_allowed,
            "repair_success": self.stopped_reason == "success",
            "stopped_reason": self.stopped_reason,
            "last_check_type": self.last_check_type,
            "last_check_status": self.last_check_status,
            "last_failure_summary": self.last_failure_summary,
            "modified_after_failure": self.modified_after_failure,
            "diff_checked_after_modification": self.diff_checked_after_modification,
            "repair_requires_diff_check": self.requires_diff_check,
            "repair_requires_build_or_test": self.requires_build_or_test,
            "repair_stop_on_success": self.stop_on_success,
            "repair_event_count": len(self.events),
        }
        if include_events:
            data["repair_events"] = self.events_as_dict()
        return data
