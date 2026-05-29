from __future__ import annotations

import dataclasses
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from forgis_config import ResolvedConfig
from migration_state import (
    safe_active_unit_switch_result,
    safe_plan_events,
    safe_resume_summary,
    safe_unit_status_update_result,
)
from plan_audit import build_migration_plan_audit_summary
from repair_report import sanitize_failure_summary, sanitize_markdown, sanitize_path, sanitize_paths, sanitize_text
from visual_evidence import NO_VISUAL_EVIDENCE, VISUAL_EVIDENCE_STATES


RUN_REPORT_MARKDOWN_FILENAME = "FORGIS_RUN_REPORT.md"
RUN_REPORT_JSON_FILENAME = "FORGIS_RUN_REPORT.json"
RUN_REPORT_SCHEMA_VERSION = "forgis.run_report.v6.0"
DEFAULT_RUN_REPORT_MAX_CHARS = 200_000
MAX_RUN_REPORT_FILE_CHARS = 1_000_000
MAX_JSON_TEXT_CHARS = 1_000
SECRET_PATH_WORDS = re.compile(
    r"(secret|token|credential|password|api[_-]?key|private|\.env|\.npmrc|\.pypirc|\.netrc)",
    re.IGNORECASE,
)
DROP_JSON_KEYS = {
    "content",
    "diff",
    "patch",
    "old_text",
    "new_text",
    "stdout",
    "stderr",
    "stdout_tail",
    "stderr_tail",
    "reasoning_content",
    "api_key",
    "authorization",
    "headers",
    "base64",
    "image_bytes",
    "raw_provider_response",
}
FORBIDDEN_REPORT_DIR_NAMES = {"source", "source-repo", "target", "target-repo"}


@dataclasses.dataclass(frozen=True)
class RunReportWriteResult:
    status: str
    markdown_path: str = ""
    json_path: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "status": self.status,
            "markdown_path": self.markdown_path,
            "json_path": self.json_path,
            "error": self.error,
        }


def safe_report_output_dir_text(value: Any) -> str:
    text = str(value if value is not None else "").strip().replace("\\", "/")
    if not text:
        raise ValueError("run_report_output_dir must be a non-empty relative path.")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError("run_report_output_dir contains an unsafe character.")
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text) or text.startswith("~"):
        raise ValueError("run_report_output_dir must be relative to the Forgis runtime workspace.")
    raw = PurePosixPath(text.strip("/"))
    if not raw.parts:
        raise ValueError("run_report_output_dir must not resolve to the runtime root.")
    lowered_parts = {part.casefold() for part in raw.parts}
    if any(part in {"", ".", "..", ".git"} for part in raw.parts):
        raise ValueError(f"run_report_output_dir contains an unsafe path segment: {text}")
    if lowered_parts & FORBIDDEN_REPORT_DIR_NAMES:
        raise ValueError("run_report_output_dir must not point at a source or target checkout directory.")
    if any(SECRET_PATH_WORDS.search(part) for part in raw.parts):
        raise ValueError("run_report_output_dir must not contain secret-like path segments.")
    return raw.as_posix()


def config_summary(config: ResolvedConfig) -> dict[str, Any]:
    return {
        "source_repo": sanitize_text(config.source_repo, limit=160),
        "source_ref": sanitize_text(config.source_ref, limit=120),
        "target_repo": sanitize_text(config.target_repo, limit=160),
        "target_subdir": sanitize_path(config.target_subdir),
        "task_prompt_path": sanitize_path(config.task_prompt_path),
        "config_path": sanitize_path(config.config_path),
        "agent_backend": sanitize_text(config.agent_backend, limit=80),
        "model": sanitize_text(config.model, limit=120),
        "api_format": sanitize_text(config.api_format, limit=80),
        "execution_mode": sanitize_text(config.execution_mode, limit=80),
        "dry_run": bool(config.dry_run),
        "run_agent_config": bool(config.run_agent_config),
        "effective_run_agent": bool(config.run_agent),
        "confirm_real_run": bool(config.confirm_real_run),
        "strict_mode": bool(config.strict_mode),
        "build_command_configured": bool(config.build_command),
        "test_command_configured": bool(config.test_command),
        "repair_loop_enabled": bool(config.repair_loop_enabled),
        "max_repair_attempts": int(config.max_repair_attempts),
        "run_report_enabled": bool(config.run_report_enabled),
        "run_report_output_dir": sanitize_path(config.run_report_output_dir),
        "run_report_include_events": bool(config.run_report_include_events),
        "run_report_max_events": int(config.run_report_max_events),
        "run_report_max_chars": int(config.run_report_max_chars),
        "run_report_required": bool(config.run_report_required),
        "skills_enabled": bool(config.skills_enabled),
        "selected_skills": [sanitize_text(name, limit=80) for name in config.selected_skills],
        "auto_select_skills": bool(config.auto_select_skills),
        "max_skill_chars": int(config.max_skill_chars),
        "max_total_skill_chars": int(config.max_total_skill_chars),
        "migration_scheduler_enabled": bool(config.migration_scheduler_enabled),
        "max_migration_units": int(config.max_migration_units),
        "migration_unit_strategy": sanitize_text(config.migration_unit_strategy, limit=80),
        "migration_unit_prioritize_ui": bool(config.migration_unit_prioritize_ui),
        "migration_unit_include_tests": bool(config.migration_unit_include_tests),
        "migration_unit_include_assets": bool(config.migration_unit_include_assets),
        "migration_plan_persistence_enabled": bool(config.migration_plan_persistence_enabled),
        "migration_plan_output_dir": _safe_runtime_path_value(config.migration_plan_output_dir),
        "migration_plan_filename": _safe_runtime_path_value(config.migration_plan_filename),
        "migration_plan_resume_enabled": bool(config.migration_plan_resume_enabled),
        "migration_plan_required": bool(config.migration_plan_required),
        "migration_plan_auto_update_enabled": bool(config.migration_plan_auto_update_enabled),
        "migration_plan_resume_summary_enabled": bool(config.migration_plan_resume_summary_enabled),
        "migration_plan_event_log_max_events": int(config.migration_plan_event_log_max_events),
        "migration_plan_audit_summary_enabled": bool(config.migration_plan_audit_summary_enabled),
        "migration_plan_audit_max_events": int(config.migration_plan_audit_max_events),
        "migration_plan_auto_complete_on_success": bool(config.migration_plan_auto_complete_on_success),
        "migration_plan_requested_active_unit_id": sanitize_text(config.migration_plan_requested_active_unit_id, limit=120),
        "migration_plan_allow_switch_from_blocked": bool(config.migration_plan_allow_switch_from_blocked),
        "migration_plan_allow_switch_from_completed": bool(config.migration_plan_allow_switch_from_completed),
        "migration_plan_allow_switch_from_deferred": bool(config.migration_plan_allow_switch_from_deferred),
        "migration_plan_switch_requires_resume": bool(config.migration_plan_switch_requires_resume),
        "migration_plan_switch_reason": sanitize_text(config.migration_plan_switch_reason, limit=300),
        "migration_plan_requested_unit_status_unit_id": sanitize_text(
            config.migration_plan_requested_unit_status_unit_id,
            limit=120,
        ),
        "migration_plan_requested_unit_status": sanitize_text(config.migration_plan_requested_unit_status, limit=80),
        "migration_plan_requested_unit_status_reason": sanitize_text(
            config.migration_plan_requested_unit_status_reason,
            limit=300,
        ),
        "migration_plan_allow_manual_complete": bool(config.migration_plan_allow_manual_complete),
        "migration_plan_allow_manual_block": bool(config.migration_plan_allow_manual_block),
        "migration_plan_allow_manual_defer": bool(config.migration_plan_allow_manual_defer),
        "migration_plan_allow_manual_activate": bool(config.migration_plan_allow_manual_activate),
        "migration_plan_status_update_requires_resume": bool(config.migration_plan_status_update_requires_resume),
        "visual_validation": {
            "enabled": sanitize_text(config.visual_validation.enabled, limit=20),
            "provider": sanitize_text(config.visual_validation.provider, limit=80),
            "max_visual_iterations": int(config.visual_validation.max_visual_iterations),
            "require_reference_first": bool(config.visual_validation.require_reference_first),
            "upload_visual_artifact": bool(config.visual_validation.upload_visual_artifact),
        },
    }


