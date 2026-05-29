#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable

from deepseek_agent import DeepSeekClient, TOOL_DEFINITIONS, build_skill_selection, initial_messages
from file_tools import READ_TOOLS, WRITE_TOOLS, FileToolSandbox, ToolError
from forgis_config import STAGED_TRANSLATION_MODE, ResolvedConfig, resolve_config
from migration_scheduler import (
    collect_scheduler_inventory,
    create_units_from_inventory,
    mark_unit_active,
    render_active_unit_context,
    select_next_unit,
)
from migration_state import (
    append_plan_event,
    generate_resume_summary,
    request_active_unit_switch,
    request_unit_status_update,
    safe_active_unit_switch_result,
    safe_unit_status_update_result,
    safe_plan_events,
    safe_resume_summary,
    update_active_unit_runtime_fields,
    update_active_unit_state,
)
from migration_plan_store import (
    MigrationPlanLoadResult,
    MigrationPlanWriteResult,
    load_migration_plan,
    migration_plan_file_path,
    write_migration_plan,
)
from migration_units import MigrationPlan
from plan_audit import build_migration_plan_audit_summary
from repair_report import (
    render_compact_actions_summary,
    render_repair_report,
    sanitize_paths,
    write_github_step_summary,
)
from repair_loop import RepairLoopController
from run_report import (
    render_run_report_json,
    render_run_report_markdown,
    write_run_reports,
)
from runtime_controller import RuntimeController
from skill_loader import SkillSelection, render_selected_skills


