from __future__ import annotations

import dataclasses
import datetime
import json
import os
from pathlib import Path
from typing import Any

from deepseek_agent import DeepSeekClient, TOOL_DEFINITIONS, initial_messages
from file_tools import WRITE_TOOLS, FileToolSandbox, ToolError
from forgis_config import ResolvedConfig
from source_inventory import (
    SourceUnit,
    bundled_units_for_folder,
    collect_source_inventory,
    folder_direct_units,
    safe_source_report_name,
)
from tool_loop import (
    ClientFactory,
    ToolLoopResult,
    assistant_tool_call_message,
    changed_paths_from_operations,
    extract_final_summary,
    format_tool_result,
    log_tool_loop_finished,
    message_from_response,
    parse_tool_arguments,
    safe_log,
    sanitize_log_path,
    tool_call_log_details,
)


PHASE_OVERVIEW = "overview"
PHASE_PER_FILE = "per_file"
PHASE_STABILIZATION = "stabilization"

MICRO_FEED = "feed"
MICRO_WRITE = "write"
MICRO_COMPARE = "readonly_compare"
MICRO_REVISE = "revise"
MICRO_FOLDER_REVIEW = "folder_batch_review"
MICRO_PHASE_GATE = "phase_gate"


@dataclasses.dataclass
class StagedState:
    phase: str = PHASE_OVERVIEW
    phase_iterations: dict[str, int] = dataclasses.field(
        default_factory=lambda: {
            PHASE_OVERVIEW: 0,
            PHASE_PER_FILE: 0,
            PHASE_STABILIZATION: 0,
        }
    )
    current_unit_index: int = 0
    current_micro_index: int = 0
    processed_units: set[str] = dataclasses.field(default_factory=set)
    reviewed_folders: set[str] = dataclasses.field(default_factory=set)
    pending_folder_review: str | None = None
    started_folder_reviews: set[str] = dataclasses.field(default_factory=set)


def staged_virtual_path(config: ResolvedConfig, relative_to_subdir: str) -> str:
    return f"target_subdir/{relative_to_subdir.strip('/')}"


def staged_target_path(target_root: Path, config: ResolvedConfig, relative_to_subdir: str) -> Path:
    return target_root / config.target_subdir / relative_to_subdir


def progress_artifact_paths(config: ResolvedConfig) -> dict[str, str]:
    files = config.staged_translation.progress_files
    return {
        "plan": files.plan,
        "source_target_map": files.source_target_map,
        "progress": files.progress,
        "compare_report_dir": files.compare_report_dir,
    }


def required_overview_artifacts_exist(target_root: Path, config: ResolvedConfig) -> bool:
    files = config.staged_translation.progress_files
    required = [files.plan, files.source_target_map, files.progress]
    return all(staged_target_path(target_root, config, relative).is_file() for relative in required)


def micro_phase_sequence(config: ResolvedConfig) -> list[str]:
    micro = config.staged_translation.per_file_micro_phases
    if not micro.enabled:
        return [MICRO_WRITE]
    sequence: list[str] = []
    if micro.require_feed:
        sequence.append(MICRO_FEED)
    if micro.require_write:
        sequence.append(MICRO_WRITE)
    if micro.require_compare_report:
        sequence.append(MICRO_COMPARE)
    if micro.require_revision:
        sequence.append(MICRO_REVISE)
    return sequence or [MICRO_WRITE]


def phase_min_iterations(config: ResolvedConfig, phase: str) -> int:
    staged = config.staged_translation
    if phase == PHASE_OVERVIEW:
        return staged.overview.min_iterations
    if phase == PHASE_PER_FILE:
        return staged.per_file.min_iterations
    return staged.stabilization.min_iterations


def phase_max_iterations(config: ResolvedConfig, phase: str) -> int:
    staged = config.staged_translation
    if phase == PHASE_OVERVIEW:
        return staged.overview.max_iterations
    if phase == PHASE_PER_FILE:
        return staged.per_file.max_iterations
    return staged.stabilization.max_iterations