def _safe_events(events: Any, *, include_events: bool, max_events: int) -> list[dict[str, Any]]:
    if not include_events or not isinstance(events, list):
        return []
    selected = events[-max(0, int(max_events)) :]
    safe: list[dict[str, Any]] = []
    for event in selected:
        if not isinstance(event, dict):
            continue
        safe.append(
            {
                "event_id": event.get("event_id"),
                "event_type": sanitize_text(event.get("event_type"), limit=80),
                "attempt_index": int(event.get("attempt_index") or 0),
                "check_type": sanitize_text(event.get("check_type") or "none", limit=40),
                "status": sanitize_text(event.get("status") or "unknown", limit=40),
                "short_message": sanitize_text(event.get("short_message") or "", limit=240),
                "affected_paths": sanitize_paths(event.get("affected_paths") or []),
                "failure_summary": sanitize_failure_summary(event.get("failure_summary")),
            }
        )
    return safe


def _stopped_reason(runtime_state: dict[str, Any]) -> str:
    return sanitize_text(runtime_state.get("stopped_reason") or "none", limit=120) or "none"


def final_recommendation(runtime_state: dict[str, Any]) -> str:
    stopped_reason = _stopped_reason(runtime_state)
    if runtime_state.get("visual_gate_status") == "VISUAL_REPORT_INCOMPLETE":
        return "Provide valid visual evidence or record an explicit visual blocker before claiming visual validation."
    if runtime_state.get("repair_success") or stopped_reason == "success":
        return "Review the diff and run the full project CI before merging."
    if stopped_reason == "max_attempts_reached":
        return "Inspect the latest failure summary manually before attempting another focused repair."
    if "diff_check_required" in stopped_reason or "git_diff" in stopped_reason:
        return "Review git_diff before running another configured build/test check."
    if runtime_state.get("last_build_status") == "skipped" or runtime_state.get("last_test_status") == "skipped":
        return "Configure build_command/test_command if this target should be verified automatically."
    if stopped_reason not in {"none", ""}:
        return "Resolve the stopped reason, then retry a small focused change."
    return "Review changed paths and run the next project-specific verification."


def _safe_name_list(value: Any, *, limit: int = 40) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple, set)) else []
    names: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        name = sanitize_text(item, limit=80)
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= limit:
            break
    return names