ClientFactory = Callable[[ResolvedConfig, dict[str, str]], Any]
SECRET_PATH_WORDS = re.compile(r"(secret|token|credential|password|api[_-]?key|private)", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class ToolLoopResult:
    executed: bool
    status: str
    final_summary: str
    iterations: int
    tool_call_count: int
    read_tool_count: int
    write_tool_count: int
    operation_log: list[dict[str, Any]]
    runtime_state: dict[str, Any] = dataclasses.field(default_factory=dict)
    repair_report: str = ""
    compact_actions_summary: str = ""
    report_markdown_path: str = ""
    report_json_path: str = ""
    report_write_status: str = ""
    report_write_error: str = ""
    migration_plan_path: str = ""
    migration_plan_write_status: str = "skipped"
    migration_plan_load_status: str = "skipped"
    migration_plan_source: str = "skipped"
    active_unit_id: str = ""
    migration_plan_write_error: str = ""
    migration_plan_load_error: str = ""
    migration_plan_update_status: str = "skipped"
    migration_plan_active_unit_status: str = ""
    migration_plan_active_unit_reason: str = ""
    migration_plan_resume_summary_short: str = ""
    migration_plan_switch_status: str = "skipped"
    migration_plan_switch_reason: str = ""
    migration_plan_requested_active_unit_id: str = ""
    migration_plan_previous_active_unit_id: str = ""
    migration_plan_unit_status_update_status: str = "skipped"
    migration_plan_unit_status_update_reason: str = ""
    migration_plan_unit_status_update_unit_id: str = ""
    migration_plan_unit_status_update_requested_status: str = ""
    migration_plan_unit_status_update_previous_status: str = ""
    migration_plan_unit_status_update_final_status: str = ""
    migration_plan_audit_summary_short: str = ""
    migration_plan_recommended_next_action: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass(frozen=True)
class MigrationPlanPreparation:
    plan: MigrationPlan | None = None
    source: str = "skipped"
    load_status: str = "skipped"
    load_error: str = ""
    path: str = ""
    resume_summary: dict[str, Any] = dataclasses.field(default_factory=dict)
    active_unit_switch: dict[str, Any] = dataclasses.field(default_factory=dict)
    manual_unit_status_update: dict[str, Any] = dataclasses.field(default_factory=dict)


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ToolError(f"Tool arguments are not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ToolError("Tool arguments must decode to a JSON object.")
    return loaded


def message_from_response(response: dict[str, Any]) -> dict[str, Any]:
    if "choices" not in response and "message" in response:
        message = response["message"]
    else:
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("DeepSeek response did not contain choices.")
        message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise RuntimeError("DeepSeek response message is not an object.")
    return message


def assistant_tool_call_message(message: dict[str, Any], tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    history_message: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": tool_calls,
    }
    if "reasoning_content" in message:
        history_message["reasoning_content"] = message["reasoning_content"]
    return history_message


def extract_final_summary(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(loaded, dict):
        value = loaded.get("final_summary") or loaded.get("summary") or loaded.get("done")
        if value is not None:
            return str(value)
    return text


def format_tool_result(result: dict[str, Any], max_chars: int) -> str:
    text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return text
    note = f'... [Forgis tool result truncated after {max_chars} characters]'
    keep = max(0, max_chars - len(note))
    return text[:keep] + note


def safe_log(message: str) -> None:
    print(f"[forgis] {message}", flush=True)


def sanitize_log_path(value: Any) -> str:
    text = str(value if value is not None else "").strip().replace("\\", "/")
    if not text:
        return "[none]"
    parts: list[str] = []
    for part in text.split("/"):
        if not part:
            continue
        parts.append("[redacted]" if SECRET_PATH_WORDS.search(part) else part)
    sanitized = "/".join(parts) or "[root]"
    if len(sanitized) <= 160:
        return sanitized
    return sanitized[:80] + ".../" + sanitized[-60:]


def tool_call_log_details(name: str, arguments: dict[str, Any] | None) -> str:
    if not arguments:
        return "path=[unavailable]"
    parts: list[str] = []
    if "path" in arguments:
        parts.append(f"path={sanitize_log_path(arguments.get('path'))}")
    if "reference_path" in arguments:
        parts.append(f"reference_path={sanitize_log_path(arguments.get('reference_path'))}")
    if "actual_path" in arguments:
        parts.append(f"actual_path={sanitize_log_path(arguments.get('actual_path'))}")
    if "root" in arguments:
        parts.append(f"root={sanitize_log_path(arguments.get('root'))}")
    if "cwd" in arguments:
        parts.append(f"cwd={sanitize_log_path(arguments.get('cwd'))}")
    for key in ("start_line", "max_lines", "max_depth", "max_results", "max_chars", "timeout_seconds"):
        if key in arguments and arguments[key] is not None:
            parts.append(f"{key}={arguments[key]}")
    if name in WRITE_TOOLS and "path" not in arguments:
        parts.append("path=[unavailable]")
    return " ".join(parts) if parts else "path=[none]"


def changed_paths_from_operations(operation_log: list[dict[str, Any]]) -> list[str]:
    return sorted(set(sanitize_paths([item.get("path") for item in operation_log if item.get("path")])))


def report_payload(
    runtime: RuntimeController,
    repair_loop: RepairLoopController,
    operation_log: list[dict[str, Any]],
) -> tuple[dict[str, Any], str, str]:
    changed_paths = changed_paths_from_operations(operation_log)
    repair_summary = repair_loop.as_dict(include_events=True)
    state = runtime.as_dict(repair_loop_summary=repair_summary)
    state["changed_paths"] = sanitize_paths(
        [*state.get("changed_paths", []), *changed_paths],
    )
    events = repair_summary.get("repair_events", [])
    report = render_repair_report(
        runtime_state=state,
        repair_state=repair_summary,
        events=events,
        changed_paths=state["changed_paths"],
    )
    compact = render_compact_actions_summary(
        runtime_state=state,
        repair_state=repair_summary,
        events=events,
        changed_paths=state["changed_paths"],
    )
    runtime.attach_report(compact_actions_summary=compact, report_markdown=report)
    state = runtime.as_dict(repair_loop_summary=repair_summary)
    state["changed_paths"] = sanitize_paths(
        [*state.get("changed_paths", []), *changed_paths],
    )
    state["compact_actions_summary"] = compact
    state["repair_report_chars"] = len(report)
    return state, report, compact


def log_skill_selection(selection: SkillSelection) -> None:
    names = ", ".join(selection.selected_skill_names) if selection.selected_skill_names else "[none]"
    skipped = ", ".join(selection.skipped_skill_names) if selection.skipped_skill_names else "[none]"
    failed = ", ".join(selection.failed_skill_names) if selection.failed_skill_names else "[none]"
    safe_log(
        "skills: "
        f"enabled={str(selection.skills_enabled).lower()} "
        f"auto_select={str(selection.auto_select_skills).lower()} "
        f"selected={names} "
        f"total_chars={selection.total_skill_chars} "
        f"skipped={skipped} "
        f"failed={failed}"
    )


def read_task_text_for_migration_scheduler(target_root: Path, config: ResolvedConfig) -> str:
    try:
        path = (target_root / config.task_prompt_path).resolve()
        root = target_root.resolve()
    except OSError:
        return ""
    if not path.is_relative_to(root) or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def effective_migration_plan_output_dir(
    config: ResolvedConfig,
    report_output_dir: str | Path | None,
) -> str | Path:
    if "migration_plan_output_dir" in config.config_keys or report_output_dir is None or not str(report_output_dir).strip():
        return config.migration_plan_output_dir
    return report_output_dir


def visual_runtime_root(
    *,
    report_allowed_root: Path | None,
    target_root: Path,
    environ: dict[str, str],
) -> Path:
    raw_root = report_allowed_root or Path(environ.get("GITHUB_WORKSPACE", "") or target_root.parent)
    root = raw_root.resolve()
    if root.name == "forgis-runtime":
        return root
    return root / "forgis-runtime"


def visual_run_id(environ: dict[str, str]) -> str:
    return environ.get("GITHUB_RUN_ID") or environ.get("FORGIS_RUN_ID") or "local"


def visual_provider_env(config: ResolvedConfig, environ: dict[str, str]) -> dict[str, str]:
    mapped_secret_names = {runtime: secret for runtime, secret in config.model_env}

    def env_value(runtime_name: str) -> str:
        secret_name = mapped_secret_names.get(runtime_name)
        if secret_name:
            return environ.get(secret_name, "")
        return environ.get(runtime_name, "")

    return {
        "qwen_api_key": env_value("QWEN_API_KEY"),
        "qwen_api_base": env_value("QWEN_API_BASE"),
        "qwen_model": env_value("QWEN_VISION_MODEL"),
    }


def migration_plan_persistence_state(
    *,
    config: ResolvedConfig,
    preparation: MigrationPlanPreparation,
    write_result: MigrationPlanWriteResult | None = None,
    path: str = "",
) -> dict[str, Any]:
    write = write_result or MigrationPlanWriteResult(status="skipped", path=path)
    plan = preparation.plan
    active_unit_id = ""
    if plan is not None:
        active = plan.active_unit
        active_unit_id = active.unit_id if active is not None else plan.active_unit_id or ""
    return {
        "migration_plan_persistence_enabled": bool(config.migration_plan_persistence_enabled),
        "migration_plan_resume_enabled": bool(config.migration_plan_resume_enabled),
        "migration_plan_resume_summary_enabled": bool(config.migration_plan_resume_summary_enabled),
        "migration_plan_auto_update_enabled": bool(config.migration_plan_auto_update_enabled),
        "migration_plan_auto_complete_on_success": bool(config.migration_plan_auto_complete_on_success),
        "migration_plan_source": preparation.source,
        "migration_plan_path": write.path or path or preparation.path,
        "migration_plan_load_status": preparation.load_status,
        "migration_plan_load_error": preparation.load_error,
        "migration_plan_write_status": write.status,
        "migration_plan_write_error": write.error,
        "active_unit_id": active_unit_id,
    }


def requested_active_unit_switch(
    *,
    plan: MigrationPlan | None,
    config: ResolvedConfig,
    resume_loaded: bool,
) -> dict[str, Any]:
    requested = config.migration_plan_requested_active_unit_id
    if not requested:
        active_id = ""
        if plan is not None:
            active = plan.active_unit
            active_id = active.unit_id if active is not None else plan.active_unit_id or ""
        return safe_active_unit_switch_result(
            {
                "status": "skipped",
                "active_unit_id": active_id,
                "message": "No requested active unit id was configured.",
            }
        )
    if plan is None:
        return safe_active_unit_switch_result(
            {
                "status": "skipped",
                "requested_active_unit_id": requested,
                "reason": "No migration plan is available for active unit switching.",
                "message": "No migration plan is available for active unit switching.",
            }
        )
    result = request_active_unit_switch(
        plan,
        requested,
        config,
        config.migration_plan_switch_reason,
        resume_loaded=resume_loaded,
        max_events=config.migration_plan_event_log_max_events,
    )
    return safe_active_unit_switch_result(result)


def requested_manual_unit_status_update(
    *,
    plan: MigrationPlan | None,
    config: ResolvedConfig,
    resume_loaded: bool,
) -> dict[str, Any]:
    unit_id = config.migration_plan_requested_unit_status_unit_id
    requested_status = config.migration_plan_requested_unit_status
    if not unit_id and not requested_status:
        return safe_unit_status_update_result(
            {
                "status": "skipped",
                "message": "No manual unit status update was configured.",
            }
        )
    if plan is None:
        return safe_unit_status_update_result(
            {
                "status": "skipped",
                "unit_id": unit_id,
                "requested_status": requested_status,
                "reason": config.migration_plan_requested_unit_status_reason,
                "message": "No migration plan is available for manual unit status update.",
            }
        )
    result = request_unit_status_update(
        plan,
        unit_id,
        requested_status,
        config,
        config.migration_plan_requested_unit_status_reason,
        resume_loaded=resume_loaded,
        max_events=config.migration_plan_event_log_max_events,
    )
    return safe_unit_status_update_result(result)


def migration_plan_runtime_fields(
    *,
    plan: MigrationPlan | None,
    config: ResolvedConfig,
    resume_summary: dict[str, Any] | None = None,
    plan_update_status: str = "",
    active_unit_switch: dict[str, Any] | None = None,
    manual_unit_status_update: dict[str, Any] | None = None,
) -> dict[str, Any]:
    audit_summary = build_migration_plan_audit_summary(
        migration_scheduler_enabled=bool(config.migration_scheduler_enabled),
        plan=plan,
        resume_summary=resume_summary,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
        max_events=config.migration_plan_audit_max_events,
        enabled=config.migration_plan_audit_summary_enabled,
    )
    if plan is None:
        return {
            "migration_plan_audit_summary": audit_summary,
            "migration_plan_audit_summary_short": audit_summary.get("summary_short") or "",
            "migration_plan_recommended_next_action": audit_summary.get("recommended_next_action") or "",
        }
    summary = plan.as_summary(
        max_units=config.max_migration_units,
        max_events=config.migration_plan_event_log_max_events,
    )
    events = safe_plan_events(plan.events, max_events=config.migration_plan_event_log_max_events)
    summary["events"] = events
    active = summary.get("active_unit") if isinstance(summary.get("active_unit"), dict) else {}
    safe_resume = safe_resume_summary(resume_summary or {})
    switch = safe_active_unit_switch_result(active_unit_switch or {})
    status_update = safe_unit_status_update_result(manual_unit_status_update or {})
    audit_summary = build_migration_plan_audit_summary(
        migration_scheduler_enabled=True,
        plan_summary=summary,
        plan_events=events,
        resume_summary=safe_resume,
        active_unit_switch=switch,
        manual_unit_status_update=status_update,
        max_events=config.migration_plan_audit_max_events,
        enabled=config.migration_plan_audit_summary_enabled,
    )
    return {
        "migration_scheduler_enabled": True,
        "migration_plan_summary": summary,
        "active_migration_unit": active,
        "active_unit_id": summary.get("active_unit_id") or active.get("unit_id") or "",
        "active_unit_status": active.get("status") or "",
        "active_unit_reason": active.get("reason") or "",
        "plan_events": events,
        "resume_summary": safe_resume,
        "resume_summary_short": safe_resume.get("summary_short") or "",
        "plan_update_status": sanitize_log_path(plan_update_status) if plan_update_status else "skipped",
        "active_unit_switch": switch,
        "migration_plan_switch_status": switch.get("status") or "skipped",
        "migration_plan_switch_reason": switch.get("reason") or "",
        "migration_plan_requested_active_unit_id": switch.get("requested_active_unit_id") or "",
        "migration_plan_previous_active_unit_id": switch.get("previous_active_unit_id") or "",
        "manual_unit_status_update": status_update,
        "migration_plan_unit_status_update_status": status_update.get("status") or "skipped",
        "migration_plan_unit_status_update_reason": status_update.get("reason") or "",
        "migration_plan_unit_status_update_unit_id": status_update.get("unit_id") or "",
        "migration_plan_unit_status_update_requested_status": status_update.get("requested_status") or "",
        "migration_plan_unit_status_update_previous_status": status_update.get("previous_status") or "",
        "migration_plan_unit_status_update_final_status": status_update.get("final_status") or "",
        "migration_plan_audit_summary": audit_summary,
        "migration_plan_audit_summary_short": audit_summary.get("summary_short") or "",
        "migration_plan_recommended_next_action": audit_summary.get("recommended_next_action") or "",
    }


def prepare_migration_plan(
    *,
    config: ResolvedConfig,
    source_root: Path,
    target_root: Path,
    skill_selection: SkillSelection,
    report_output_dir: str | Path | None = None,
    report_allowed_root: Path | None = None,
) -> MigrationPlanPreparation:
    if not config.migration_scheduler_enabled:
        return MigrationPlanPreparation()
    plan_path = ""
    load_result = MigrationPlanLoadResult(status="disabled")
    if config.migration_plan_persistence_enabled:
        root = (report_allowed_root or Path(os.environ.get("GITHUB_WORKSPACE", "") or Path.cwd())).resolve()
        try:
            plan_path = migration_plan_file_path(
                effective_migration_plan_output_dir(config, report_output_dir),
                filename=config.migration_plan_filename,
                allowed_root=root,
                source_root=source_root,
                target_root=target_root,
            ).as_posix()
        except Exception as exc:
            plan_path = ""
            load_result = MigrationPlanLoadResult(status="failed", error=sanitize_log_path(str(exc)))
        if config.migration_plan_resume_enabled and plan_path:
            load_result = load_migration_plan(
                plan_path,
                allowed_root=root,
                source_root=source_root,
                target_root=target_root,
            )
            if load_result.status == "loaded" and load_result.plan is not None:
                for unit in load_result.plan.units:
                    unit.selected_skill_names = list(skill_selection.selected_skill_names)
                append_plan_event(
                    load_result.plan,
                    "plan_loaded",
                    unit_id=load_result.plan.active_unit_id or "",
                    status_after=(load_result.plan.active_unit.status if load_result.plan.active_unit is not None else ""),
                    reason="Loaded persisted migration plan for resume.",
                    short_message="Migration plan loaded from runtime artifact.",
                    max_events=config.migration_plan_event_log_max_events,
                )
                if load_result.plan.active_unit is not None:
                    append_plan_event(
                        load_result.plan,
                        "active_unit_selected",
                        unit_id=load_result.plan.active_unit.unit_id,
                        status_after=load_result.plan.active_unit.status,
                        reason="Resuming the active unit recorded in the loaded plan.",
                        short_message="Active unit resumed from persisted plan.",
                        max_events=config.migration_plan_event_log_max_events,
                    )
                active_unit_switch = requested_active_unit_switch(
                    plan=load_result.plan,
                    config=config,
                    resume_loaded=True,
                )
                manual_unit_status_update = requested_manual_unit_status_update(
                    plan=load_result.plan,
                    config=config,
                    resume_loaded=True,
                )
                resume_summary = {}
                if config.migration_plan_resume_summary_enabled:
                    resume_summary = generate_resume_summary(
                        load_result.plan,
                        active_unit_switch=active_unit_switch,
                        manual_unit_status_update=manual_unit_status_update,
                    )
                    append_plan_event(
                        load_result.plan,
                        "resume_summary_generated",
                        unit_id=resume_summary.get("active_unit_id") or "",
                        status_after=resume_summary.get("last_active_unit_status") or "",
                        reason=resume_summary.get("next_step") or "",
                        short_message="Resume summary generated.",
                        max_events=config.migration_plan_event_log_max_events,
                    )
                safe_log(
                    "migration scheduler resume loaded: "
                    f"plan_id={load_result.plan.plan_id} "
                    f"units={len(load_result.plan.units)} "
                    f"active_unit={load_result.plan.active_unit_id or '[none]'} "
                    f"switch_status={active_unit_switch.get('status') or 'skipped'} "
                    f"status_update={manual_unit_status_update.get('status') or 'skipped'}"
                )
                return MigrationPlanPreparation(
                    plan=load_result.plan,
                    source="loaded",
                    load_status=load_result.status,
                    load_error=load_result.error,
                    path=load_result.path or plan_path,
                    resume_summary=resume_summary,
                    active_unit_switch=active_unit_switch,
                    manual_unit_status_update=manual_unit_status_update,
                )
    task_text = read_task_text_for_migration_scheduler(target_root, config)
    inventory: list[Any] = []
    if config.migration_unit_strategy == "inventory":
        try:
            inventory = collect_scheduler_inventory(
                source_root,
                config.staged_translation.source_inventory,
                max_units=config.max_migration_units,
            )
        except Exception as exc:
            safe_log(f"migration scheduler inventory unavailable: {exc}")
            inventory = []
    plan = create_units_from_inventory(inventory, config, task_text)
    for unit in plan.units:
        unit.selected_skill_names = list(skill_selection.selected_skill_names)
    append_plan_event(
        plan,
        "plan_generated",
        reason="Generated migration plan from scheduler inventory/task text.",
        short_message=f"Generated migration plan with {len(plan.units)} unit(s).",
        max_events=config.migration_plan_event_log_max_events,
    )
    next_unit = select_next_unit(plan)
    if next_unit is not None:
        mark_unit_active(plan, next_unit.unit_id)
    active_unit_switch = requested_active_unit_switch(
        plan=plan,
        config=config,
        resume_loaded=False,
    )
    manual_unit_status_update = requested_manual_unit_status_update(
        plan=plan,
        config=config,
        resume_loaded=False,
    )
    if not config.migration_plan_persistence_enabled:
        load_status = "disabled"
        source = "generated"
        load_error = ""
    elif config.migration_plan_resume_enabled and load_result.status not in {"disabled", "skipped"}:
        load_status = load_result.status
        source = "failed_to_load_generated"
        load_error = load_result.error
    elif config.migration_plan_resume_enabled:
        load_status = load_result.status if load_result.status != "disabled" else "skipped"
        source = "generated"
        load_error = load_result.error
    else:
        load_status = "disabled"
        source = "generated"
        load_error = ""
    safe_log(
        "migration scheduler enabled: "
        f"plan_id={plan.plan_id} "
        f"units={len(plan.units)} "
        f"active_unit={plan.active_unit_id or '[none]'} "
        f"plan_source={source} "
        f"switch_status={active_unit_switch.get('status') or 'skipped'} "
        f"status_update={manual_unit_status_update.get('status') or 'skipped'}"
    )
    return MigrationPlanPreparation(
        plan=plan,
        source=source,
        load_status=load_status,
        load_error=load_error,
        path=load_result.path or plan_path,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
    )


def attach_migration_state(
    runtime: RuntimeController,
    plan: MigrationPlan | None,
    config: ResolvedConfig,
    *,
    resume_summary: dict[str, Any] | None = None,
    plan_update_status: str = "",
    active_unit_switch: dict[str, Any] | None = None,
    manual_unit_status_update: dict[str, Any] | None = None,
) -> None:
    fields = migration_plan_runtime_fields(
        plan=plan,
        config=config,
        resume_summary=resume_summary,
        plan_update_status=plan_update_status or runtime.plan_update_status,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
    )
    if plan is not None:
        runtime.attach_migration_plan(fields.get("migration_plan_summary"))
        runtime.attach_active_unit_switch(fields.get("active_unit_switch"))
        runtime.attach_manual_unit_status_update(fields.get("manual_unit_status_update"))
        runtime.attach_migration_plan_update(
            plan_update_status=str(fields.get("plan_update_status") or ""),
            resume_summary=fields.get("resume_summary") if isinstance(fields.get("resume_summary"), dict) else None,
        )
    audit_summary = fields.get("migration_plan_audit_summary")
    runtime.attach_migration_plan_audit(audit_summary if isinstance(audit_summary, dict) else None)


def skipped_result(
    *,
    status: str,
    final_summary: str,
    config: ResolvedConfig,
    visual_task_text: str = "",
    skill_selection: SkillSelection | None = None,
    migration_plan: MigrationPlan | None = None,
    resume_summary: dict[str, Any] | None = None,
    active_unit_switch: dict[str, Any] | None = None,
    manual_unit_status_update: dict[str, Any] | None = None,
) -> ToolLoopResult:
    runtime = RuntimeController()
    if skill_selection is not None:
        runtime.attach_skills(skill_selection.as_runtime_state())
    runtime.attach_visual_config(config.visual_validation)
    runtime.attach_visual_task_text(visual_task_text)
    attach_migration_state(
        runtime,
        migration_plan,
        config,
        resume_summary=resume_summary,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
    )
    repair_loop = RepairLoopController.from_config(config)
    state, report, compact = report_payload(runtime, repair_loop, [])
    return ToolLoopResult(
        executed=False,
        status=status,
        final_summary=final_summary,
        iterations=0,
        tool_call_count=0,
        read_tool_count=0,
        write_tool_count=0,
        operation_log=[],
        runtime_state=state,
        repair_report=report,
        compact_actions_summary=compact,
    )


def attach_migration_plan_persistence_to_result(
    *,
    result: ToolLoopResult,
    config: ResolvedConfig,
    preparation: MigrationPlanPreparation,
    write_result: MigrationPlanWriteResult,
) -> ToolLoopResult:
    state = dict(result.runtime_state or {})
    state.update(
        migration_plan_runtime_fields(
            plan=preparation.plan,
            config=config,
            resume_summary=preparation.resume_summary,
            plan_update_status=str(state.get("plan_update_status") or "skipped"),
            active_unit_switch=preparation.active_unit_switch,
            manual_unit_status_update=preparation.manual_unit_status_update,
        )
    )
    persistence = migration_plan_persistence_state(
        config=config,
        preparation=preparation,
        write_result=write_result,
    )
    state.update(persistence)
    return dataclasses.replace(
        result,
        runtime_state=state,
        migration_plan_path=str(persistence.get("migration_plan_path") or ""),
        migration_plan_write_status=str(persistence.get("migration_plan_write_status") or "skipped"),
        migration_plan_load_status=str(persistence.get("migration_plan_load_status") or "skipped"),
        migration_plan_source=str(persistence.get("migration_plan_source") or "skipped"),
        active_unit_id=str(persistence.get("active_unit_id") or ""),
        migration_plan_write_error=str(persistence.get("migration_plan_write_error") or ""),
        migration_plan_load_error=str(persistence.get("migration_plan_load_error") or ""),
        migration_plan_update_status=str(state.get("plan_update_status") or "skipped"),
        migration_plan_active_unit_status=str(state.get("active_unit_status") or ""),
        migration_plan_active_unit_reason=str(state.get("active_unit_reason") or ""),
        migration_plan_resume_summary_short=str(state.get("resume_summary_short") or ""),
        migration_plan_switch_status=str(state.get("migration_plan_switch_status") or "skipped"),
        migration_plan_switch_reason=str(state.get("migration_plan_switch_reason") or ""),
        migration_plan_requested_active_unit_id=str(state.get("migration_plan_requested_active_unit_id") or ""),
        migration_plan_previous_active_unit_id=str(state.get("migration_plan_previous_active_unit_id") or ""),
        migration_plan_unit_status_update_status=str(state.get("migration_plan_unit_status_update_status") or "skipped"),
        migration_plan_unit_status_update_reason=str(state.get("migration_plan_unit_status_update_reason") or ""),
        migration_plan_unit_status_update_unit_id=str(state.get("migration_plan_unit_status_update_unit_id") or ""),
        migration_plan_unit_status_update_requested_status=str(state.get("migration_plan_unit_status_update_requested_status") or ""),
        migration_plan_unit_status_update_previous_status=str(state.get("migration_plan_unit_status_update_previous_status") or ""),
        migration_plan_unit_status_update_final_status=str(state.get("migration_plan_unit_status_update_final_status") or ""),
        migration_plan_audit_summary_short=str(state.get("migration_plan_audit_summary_short") or ""),
        migration_plan_recommended_next_action=str(state.get("migration_plan_recommended_next_action") or ""),
    )


def persist_migration_plan_for_result(
    *,
    result: ToolLoopResult,
    config: ResolvedConfig,
    preparation: MigrationPlanPreparation,
    source_root: Path,
    target_root: Path,
    report_output_dir: str | Path | None,
    report_allowed_root: Path | None,
) -> ToolLoopResult:
    plan = preparation.plan
    if not config.migration_scheduler_enabled or plan is None:
        write_result = MigrationPlanWriteResult(status="skipped", path=preparation.path)
        return attach_migration_plan_persistence_to_result(
            result=result,
            config=config,
            preparation=preparation,
            write_result=write_result,
        )
    if not config.migration_plan_persistence_enabled:
        write_result = MigrationPlanWriteResult(status="disabled", path=preparation.path)
        return attach_migration_plan_persistence_to_result(
            result=result,
            config=config,
            preparation=preparation,
            write_result=write_result,
        )
    output_dir = effective_migration_plan_output_dir(config, report_output_dir)
    root = (report_allowed_root or Path(os.environ.get("GITHUB_WORKSPACE", "") or Path.cwd())).resolve()
    write_result = write_migration_plan(
        plan,
        output_dir,
        filename=config.migration_plan_filename,
        allowed_root=root,
        source_root=source_root,
        target_root=target_root,
        required=config.migration_plan_required,
        max_events=config.migration_plan_event_log_max_events,
    )
    if write_result.status == "written":
        append_plan_event(
            plan,
            "plan_write_succeeded",
            unit_id=plan.active_unit_id or "",
            status_after=(plan.active_unit.status if plan.active_unit is not None else ""),
            reason="Migration plan persisted to the runtime report artifact directory.",
            short_message="Migration plan write succeeded.",
            max_events=config.migration_plan_event_log_max_events,
        )
        second_write = write_migration_plan(
            plan,
            output_dir,
            filename=config.migration_plan_filename,
            allowed_root=root,
            source_root=source_root,
            target_root=target_root,
            required=config.migration_plan_required,
            max_events=config.migration_plan_event_log_max_events,
        )
        if second_write.status != "written":
            write_result = second_write
    else:
        append_plan_event(
            plan,
            "plan_write_failed",
            unit_id=plan.active_unit_id or "",
            status_after=(plan.active_unit.status if plan.active_unit is not None else ""),
            reason=write_result.error or "Migration plan write was skipped or failed.",
            short_message="Migration plan write failed.",
            max_events=config.migration_plan_event_log_max_events,
        )
    return attach_migration_plan_persistence_to_result(
        result=result,
        config=config,
        preparation=preparation,
        write_result=write_result,
    )


def finalize_tool_loop_result(
    *,
    result: ToolLoopResult,
    config: ResolvedConfig,
    preparation: MigrationPlanPreparation,
    source_root: Path,
    target_root: Path,
    report_output_dir: str | Path | None,
    report_allowed_root: Path | None,
    run_metadata: dict[str, Any] | None = None,
) -> ToolLoopResult:
    result_with_plan = persist_migration_plan_for_result(
        result=result,
        config=config,
        preparation=preparation,
        source_root=source_root,
        target_root=target_root,
        report_output_dir=report_output_dir,
        report_allowed_root=report_allowed_root,
    )
    return attach_run_reports(
        result=result_with_plan,
        config=config,
        source_root=source_root,
        target_root=target_root,
        output_dir=report_output_dir,
        allowed_root=report_allowed_root,
        metadata=run_metadata,
    )


def attach_run_reports(
    *,
    result: ToolLoopResult,
    config: ResolvedConfig,
    source_root: Path,
    target_root: Path,
    output_dir: str | Path | None,
    allowed_root: Path | None,
    metadata: dict[str, Any] | None = None,
) -> ToolLoopResult:
    if not config.run_report_enabled:
        return dataclasses.replace(result, report_write_status="disabled")
    if output_dir is None or not str(output_dir).strip():
        return dataclasses.replace(result, report_write_status="skipped", report_write_error="run report output dir was not provided")

    root = (allowed_root or Path(os.environ.get("GITHUB_WORKSPACE", "") or Path.cwd())).resolve()
    report_markdown = render_run_report_markdown(
        config=config,
        runtime_state=result.runtime_state,
        repair_report_markdown=result.repair_report,
        final_summary=result.final_summary,
        status=result.status,
        executed=result.executed,
        iterations=result.iterations,
        tool_call_count=result.tool_call_count,
        read_tool_count=result.read_tool_count,
        write_tool_count=result.write_tool_count,
        operation_log=result.operation_log,
        metadata=metadata,
    )
    report_json = render_run_report_json(
        config=config,
        runtime_state=result.runtime_state,
        repair_report_markdown=result.repair_report,
        final_summary=result.final_summary,
        status=result.status,
        executed=result.executed,
        iterations=result.iterations,
        tool_call_count=result.tool_call_count,
        read_tool_count=result.read_tool_count,
        write_tool_count=result.write_tool_count,
        operation_log=result.operation_log,
        metadata=metadata,
    )
    write_result = write_run_reports(
        output_dir=output_dir,
        markdown=report_markdown,
        json_data=report_json,
        allowed_root=root,
        source_root=source_root,
        target_root=target_root,
        required=config.run_report_required,
        max_chars=config.run_report_max_chars,
    )
    return dataclasses.replace(
        result,
        report_markdown_path=write_result.markdown_path,
        report_json_path=write_result.json_path,
        report_write_status=write_result.status,
        report_write_error=write_result.error,
    )


def log_tool_loop_finished(
    *,
    iterations: int,
    tool_call_count: int,
    sandbox: FileToolSandbox,
) -> None:
    changed_paths = changed_paths_from_operations(sandbox.operation_log())
    safe_log(
        "tool loop finished: "
        f"iterations={iterations} "
        f"tool_calls={tool_call_count} "
        f"reads={sandbox.read_count} "
        f"writes={sandbox.write_count} "
        f"changed_paths={len(changed_paths)}"
    )


def runtime_state_snapshot(
    runtime: RuntimeController,
    repair_loop: RepairLoopController,
    operation_log: list[dict[str, Any]],
) -> dict[str, Any]:
    repair_summary = repair_loop.as_dict(include_events=True)
    state = runtime.as_dict(repair_loop_summary=repair_summary)
    state["changed_paths"] = sanitize_paths(
        [*state.get("changed_paths", []), *changed_paths_from_operations(operation_log)],
    )
    return state


def finalize_active_unit_state(
    *,
    runtime: RuntimeController,
    repair_loop: RepairLoopController,
    operation_log: list[dict[str, Any]],
    migration_plan: MigrationPlan | None,
    config: ResolvedConfig,
    tool_loop_status: str,
    resume_summary: dict[str, Any] | None = None,
    active_unit_switch: dict[str, Any] | None = None,
    manual_unit_status_update: dict[str, Any] | None = None,
) -> None:
    if migration_plan is None:
        return
    if not config.migration_plan_auto_update_enabled:
        attach_migration_state(
            runtime,
            migration_plan,
            config,
            resume_summary=resume_summary,
            plan_update_status="disabled",
            active_unit_switch=active_unit_switch,
            manual_unit_status_update=manual_unit_status_update,
        )
        return
    state = runtime_state_snapshot(runtime, repair_loop, operation_log)
    update = update_active_unit_state(
        migration_plan,
        state,
        auto_complete_on_success=config.migration_plan_auto_complete_on_success,
        normal_tool_loop_end=tool_loop_status == "completed",
        max_events=config.migration_plan_event_log_max_events,
    )
    attach_migration_state(
        runtime,
        migration_plan,
        config,
        resume_summary=resume_summary,
        plan_update_status=update.update_status,
        active_unit_switch=active_unit_switch,
        manual_unit_status_update=manual_unit_status_update,
    )


def run_tool_loop(
    *,
    config: ResolvedConfig,
    source_root: Path,
    target_root: Path,
    environ: dict[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    report_output_dir: str | Path | None = None,
    report_allowed_root: Path | None = None,
    run_metadata: dict[str, Any] | None = None,
) -> ToolLoopResult:
    env = dict(os.environ if environ is None else environ)
    task_text = read_task_text_for_migration_scheduler(target_root, config)
    skill_selection = build_skill_selection(config, target_root=target_root)
    log_skill_selection(skill_selection)
    migration_preparation = prepare_migration_plan(
        config=config,
        source_root=source_root,
        target_root=target_root,
        skill_selection=skill_selection,
        report_output_dir=report_output_dir,
        report_allowed_root=report_allowed_root,
    )
    migration_plan = migration_preparation.plan
    if config.dry_run:
        safe_log("dry_run=true; skipping DeepSeek tool loop")
        result = skipped_result(
            status="skipped-dry-run",
            final_summary="dry_run=true; DeepSeek was not called.",
            config=config,
            visual_task_text=task_text,
            skill_selection=skill_selection,
            migration_plan=migration_plan,
            resume_summary=migration_preparation.resume_summary,
            active_unit_switch=migration_preparation.active_unit_switch,
            manual_unit_status_update=migration_preparation.manual_unit_status_update,
        )
        return finalize_tool_loop_result(
            result=result,
            config=config,
            preparation=migration_preparation,
            source_root=source_root,
            target_root=target_root,
            report_output_dir=report_output_dir,
            report_allowed_root=report_allowed_root,
            run_metadata=run_metadata,
        )
    if not config.run_agent:
        safe_log("run_agent=false; skipping DeepSeek tool loop")
        result = skipped_result(
            status="skipped-run-agent-false",
            final_summary="run_agent=false; DeepSeek was not called.",
            config=config,
            visual_task_text=task_text,
            skill_selection=skill_selection,
            migration_plan=migration_plan,
            resume_summary=migration_preparation.resume_summary,
            active_unit_switch=migration_preparation.active_unit_switch,
            manual_unit_status_update=migration_preparation.manual_unit_status_update,
        )
        return finalize_tool_loop_result(
            result=result,
            config=config,
            preparation=migration_preparation,
            source_root=source_root,
            target_root=target_root,
            report_output_dir=report_output_dir,
            report_allowed_root=report_allowed_root,
            run_metadata=run_metadata,
        )

    if config.execution_mode == STAGED_TRANSLATION_MODE:
        from staged_translation import run_staged_translation_loop

        staged_result = run_staged_translation_loop(
            config=config,
            source_root=source_root,
            target_root=target_root,
            environ=env,
            client_factory=client_factory,
            skill_selection=skill_selection,
            report_allowed_root=report_allowed_root,
        )
        if migration_plan is not None:
            state = dict(staged_result.runtime_state or {})
            state.update(
                migration_plan_runtime_fields(
                    plan=migration_plan,
                    config=config,
                    resume_summary=migration_preparation.resume_summary,
                    plan_update_status="staged_summary_only",
                    active_unit_switch=migration_preparation.active_unit_switch,
                    manual_unit_status_update=migration_preparation.manual_unit_status_update,
                )
            )
            staged_result = dataclasses.replace(staged_result, runtime_state=state)
        return finalize_tool_loop_result(
            result=staged_result,
            config=config,
            preparation=migration_preparation,
            source_root=source_root,
            target_root=target_root,
            report_output_dir=report_output_dir,
            report_allowed_root=report_allowed_root,
            run_metadata=run_metadata,
        )

    visual_env = visual_provider_env(config, env)
    sandbox = FileToolSandbox(
        source_root=source_root,
        target_root=target_root,
        target_subdir=config.target_subdir,
        config_path=config.config_path,
        task_path=config.task_prompt_path,
        max_result_chars=config.max_tool_result_chars,
        build_command=config.build_command,
        test_command=config.test_command,
        build_timeout_seconds=config.build_timeout_seconds,
        test_timeout_seconds=config.test_timeout_seconds,
        max_command_output_chars=config.max_command_output_chars,
        visual_validation_enabled=config.visual_validation.enabled,
        visual_validation_provider=config.visual_validation.provider,
        visual_validation_mode=config.visual_validation.mode,
        reference_screenshot_dirs=config.visual_validation.reference_screenshot_dirs,
        actual_screenshot_dirs=config.visual_validation.actual_screenshot_dirs,
        require_actual_for_full_validation=config.visual_validation.require_actual_for_full_validation,
        max_visual_iterations=config.visual_validation.max_visual_iterations,
        visual_evidence_runtime_root=visual_runtime_root(
            report_allowed_root=report_allowed_root,
            target_root=target_root,
            environ=env,
        ),
        visual_evidence_run_id=visual_run_id(env),
        target_repo=config.target_repo,
        qwen_api_key=visual_env.get("qwen_api_key") or None,
        qwen_api_base=visual_env.get("qwen_api_base") or None,
        qwen_model=visual_env.get("qwen_model") or None,
    )
    runtime = RuntimeController()
    runtime.attach_skills(skill_selection.as_runtime_state())
    runtime.attach_visual_config(config.visual_validation)
    runtime.attach_visual_task_text(task_text)
    attach_migration_state(
        runtime,
        migration_plan,
        config,
        resume_summary=migration_preparation.resume_summary,
        active_unit_switch=migration_preparation.active_unit_switch,
        manual_unit_status_update=migration_preparation.manual_unit_status_update,
    )
    repair_loop = RepairLoopController.from_config(config)
    factory = client_factory or (lambda cfg, local_env: DeepSeekClient.from_config(cfg, local_env))
    client = factory(config, env)
    messages: list[dict[str, Any]] = initial_messages(
        config,
        render_selected_skills(skill_selection),
        render_active_unit_context(
            migration_plan,
            migration_preparation.active_unit_switch,
            migration_preparation.manual_unit_status_update,
        )
        if migration_plan is not None
        else "",
    )
    tool_call_count = 0
    safe_log(f"tool loop started: max_iterations={config.max_iterations}")
    if repair_loop.enabled:
        safe_log(
            "repair loop enabled: "
            f"max_attempts={repair_loop.max_attempts} "
            f"requires_diff_check={str(repair_loop.requires_diff_check).lower()} "
            f"requires_build_or_test={str(repair_loop.requires_build_or_test).lower()}"
        )

    for iteration in range(1, config.max_iterations + 1):
        safe_log(f"iteration {iteration}/{config.max_iterations}: requesting model")
        response = client.chat(messages, TOOL_DEFINITIONS)
        message = message_from_response(response)
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""
        has_assistant_message = "yes" if message else "no"

        if not tool_calls:
            summary = extract_final_summary(str(content))
            safe_log(
                f"iteration {iteration}/{config.max_iterations}: "
                f"assistant_message={has_assistant_message} tool_calls=0 "
                f"final_summary={'yes' if summary else 'no'}"
            )
            if summary:
                final_block_reason = repair_loop.final_summary_block_reason()
                if final_block_reason:
                    safe_log(f"final_summary blocked by repair loop: {final_block_reason}")
                    repair_loop.observe_final_summary_blocked(final_block_reason)
                    messages.append({"role": "assistant", "content": str(content)})
                    messages.append(
                        {
                            "role": "user",
                            "content": "\n".join(
                                [
                                    "[forgis repair loop]",
                                    final_block_reason,
                                    "Inspect the current diff and run the configured build/test check before final_summary.",
                                    f"repair_state: {json.dumps(repair_loop.as_dict(), ensure_ascii=False, sort_keys=True)}",
                                ]
                            ),
                        }
                    )
                    continue
                safe_log("final_summary received")
            log_tool_loop_finished(
                iterations=iteration,
                tool_call_count=tool_call_count,
                sandbox=sandbox,
            )
            operation_log = sandbox.operation_log()
            loop_status = runtime.visual_effective_status("completed")
            finalize_active_unit_state(
                runtime=runtime,
                repair_loop=repair_loop,
                operation_log=operation_log,
                migration_plan=migration_plan,
                config=config,
                tool_loop_status=loop_status,
                resume_summary=migration_preparation.resume_summary,
                active_unit_switch=migration_preparation.active_unit_switch,
                manual_unit_status_update=migration_preparation.manual_unit_status_update,
            )
            state, report, compact = report_payload(runtime, repair_loop, operation_log)
            result = ToolLoopResult(
                executed=True,
                status=loop_status,
                final_summary=summary or "DeepSeek returned no final summary.",
                iterations=iteration,
                tool_call_count=tool_call_count,
                read_tool_count=sandbox.read_count,
                write_tool_count=sandbox.write_count,
                operation_log=operation_log,
                runtime_state=state,
                repair_report=report,
                compact_actions_summary=compact,
            )
            return finalize_tool_loop_result(
                result=result,
                config=config,
                preparation=migration_preparation,
                source_root=source_root,
                target_root=target_root,
                report_output_dir=report_output_dir,
                report_allowed_root=report_allowed_root,
                run_metadata=run_metadata,
            )

        messages.append(assistant_tool_call_message(message, tool_calls))
        safe_log(
            f"iteration {iteration}/{config.max_iterations}: "
            f"assistant_message={has_assistant_message} "
            f"model returned {len(tool_calls)} tool calls "
            "final_summary=no"
        )

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            raw_arguments = function.get("arguments", "{}")
            tool_call_count += 1
            arguments: dict[str, Any] | None = None
            status = "error"
            try:
                arguments = parse_tool_arguments(raw_arguments)
                safe_log(
                    f"tool call {tool_call_count}: iteration={iteration} "
                    f"{name or '[unknown]'} {tool_call_log_details(name, arguments)}"
                )
                block_reason = repair_loop.block_reason_for_tool(name)
                if block_reason:
                    result = repair_loop.blocked_tool_result(name, block_reason)
                    status = "blocked"
                else:
                    repair_loop.observe_tool_started(name=name)
                    result = sandbox.invoke(name, arguments)
                    status = "ok" if result.get("ok") else "error"
            except ToolError as exc:
                if arguments is None:
                    safe_log(
                        f"tool call {tool_call_count}: iteration={iteration} "
                        f"{name or '[unknown]'} path=[unavailable]"
                    )
                result = {"ok": False, "error": str(exc)}
                status = "blocked"
            except Exception as exc:
                if arguments is None:
                    safe_log(
                        f"tool call {tool_call_count}: iteration={iteration} "
                        f"{name or '[unknown]'} path=[unavailable]"
                    )
                result = {"ok": False, "error": str(exc)}
                status = "error"
            runtime.observe_tool_result(name=name, arguments=arguments or {}, result=result)
            repair_loop.observe_tool_result(name=name, result=result)
            if (
                config.migration_plan_auto_update_enabled
                and migration_plan is not None
                and migration_plan.active_unit is not None
            ):
                update_active_unit_runtime_fields(
                    migration_plan,
                    runtime.as_dict(),
                    max_events=config.migration_plan_event_log_max_events,
                )
                attach_migration_state(
                    runtime,
                    migration_plan,
                    config,
                    resume_summary=migration_preparation.resume_summary,
                    plan_update_status="running",
                    active_unit_switch=migration_preparation.active_unit_switch,
                    manual_unit_status_update=migration_preparation.manual_unit_status_update,
                )
            if repair_loop.enabled:
                result["repair_loop"] = repair_loop.as_dict()
                if result["repair_loop"].get("stopped_reason"):
                    safe_log(
                        "repair loop state: "
                        f"attempts={result['repair_loop'].get('repair_attempts_used')} "
                        f"stopped_reason={result['repair_loop'].get('stopped_reason')}"
                    )
            full_result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
            formatted_result = format_tool_result(result, config.max_tool_result_chars)
            result_truncated = bool(result.get("truncated")) or len(full_result_text) > config.max_tool_result_chars
            changed_paths = changed_paths_from_operations(sandbox.operation_log())
            safe_log(
                f"tool call {tool_call_count} result: {status} "
                f"chars={len(formatted_result)} "
                f"truncated={str(result_truncated).lower()} "
                f"total_tool_calls={tool_call_count} "
                f"reads={sandbox.read_count} "
                f"writes={sandbox.write_count} "
                f"changed_paths={len(changed_paths)}"
            )
            if name in WRITE_TOOLS and result.get("ok") and result.get("path"):
                safe_log(f"tool call {tool_call_count} changed_path={sanitize_log_path(result.get('path'))}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", f"tool-{tool_call_count}"),
                    "name": name,
                    "content": formatted_result,
                }
            )

    safe_log(f"max_iterations reached: {config.max_iterations}")
    log_tool_loop_finished(
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        sandbox=sandbox,
    )
    operation_log = sandbox.operation_log()
    loop_status = runtime.visual_effective_status("max-iterations")
    finalize_active_unit_state(
        runtime=runtime,
        repair_loop=repair_loop,
        operation_log=operation_log,
        migration_plan=migration_plan,
        config=config,
        tool_loop_status=loop_status,
        resume_summary=migration_preparation.resume_summary,
        active_unit_switch=migration_preparation.active_unit_switch,
        manual_unit_status_update=migration_preparation.manual_unit_status_update,
    )
    state, report, compact = report_payload(runtime, repair_loop, operation_log)
    result = ToolLoopResult(
        executed=True,
        status=loop_status,
        final_summary=f"DeepSeek tool loop stopped after max_iterations={config.max_iterations}.",
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        read_tool_count=sandbox.read_count,
        write_tool_count=sandbox.write_count,
        operation_log=operation_log,
        runtime_state=state,
        repair_report=report,
        compact_actions_summary=compact,
    )
    return finalize_tool_loop_result(
        result=result,
        config=config,
        preparation=migration_preparation,
        source_root=source_root,
        target_root=target_root,
        report_output_dir=report_output_dir,
        report_allowed_root=report_allowed_root,
        run_metadata=run_metadata,
    )


def write_status(path: str, result: ToolLoopResult) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    safe_summary = result.final_summary.replace("\n", "\\n")
    values = {
        "deepseek_executed": "true" if result.executed else "false",
        "deepseek_status": result.status,
        "tool_call_count": str(result.tool_call_count),
        "read_tool_count": str(result.read_tool_count),
        "write_tool_count": str(result.write_tool_count),
        "final_summary": safe_summary,
        "compact_actions_summary": result.compact_actions_summary.replace("\n", "\\n"),
        "report_markdown_path": result.report_markdown_path,
        "report_json_path": result.report_json_path,
        "report_write_status": result.report_write_status,
        "report_write_error": result.report_write_error.replace("\n", "\\n"),
        "migration_plan_path": result.migration_plan_path,
        "migration_plan_write_status": result.migration_plan_write_status,
        "migration_plan_load_status": result.migration_plan_load_status,
        "migration_plan_source": result.migration_plan_source,
        "active_unit_id": result.active_unit_id,
        "migration_plan_write_error": result.migration_plan_write_error.replace("\n", "\\n"),
        "migration_plan_load_error": result.migration_plan_load_error.replace("\n", "\\n"),
        "migration_plan_update_status": result.migration_plan_update_status,
        "migration_plan_active_unit_status": result.migration_plan_active_unit_status,
        "migration_plan_active_unit_reason": result.migration_plan_active_unit_reason.replace("\n", "\\n"),
        "migration_plan_resume_summary_short": result.migration_plan_resume_summary_short.replace("\n", "\\n"),
        "migration_plan_switch_status": result.migration_plan_switch_status,
        "migration_plan_switch_reason": result.migration_plan_switch_reason.replace("\n", "\\n"),
        "migration_plan_requested_active_unit_id": result.migration_plan_requested_active_unit_id,
        "migration_plan_previous_active_unit_id": result.migration_plan_previous_active_unit_id,
        "migration_plan_unit_status_update_status": result.migration_plan_unit_status_update_status,
        "migration_plan_unit_status_update_reason": result.migration_plan_unit_status_update_reason.replace("\n", "\\n"),
        "migration_plan_unit_status_update_unit_id": result.migration_plan_unit_status_update_unit_id,
        "migration_plan_unit_status_update_requested_status": result.migration_plan_unit_status_update_requested_status,
        "migration_plan_unit_status_update_previous_status": result.migration_plan_unit_status_update_previous_status,
        "migration_plan_unit_status_update_final_status": result.migration_plan_unit_status_update_final_status,
        "migration_plan_audit_summary_short": result.migration_plan_audit_summary_short.replace("\n", "\\n"),
        "migration_plan_recommended_next_action": result.migration_plan_recommended_next_action.replace("\n", "\\n"),
    }
    for key, value in (result.runtime_state or {}).items():
        if isinstance(value, bool):
            values[f"runtime_{key}"] = "true" if value else "false"
        elif isinstance(value, int):
            values[f"runtime_{key}"] = str(value)
        elif isinstance(value, str):
            values[f"runtime_{key}"] = value
        elif isinstance(value, (list, tuple)):
            values[f"runtime_{key}"] = json.dumps(list(value), ensure_ascii=False, sort_keys=True)
        elif isinstance(value, dict):
            values[f"runtime_{key}"] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    output.write_text(
        "\n".join(f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def write_json(path: str, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Forgis DeepSeek tool loop")
    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target repository")
    parser.add_argument("--target-repo", required=True, help="Target repository, for example owner/target-repo")
    parser.add_argument("--status-output", default="")
    parser.add_argument("--operation-log-output", default="")
    parser.add_argument("--summary-output", default="")
    parser.add_argument("--report-output-dir", default="")
    args = parser.parse_args()

    config = resolve_config(target_root=Path(args.target), target_repo=args.target_repo)
    report_allowed_root = Path(os.environ.get("GITHUB_WORKSPACE", "") or Path.cwd()).resolve()
    report_output_dir = args.report_output_dir or config.run_report_output_dir
    result = run_tool_loop(
        config=config,
        source_root=Path(args.source),
        target_root=Path(args.target),
        environ=dict(os.environ),
        report_output_dir=report_output_dir,
        report_allowed_root=report_allowed_root,
        run_metadata={"target_repo": args.target_repo, "mode": "tool_loop"},
    )
    write_status(args.status_output, result)
    write_json(args.operation_log_output, result.operation_log)
    write_json(args.summary_output, result.as_dict())
    if result.repair_report and write_github_step_summary(result.repair_report, env=dict(os.environ)):
        safe_log("runtime report appended to GitHub step summary")
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False, sort_keys=True))

    if result.status == "low-impact":
        raise RuntimeError(result.final_summary)

    if result.status == "max-iterations" and (
        config.execution_mode != STAGED_TRANSLATION_MODE or config.strict_mode
    ):
        raise RuntimeError(result.final_summary)
    if result.status == "max-iterations":
        print("WARNING: staged_translation reached max_iterations; continuing with partial progress.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