def current_unit(state: StagedState, units: list[SourceUnit]) -> SourceUnit | None:
    if state.phase != PHASE_PER_FILE or state.pending_folder_review is not None:
        return None
    if state.current_unit_index >= len(units):
        return None
    return units[state.current_unit_index]


def current_micro_phase(state: StagedState, units: list[SourceUnit], config: ResolvedConfig) -> str:
    if state.phase == PHASE_OVERVIEW:
        return "overview"
    if state.phase == PHASE_STABILIZATION:
        return "stabilization"
    if state.pending_folder_review is not None:
        return MICRO_FOLDER_REVIEW
    if state.current_unit_index >= len(units):
        return MICRO_PHASE_GATE
    sequence = micro_phase_sequence(config)
    return sequence[min(state.current_micro_index, len(sequence) - 1)]


def normalize_target_subdir_write_path(path: Any, config: ResolvedConfig) -> str | None:
    text = str(path if path is not None else "").strip().replace("\\", "/").strip("/")
    if not text:
        return None
    prefix = "target_subdir/"
    if text == "target_subdir":
        return ""
    if text.startswith(prefix):
        return text[len(prefix) :]
    target_prefix = f"target/{config.target_subdir}/"
    if text == f"target/{config.target_subdir}":
        return ""
    if text.startswith(target_prefix):
        return text[len(target_prefix) :]
    direct_prefix = f"{config.target_subdir}/"
    if text == config.target_subdir:
        return ""
    if text.startswith(direct_prefix):
        return text[len(direct_prefix) :]
    return None


def is_progress_artifact_write(relative: str | None, config: ResolvedConfig) -> bool:
    if relative is None:
        return False
    files = config.staged_translation.progress_files
    report_dir = files.compare_report_dir.rstrip("/")
    return relative in {
        files.plan,
        files.source_target_map,
        files.progress,
        report_dir,
    } or relative.startswith(report_dir + "/")


def write_allowed_in_current_step(
    *,
    name: str,
    arguments: dict[str, Any],
    state: StagedState,
    units: list[SourceUnit],
    config: ResolvedConfig,
) -> tuple[bool, str | None]:
    if name not in WRITE_TOOLS:
        return True, None

    relative = normalize_target_subdir_write_path(arguments.get("path"), config)
    micro = current_micro_phase(state, units, config)

    if state.phase == PHASE_OVERVIEW:
        if is_progress_artifact_write(relative, config):
            return True, None
        return False, "Overview phase may only write staged progress artifacts."

    if state.phase == PHASE_PER_FILE and micro in {MICRO_FEED, MICRO_COMPARE, MICRO_PHASE_GATE}:
        if is_progress_artifact_write(relative, config):
            return True, None
        return False, f"{micro} may only write staged progress or compare-report artifacts."

    return True, None


def compare_report_virtual_path(config: ResolvedConfig, source_path: str) -> str:
    files = config.staged_translation.progress_files
    return staged_virtual_path(
        config,
        f"{files.compare_report_dir.rstrip('/')}/{safe_source_report_name(source_path)}",
    )


def source_unit_label(unit: SourceUnit | None) -> str:
    return f"source/{unit.path}" if unit else "[none]"


def folder_label(folder: str) -> str:
    return "source" if not folder else f"source/{folder}"


