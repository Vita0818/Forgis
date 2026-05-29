from __future__ import annotations

import dataclasses
import re
from typing import Any

from repair_report import sanitize_path, sanitize_text
from visual_evidence import (
    ACTUAL_ONLY,
    NO_VISUAL_EVIDENCE,
    REFERENCE_AND_ACTUAL,
    REFERENCE_ONLY,
    VISUAL_REPORT_INCOMPLETE,
    classify_visual_evidence,
)


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
VISUAL_OBSERVATION_TOOLS = {
    "inspect_visual_reference",
    "inspect_visual_actual",
    "compare_visual_screenshots",
}
VISUAL_ASCII_KEYWORDS = frozenset(
    {
        "ui",
        "visual",
        "screenshot",
        "reference",
        "actual",
        "parity",
        "layout",
        "color",
        "typography",
        "spacing",
        "radius",
        "shadow",
        "component",
        "mockup",
        "rendered",
        "simulator",
        "preview",
    }
)
VISUAL_TEXT_KEYWORDS = frozenset(
    {
        "界面",
        "视觉",
        "截图",
        "复刻",
        "验收",
        "布局",
        "颜色",
        "字体",
        "间距",
        "圆角",
        "阴影",
        "组件",
        "质感",
        "像不像",
        "真机",
        "模拟器",
        "预览",
    }
)


