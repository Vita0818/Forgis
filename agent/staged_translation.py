from __future__ import annotations

import dataclasses
import datetime
import json
import os
from pathlib import Path
from typing import Any

from deepseek_agent import DeepSeekClient, TOOL_DEFINITIONS, build_skill_selection, initial_messages
from file_tools import WRITE_TOOLS, FileToolSandbox, ToolError
from forgis_config import ResolvedConfig
from runtime_controller import RuntimeController
from skill_loader import SkillSelection, render_selected_skills
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
    read_task_text_for_migration_scheduler,
    safe_log,
    sanitize_log_path,
    tool_call_log_details,
    visual_provider_env,
    visual_run_id,
    visual_runtime_root,
)


PHASE_OVERVIEW = "overview"
PHASE_PER_FILE = "per_file"
PHASE_STABILIZATION = "stabilization"

MICRO_FEED = "feed"
MICRO_WRITE = "write"
MICRO_COMPARE = "readonly_compare"
MICRO_REVISE = "revise"
MICRO_FOLDER_REVIEW = "folder_review"
MICRO_PHASE_GATE = "phase_gate"

DEFERRED_MARKERS = ("deferred", "missing target support", "missing_target_support")
ALREADY_COVERED_MARKERS = ("already_covered", "already covered")
NO_REVISION_MARKERS = ("no_revision_needed", "no revision needed")
NO_FIX_MARKERS = ("no_fix_needed", "no fix needed")
COMPARE_MARKERS = ("compare", "comparison")

NON_CODE_SUFFIXES = {
    ".adoc",
    ".csv",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".json",
    ".lock",
    ".md",
    ".pdf",
    ".png",
    ".rst",
    ".svg",
    ".txt",
    ".webp",
    ".yaml",
    ".yml",
}


@dataclasses.dataclass
class UnitProgress:
    source_path: str
    source_read: bool = False
    compare_source_read: bool = False
    compare_target_read: bool = False
    target_reads: set[str] = dataclasses.field(default_factory=set)
    changed_paths_before: set[str] = dataclasses.field(default_factory=set)
    implementation_changed_paths: set[str] = dataclasses.field(default_factory=set)
    progress_updated: bool = False
    map_updated: bool = False
    compare_report_written: bool = False
    compare_section_written: bool = False
    deferred_reason: bool = False
    already_covered: bool = False
    no_revision_needed: bool = False
    revise_progress_updated: bool = False
    revise_map_updated: bool = False


@dataclasses.dataclass
class FolderReviewProgress:
    folder: str
    started: bool = False
    progress_updated: bool = False
    map_updated: bool = False
    no_fix_needed: bool = False
    implementation_changed_paths: set[str] = dataclasses.field(default_factory=set)


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
    deferred_units: set[str] = dataclasses.field(default_factory=set)
    reviewed_folders: set[str] = dataclasses.field(default_factory=set)
    pending_folder_review: str | None = None
    started_folder_reviews: set[str] = dataclasses.field(default_factory=set)
    unit_progress: dict[str, UnitProgress] = dataclasses.field(default_factory=dict)
    folder_progress: dict[str, FolderReviewProgress] = dataclasses.field(default_factory=dict)
    progress_updated: bool = False
    source_target_map_updated: bool = False
    compare_reports: set[str] = dataclasses.field(default_factory=set)
    compare_sections: set[str] = dataclasses.field(default_factory=set)
    implementation_changed_paths: set[str] = dataclasses.field(default_factory=set)
    last_gate_blockers: list[str] = dataclasses.field(default_factory=list)
    per_file_started: bool = False


def staged_virtual_path(_config: ResolvedConfig, relative_to_subdir: str) -> str:
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
    if not config.staged_translation.enforce_micro_phases:
        return [MICRO_WRITE]
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


def active_units_for_run(units: list[SourceUnit], config: ResolvedConfig) -> list[SourceUnit]:
    return units[: config.staged_translation.max_units_per_run]


def effective_min_processed_units(config: ResolvedConfig, active_units: list[SourceUnit]) -> int:
    return min(config.staged_translation.min_processed_units, len(active_units))


def completed_unit_count(state: StagedState) -> int:
    return len(state.processed_units | state.deferred_units)


def current_unit(state: StagedState, units: list[SourceUnit]) -> SourceUnit | None:
    if state.phase != PHASE_PER_FILE or state.pending_folder_review is not None:
        return None
    if state.current_unit_index >= len(units):
        return None
    return units[state.current_unit_index]