def _safe_table_key(value: Any) -> str:
    text = str(value if value is not None else "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"(?i)(api[_-]?key|secret|token|password|credential|private)", "[redacted]", text)
    if len(text) <= 80:
        return text or "field"
    return text[:76].rstrip() + "..."


def _safe_runtime_path_value(value: Any, *, limit: int = 220) -> str:
    text = str(value if value is not None else "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        name = PurePosixPath(text).name
        text = f"[path-redacted]/{name}" if name and not SECRET_PATH_WORDS.search(name) else "[path-redacted]"
    parts: list[str] = []
    for part in PurePosixPath(text.strip("/")).parts:
        if part in {"", ".", "..", ".git"}:
            continue
        parts.append("[redacted]" if SECRET_PATH_WORDS.search(part) else part)
    cleaned = "/".join(parts) or "[root]"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:120] + ".../" + cleaned[-80:]


def _migration_plan_summary(runtime_state: dict[str, Any], *, max_units: int = 50) -> dict[str, Any]:
    raw = runtime_state.get("migration_plan_summary")
    if not isinstance(raw, dict):
        return {
            "plan_id": "",
            "active_unit_id": "",
            "completed_count": 0,
            "blocked_count": 0,
            "pending_count": 0,
            "deferred_count": 0,
            "active_count": 0,
            "unit_count": 0,
            "active_unit": None,
            "units": [],
        }
    summary = _safe_json_value(raw)
    if isinstance(summary, dict) and isinstance(summary.get("units"), list):
        summary["units"] = summary["units"][: max(0, min(int(max_units), 200))]
    return summary if isinstance(summary, dict) else {}


def _plan_events(runtime_state: dict[str, Any], config: ResolvedConfig) -> list[dict[str, Any]]:
    events = runtime_state.get("plan_events")
    if not isinstance(events, list):
        summary = runtime_state.get("migration_plan_summary")
        events = summary.get("events") if isinstance(summary, dict) else []
    return safe_plan_events(events, max_events=config.migration_plan_event_log_max_events)


def _resume_summary(runtime_state: dict[str, Any]) -> dict[str, Any]:
    return safe_resume_summary(runtime_state.get("resume_summary"))


def _safe_json_value(value: Any, *, text_limit: int = MAX_JSON_TEXT_CHARS) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, raw in value.items():
            clean_key = sanitize_text(key, limit=80)
            if clean_key.casefold() in DROP_JSON_KEYS:
                output[clean_key] = "[redacted]"
                continue
            output[clean_key] = _safe_json_value(raw, text_limit=text_limit)
        return output
    if isinstance(value, list):
        return [_safe_json_value(item, text_limit=text_limit) for item in value[:200]]
    if isinstance(value, tuple):
        return [_safe_json_value(item, text_limit=text_limit) for item in list(value)[:200]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return sanitize_text(value, limit=text_limit)


def _safe_visual_list(value: Any, *, limit: int = 40) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple, set)) else []
    output: list[str] = []
    seen: set[str] = set()
    for item in raw_values:
        clean = _safe_runtime_path_value(item, limit=220)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        output.append(clean)
        if len(output) >= limit:
            break
    return output


def visual_validation_summary(config: ResolvedConfig, runtime_state: dict[str, Any]) -> dict[str, Any]:
    state = sanitize_text(runtime_state.get("valid_visual_evidence") or NO_VISUAL_EVIDENCE, limit=80)
    if state not in VISUAL_EVIDENCE_STATES:
        state = NO_VISUAL_EVIDENCE
    tools = _safe_name_list(runtime_state.get("visual_tools_called"))
    blocker = sanitize_text(runtime_state.get("actual_screenshot_blocker") or "", limit=120)
    limitations = sanitize_text(runtime_state.get("visual_validation_limitations") or "", limit=1000)
    if state == "REFERENCE_ONLY" and "not full rendered visual validation" not in limitations:
        limitations = (
            limitations + "; reference-only; not full rendered visual validation."
            if limitations
            else "reference-only; not full rendered visual validation."
        )
    if blocker and "provider" not in limitations.casefold():
        limitations = (limitations + "; " if limitations else "") + "Provider or screenshot path blocker is recorded."
    required = bool(runtime_state.get("visual_required"))
    if config.visual_validation.enabled == "true":
        required = True
    if config.visual_validation.enabled == "false":
        required = False
    return {
        "required": required,
        "provider": sanitize_text(runtime_state.get("visual_provider") or config.visual_validation.provider, limit=80) or "qwen",
        "called": bool(tools),
        "valid_visual_evidence": state,
        "compare_screenshots_completed": bool(runtime_state.get("compare_screenshots_completed")),
        "reference_screenshots_used": _safe_visual_list(runtime_state.get("reference_screenshots_used")),
        "actual_screenshots": _safe_visual_list(runtime_state.get("actual_screenshots")),
        "vision_tools_called": tools,
        "vision_result_summary": sanitize_text(runtime_state.get("vision_result_summary") or "", limit=1000),
        "actual_screenshot_blocker": blocker,
        "visual_validation_limitations": limitations,
        "fixes_from_qwen_result": sanitize_text(runtime_state.get("fixes_from_qwen_result") or "", limit=1000),
        "remaining_ui_differences": sanitize_text(runtime_state.get("remaining_ui_differences") or "", limit=1000),
        "gate_status": sanitize_text(runtime_state.get("visual_gate_status") or "not_required", limit=80),
        "required_reason": sanitize_text(runtime_state.get("visual_validation_required_reason") or "", limit=240),
    }