def control_message(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    target_root: Path,
    global_iteration: int,
) -> str:
    artifacts = progress_artifact_paths(config)
    micro = current_micro_phase(state, units, config)
    unit = current_unit(state, units)
    phase_iteration = state.phase_iterations[state.phase] + 1
    lines = [
        "[forgis staged control]",
        f"execution_mode: {config.execution_mode}",
        f"global_iteration: {global_iteration}/{config.max_iterations}",
        f"phase: {state.phase}",
        f"phase_iteration: {phase_iteration}/{phase_max_iterations(config, state.phase)}",
        f"phase_min_iterations: {phase_min_iterations(config, state.phase)}",
        f"min_total_iterations: {config.staged_translation.min_total_iterations}",
        f"current_source_unit: {source_unit_label(unit)}",
        f"current_micro_phase: {micro}",
        "",
        "Progress artifacts must stay under target_subdir:",
        f"- plan: {staged_virtual_path(config, artifacts['plan'])}",
        f"- source_target_map: {staged_virtual_path(config, artifacts['source_target_map'])}",
        f"- progress: {staged_virtual_path(config, artifacts['progress'])}",
        f"- compare_report_dir: {staged_virtual_path(config, artifacts['compare_report_dir'])}",
    ]

    if state.phase == PHASE_OVERVIEW:
        lines.extend(
            [
                "",
                "Overview phase requirements:",
                "- Read the task file, source tree, and target_subdir tree.",
                "- Identify source units, target structure, processing order, risks, and scope.",
                "- Write or update the plan, source-target map, and progress files.",
                "- Do not rewrite target implementation files in this phase.",
                "- Do not return final_summary until Forgis moves to stabilization.",
            ]
        )
    elif state.phase == PHASE_PER_FILE and micro == MICRO_FOLDER_REVIEW and state.pending_folder_review is not None:
        folder = state.pending_folder_review
        included, omitted = bundled_units_for_folder(
            units,
            folder,
            max_bundle_chars=config.staged_translation.folder_batch_review.max_bundle_chars,
        )
        lines.extend(
            [
                "",
                "Folder batch review requirements:",
                f"- folder: {folder_label(folder)}",
                f"- max_bundle_chars: {config.staged_translation.folder_batch_review.max_bundle_chars}",
                "- Review the folder as one semantic unit after its direct files were processed.",
                "- Read included source files and related target files; paginate when needed.",
                "- Check cross-file state, type, navigation, component, and dependency consistency.",
                "- Make only small alignment fixes and update progress/source-target map.",
                "- If any files are omitted by the character cap, state exactly which files were checked.",
                "included_source_files:",
                *[f"- source/{unit.path} ({unit.size_chars} chars)" for unit in included],
                "omitted_due_to_max_bundle_chars:",
                *[f"- source/{unit.path} ({unit.size_chars} chars)" for unit in omitted],
            ]
        )
    elif state.phase == PHASE_PER_FILE and unit is not None:
        report_path = compare_report_virtual_path(config, unit.path)
        lines.extend(
            [
                "",
                "Per-file staged translation requirements:",
                f"- Focus on exactly this source unit: source/{unit.path}",
                "- Do not jump to another source unit.",
                f"- Compare report path for this unit: {report_path}",
            ]
        )
        if micro == MICRO_FEED:
            lines.extend(
                [
                    "- Micro-phase feed: read this source unit and related target files.",
                    "- Understand responsibility, coverage, missing target support, and local translation intent.",
                    "- Do not write target implementation code in this micro-phase.",
                ]
            )
        elif micro == MICRO_WRITE:
            lines.extend(
                [
                    "- Micro-phase write/translate: translate or semantically rebuild this unit into target implementation.",
                    "- Merge with existing target structure; do not mechanically line-translate.",
                    "- Do not rewrite unrelated files and do not move to another source unit.",
                ]
            )
        elif micro == MICRO_COMPARE:
            lines.extend(
                [
                    "- Micro-phase readonly compare: read the source unit and generated target files.",
                    "- Compare responsibility, semantics, state, UI/interaction intent, and gaps.",
                    "- Write only the compare report/progress artifacts; do not change target implementation code.",
                ]
            )
        elif micro == MICRO_REVISE:
            lines.extend(
                [
                    "- Micro-phase revise: make one small correction pass based on the compare report.",
                    "- Only fix this source unit's related target issues.",
                    "- Update progress with one of translated, partially_translated, missing target support, deferred, or needs_review.",
                ]
            )
    else:
        lines.extend(
            [
                "",
                "Stabilization requirements:",
                "- Perform small build-oriented consistency checks and fixes.",
                "- Review build configuration, resources, namespace/package references, imports, UI APIs, navigation, state, and models.",
                "- Run configured validation_commands only if the workflow provides them; otherwise do static review only.",
                "- Update progress with final notes and next recommended run.",
                "- Return final_summary only when Forgis requirements are satisfied.",
            ]
        )

    if not required_overview_artifacts_exist(target_root, config):
        lines.append("overview_artifacts_status: missing_or_incomplete")
    else:
        lines.append("overview_artifacts_status: present")
    return "\n".join(lines)