def task_text_indicates_visual(value: Any) -> bool:
    text = str(value if value is not None else "")
    if not text.strip():
        return False
    lowered = text.casefold()
    if any(keyword in lowered for keyword in VISUAL_TEXT_KEYWORDS):
        return True
    return any(
        re.search(rf"(?<![a-z0-9_]){re.escape(keyword)}(?![a-z0-9_])", lowered)
        for keyword in VISUAL_ASCII_KEYWORDS
    )


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
    visual_required: bool = False
    visual_provider: str = "qwen"
    visual_tools_called: list[str] = dataclasses.field(default_factory=list)
    reference_screenshots_used: list[str] = dataclasses.field(default_factory=list)
    actual_screenshots: list[str] = dataclasses.field(default_factory=list)
    valid_visual_evidence: str = NO_VISUAL_EVIDENCE
    compare_screenshots_completed: bool = False
    vision_result_summary: str = ""
    actual_screenshot_blocker: str = ""
    visual_validation_limitations: str = ""
    fixes_from_qwen_result: str = ""
    remaining_ui_differences: str = ""
    visual_gate_status: str = "not_required"
    visual_validation_required_reason: str = ""
    _visual_enabled_mode: str = dataclasses.field(default="auto", repr=False)
    _visual_skill_selected: bool = dataclasses.field(default=False, repr=False)
    _visual_task_signal: bool = dataclasses.field(default=False, repr=False)
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
        self._visual_skill_selected = "qwen_visual_mode" in {
            name.casefold() for name in self.selected_skill_names
        }
        self._refresh_visual_gate()

    def attach_visual_config(self, visual_config: Any) -> None:
        self._visual_enabled_mode = sanitize_text(
            getattr(visual_config, "enabled", "auto") or "auto",
            limit=20,
        ).casefold()
        if self._visual_enabled_mode not in {"auto", "true", "false"}:
            self._visual_enabled_mode = "auto"
        self.visual_provider = sanitize_text(getattr(visual_config, "provider", "qwen") or "qwen", limit=80) or "qwen"
        self._refresh_visual_gate()

    def attach_visual_task_text(self, task_text: Any) -> None:
        self._visual_task_signal = task_text_indicates_visual(task_text)
        self._refresh_visual_gate()

    def _compute_visual_required(self) -> tuple[bool, str]:
        if self._visual_enabled_mode == "false":
            return False, "visual_validation.enabled=false"
        if self._visual_enabled_mode == "true":
            return True, "visual_validation.enabled=true"
        if self.visual_tools_called:
            return True, "visual_validation.enabled=auto and a visual tool was called"
        if self._visual_skill_selected:
            return True, "visual_validation.enabled=auto and qwen_visual_mode skill is selected"
        if self._visual_task_signal:
            return True, "visual_validation.enabled=auto and task text contains visual keywords"
        return False, "visual_validation.enabled=auto and no visual runtime signal was present"

    def _append_visual_limitation(self, message: str) -> None:
        clean = sanitize_text(message, limit=400)
        if not clean:
            return
        existing = self.visual_validation_limitations
        parts = [part.strip() for part in existing.split(";") if part.strip()] if existing else []
        if clean not in parts:
            parts.append(clean)
        self.visual_validation_limitations = "; ".join(parts)[:1000]

    def _refresh_visual_gate(self) -> None:
        self.valid_visual_evidence = classify_visual_evidence(
            self.reference_screenshots_used,
            self.actual_screenshots,
        )
        required, reason = self._compute_visual_required()
        self.visual_required = required
        self.visual_validation_required_reason = sanitize_text(reason, limit=200)
        if not required:
            self.visual_gate_status = "not_required"
            return
        if self.actual_screenshot_blocker:
            self.visual_gate_status = "blocked"
            return
        if not self.visual_tools_called:
            self.visual_gate_status = VISUAL_REPORT_INCOMPLETE
            self._append_visual_limitation("Visual validation is required but no visual tool was called.")
            return
        if self.valid_visual_evidence == REFERENCE_ONLY:
            self.visual_gate_status = "reference_only"
            self._append_visual_limitation("reference-only; not full rendered visual validation.")
            return
        if self.valid_visual_evidence == ACTUAL_ONLY:
            self.visual_gate_status = "actual_only"
            self._append_visual_limitation("actual-only; no reference screenshot was used.")
            return
        if self.valid_visual_evidence == REFERENCE_AND_ACTUAL and self.compare_screenshots_completed:
            self.visual_gate_status = "compare_completed"
            return
        if self.valid_visual_evidence == REFERENCE_AND_ACTUAL:
            self.visual_gate_status = VISUAL_REPORT_INCOMPLETE
            self._append_visual_limitation("reference and actual screenshots were seen, but compare was not completed.")
            return
        self.visual_gate_status = VISUAL_REPORT_INCOMPLETE
        self._append_visual_limitation("Visual validation is required but no valid screenshot evidence was recorded.")

    def visual_effective_status(self, status: str) -> str:
        clean_status = sanitize_text(status, limit=80) or "unknown"
        self._refresh_visual_gate()
        if clean_status == "completed" and self.visual_required and self.visual_gate_status == VISUAL_REPORT_INCOMPLETE:
            return "visual-incomplete"
        return clean_status

    def observe_visual_tool_result(
        self,
        *,
        name: str,
        result: dict[str, Any],
    ) -> None:
        if name not in self.visual_tools_called:
            self.visual_tools_called.append(name)
        provider = sanitize_text(result.get("provider") or self.visual_provider or "qwen", limit=80)
        if provider:
            self.visual_provider = provider
        for raw in result.get("reference_screenshots_used") or []:
            path = sanitize_path(raw)
            if path and path not in self.reference_screenshots_used:
                self.reference_screenshots_used.append(path)
        for raw in result.get("actual_screenshots") or []:
            path = sanitize_path(raw)
            if path and path not in self.actual_screenshots:
                self.actual_screenshots.append(path)
        self.compare_screenshots_completed = bool(
            self.compare_screenshots_completed or result.get("compare_screenshots_completed")
        )
        summary = sanitize_text(result.get("summary") or "", limit=1000)
        if summary:
            self.vision_result_summary = summary
        blocker = sanitize_text(result.get("blocker") or "", limit=120)
        if blocker:
            self.actual_screenshot_blocker = blocker
        limitations = result.get("limitations") if isinstance(result.get("limitations"), list) else []
        for limitation in limitations:
            self._append_visual_limitation(str(limitation))
        findings = result.get("findings") if isinstance(result.get("findings"), list) else []
        if findings:
            joined = "; ".join(sanitize_text(item, limit=220) for item in findings if str(item).strip())
            if name == "compare_visual_screenshots":
                self.remaining_ui_differences = joined[:1000]
            else:
                self.fixes_from_qwen_result = joined[:1000]
        self._refresh_visual_gate()

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
        if name in VISUAL_OBSERVATION_TOOLS:
            self.observe_visual_tool_result(name=name, result=result)

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
        self._refresh_visual_gate()
        data = dataclasses.asdict(self)
        data.pop("_pending_failed_check", None)
        data.pop("_visual_enabled_mode", None)
        data.pop("_visual_skill_selected", None)
        data.pop("_visual_task_signal", None)
        data["build_runs"] = self.build_tool_calls
        data["test_runs"] = self.test_tool_calls
        if repair_loop_summary is not None:
            for key, value in repair_loop_summary.items():
                if key == "last_failure_summary" and value is None and data.get("last_failure_summary") is not None:
                    continue
                data[key] = value
        return data