def render_run_report_json(
    *,
    config: ResolvedConfig,
    runtime_state: dict[str, Any],
    repair_report_markdown: str,
    final_summary: str,
    status: str,
    executed: bool,
    iterations: int,
    tool_call_count: int,
    read_tool_count: int,
    write_tool_count: int,
    operation_log: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    include_events: bool | None = None,
    max_events: int | None = None,
) -> dict[str, Any]:
    include = config.run_report_include_events if include_events is None else bool(include_events)
    event_limit = config.run_report_max_events if max_events is None else max(0, int(max_events))
    events = _safe_events(
        runtime_state.get("repair_events"),
        include_events=include,
        max_events=event_limit,
    )
    changed_paths = sanitize_paths(
        [
            *(runtime_state.get("changed_paths") or []),
            *[item.get("path") for item in operation_log if isinstance(item, dict) and item.get("path")],
        ]
    )
    last_failure = sanitize_failure_summary(runtime_state.get("last_failure_summary"))
    migration_scheduler_enabled = bool(runtime_state.get("migration_scheduler_enabled") or config.migration_scheduler_enabled)
    migration_plan_summary = _migration_plan_summary(runtime_state, max_units=config.max_migration_units)
    active_unit = migration_plan_summary.get("active_unit") if isinstance(migration_plan_summary.get("active_unit"), dict) else {}
    active_unit_id = (
        sanitize_text(runtime_state.get("active_unit_id"), limit=120)
        or sanitize_text(migration_plan_summary.get("active_unit_id"), limit=120)
        or sanitize_text(active_unit.get("unit_id"), limit=120)
    )
    plan_path = _safe_runtime_path_value(runtime_state.get("migration_plan_path"))
    plan_load_status = sanitize_text(runtime_state.get("migration_plan_load_status") or "skipped", limit=80)
    plan_write_status = sanitize_text(runtime_state.get("migration_plan_write_status") or "skipped", limit=80)
    plan_source = sanitize_text(runtime_state.get("migration_plan_source") or "skipped", limit=80)
    plan_update_status = sanitize_text(runtime_state.get("plan_update_status") or "skipped", limit=80)
    active_unit_status = sanitize_text(runtime_state.get("active_unit_status") or active_unit.get("status") or "none", limit=80)
    active_unit_reason = sanitize_text(runtime_state.get("active_unit_reason") or active_unit.get("reason") or "", limit=300)
    plan_events = _plan_events(runtime_state, config)
    resume_summary = _resume_summary(runtime_state)
    active_unit_switch = safe_active_unit_switch_result(runtime_state.get("active_unit_switch"))
    manual_unit_status_update = safe_unit_status_update_result(runtime_state.get("manual_unit_status_update"))
    migration_plan_audit_summary = build_migration_plan_audit_summary(
        migration_scheduler_enabled=migration_scheduler_enabled,
        plan_summary=migration_plan_summary,
        plan_events=plan_events,
        resume_summary=resume_summary,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
        max_events=config.migration_plan_audit_max_events,
        enabled=config.migration_plan_audit_summary_enabled,
    )
    visual_validation = visual_validation_summary(config, runtime_state)
    data: dict[str, Any] = {
        "schema_version": RUN_REPORT_SCHEMA_VERSION,
        "metadata": _safe_json_value(metadata or {}),
        "config": config_summary(config),
        "skills": {
            "skills_enabled": bool(config.skills_enabled),
            "auto_select_skills": bool(config.auto_select_skills),
            "configured_selected_skill_names": _safe_name_list(config.selected_skills),
            "selected_skill_names": _safe_name_list(runtime_state.get("selected_skill_names")),
            "skipped_skill_names": _safe_name_list(runtime_state.get("skipped_skill_names")),
            "failed_skill_names": _safe_name_list(runtime_state.get("failed_skill_names")),
            "total_skill_chars": int(runtime_state.get("total_skill_chars") or 0),
        },
        "migration_plan": {
            "migration_scheduler_enabled": migration_scheduler_enabled,
            **migration_plan_summary,
            "migration_plan_persistence": {
                "enabled": bool(config.migration_plan_persistence_enabled),
                "resume_enabled": bool(config.migration_plan_resume_enabled),
                "required": bool(config.migration_plan_required),
                "output_dir": sanitize_path(config.migration_plan_output_dir),
                "filename": sanitize_path(config.migration_plan_filename),
            },
            "plan_source": plan_source,
            "plan_load_status": plan_load_status,
            "plan_write_status": plan_write_status,
            "plan_path": plan_path,
            "active_unit_id": active_unit_id,
            "active_unit_status": active_unit_status,
            "active_unit_reason": active_unit_reason,
            "plan_update_status": plan_update_status,
            "active_unit_switch": active_unit_switch,
            "manual_unit_status_update": manual_unit_status_update,
            "audit_summary": migration_plan_audit_summary,
            "resume_summary": resume_summary,
            "plan_events": plan_events,
        },
        "tool_loop": {
            "executed": bool(executed),
            "status": sanitize_text(status, limit=80),
            "iterations": int(iterations),
            "tool_call_count": int(tool_call_count),
            "read_tool_count": int(read_tool_count),
            "write_tool_count": int(write_tool_count),
        },
        "build_test": {
            "build_runs": int(runtime_state.get("build_runs") or 0),
            "test_runs": int(runtime_state.get("test_runs") or 0),
            "last_build_status": sanitize_text(runtime_state.get("last_build_status") or "unknown", limit=80),
            "last_test_status": sanitize_text(runtime_state.get("last_test_status") or "unknown", limit=80),
            "last_failure_summary": last_failure,
        },
        "visual_validation": visual_validation,
        "repair_loop": {
            "enabled": bool(runtime_state.get("repair_loop_enabled")),
            "max_repair_attempts": int(runtime_state.get("max_repair_attempts") or 0),
            "attempts_used": int(runtime_state.get("repair_attempts_used") or 0),
            "allowed": bool(runtime_state.get("repair_allowed")),
            "success": bool(runtime_state.get("repair_success")),
            "stopped_reason": _stopped_reason(runtime_state),
            "requires_diff_check": bool(runtime_state.get("repair_requires_diff_check")),
            "requires_build_or_test": bool(runtime_state.get("repair_requires_build_or_test")),
            "event_count": int(runtime_state.get("repair_event_count") or len(events)),
        },
        "events": events,
        "plan_events": plan_events,
        "resume_summary": resume_summary,
        "active_unit_switch": active_unit_switch,
        "manual_unit_status_update": manual_unit_status_update,
        "migration_plan_audit_summary": migration_plan_audit_summary,
        "migration_plan_audit_summary_short": migration_plan_audit_summary.get("summary_short") or "",
        "migration_plan_recommended_next_action": migration_plan_audit_summary.get("recommended_next_action") or "",
        "migration_plan_switch_status": active_unit_switch.get("status") or "skipped",
        "migration_plan_switch_reason": active_unit_switch.get("reason") or "",
        "migration_plan_requested_active_unit_id": active_unit_switch.get("requested_active_unit_id") or "",
        "migration_plan_previous_active_unit_id": active_unit_switch.get("previous_active_unit_id") or "",
        "migration_plan_unit_status_update_status": manual_unit_status_update.get("status") or "skipped",
        "migration_plan_unit_status_update_reason": manual_unit_status_update.get("reason") or "",
        "migration_plan_unit_status_update_unit_id": manual_unit_status_update.get("unit_id") or "",
        "migration_plan_unit_status_update_requested_status": manual_unit_status_update.get("requested_status") or "",
        "migration_plan_unit_status_update_previous_status": manual_unit_status_update.get("previous_status") or "",
        "migration_plan_unit_status_update_final_status": manual_unit_status_update.get("final_status") or "",
        "active_unit_status": active_unit_status,
        "active_unit_reason": active_unit_reason,
        "plan_update_status": plan_update_status,
        "changed_paths": changed_paths,
        "stopped_reason": _stopped_reason(runtime_state),
        "final_recommendation": final_recommendation(runtime_state),
        "final_summary": sanitize_text(final_summary, limit=2_000),
        "repair_report_chars": len(sanitize_markdown(repair_report_markdown, limit=config.run_report_max_chars)),
        "operation_log": _safe_json_value(operation_log),
    }
    return _safe_json_value(data)