def log_staged_iteration(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    global_iteration: int,
) -> None:
    micro = current_micro_phase(state, units, config)
    unit = current_unit(state, units)
    safe_log(
        "staged progress: "
        f"phase={state.phase} "
        f"phase_iteration={state.phase_iterations[state.phase] + 1}/"
        f"{phase_max_iterations(config, state.phase)} "
        f"global_iteration={global_iteration}/{config.max_iterations} "
        f"current_source_unit={source_unit_label(unit)} "
        f"current_micro_phase={micro}"
    )


def maybe_log_folder_review_start(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
) -> None:
    if state.phase != PHASE_PER_FILE or state.pending_folder_review is None:
        return
    folder = state.pending_folder_review
    if folder in state.started_folder_reviews:
        return
    included, omitted = bundled_units_for_folder(
        units,
        folder,
        max_bundle_chars=config.staged_translation.folder_batch_review.max_bundle_chars,
    )
    state.started_folder_reviews.add(folder)
    safe_log(
        "folder batch review start: "
        f"folder={folder_label(folder)} "
        f"included_files={len(included)} "
        f"omitted_files={len(omitted)} "
        f"max_bundle_chars={config.staged_translation.folder_batch_review.max_bundle_chars}"
    )


def overview_ready(target_root: Path, config: ResolvedConfig, state: StagedState) -> bool:
    return (
        state.phase_iterations[PHASE_OVERVIEW] >= config.staged_translation.overview.min_iterations
        and required_overview_artifacts_exist(target_root, config)
    )


def per_file_ready(config: ResolvedConfig, state: StagedState, units: list[SourceUnit]) -> bool:
    return (
        state.current_unit_index >= len(units)
        and state.pending_folder_review is None
        and state.phase_iterations[PHASE_PER_FILE] >= config.staged_translation.per_file.min_iterations
    )


def final_summary_acceptable(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    target_root: Path,
    global_iteration: int,
) -> tuple[bool, str]:
    if global_iteration < config.staged_translation.min_total_iterations:
        return False, "min_total_iterations not met"
    if state.phase != PHASE_STABILIZATION:
        return False, f"current phase is {state.phase}"
    if state.phase_iterations[PHASE_STABILIZATION] < config.staged_translation.stabilization.min_iterations:
        return False, "stabilization min_iterations not met"
    if not required_overview_artifacts_exist(target_root, config):
        return False, "required progress artifacts are missing or incomplete"
    if not per_file_ready(config, state, units):
        return False, "per-file source units or folder reviews are incomplete"
    return True, "requirements satisfied"


def advance_after_productive_iteration(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
) -> None:
    if state.phase != PHASE_PER_FILE:
        return

    if state.pending_folder_review is not None:
        folder = state.pending_folder_review
        state.reviewed_folders.add(folder)
        state.pending_folder_review = None
        safe_log(f"folder batch review end: folder={folder_label(folder)}")
        return

    if state.current_unit_index >= len(units):
        return

    sequence = micro_phase_sequence(config)
    state.current_micro_index += 1
    if state.current_micro_index < len(sequence):
        return

    completed = units[state.current_unit_index]
    state.processed_units.add(completed.path)
    state.current_unit_index += 1
    state.current_micro_index = 0

    direct_units = folder_direct_units(units, completed.folder)
    folder_done = all(unit.path in state.processed_units for unit in direct_units)
    if (
        config.staged_translation.folder_batch_review.enabled
        and folder_done
        and completed.folder not in state.reviewed_folders
    ):
        state.pending_folder_review = completed.folder