def current_unit_progress(state: StagedState, unit: SourceUnit) -> UnitProgress:
    if unit.path not in state.unit_progress:
        state.unit_progress[unit.path] = UnitProgress(source_path=unit.path)
    return state.unit_progress[unit.path]


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


def normalize_virtual_path(path: Any) -> str:
    return str(path if path is not None else "").strip().replace("\\", "/").strip("/")


def normalize_target_subdir_write_path(path: Any, config: ResolvedConfig) -> str | None:
    text = normalize_virtual_path(path)
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


def is_progress_path(relative: str | None, config: ResolvedConfig) -> bool:
    return relative == config.staged_translation.progress_files.progress


def is_map_path(relative: str | None, config: ResolvedConfig) -> bool:
    return relative == config.staged_translation.progress_files.source_target_map


def is_compare_report_path(relative: str | None, config: ResolvedConfig) -> bool:
    if relative is None:
        return False
    report_dir = config.staged_translation.progress_files.compare_report_dir.rstrip("/")
    return relative.startswith(report_dir + "/") and relative.endswith(".md")


def compare_report_virtual_path(config: ResolvedConfig, source_path: str) -> str:
    files = config.staged_translation.progress_files
    return staged_virtual_path(
        config,
        f"{files.compare_report_dir.rstrip('/')}/{safe_source_report_name(source_path)}",
    )


def compare_report_relative_path(config: ResolvedConfig, source_path: str) -> str:
    files = config.staged_translation.progress_files
    return f"{files.compare_report_dir.rstrip('/')}/{safe_source_report_name(source_path)}"


def source_unit_label(unit: SourceUnit | None) -> str:
    return f"source/{unit.path}" if unit else "[none]"


def folder_label(folder: str) -> str:
    return "source" if not folder else f"source/{folder}"


def content_mentions_unit(content: Any, unit: SourceUnit | None) -> bool:
    if unit is None:
        return False
    lowered = str(content if content is not None else "").casefold()
    source_path = unit.path.casefold()
    return source_path in lowered or f"source/{source_path}" in lowered


def content_has_any(content: Any, markers: tuple[str, ...]) -> bool:
    lowered = str(content if content is not None else "").casefold()
    return any(marker in lowered for marker in markers)


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
        return False, "overview may only write staged progress artifacts."

    if state.phase == PHASE_PER_FILE and micro in {MICRO_FEED, MICRO_COMPARE, MICRO_PHASE_GATE}:
        if is_progress_artifact_write(relative, config):
            return True, None
        return False, f"{micro} may only write staged progress or compare-report artifacts."

    return True, None


def implementation_path_from_result(result: dict[str, Any], config: ResolvedConfig) -> str | None:
    relative = normalize_target_subdir_write_path(result.get("path"), config)
    if relative is None or is_progress_artifact_write(relative, config):
        return None
    return relative


def is_code_like_changed_path(path: str) -> bool:
    clean = path.replace("\\", "/").casefold()
    name = Path(clean).name
    suffix = Path(clean).suffix
    if name.startswith("readme") or "report" in clean or "log" in clean:
        return False
    return suffix not in NON_CODE_SUFFIXES