def _markdown_table(rows: list[tuple[str, Any]]) -> list[str]:
    lines = ["| Field | Value |", "|---|---|"]
    for key, value in rows:
        safe_key = _safe_table_key(key)
        if "path" in str(key).casefold() or "dir" in str(key).casefold() or "filename" in str(key).casefold():
            value_text = _safe_runtime_path_value(value)
        else:
            value_text = sanitize_text(value, limit=220)
        safe_value = (value_text or "none").replace("|", "\\|")
        lines.append(f"| {safe_key} | `{safe_value}` |")
    return lines


def render_run_report_markdown(
    *,
    config: ResolvedConfig,
    runtime_state: dict[str, Any],
    repair_report_markdown: str,
    final_summary: str,
    status: str,
    executed: bool,
    iterations: int,
    tool_call_count: int,
    read_tool_count: int,
    write_tool_count: int,
    operation_log: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
    max_chars: int | None = None,
) -> str:
    limit = config.run_report_max_chars if max_chars is None else int(max_chars)
    changed_paths = sanitize_paths(
        [
            *(runtime_state.get("changed_paths") or []),
            *[item.get("path") for item in operation_log if isinstance(item, dict) and item.get("path")],
        ]
    )
    stopped = _stopped_reason(runtime_state)
    last_failure = sanitize_failure_summary(runtime_state.get("last_failure_summary"))
    last_failure_message = "none"
    if last_failure:
        last_failure_message = last_failure.get("message") or last_failure.get("error_type") or "failure"
    selected_skill_names = _safe_name_list(runtime_state.get("selected_skill_names"))
    skipped_skill_names = _safe_name_list(runtime_state.get("skipped_skill_names"))
    failed_skill_names = _safe_name_list(runtime_state.get("failed_skill_names"))
    migration_plan = _migration_plan_summary(runtime_state, max_units=config.max_migration_units)
    migration_scheduler_enabled = bool(runtime_state.get("migration_scheduler_enabled") or config.migration_scheduler_enabled)
    active_unit = migration_plan.get("active_unit") if isinstance(migration_plan.get("active_unit"), dict) else {}
    active_unit_id = runtime_state.get("active_unit_id") or migration_plan.get("active_unit_id") or active_unit.get("unit_id") or "none"
    active_unit_status = active_unit.get("status") or "none"
    active_unit_reason = active_unit.get("reason") or "none"
    migration_plan_source = runtime_state.get("migration_plan_source") or "skipped"
    migration_plan_path = runtime_state.get("migration_plan_path") or "none"
    migration_plan_load_status = runtime_state.get("migration_plan_load_status") or "skipped"
    migration_plan_write_status = runtime_state.get("migration_plan_write_status") or "skipped"
    plan_update_status = runtime_state.get("plan_update_status") or "skipped"
    plan_events = _plan_events(runtime_state, config)
    resume_summary = _resume_summary(runtime_state)
    resume_counts = resume_summary.get("counts") if isinstance(resume_summary.get("counts"), dict) else {}
    active_unit_switch = safe_active_unit_switch_result(runtime_state.get("active_unit_switch"))
    manual_unit_status_update = safe_unit_status_update_result(runtime_state.get("manual_unit_status_update"))
    migration_plan_audit_summary = build_migration_plan_audit_summary(
        migration_scheduler_enabled=migration_scheduler_enabled,
        plan_summary=migration_plan,
        plan_events=plan_events,
        resume_summary=resume_summary,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
        max_events=config.migration_plan_audit_max_events,
        enabled=config.migration_plan_audit_summary_enabled,
    )
    visual_validation = visual_validation_summary(config, runtime_state)

    lines: list[str] = [
        "# Forgis Run Report",
        "",
        "v5.0 persistent runtime report",
        "",
        "## Overview",
        "",
        *_markdown_table(
            [
                ("status", status),
                ("executed", str(bool(executed)).lower()),
                ("iterations", iterations),
                ("tool_call_count", tool_call_count),
                ("read_tool_count", read_tool_count),
                ("write_tool_count", write_tool_count),
                ("stopped_reason", stopped),
                ("final_recommendation", final_recommendation(runtime_state)),
            ]
        ),
        "",
        "## Config Summary",
        "",
        *_markdown_table(
            [
                ("source_repo", config.source_repo),
                ("source_ref", config.source_ref),
                ("target_repo", config.target_repo),
                ("target_subdir", config.target_subdir),
                ("execution_mode", config.execution_mode),
                ("dry_run", str(config.dry_run).lower()),
                ("effective_run_agent", str(config.run_agent).lower()),
                ("build_command", "configured" if config.build_command else "none"),
                ("test_command", "configured" if config.test_command else "none"),
                ("run_report_output_dir", config.run_report_output_dir),
                ("migration_scheduler_enabled", str(migration_scheduler_enabled).lower()),
                ("max_migration_units", config.max_migration_units),
                ("migration_unit_strategy", config.migration_unit_strategy),
                ("migration_plan_persistence_enabled", str(config.migration_plan_persistence_enabled).lower()),
                ("migration_plan_resume_enabled", str(config.migration_plan_resume_enabled).lower()),
                ("migration_plan_audit_summary_enabled", str(config.migration_plan_audit_summary_enabled).lower()),
                ("migration_plan_audit_max_events", config.migration_plan_audit_max_events),
                ("visual_validation_enabled", config.visual_validation.enabled),
                ("visual_validation_provider", config.visual_validation.provider),
            ]
        ),
        "",
        "## Skills",
        "",
        *_markdown_table(
            [
                ("skills_enabled", str(config.skills_enabled).lower()),
                ("auto_select_skills", str(config.auto_select_skills).lower()),
                ("configured_selected_skills", ", ".join(config.selected_skills) if config.selected_skills else "none"),
                ("selected_skill_names", ", ".join(selected_skill_names) if selected_skill_names else "none"),
                ("skipped_skill_names", ", ".join(skipped_skill_names) if skipped_skill_names else "none"),
                ("failed_skill_names", ", ".join(failed_skill_names) if failed_skill_names else "none"),
                ("total_skill_chars", int(runtime_state.get("total_skill_chars") or 0)),
            ]
        ),
        "",
        "## Migration Plan",
        "",
        *_markdown_table(
            [
                ("migration_scheduler_enabled", str(migration_scheduler_enabled).lower()),
                ("migration_plan_persistence_enabled", str(config.migration_plan_persistence_enabled).lower()),
                ("migration_plan_resume_enabled", str(config.migration_plan_resume_enabled).lower()),
                ("migration_plan_source", migration_plan_source),
                ("migration_plan_path", migration_plan_path),
                ("migration_plan_load_status", migration_plan_load_status),
                ("migration_plan_write_status", migration_plan_write_status),
                ("plan_update_status", plan_update_status),
                ("active_unit_id", active_unit_id),
                ("plan_id", migration_plan.get("plan_id") or "none"),
                ("active_unit", active_unit_id),
                ("completed_count", migration_plan.get("completed_count") or 0),
                ("blocked_count", migration_plan.get("blocked_count") or 0),
                ("pending_count", migration_plan.get("pending_count") or 0),
                ("deferred_count", migration_plan.get("deferred_count") or 0),
                ("current_unit_status", active_unit_status),
                ("blocked_reason", active_unit_reason if active_unit_status == "blocked" else "none"),
            ]
        ),
        "",
        "## Migration Plan Audit Summary",
        "",
        *_markdown_table(
            [
                ("status", migration_plan_audit_summary.get("status") or "skipped"),
                ("latest_action_type", migration_plan_audit_summary.get("latest_action_type") or "none"),
                ("latest_action_status", migration_plan_audit_summary.get("latest_action_status") or "none"),
                ("latest_unit_id", migration_plan_audit_summary.get("latest_unit_id") or "none"),
                ("latest_unit_status", migration_plan_audit_summary.get("latest_unit_status") or "none"),
                ("latest_reason", migration_plan_audit_summary.get("latest_reason") or "none"),
                ("latest_message", migration_plan_audit_summary.get("latest_message") or "none"),
                ("blocked_units_count", migration_plan_audit_summary.get("blocked_units_count") or 0),
                ("deferred_units_count", migration_plan_audit_summary.get("deferred_units_count") or 0),
                ("completed_units_count", migration_plan_audit_summary.get("completed_units_count") or 0),
                ("active_unit_id", migration_plan_audit_summary.get("active_unit_id") or "none"),
                ("recommended_next_action", migration_plan_audit_summary.get("recommended_next_action") or "none"),
            ]
        ),
        "",
        *(
            [
                "| Order | Action | Status | Unit | Reason / Message |",
                "|---:|---|---|---|---|",
                *[
                    "| "
                    + " | ".join(
                        [
                            str(event.get("order") or 0),
                            sanitize_text(event.get("action_type") or "", limit=80).replace("|", "\\|"),
                            sanitize_text(event.get("action_status") or "", limit=40).replace("|", "\\|"),
                            sanitize_text(event.get("unit_id") or "none", limit=120).replace("|", "\\|"),
                            sanitize_text(
                                event.get("reason") or event.get("message") or "none",
                                limit=160,
                            ).replace("|", "\\|"),
                        ]
                    )
                    + " |"
                    for event in migration_plan_audit_summary.get("recent_events") or []
                    if isinstance(event, dict)
                ],
            ]
            if migration_plan_audit_summary.get("recent_events")
            else ["- recent_events: none"]
        ),
        "",
        "## Resume Summary",
        "",
        *_markdown_table(
            [
                ("plan_id", resume_summary.get("plan_id") or "none"),
                ("active_unit_id", resume_summary.get("active_unit_id") or "none"),
                ("last_active_unit_status", resume_summary.get("last_active_unit_status") or "none"),
                ("completed_count", resume_counts.get("completed") or 0),
                ("blocked_count", resume_counts.get("blocked") or 0),
                ("deferred_count", resume_counts.get("deferred") or 0),
                ("pending_count", resume_counts.get("pending") or 0),
                ("active_count", resume_counts.get("active") or 0),
                ("last_stopped_reason", resume_summary.get("last_stopped_reason") or "none"),
                ("changed_paths", ", ".join(resume_summary.get("changed_paths") or []) or "none"),
                ("next_step", resume_summary.get("next_step") or "none"),
                ("switch_result", (resume_summary.get("active_unit_switch") or {}).get("status") or "skipped"),
                ("switch_requested_unit_id", (resume_summary.get("active_unit_switch") or {}).get("requested_active_unit_id") or "none"),
                ("switch_manual_guidance", resume_summary.get("switch_manual_guidance") or "none"),
                ("unit_status_update_result", (resume_summary.get("manual_unit_status_update") or {}).get("status") or "skipped"),
                ("unit_status_update_unit_id", (resume_summary.get("manual_unit_status_update") or {}).get("unit_id") or "none"),
                ("unit_status_update_guidance", resume_summary.get("unit_status_update_manual_guidance") or "none"),
            ]
        ),
        "",
        "## Active Unit Switch",
        "",
        *_markdown_table(
            [
                ("requested_active_unit_id", active_unit_switch.get("requested_active_unit_id") or "none"),
                ("previous_active_unit_id", active_unit_switch.get("previous_active_unit_id") or "none"),
                ("active_unit_id", active_unit_switch.get("active_unit_id") or active_unit_id or "none"),
                ("result", active_unit_switch.get("status") or "skipped"),
                ("reason", active_unit_switch.get("reason") or "none"),
                ("message", active_unit_switch.get("message") or "none"),
            ]
        ),
        "",
        "## Manual Unit Status Update",
        "",
        *_markdown_table(
            [
                ("unit_id", manual_unit_status_update.get("unit_id") or "none"),
                ("previous_status", manual_unit_status_update.get("previous_status") or "none"),
                ("requested_status", manual_unit_status_update.get("requested_status") or "none"),
                ("final_status", manual_unit_status_update.get("final_status") or "none"),
                ("result", manual_unit_status_update.get("status") or "skipped"),
                ("reason", manual_unit_status_update.get("reason") or "none"),
                ("message", manual_unit_status_update.get("message") or "none"),
            ]
        ),
        "",
        "## Active Unit State",
        "",
        *_markdown_table(
            [
                ("active_unit_id", active_unit_id),
                ("active_unit_status", active_unit_status),
                ("active_unit_reason", active_unit_reason or "none"),
                ("active_unit_build_status", active_unit.get("build_status") or "unknown"),
                ("active_unit_test_status", active_unit.get("test_status") or "unknown"),
                ("active_unit_changed_paths", ", ".join(active_unit.get("changed_paths") or []) or "none"),
            ]
        ),
        "",
        "## Plan Update Status",
        "",
        *_markdown_table(
            [
                ("plan_update_status", plan_update_status),
                ("auto_update_enabled", str(config.migration_plan_auto_update_enabled).lower()),
                ("auto_complete_on_success", str(config.migration_plan_auto_complete_on_success).lower()),
                ("event_log_max_events", config.migration_plan_event_log_max_events),
            ]
        ),
        "",
        "## Migration Plan Events",
        "",
        *(
            [
                "| Order | Event | Unit | Before | After | Reason |",
                "|---:|---|---|---|---|---|",
                *[
                    "| "
                    + " | ".join(
                        [
                            str(event.get("order") or 0),
                            sanitize_text(event.get("event_type") or "", limit=80).replace("|", "\\|"),
                            sanitize_text(event.get("unit_id") or "none", limit=120).replace("|", "\\|"),
                            sanitize_text(event.get("status_before") or "none", limit=40).replace("|", "\\|"),
                            sanitize_text(event.get("status_after") or "none", limit=40).replace("|", "\\|"),
                            sanitize_text(event.get("reason") or event.get("short_message") or "none", limit=160).replace("|", "\\|"),
                        ]
                    )
                    + " |"
                    for event in plan_events
                ],
            ]
            if plan_events
            else ["- none"]
        ),
        "",
        "## Build / Test",
        "",
        *_markdown_table(
            [
                ("build_runs", runtime_state.get("build_runs") or 0),
                ("test_runs", runtime_state.get("test_runs") or 0),
                ("last_build_status", runtime_state.get("last_build_status") or "unknown"),
                ("last_test_status", runtime_state.get("last_test_status") or "unknown"),
                ("last_failure_summary", last_failure_message),
            ]
        ),
        "",
        "## Visual Validation",
        "",
        *_markdown_table(
            [
                ("required", str(bool(visual_validation.get("required"))).lower()),
                ("provider", visual_validation.get("provider") or "qwen"),
                ("called", str(bool(visual_validation.get("called"))).lower()),
                ("valid_visual_evidence", visual_validation.get("valid_visual_evidence") or "NO"),
                ("compare_screenshots_completed", str(bool(visual_validation.get("compare_screenshots_completed"))).lower()),
                ("vision_tools_called", ", ".join(visual_validation.get("vision_tools_called") or []) or "none"),
                (
                    "reference_screenshots_used",
                    ", ".join(visual_validation.get("reference_screenshots_used") or []) or "none",
                ),
                ("actual_screenshots", ", ".join(visual_validation.get("actual_screenshots") or []) or "none"),
                ("actual_screenshot_blocker", visual_validation.get("actual_screenshot_blocker") or "none"),
                ("visual_validation_limitations", visual_validation.get("visual_validation_limitations") or "none"),
                ("gate_status", visual_validation.get("gate_status") or "not_required"),
            ]
        ),
        "",
        "## Repair",
        "",
        *_markdown_table(
            [
                ("repair_loop_enabled", str(bool(runtime_state.get("repair_loop_enabled"))).lower()),
                ("attempts_used", runtime_state.get("repair_attempts_used") or 0),
                ("repair_success", str(bool(runtime_state.get("repair_success"))).lower()),
                ("stopped_reason", stopped),
                ("event_count", runtime_state.get("repair_event_count") or 0),
            ]
        ),
        "",
        "## Changed Paths",
        "",
        *([f"- `{path}`" for path in changed_paths] if changed_paths else ["- none"]),
        "",
        "## Runtime Repair Report",
        "",
        sanitize_markdown(repair_report_markdown, limit=min(limit, 20_000)).strip() or "none",
        "",
        "## Final Summary",
        "",
        sanitize_markdown(final_summary, limit=4_000).strip() or "none",
    ]
    if metadata:
        lines.extend(["", "## Metadata", ""])
        lines.extend(_markdown_table([(key, value) for key, value in metadata.items()]))
    return sanitize_markdown("\n".join(lines).rstrip() + "\n", limit=limit)