def maybe_advance_phase(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    target_root: Path,
) -> None:
    if state.phase == PHASE_OVERVIEW and overview_ready(target_root, config, state):
        state.phase = PHASE_PER_FILE
        state.current_unit_index = 0
        state.current_micro_index = 0
        safe_log("staged phase transition: overview -> per_file")
        return

    if state.phase == PHASE_PER_FILE and per_file_ready(config, state, units):
        state.phase = PHASE_STABILIZATION
        safe_log("staged phase transition: per_file -> stabilization")


def log_progress_artifact_update(
    *,
    name: str,
    result: dict[str, Any],
    config: ResolvedConfig,
) -> None:
    if name not in WRITE_TOOLS or not result.get("ok"):
        return
    relative = normalize_target_subdir_write_path(result.get("path"), config)
    if is_progress_artifact_write(relative, config):
        safe_log(f"progress file update: path={sanitize_log_path(result.get('path'))}")


def partial_progress_text(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    iteration: int,
) -> str:
    remaining = max(0, len(units) - state.current_unit_index)
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    next_unit = units[state.current_unit_index].path if state.current_unit_index < len(units) else "[none]"
    return "\n".join(
        [
            "",
            f"## Partial progress saved at {now}",
            "",
            f"- max_iterations reached: {config.max_iterations}",
            f"- stopped at global iteration: {iteration}",
            f"- current phase: {state.phase}",
            f"- current micro-phase: {current_micro_phase(state, units, config)}",
            f"- processed source units: {len(state.processed_units)}",
            f"- remaining source units: {remaining}",
            f"- next source unit: {next_unit}",
            "- status: partial; do not treat this run as complete",
            "",
        ]
    )


def append_partial_progress(
    *,
    sandbox: FileToolSandbox,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    iteration: int,
) -> None:
    path = staged_virtual_path(config, config.staged_translation.progress_files.progress)
    try:
        result = sandbox.invoke(
            "append_file",
            {
                "path": path,
                "content": partial_progress_text(
                    config=config,
                    state=state,
                    units=units,
                    iteration=iteration,
                ),
            },
        )
    except Exception as exc:
        safe_log(f"partial progress save failed: {exc}")
        return
    if result.get("ok"):
        safe_log(f"partial progress saved: path={sanitize_log_path(result.get('path'))}")