def update_state_from_tool_result(
    *,
    name: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    state: StagedState,
    units: list[SourceUnit],
    config: ResolvedConfig,
    micro: str,
) -> None:
    if not result.get("ok"):
        return

    unit = current_unit(state, units)
    unit_progress = current_unit_progress(state, unit) if unit is not None else None

    if name == "read_file":
        path = normalize_virtual_path(arguments.get("path"))
        if unit is not None and path == f"source/{unit.path}":
            if micro == MICRO_COMPARE:
                unit_progress.compare_source_read = True
            else:
                unit_progress.source_read = True
        if path.startswith("target/") or path.startswith("target_subdir"):
            if unit_progress is not None:
                unit_progress.target_reads.add(path)
                if micro == MICRO_COMPARE:
                    unit_progress.compare_target_read = True
        return

    if name not in WRITE_TOOLS:
        return

    relative = normalize_target_subdir_write_path(result.get("path") or arguments.get("path"), config)
    content = arguments.get("content", "")

    if is_progress_path(relative, config):
        state.progress_updated = True
        if unit_progress is not None:
            unit_progress.progress_updated = True
            if micro == MICRO_REVISE:
                unit_progress.revise_progress_updated = True
            if content_mentions_unit(content, unit) and content_has_any(content, COMPARE_MARKERS):
                unit_progress.compare_section_written = True
                state.compare_sections.add(unit.path)
        if state.pending_folder_review is not None:
            folder = state.pending_folder_review
            review = state.folder_progress.setdefault(folder, FolderReviewProgress(folder=folder))
            review.progress_updated = True
            if content_has_any(content, NO_FIX_MARKERS):
                review.no_fix_needed = True

    if is_map_path(relative, config):
        state.source_target_map_updated = True
        if unit_progress is not None:
            unit_progress.map_updated = True
            if micro == MICRO_REVISE:
                unit_progress.revise_map_updated = True
        if state.pending_folder_review is not None:
            folder = state.pending_folder_review
            review = state.folder_progress.setdefault(folder, FolderReviewProgress(folder=folder))
            review.map_updated = True

    if is_compare_report_path(relative, config) and unit_progress is not None:
        unit_progress.compare_report_written = True
        state.compare_reports.add(unit_progress.source_path)

    if unit_progress is not None and content_mentions_unit(content, unit):
        if content_has_any(content, DEFERRED_MARKERS):
            unit_progress.deferred_reason = True
        if content_has_any(content, ALREADY_COVERED_MARKERS):
            unit_progress.already_covered = True
        if content_has_any(content, NO_REVISION_MARKERS):
            unit_progress.no_revision_needed = True

    implementation_path = implementation_path_from_result(result, config)
    if implementation_path is not None:
        state.implementation_changed_paths.add(implementation_path)
        if unit_progress is not None:
            unit_progress.implementation_changed_paths.add(implementation_path)
        if state.pending_folder_review is not None:
            folder = state.pending_folder_review
            review = state.folder_progress.setdefault(folder, FolderReviewProgress(folder=folder))
            review.implementation_changed_paths.add(implementation_path)


def unit_gate_blockers(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
) -> list[str]:
    unit = current_unit(state, units)
    if unit is None:
        return []
    progress = current_unit_progress(state, unit)
    micro = current_micro_phase(state, units, config)

    if micro == MICRO_FEED:
        if config.staged_translation.require_source_read and not progress.source_read:
            return [f"feed has not read source/{unit.path} with read_file"]
        return []

    if micro == MICRO_WRITE:
        if not config.staged_translation.require_target_effect_or_deferred_reason:
            return []
        if progress.implementation_changed_paths or progress.already_covered:
            return []
        if progress.deferred_reason:
            return []
        return ["write produced no target implementation effect and no deferred/already_covered reason"]

    if micro == MICRO_COMPARE:
        blockers: list[str] = []
        if config.staged_translation.require_source_read and not progress.compare_source_read:
            blockers.append(f"readonly_compare has not re-read source/{unit.path}")
        if progress.implementation_changed_paths and not progress.compare_target_read:
            blockers.append("readonly_compare has not read the generated target file")
        if config.staged_translation.require_compare_report and not (
            progress.compare_report_written or progress.compare_section_written
        ):
            blockers.append("compare report or explicit progress compare section is missing")
        return blockers

    if micro == MICRO_REVISE:
        if not config.staged_translation.require_progress_update:
            return []
        if progress.no_revision_needed or progress.revise_progress_updated or progress.revise_map_updated:
            return []
        return ["revise has not updated progress/source-target map or recorded no_revision_needed"]

    return []


def folder_review_blockers(config: ResolvedConfig, state: StagedState) -> list[str]:
    if state.pending_folder_review is None:
        return []
    review = state.folder_progress.setdefault(
        state.pending_folder_review,
        FolderReviewProgress(folder=state.pending_folder_review),
    )
    if review.progress_updated or review.map_updated:
        return []
    return ["folder_review has not updated progress or source-target map"]