def _is_forbidden_home_path(path: Path) -> bool:
    try:
        home = Path.home().resolve()
    except OSError:
        return False
    forbidden = [home / "Desktop", home / "Downloads", home / "Documents"]
    return any(path == item or path.is_relative_to(item) for item in forbidden)


def _safe_output_dir(
    output_dir: str | Path,
    *,
    allowed_root: Path,
    source_root: Path | None = None,
    target_root: Path | None = None,
) -> Path:
    raw = Path(str(output_dir).strip())
    if not str(output_dir).strip():
        raise ValueError("run report output directory is empty.")
    if "\x00" in str(output_dir) or "\n" in str(output_dir) or "\r" in str(output_dir):
        raise ValueError("run report output directory contains an unsafe character.")
    root = allowed_root.resolve()
    candidate = raw.expanduser().resolve() if raw.is_absolute() else (root / raw).resolve()
    if candidate == root:
        raise ValueError("run report output directory must be below the runtime root.")
    if not candidate.is_relative_to(root):
        raise ValueError("run report output directory must stay inside the Forgis runtime root.")
    if source_root is not None:
        source = source_root.resolve()
        if candidate == source or candidate.is_relative_to(source):
            raise ValueError("run report output directory must not be inside the source repository.")
    if target_root is not None:
        target = target_root.resolve()
        if candidate == target or candidate.is_relative_to(target):
            raise ValueError("run report output directory must not be inside the target repository.")
    if _is_forbidden_home_path(candidate):
        raise ValueError("run report output directory must not be Desktop, Downloads, or Documents.")
    for part in candidate.relative_to(root).parts:
        if part in {"", ".", "..", ".git"} or SECRET_PATH_WORDS.search(part):
            raise ValueError("run report output directory contains an unsafe path segment.")
    return candidate