def run_staged_translation_loop(
    *,
    config: ResolvedConfig,
    source_root: Path,
    target_root: Path,
    environ: dict[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> ToolLoopResult:
    env = dict(os.environ if environ is None else environ)
    sandbox = FileToolSandbox(
        source_root=source_root,
        target_root=target_root,
        target_subdir=config.target_subdir,
        config_path=config.config_path,
        task_path=config.task_prompt_path,
        max_result_chars=config.max_tool_result_chars,
    )
    factory = client_factory or (lambda cfg, local_env: DeepSeekClient.from_config(cfg, local_env))
    client = factory(config, env)
    messages: list[dict[str, Any]] = initial_messages(config)
    units = collect_source_inventory(source_root, config.staged_translation.source_inventory)
    state = StagedState()
    tool_call_count = 0

    safe_log(
        "staged mode enabled: "
        f"max_iterations={config.max_iterations} "
        f"min_total_iterations={config.staged_translation.min_total_iterations} "
        f"source_units={len(units)}"
    )

    for iteration in range(1, config.max_iterations + 1):
        log_staged_iteration(config=config, state=state, units=units, global_iteration=iteration)
        maybe_log_folder_review_start(config=config, state=state, units=units)
        messages.append(
            {
                "role": "user",
                "content": control_message(
                    config=config,
                    state=state,
                    units=units,
                    target_root=target_root,
                    global_iteration=iteration,
                ),
            }
        )
        state.phase_iterations[state.phase] += 1

        response = client.chat(messages, TOOL_DEFINITIONS)
        message = message_from_response(response)
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""
        has_assistant_message = "yes" if message else "no"

        if not tool_calls:
            summary = extract_final_summary(str(content))
            safe_log(
                f"staged iteration {iteration}/{config.max_iterations}: "
                f"assistant_message={has_assistant_message} tool_calls=0 "
                f"final_summary={'yes' if summary else 'no'}"
            )
            if summary:
                acceptable, reason = final_summary_acceptable(
                    config=config,
                    state=state,
                    units=units,
                    target_root=target_root,
                    global_iteration=iteration,
                )
                if acceptable:
                    safe_log("final_summary accepted")
                    log_tool_loop_finished(
                        iterations=iteration,
                        tool_call_count=tool_call_count,
                        sandbox=sandbox,
                    )
                    return ToolLoopResult(
                        executed=True,
                        status="completed",
                        final_summary=summary,
                        iterations=iteration,
                        tool_call_count=tool_call_count,
                        read_tool_count=sandbox.read_count,
                        write_tool_count=sandbox.write_count,
                        operation_log=sandbox.operation_log(),
                    )

                phase_min = phase_min_iterations(config, state.phase)
                safe_log(
                    "early final_summary rejected because min phase iterations not met or gates incomplete: "
                    f"phase={state.phase} "
                    f"phase_iterations={state.phase_iterations[state.phase]} "
                    f"minimum_required={phase_min} "
                    f"reason={reason}"
                )
                messages.append({"role": "assistant", "content": str(content)})
                messages.append(
                    {
                        "role": "user",
                        "content": "\n".join(
                            [
                                "[forgis] You returned final_summary before the staged translation requirements were satisfied.",
                                f"Current phase: {state.phase}",
                                f"Current phase iterations: {state.phase_iterations[state.phase]}",
                                f"Minimum required: {phase_min}",
                                f"Reason: {reason}",
                                "Continue the staged workflow. Do not return final_summary yet.",
                            ]
                        ),
                    }
                )
                maybe_advance_phase(config=config, state=state, units=units, target_root=target_root)
                continue

            messages.append({"role": "assistant", "content": str(content)})
            maybe_advance_phase(config=config, state=state, units=units, target_root=target_root)
            continue

        messages.append(assistant_tool_call_message(message, tool_calls))
        safe_log(
            f"staged iteration {iteration}/{config.max_iterations}: "
            f"assistant_message={has_assistant_message} "
            f"model returned {len(tool_calls)} tool calls final_summary=no"
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
                allowed, reason = write_allowed_in_current_step(
                    name=name,
                    arguments=arguments,
                    state=state,
                    units=units,
                    config=config,
                )
                if not allowed:
                    raise ToolError(reason or "Write is not allowed in the current staged step.")
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
            log_progress_artifact_update(name=name, result=result, config=config)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", f"tool-{tool_call_count}"),
                    "name": name,
                    "content": formatted_result,
                }
            )

        advance_after_productive_iteration(config=config, state=state, units=units)
        maybe_advance_phase(config=config, state=state, units=units, target_root=target_root)

    safe_log(
        "max_iterations reached: "
        f"{config.max_iterations} "
        f"current_phase={state.phase} "
        f"processed_files={len(state.processed_units)} "
        f"remaining_files={max(0, len(units) - state.current_unit_index)}"
    )
    append_partial_progress(
        sandbox=sandbox,
        config=config,
        state=state,
        units=units,
        iteration=config.max_iterations,
    )
    log_tool_loop_finished(
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        sandbox=sandbox,
    )
    return ToolLoopResult(
        executed=True,
        status="max-iterations",
        final_summary=(
            f"Staged translation stopped after max_iterations={config.max_iterations}; "
            f"current_phase={state.phase}; processed_files={len(state.processed_units)}; "
            f"remaining_files={max(0, len(units) - state.current_unit_index)}. Partial progress was saved."
        ),
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        read_tool_count=sandbox.read_count,
        write_tool_count=sandbox.write_count,
        operation_log=sandbox.operation_log(),
    )