def control_message(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    all_units: list[SourceUnit],
    target_root: Path,
    global_iteration: int,
) -> str:
    artifacts = progress_artifact_paths(config)
    micro = current_micro_phase(state, units, config)
    unit = current_unit(state, units)
    phase_iteration = state.phase_iterations[state.phase] + 1
    current_index = state.current_unit_index + 1 if unit is not None else 0
    report_path = compare_report_virtual_path(config, unit.path) if unit is not None else "[none]"
    unit_progress = current_unit_progress(state, unit) if unit is not None else None
    lines = [
        "[forgis staged control]",
        "This is controller-enforced. Forgis will not advance until the current gate is satisfied.",
        f"execution_mode: {config.execution_mode}",
        f"global_iteration: {global_iteration}/{config.max_iterations}",
        f"phase: {state.phase}",
        f"phase_iteration: {phase_iteration}/{phase_max_iterations(config, state.phase)}",
        f"phase_min_iterations: {phase_min_iterations(config, state.phase)}",
        f"min_total_iterations: {config.staged_translation.min_total_iterations}",
        f"source_unit_queue_length: {len(all_units)}",
        f"active_source_units_this_run: {len(units)}",
        f"current_source_unit_index: {current_index}/{len(units)}",
        f"current_source_unit: {source_unit_label(unit)}",
        f"current_micro_phase: {micro}",
        f"current_source_unit_was_read: {str(bool(unit_progress and unit_progress.source_read)).lower()}",
        f"processed_units: {len(state.processed_units)}",
        f"deferred_units: {len(state.deferred_units)}",
        f"compare_report_path: {report_path}",
        "",
        "Progress artifacts must stay under target_subdir:",
        f"- plan: {staged_virtual_path(config, artifacts['plan'])}",
        f"- source_target_map: {staged_virtual_path(config, artifacts['source_target_map'])}",
        f"- progress: {staged_virtual_path(config, artifacts['progress'])}",
        f"- compare_report_dir: {staged_virtual_path(config, artifacts['compare_report_dir'])}",
    ]
    if state.last_gate_blockers:
        lines.extend(["", "Previous controller gate blockers:", *[f"- {item}" for item in state.last_gate_blockers]])

    if state.phase == PHASE_OVERVIEW:
        lines.extend(
            [
                "",
                "Overview phase requirements:",
                "- Read the task file, source tree, and target_subdir tree.",
                "- Write or update the plan, source-target map, and progress files.",
                "- Do not rewrite target implementation files in this phase.",
                "- Forgis already generated a stable source unit queue from source_inventory.",
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
                "Folder review requirements:",
                f"- folder: {folder_label(folder)}",
                f"- max_bundle_chars: {config.staged_translation.folder_batch_review.max_bundle_chars}",
                "- This folder review is mandatory after direct files in this run were processed/deferred.",
                "- Read included source files and related target files; paginate when needed.",
                "- Record folder path, included files, omitted files, related target files, issues, fixes or no_fix_needed.",
                "- Update progress and/or source-target map before Forgis will advance.",
                "included_source_files:",
                *[f"- source/{item.path} ({item.size_chars} chars)" for item in included],
                "omitted_due_to_max_bundle_chars:",
                *[f"- source/{item.path} ({item.size_chars} chars)" for item in omitted],
            ]
        )
    elif state.phase == PHASE_PER_FILE and unit is not None:
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
                    "- Micro-phase feed: read this source unit with read_file.",
                    "- Read related target files when present.",
                    "- Explain the source responsibility and current target coverage.",
                    "- Do not write target implementation code in feed.",
                ]
            )
        elif micro == MICRO_WRITE:
            lines.extend(
                [
                    "- Micro-phase write: create or modify target implementation for this source unit.",
                    "- If no target change is needed, update progress/map with already_covered or deferred and the reason.",
                    "- Forgis will not complete this unit without implementation changes or an explicit deferred/already_covered reason.",
                ]
            )
        elif micro == MICRO_COMPARE:
            lines.extend(
                [
                    "- Micro-phase readonly_compare: re-read this source unit and generated/related target files.",
                    "- Write the compare report under FORGIS_COMPARE_REPORTS or an explicit compare section in progress.",
                    "- Do not modify target implementation files in readonly_compare.",
                ]
            )
        elif micro == MICRO_REVISE:
            lines.extend(
                [
                    "- Micro-phase revise: make one small correction pass based on the compare report.",
                    "- If no code change is needed, record no_revision_needed for this source unit.",
                    "- Update progress and/or source-target map before Forgis marks this unit complete.",
                ]
            )
    else:
        lines.extend(
            [
                "",
                "Stabilization requirements:",
                "- Perform small build-oriented consistency checks and fixes.",
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
    all_units: list[SourceUnit],
    global_iteration: int,
) -> None:
    micro = current_micro_phase(state, units, config)
    unit = current_unit(state, units)
    current_index = state.current_unit_index + 1 if unit is not None else 0
    unit_progress = current_unit_progress(state, unit) if unit is not None else None
    before_count = len(unit_progress.changed_paths_before) if unit_progress is not None else 0
    after_count = len(unit_progress.implementation_changed_paths) if unit_progress is not None else 0
    safe_log(
        "staged progress: "
        f"phase={state.phase} "
        f"phase_iteration={state.phase_iterations[state.phase] + 1}/"
        f"{phase_max_iterations(config, state.phase)} "
        f"global_iteration={global_iteration}/{config.max_iterations} "
        f"queue_length={len(all_units)} "
        f"unit_index={current_index}/{len(units)} "
        f"current_source_unit={source_unit_label(unit)} "
        f"current_micro_phase={micro} "
        f"source_unit_read={str(bool(unit_progress and unit_progress.source_read)).lower()} "
        f"target_changed_paths_before={before_count} "
        f"target_changed_paths_after={after_count} "
        f"compare_report={compare_report_virtual_path(config, unit.path) if unit else '[none]'} "
        f"processed_units={len(state.processed_units)} "
        f"deferred_units={len(state.deferred_units)}"
    )
    if state.phase == PHASE_PER_FILE and unit is not None:
        safe_log(f"staged per_file unit {current_index}/{len(units)}: source/{unit.path}")


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
    review = state.folder_progress.setdefault(folder, FolderReviewProgress(folder=folder))
    review.started = True
    safe_log(
        "folder review start: "
        f"folder={folder_label(folder)} "
        f"included_files={len(included)} "
        f"omitted_files={len(omitted)} "
        f"max_bundle_chars={config.staged_translation.folder_batch_review.max_bundle_chars}"
    )


def overview_ready(target_root: Path, config: ResolvedConfig, state: StagedState) -> bool:
    return (
        state.phase_iterations[PHASE_OVERVIEW] >= config.staged_translation.overview.min_iterations
        and required_overview_artifacts_exist(target_root, config)
        and state.progress_updated
        and state.source_target_map_updated
    )


def per_file_ready(config: ResolvedConfig, state: StagedState, units: list[SourceUnit]) -> bool:
    return (
        completed_unit_count(state) >= len(units)
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
    if current_micro_phase(state, units, config) not in {"stabilization", MICRO_PHASE_GATE}:
        return False, "current micro-phase is mid-unit"
    if len(state.processed_units) < effective_min_processed_units(config, units):
        return False, "min_processed_units not met"
    if not required_overview_artifacts_exist(target_root, config):
        return False, "required progress artifacts are missing or incomplete"
    if config.staged_translation.require_progress_update and not state.progress_updated:
        return False, "progress artifact was not updated"
    if not state.source_target_map_updated:
        return False, "source-target map was not updated"
    if state.per_file_started and not (state.compare_reports or state.compare_sections):
        return False, "no compare report or compare section was written"
    if not per_file_ready(config, state, units):
        return False, "per-file source units or folder reviews are incomplete"
    return True, "requirements satisfied"


def complete_current_unit_if_gate_satisfied(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
) -> None:
    blockers = unit_gate_blockers(config=config, state=state, units=units)
    state.last_gate_blockers = blockers
    if blockers:
        safe_log("staged gate blocked: " + "; ".join(blockers))
        return

    unit = current_unit(state, units)
    if unit is None:
        return
    micro = current_micro_phase(state, units, config)
    sequence = micro_phase_sequence(config)

    state.current_micro_index += 1
    if state.current_micro_index < len(sequence):
        next_micro = sequence[state.current_micro_index]
        if next_micro == MICRO_WRITE:
            current_unit_progress(state, unit).changed_paths_before = set(state.implementation_changed_paths)
        state.last_gate_blockers = []
        return

    progress = current_unit_progress(state, unit)
    if progress.deferred_reason and not progress.implementation_changed_paths and not progress.already_covered:
        state.deferred_units.add(unit.path)
    else:
        state.processed_units.add(unit.path)

    safe_log(
        "staged unit complete: "
        f"source/{unit.path} "
        f"processed_units={len(state.processed_units)} "
        f"deferred_units={len(state.deferred_units)} "
        f"target_changed_paths_after={len(progress.implementation_changed_paths)}"
    )
    state.current_unit_index += 1
    state.current_micro_index = 0
    state.last_gate_blockers = []

    direct_units = folder_direct_units(units, unit.folder)
    direct_paths = {item.path for item in direct_units}
    folder_done = direct_paths.issubset(state.processed_units | state.deferred_units)
    if (
        config.staged_translation.folder_batch_review.enabled
        and config.staged_translation.folder_batch_review.require_after_folder_complete
        and folder_done
        and unit.folder not in state.reviewed_folders
    ):
        state.pending_folder_review = unit.folder


def complete_folder_review_if_gate_satisfied(config: ResolvedConfig, state: StagedState) -> None:
    blockers = folder_review_blockers(config, state)
    state.last_gate_blockers = blockers
    if blockers:
        safe_log("staged gate blocked: " + "; ".join(blockers))
        return
    if state.pending_folder_review is None:
        return
    folder = state.pending_folder_review
    state.reviewed_folders.add(folder)
    state.pending_folder_review = None
    state.last_gate_blockers = []
    safe_log(f"folder review end: folder={folder_label(folder)}")


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
        state.per_file_started = bool(units)
        state.last_gate_blockers = []
        safe_log("staged phase transition: overview -> per_file")
        return

    if state.phase == PHASE_PER_FILE and per_file_ready(config, state, units):
        state.phase = PHASE_STABILIZATION
        state.last_gate_blockers = []
        safe_log("staged phase transition: per_file -> stabilization")


def maybe_advance_staged_controller(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    target_root: Path,
) -> None:
    if state.phase == PHASE_PER_FILE:
        if state.pending_folder_review is not None:
            complete_folder_review_if_gate_satisfied(config, state)
        else:
            complete_current_unit_if_gate_satisfied(config=config, state=state, units=units)
    maybe_advance_phase(config=config, state=state, units=units, target_root=target_root)


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


def controller_append_artifact(
    *,
    sandbox: FileToolSandbox,
    config: ResolvedConfig,
    state: StagedState,
    path: str,
    content: str,
) -> None:
    result = sandbox.invoke("append_file", {"path": staged_virtual_path(config, path), "content": content})
    if result.get("ok"):
        relative = normalize_target_subdir_write_path(result.get("path"), config)
        if is_progress_path(relative, config):
            state.progress_updated = True
        if is_map_path(relative, config):
            state.source_target_map_updated = True
        safe_log(f"progress file update: path={sanitize_log_path(result.get('path'))}")


def initialize_progress_artifacts(
    *,
    sandbox: FileToolSandbox,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    active_units: list[SourceUnit],
) -> None:
    files = config.staged_translation.progress_files
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    queue_lines = [
        "",
        f"## Controller Source Unit Queue ({now})",
        "",
        f"- total source units: {len(units)}",
        f"- max_units_per_run: {config.staged_translation.max_units_per_run}",
        f"- active source units this run: {len(active_units)}",
        "",
        "| Index | Source path/unit | Status | Notes |",
        "|---:|---|---|---|",
    ]
    for index, unit in enumerate(active_units, start=1):
        queue_lines.append(f"| {index} | `source/{unit.path}` | not_started | controller queue |")
    controller_append_artifact(
        sandbox=sandbox,
        config=config,
        state=state,
        path=files.progress,
        content="\n".join(queue_lines) + "\n",
    )

    map_lines = [
        "",
        f"## Controller Source-Target Queue ({now})",
        "",
        "| Source path/unit | Target path/unit | Status | Notes |",
        "|---|---|---|---|",
    ]
    for unit in active_units:
        map_lines.append(f"| `source/{unit.path}` | TBD | not_started | queued by Forgis controller |")
    controller_append_artifact(
        sandbox=sandbox,
        config=config,
        state=state,
        path=files.source_target_map,
        content="\n".join(map_lines) + "\n",
    )
    sandbox.invoke("mkdir", {"path": staged_virtual_path(config, files.compare_report_dir)})


def partial_progress_text(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    iteration: int,
    low_impact_reasons: list[str],
) -> str:
    remaining = max(0, len(units) - completed_unit_count(state))
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    next_unit = units[state.current_unit_index].path if state.current_unit_index < len(units) else "[none]"
    lines = [
        "",
        f"## Partial progress saved at {now}",
        "",
        f"- max_iterations reached: {config.max_iterations}",
        f"- stopped at global iteration: {iteration}",
        f"- current phase: {state.phase}",
        f"- current micro-phase: {current_micro_phase(state, units, config)}",
        f"- processed source units: {len(state.processed_units)}",
        f"- deferred source units: {len(state.deferred_units)}",
        f"- remaining active source units: {remaining}",
        f"- next source unit: {next_unit}",
        "- status: partial; do not treat this run as complete",
        "",
    ]
    if low_impact_reasons:
        lines.extend(["LOW IMPACT WARNING", *[f"- {reason}" for reason in low_impact_reasons], ""])
    return "\n".join(lines)


def append_partial_progress(
    *,
    sandbox: FileToolSandbox,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    iteration: int,
    low_impact_reasons: list[str],
) -> None:
    path = config.staged_translation.progress_files.progress
    try:
        controller_append_artifact(
            sandbox=sandbox,
            config=config,
            state=state,
            path=path,
            content=partial_progress_text(
                config=config,
                state=state,
                units=units,
                iteration=iteration,
                low_impact_reasons=low_impact_reasons,
            ),
        )
    except Exception as exc:
        safe_log(f"partial progress save failed: {exc}")
        return
    safe_log(f"partial progress saved: path={sanitize_log_path(staged_virtual_path(config, path))}")


def low_impact_reasons(
    *,
    config: ResolvedConfig,
    state: StagedState,
    units: list[SourceUnit],
    iteration: int,
) -> list[str]:
    warning = config.staged_translation.low_impact_warning
    if not warning.enabled:
        return []
    reasons: list[str] = []
    code_changed = [path for path in state.implementation_changed_paths if is_code_like_changed_path(path)]
    if iteration >= 20 and len(state.processed_units) < effective_min_processed_units(config, units):
        reasons.append("many iterations completed but processed_units is below min_processed_units")
    if state.processed_units and len(code_changed) < warning.min_code_changed_paths:
        reasons.append("processed source units but code-like target changed paths are below threshold")
    if warning.ignore_report_only_changes and not state.implementation_changed_paths:
        reasons.append("only report/progress artifacts changed; no target implementation files changed")
    if state.implementation_changed_paths and not code_changed:
        reasons.append("target changes are documentation/report-like only; no code-like implementation path changed")
    if state.per_file_started and not (state.compare_reports or state.compare_sections):
        reasons.append("compare report or compare section is missing")
    if not state.source_target_map_updated:
        reasons.append("source-target map was not updated")
    if not state.progress_updated:
        reasons.append("progress file was not updated")
    return reasons


def append_low_impact_warning(
    *,
    sandbox: FileToolSandbox,
    config: ResolvedConfig,
    state: StagedState,
    reasons: list[str],
) -> None:
    if not reasons:
        return
    safe_log("low-impact warning: " + "; ".join(reasons))
    text = "\n".join(["", "## LOW IMPACT WARNING", "", *[f"- {reason}" for reason in reasons], ""])
    try:
        controller_append_artifact(
            sandbox=sandbox,
            config=config,
            state=state,
            path=config.staged_translation.progress_files.progress,
            content=text,
        )
    except Exception as exc:
        safe_log(f"low-impact warning save failed: {exc}")


def final_summary_with_warnings(summary: str, reasons: list[str]) -> str:
    if not reasons:
        return summary
    return "\n".join(["LOW IMPACT WARNING", *[f"- {reason}" for reason in reasons], "", summary])


def run_staged_translation_loop(
    *,
    config: ResolvedConfig,
    source_root: Path,
    target_root: Path,
    environ: dict[str, str] | None = None,
    client_factory: ClientFactory | None = None,
    skill_selection: SkillSelection | None = None,
    report_allowed_root: Path | None = None,
) -> ToolLoopResult:
    env = dict(os.environ if environ is None else environ)
    all_units = collect_source_inventory(source_root, config.staged_translation.source_inventory)
    if not all_units:
        raise RuntimeError("staged_translation source unit queue is empty after source_inventory filters.")
    active_units = active_units_for_run(all_units, config)
    if not active_units:
        raise RuntimeError("staged_translation active source unit queue is empty.")

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
    effective_skill_selection = skill_selection or build_skill_selection(config, target_root=target_root)
    runtime.attach_skills(effective_skill_selection.as_runtime_state())
    runtime.attach_visual_config(config.visual_validation)
    runtime.attach_visual_task_text(read_task_text_for_migration_scheduler(target_root, config))
    state = StagedState()
    initialize_progress_artifacts(
        sandbox=sandbox,
        config=config,
        state=state,
        units=all_units,
        active_units=active_units,
    )

    factory = client_factory or (lambda cfg, local_env: DeepSeekClient.from_config(cfg, local_env))
    client = factory(config, env)
    messages: list[dict[str, Any]] = initial_messages(config, render_selected_skills(effective_skill_selection))
    tool_call_count = 0

    safe_log(
        "staged mode enabled: "
        f"max_iterations={config.max_iterations} "
        f"min_total_iterations={config.staged_translation.min_total_iterations} "
        f"min_processed_units={config.staged_translation.min_processed_units} "
        f"max_units_per_run={config.staged_translation.max_units_per_run} "
        f"source_unit_queue_length={len(all_units)} "
        f"active_source_units={len(active_units)}"
    )

    for iteration in range(1, config.max_iterations + 1):
        log_staged_iteration(
            config=config,
            state=state,
            units=active_units,
            all_units=all_units,
            global_iteration=iteration,
        )
        maybe_log_folder_review_start(config=config, state=state, units=active_units)
        messages.append(
            {
                "role": "user",
                "content": control_message(
                    config=config,
                    state=state,
                    units=active_units,
                    all_units=all_units,
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
                    units=active_units,
                    target_root=target_root,
                    global_iteration=iteration,
                )
                if acceptable:
                    reasons = low_impact_reasons(
                        config=config,
                        state=state,
                        units=active_units,
                        iteration=iteration,
                    )
                    append_low_impact_warning(
                        sandbox=sandbox,
                        config=config,
                        state=state,
                        reasons=reasons,
                    )
                    status = "low-impact" if reasons and config.strict_mode else "completed"
                    status = runtime.visual_effective_status(status)
                    safe_log(
                        "final_summary accepted"
                        + (f" with low-impact warning reasons={len(reasons)}" if reasons else "")
                    )
                    log_tool_loop_finished(
                        iterations=iteration,
                        tool_call_count=tool_call_count,
                        sandbox=sandbox,
                    )
                    return ToolLoopResult(
                        executed=True,
                        status=status,
                        final_summary=final_summary_with_warnings(summary, reasons),
                        iterations=iteration,
                        tool_call_count=tool_call_count,
                        read_tool_count=sandbox.read_count,
                        write_tool_count=sandbox.write_count,
                        operation_log=sandbox.operation_log(),
                        runtime_state=runtime.as_dict(),
                    )

                phase_min = phase_min_iterations(config, state.phase)
                safe_log(
                    "final_summary rejected: "
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
                                "Continue the controller-enforced staged workflow. Do not return final_summary yet.",
                            ]
                        ),
                    }
                )
                maybe_advance_phase(config=config, state=state, units=active_units, target_root=target_root)
                continue

            messages.append({"role": "assistant", "content": str(content)})
            maybe_advance_phase(config=config, state=state, units=active_units, target_root=target_root)
            continue

        messages.append(assistant_tool_call_message(message, tool_calls))
        safe_log(
            f"staged iteration {iteration}/{config.max_iterations}: "
            f"assistant_message={has_assistant_message} "
            f"model returned {len(tool_calls)} tool calls final_summary=no"
        )

        iteration_micro = current_micro_phase(state, active_units, config)
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
                    units=active_units,
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
                arguments = arguments or {}
            except Exception as exc:
                if arguments is None:
                    safe_log(
                        f"tool call {tool_call_count}: iteration={iteration} "
                        f"{name or '[unknown]'} path=[unavailable]"
                    )
                result = {"ok": False, "error": str(exc)}
                status = "error"
                arguments = arguments or {}

            update_state_from_tool_result(
                name=name,
                arguments=arguments,
                result=result,
                state=state,
                units=active_units,
                config=config,
                micro=iteration_micro,
            )
            runtime.observe_tool_result(name=name, arguments=arguments, result=result)
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

        maybe_advance_staged_controller(
            config=config,
            state=state,
            units=active_units,
            target_root=target_root,
        )

    reasons = low_impact_reasons(
        config=config,
        state=state,
        units=active_units,
        iteration=config.max_iterations,
    )
    safe_log(
        "max_iterations reached: "
        f"{config.max_iterations} "
        f"current_phase={state.phase} "
        f"processed_files={len(state.processed_units)} "
        f"deferred_files={len(state.deferred_units)} "
        f"remaining_files={max(0, len(active_units) - completed_unit_count(state))}"
    )
    append_partial_progress(
        sandbox=sandbox,
        config=config,
        state=state,
        units=active_units,
        iteration=config.max_iterations,
        low_impact_reasons=reasons,
    )
    log_tool_loop_finished(
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        sandbox=sandbox,
    )
    status = runtime.visual_effective_status("max-iterations")
    return ToolLoopResult(
        executed=True,
        status=status,
        final_summary=final_summary_with_warnings(
            (
                f"Staged translation stopped after max_iterations={config.max_iterations}; "
                f"current_phase={state.phase}; processed_files={len(state.processed_units)}; "
                f"deferred_files={len(state.deferred_units)}; "
                f"remaining_files={max(0, len(active_units) - completed_unit_count(state))}. "
                "Partial progress was saved."
            ),
            reasons,
        ),
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        read_tool_count=sandbox.read_count,
        write_tool_count=sandbox.write_count,
        operation_log=sandbox.operation_log(),
        runtime_state=runtime.as_dict(),
    )