def _json_text_limited(data: dict[str, Any], *, max_chars: int) -> str:
    safe_data = _safe_json_value(data)
    text = json.dumps(safe_data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if len(text) <= max_chars:
        return text

    limited = dict(safe_data)
    limited["truncated"] = True
    limited["truncation_note"] = f"FORGIS_RUN_REPORT.json was reduced to stay under {max_chars} characters."
    events = list(limited.get("events") or [])
    while events and len(json.dumps({**limited, "events": events}, ensure_ascii=False)) + 1 > max_chars:
        events = events[len(events) // 2 :]
    limited["events"] = events
    if len(json.dumps(limited, ensure_ascii=False)) + 1 > max_chars:
        limited["operation_log"] = []
        limited["final_summary"] = sanitize_text(limited.get("final_summary"), limit=500)
    text = json.dumps(limited, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if len(text) <= max_chars:
        return text
    minimal = {
        "schema_version": RUN_REPORT_SCHEMA_VERSION,
        "truncated": True,
        "truncation_note": f"FORGIS_RUN_REPORT.json exceeded {max_chars} characters.",
        "tool_loop": limited.get("tool_loop", {}),
        "repair_loop": limited.get("repair_loop", {}),
        "visual_validation": limited.get("visual_validation", {}),
        "migration_plan_audit_summary": limited.get("migration_plan_audit_summary", {}),
        "stopped_reason": limited.get("stopped_reason", "unknown"),
        "final_recommendation": limited.get("final_recommendation", ""),
    }
    return json.dumps(minimal, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_run_reports(
    *,
    output_dir: str | Path,
    markdown: str,
    json_data: dict[str, Any],
    allowed_root: Path,
    source_root: Path | None = None,
    target_root: Path | None = None,
    required: bool = False,
    max_chars: int = DEFAULT_RUN_REPORT_MAX_CHARS,
) -> RunReportWriteResult:
    limit = max(1_000, min(int(max_chars), MAX_RUN_REPORT_FILE_CHARS))
    try:
        destination = _safe_output_dir(
            output_dir,
            allowed_root=allowed_root,
            source_root=source_root,
            target_root=target_root,
        )
        destination.mkdir(parents=True, exist_ok=True)
        markdown_path = destination / RUN_REPORT_MARKDOWN_FILENAME
        json_path = destination / RUN_REPORT_JSON_FILENAME
        markdown_text = sanitize_markdown(markdown, limit=limit).rstrip() + "\n"
        json_text = _json_text_limited(json_data, max_chars=limit)
        markdown_path.write_text(markdown_text, encoding="utf-8")
        json_path.write_text(json_text, encoding="utf-8")
        return RunReportWriteResult(
            status="written",
            markdown_path=markdown_path.as_posix(),
            json_path=json_path.as_posix(),
        )
    except Exception as exc:
        message = sanitize_text(exc, limit=300)
        if required:
            raise RuntimeError(message) from exc
        return RunReportWriteResult(status="skipped", error=message)
