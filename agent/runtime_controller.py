from __future__ import annotations

import dataclasses
from typing import Any

from repair_report import sanitize_path, sanitize_text


READ_OBSERVATION_TOOLS = {
    "read_file",
    "search_text",
}

WRITE_OBSERVATION_TOOLS = {
    "mkdir",
    "write_file",
    "append_file",
    "delete_file",
    "edit_file",
    "apply_patch",
}
CHECK_FAILURE_STATUSES = {"failed", "rejected", "timeout", "blocked"}


@dataclasses.dataclass
class RuntimeController:
    """Small v3 runtime state skeleton layered over the existing tool loop."""

    read_files: bool = False
    searched_text: bool = False
    modified_target_files: bool = False
    viewed_diff: bool = False
    ran_command: bool = False
    ran_build: bool = False
    ran_tests: bool = False
    modified_target_after_failure: bool = False
    read_tool_calls: int = 0
    write_tool_calls: int = 0
    diff_tool_calls: int = 0
    command_tool_calls: int = 0
    build_tool_calls: int = 0
    test_tool_calls: int = 0
    last_build_status: str | None = None
    last_test_status: str | None = None
    last_failure_summary: dict[str, Any] | None = None
    changed_paths: list[str] = dataclasses.field(default_factory=list)
    compact_actions_summary: str = ""
    repair_report_chars: int = 0
    skills_enabled: bool = False
    auto_select_skills: bool = False
    selected_skill_names: list[str] = dataclasses.field(default_factory=list)
    skipped_skill_names: list[str] = dataclasses.field(default_factory=list)
    failed_skill_names: list[str] = dataclasses.field(default_factory=list)
    total_skill_chars: int = 0
    migration_scheduler_enabled: bool = False
    migration_plan_summary: dict[str, Any] = dataclasses.field(default_factory=dict)
    active_migration_unit: dict[str, Any] = dataclasses.field(default_factory=dict)
    active_unit_id: str = ""
    migration_plan_persistence_enabled: bool = False
    migration_plan_resume_enabled: bool = False
    migration_plan_source: str = "skipped"
    migration_plan_path: str = ""
    migration_plan_load_status: str = "skipped"
    migration_plan_load_error: str = ""
    migration_plan_write_status: str = "skipped"
    migration_plan_write_error: str = ""
    plan_update_status: str = "skipped"
    plan_events: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    active_unit_status: str = ""
    active_unit_reason: str = ""
    resume_summary: dict[str, Any] = dataclasses.field(default_factory=dict)
    resume_summary_short: str = ""
    active_unit_switch: dict[str, Any] = dataclasses.field(default_factory=dict)
    migration_plan_switch_status: str = "skipped"
    migration_plan_switch_reason: str = ""
    migration_plan_requested_active_unit_id: str = ""
    migration_plan_previous_active_unit_id: str = ""
    manual_unit_status_update: dict[str, Any] = dataclasses.field(default_factory=dict)
    migration_plan_unit_status_update_status: str = "skipped"
    migration_plan_unit_status_update_reason: str = ""
    migration_plan_unit_status_update_unit_id: str = ""
    migration_plan_unit_status_update_requested_status: str = ""
    migration_plan_unit_status_update_previous_status: str = ""
    migration_plan_unit_status_update_final_status: str = ""
    migration_plan_audit_summary: dict[str, Any] = dataclasses.field(default_factory=dict)
    migration_plan_audit_summary_short: str = ""
    migration_plan_recommended_next_action: str = ""
    _pending_failed_check: bool = dataclasses.field(default=False, repr=False)

    def _add_changed_path(self, value: Any) -> None:
        path = sanitize_path(value)
        if path and path not in self.changed_paths:
            self.changed_paths.append(path)

    def attach_report(self, *, compact_actions_summary: str, report_markdown: str) -> None:
        self.compact_actions_summary = compact_actions_summary
        self.repair_report_chars = len(report_markdown)

    def attach_skills(self, skill_state: dict[str, Any] | None) -> None:
        state = skill_state or {}
        self.skills_enabled = bool(state.get("skills_enabled"))
        self.auto_select_skills = bool(state.get("auto_select_skills"))
        self.selected_skill_names = [str(item) for item in state.get("selected_skill_names") or []]
        self.skipped_skill_names = [str(item) for item in state.get("skipped_skill_names") or []]
        self.failed_skill_names = [str(item) for item in state.get("failed_skill_names") or []]
        self.total_skill_chars = int(state.get("total_skill_chars") or 0)

    def attach_migration_plan(self, plan_summary: dict[str, Any] | None) -> None:
        summary = plan_summary or {}
        self.migration_scheduler_enabled = bool(summary)
        self.migration_plan_summary = dict(summary)
        active = summary.get("active_unit") if isinstance(summary, dict) else None
        self.active_migration_unit = dict(active) if isinstance(active, dict) else {}
        self.active_unit_id = str(summary.get("active_unit_id") or self.active_migration_unit.get("unit_id") or "")
        self.active_unit_status = str(self.active_migration_unit.get("status") or "")
        self.active_unit_reason = sanitize_text(self.active_migration_unit.get("reason") or "", limit=300)
        events = summary.get("events") if isinstance(summary, dict) else []
        self.plan_events = [dict(event) for event in events if isinstance(event, dict)]

    def attach_active_unit_switch(self, switch_state: dict[str, Any] | None) -> None:
        state = switch_state or {}
        status = sanitize_text(state.get("status") or "skipped", limit=40).casefold()
        if status not in {"switched", "skipped", "rejected"}:
            status = "skipped"
        requested = sanitize_text(state.get("requested_active_unit_id") or "", limit=120)
        previous = sanitize_text(state.get("previous_active_unit_id") or "", limit=120)
        active = sanitize_text(state.get("active_unit_id") or "", limit=120)
        reason = sanitize_text(state.get("reason") or "", limit=300)
        message = sanitize_text(state.get("message") or "", limit=300)
        self.active_unit_switch = {
            "status": status,
            "requested_active_unit_id": requested,
            "previous_active_unit_id": previous,
            "active_unit_id": active,
            "reason": reason,
            "message": message,
        }
        self.migration_plan_switch_status = status
        self.migration_plan_switch_reason = reason
        self.migration_plan_requested_active_unit_id = requested
        self.migration_plan_previous_active_unit_id = previous

    def attach_manual_unit_status_update(self, update_state: dict[str, Any] | None) -> None:
        state = update_state or {}
        status = sanitize_text(state.get("status") or "skipped", limit=40).casefold()
        if status not in {"updated", "skipped", "rejected"}:
            status = "skipped"
        unit_id = sanitize_text(state.get("unit_id") or "", limit=120)
        previous_status = sanitize_text(state.get("previous_status") or "", limit=40)
        requested_status = sanitize_text(state.get("requested_status") or "", limit=40)
        final_status = sanitize_text(state.get("final_status") or "", limit=40)
        reason = sanitize_text(state.get("reason") or "", limit=300)
        message = sanitize_text(state.get("message") or "", limit=300)
        self.manual_unit_status_update = {
            "status": status,
            "unit_id": unit_id,
            "previous_status": previous_status,
            "requested_status": requested_status,
            "final_status": final_status,
            "reason": reason,
            "message": message,
        }
        self.migration_plan_unit_status_update_status = status
        self.migration_plan_unit_status_update_reason = reason
        self.migration_plan_unit_status_update_unit_id = unit_id
        self.migration_plan_unit_status_update_requested_status = requested_status
        self.migration_plan_unit_status_update_previous_status = previous_status
        self.migration_plan_unit_status_update_final_status = final_status

    def attach_migration_plan_audit(self, audit_state: dict[str, Any] | None) -> None:
        state = dict(audit_state or {})
        self.migration_plan_audit_summary = state
        self.migration_plan_audit_summary_short = sanitize_text(state.get("summary_short") or "", limit=500)
        self.migration_plan_recommended_next_action = sanitize_text(
            state.get("recommended_next_action") or "",
            limit=300,
        )

    def attach_migration_plan_update(
        self,
        *,
        plan_update_status: str = "",
        resume_summary: dict[str, Any] | None = None,
    ) -> None:
        if plan_update_status:
            self.plan_update_status = sanitize_text(plan_update_status, limit=80) or "skipped"
        if resume_summary:
            self.resume_summary = dict(resume_summary)
            self.resume_summary_short = sanitize_text(resume_summary.get("summary_short") or "", limit=500)

    def attach_migration_plan_persistence(self, state: dict[str, Any] | None) -> None:
        info = state or {}
        self.migration_plan_persistence_enabled = bool(info.get("migration_plan_persistence_enabled"))
        self.migration_plan_resume_enabled = bool(info.get("migration_plan_resume_enabled"))
        self.migration_plan_source = str(info.get("migration_plan_source") or "skipped")
        self.migration_plan_path = sanitize_path(info.get("migration_plan_path"))
        self.migration_plan_load_status = str(info.get("migration_plan_load_status") or "skipped")
        self.migration_plan_load_error = sanitize_text(info.get("migration_plan_load_error") or "", limit=300)
        self.migration_plan_write_status = str(info.get("migration_plan_write_status") or "skipped")
        self.migration_plan_write_error = sanitize_text(info.get("migration_plan_write_error") or "", limit=300)

    def observe_tool_result(
        self,
        *,
        name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        if name in {"run_build", "run_tests"}:
            status = str(result.get("status", "unknown"))
            if name == "run_build":
                self.build_tool_calls += 1
                self.last_build_status = status
                if status != "skipped":
                    self.ran_build = True
            else:
                self.test_tool_calls += 1
                self.last_test_status = status
                if status != "skipped":
                    self.ran_tests = True
            if status in CHECK_FAILURE_STATUSES:
                self.last_failure_summary = result.get("summary") if isinstance(result.get("summary"), dict) else None
                self._pending_failed_check = True

        if name == "run_command" and ("exit_code" in result or result.get("timed_out")):
            self.ran_command = True
            self.command_tool_calls += 1

        if not result.get("ok"):
            return

        if name in READ_OBSERVATION_TOOLS:
            self.read_files = True
            self.read_tool_calls += 1
        if name == "search_text":
            self.searched_text = True
        if name in WRITE_OBSERVATION_TOOLS:
            self.modified_target_files = True
            self.write_tool_calls += 1
            self._add_changed_path(result.get("path") or arguments.get("path"))
            if self._pending_failed_check:
                self.modified_target_after_failure = True
        if name == "git_diff":
            self.viewed_diff = True
            self.diff_tool_calls += 1

    def as_dict(self, repair_loop_summary: dict[str, Any] | None = None) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data.pop("_pending_failed_check", None)
        data["build_runs"] = self.build_tool_calls
        data["test_runs"] = self.test_tool_calls
        if repair_loop_summary is not None:
            for key, value in repair_loop_summary.items():
                if key == "last_failure_summary" and value is None and data.get("last_failure_summary") is not None:
                    continue
                data[key] = value
        return data
