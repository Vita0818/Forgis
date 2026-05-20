from __future__ import annotations

import dataclasses
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from migration_state import append_plan_event, safe_active_unit_switch_result, safe_unit_status_update_result
from migration_units import MigrationPlan, MigrationUnit, sanitize_unit_path, sanitize_unit_paths, stable_unit_id
from repair_report import sanitize_failure_summary, sanitize_text
from source_inventory import (
    SKIP_NAME_WORDS,
    SKIP_PATH_PARTS,
    SKIP_SUFFIXES,
    SOURCE_HINT_SUFFIXES,
    SourceInventoryConfig,
    SourceUnit,
    excluded_by_globs,
    included_by_globs,
    source_unit_sort_key,
)


DEFAULT_MAX_MIGRATION_UNITS = 50
MAX_MIGRATION_UNITS_LIMIT = 200
PATH_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_./-])"
    r"((?:source/|target/|target_subdir/)?[A-Za-z0-9][A-Za-z0-9_./@+-]*"
    r"\.(?:swift|kt|kts|java|xml|json|yaml|yml|toml|gradle|py|js|jsx|ts|tsx|css|scss|html|md|png|jpg|jpeg|webp|svg|plist))"
    r"(?![A-Za-z0-9_./-])"
)
TEST_WORDS = {"test", "tests", "__tests__", "spec", "specs"}
ASSET_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".ico", ".pdf"}
CONFIG_SUFFIXES = {".json", ".yaml", ".yml", ".toml", ".xml", ".plist", ".gradle", ".kts"}
DEFAULT_MAX_SCAN_FILES_FACTOR = 8


def _config_bool(config: Any, name: str, default: bool) -> bool:
    return bool(getattr(config, name, default))


def _config_int(config: Any, name: str, default: int) -> int:
    try:
        return int(getattr(config, name, default))
    except (TypeError, ValueError):
        return default


def _max_units(config: Any) -> int:
    requested = _config_int(config, "max_migration_units", DEFAULT_MAX_MIGRATION_UNITS)
    return max(1, min(requested, MAX_MIGRATION_UNITS_LIMIT))


def _selected_skill_names(config: Any) -> list[str]:
    return [sanitize_text(name, limit=80) for name in (getattr(config, "selected_skills", ()) or ()) if sanitize_text(name, limit=80)]


def _inventory_path(item: Any) -> str:
    if isinstance(item, dict):
        raw = item.get("path") or item.get("source_path")
    else:
        raw = getattr(item, "path", "")
    return sanitize_unit_path(raw)


def _skip_inventory_path_by_metadata(relative: str, suffix: str) -> bool:
    parts = [part.casefold() for part in PurePosixPath(relative).parts]
    if any(part in SKIP_PATH_PARTS for part in parts[:-1]):
        return True
    name = parts[-1] if parts else ""
    if suffix in SKIP_SUFFIXES:
        return True
    if name.endswith(".lock") or ("lock" in name and name.endswith((".json", ".yaml", ".yml"))):
        return True
    return any(word in name for word in SKIP_NAME_WORDS)


def collect_scheduler_inventory(
    source_root: Path,
    config: SourceInventoryConfig,
    *,
    max_units: int = DEFAULT_MAX_MIGRATION_UNITS,
) -> list[SourceUnit]:
    root = source_root.resolve()
    units: list[SourceUnit] = []
    scanned_files = 0
    max_scan_files = max(1, min(max_units, MAX_MIGRATION_UNITS_LIMIT)) * DEFAULT_MAX_SCAN_FILES_FACTOR
    if not root.is_dir():
        return []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            name for name in dirnames if name.casefold() not in SKIP_PATH_PARTS and name != ".git"
        )
        current = Path(dirpath)
        for filename in sorted(filenames, key=str.casefold):
            if scanned_files >= max_scan_files:
                return sorted(units, key=source_unit_sort_key)
            path = current / filename
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                continue
            scanned_files += 1
            suffix = path.suffix.casefold()
            if _skip_inventory_path_by_metadata(relative, suffix):
                continue
            if suffix and suffix not in SOURCE_HINT_SUFFIXES and suffix not in ASSET_SUFFIXES:
                continue
            if not included_by_globs(relative, config.include_globs):
                continue
            if excluded_by_globs(relative, config.exclude_globs):
                continue
            try:
                size_chars = path.stat().st_size
            except OSError:
                size_chars = 0
            folder = PurePosixPath(relative).parent.as_posix()
            if folder == ".":
                folder = ""
            units.append(SourceUnit(path=relative, folder=folder, size_chars=size_chars))
            if len(units) >= max(1, min(max_units, MAX_MIGRATION_UNITS_LIMIT)) * 4:
                return sorted(units, key=source_unit_sort_key)
    return sorted(units, key=source_unit_sort_key)


def classify_unit_type(path: str) -> str:
    clean = sanitize_unit_path(path)
    lowered = clean.casefold()
    pure = PurePosixPath(clean)
    name = pure.name.casefold()
    stem = pure.stem.casefold()
    suffix = pure.suffix.casefold()
    parts = {part.casefold() for part in pure.parts}

    if parts & TEST_WORDS or stem.endswith(("test", "tests", "spec")) or "test" in stem:
        return "test"
    if suffix in ASSET_SUFFIXES or parts & {"asset", "assets", "res", "resources", "drawable", "images"}:
        return "asset"
    if any(word in lowered for word in ("view", "screen", "page", "component", "widget", "fragment", "activity", "composable")):
        return "ui"
    if any(word in lowered for word in ("service", "api", "client", "repository", "network", "manager")):
        return "service"
    if any(word in lowered for word in ("model", "entity", "schema", "dto", "state", "store", "data")):
        return "model"
    if suffix in CONFIG_SUFFIXES or name in {"makefile", "dockerfile"} or parts & {"config", "configs"}:
        return "config"
    return "unknown"


def unit_priority(unit_type: str, *, prioritize_ui: bool) -> int:
    if prioritize_ui:
        priorities = {
            "ui": 100,
            "model": 70,
            "service": 60,
            "unknown": 40,
            "config": 30,
            "asset": 20,
            "test": 10,
        }
    else:
        priorities = {
            "model": 70,
            "service": 60,
            "ui": 50,
            "unknown": 40,
            "config": 30,
            "asset": 20,
            "test": 10,
        }
    return priorities.get(unit_type, 0)


def should_include_unit(unit_type: str, config: Any) -> bool:
    if unit_type == "test" and not _config_bool(config, "migration_unit_include_tests", True):
        return False
    if unit_type == "asset" and not _config_bool(config, "migration_unit_include_assets", True):
        return False
    return True


def _title_for_path(path: str, unit_type: str) -> str:
    clean = sanitize_unit_path(path)
    return sanitize_text(f"{unit_type} migration: {clean}", limit=120)


def _unit_from_source_path(path: str, config: Any) -> MigrationUnit | None:
    clean = sanitize_unit_path(path)
    if not clean:
        return None
    unit_type = classify_unit_type(clean)
    if not should_include_unit(unit_type, config):
        return None
    priority = unit_priority(
        unit_type,
        prioritize_ui=_config_bool(config, "migration_unit_prioritize_ui", True),
    )
    title = _title_for_path(clean, unit_type)
    return MigrationUnit(
        unit_id=stable_unit_id(title=title, source_paths=[clean], unit_type=unit_type),
        title=title,
        source_paths=[clean],
        target_paths=[],
        unit_type=unit_type,
        priority=priority,
        status="pending",
        reason="generated from source inventory",
        selected_skill_names=_selected_skill_names(config),
    )


def _unit_from_explicit_path(path: str, config: Any) -> MigrationUnit | None:
    clean = sanitize_unit_path(path)
    if not clean:
        return None
    unit_type = classify_unit_type(clean)
    if not should_include_unit(unit_type, config):
        return None
    source_paths: list[str] = []
    target_paths: list[str] = []
    if clean.startswith("target/") or clean.startswith("target_subdir/"):
        target_paths.append(clean)
    else:
        source_paths.append(clean)
    priority = unit_priority(
        unit_type,
        prioritize_ui=_config_bool(config, "migration_unit_prioritize_ui", True),
    )
    title = _title_for_path(clean, unit_type)
    return MigrationUnit(
        unit_id=stable_unit_id(title=title, source_paths=source_paths, target_paths=target_paths, unit_type=unit_type),
        title=title,
        source_paths=source_paths,
        target_paths=target_paths,
        unit_type=unit_type,
        priority=priority,
        status="pending",
        reason="generated from explicit task path",
        selected_skill_names=_selected_skill_names(config),
    )


def explicit_paths_from_task_text(task_text: str) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for match in PATH_TOKEN_RE.finditer(task_text or ""):
        path = sanitize_unit_path(match.group(1))
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
    return paths


def create_units_from_inventory(
    inventory: list[Any] | tuple[Any, ...] | None,
    config: Any,
    task_text: str = "",
) -> MigrationPlan:
    max_units = _max_units(config)
    units_by_id: dict[str, MigrationUnit] = {}

    strategy = sanitize_text(getattr(config, "migration_unit_strategy", "inventory"), limit=40).casefold() or "inventory"
    include_inventory = strategy == "inventory"
    if include_inventory:
        for item in inventory or []:
            unit = _unit_from_source_path(_inventory_path(item), config)
            if unit is not None:
                units_by_id.setdefault(unit.unit_id, unit)

    for path in explicit_paths_from_task_text(task_text):
        unit = _unit_from_explicit_path(path, config)
        if unit is not None:
            units_by_id.setdefault(unit.unit_id, unit)

    units = sorted(units_by_id.values(), key=lambda unit: (-unit.priority, unit.unit_id))
    return MigrationPlan(units=units[:max_units])


def select_next_unit(plan: MigrationPlan) -> MigrationUnit | None:
    active = plan.active_unit
    if active is not None and active.status == "active":
        return active
    for unit in plan.units:
        if unit.status == "pending":
            return unit
    return None


def mark_unit_active(plan: MigrationPlan, unit_id: str) -> MigrationUnit:
    selected = plan.unit_by_id(unit_id)
    for unit in plan.units:
        if unit.unit_id != selected.unit_id and unit.status == "active":
            unit.transition_to("pending")
    before = selected.status
    selected.transition_to("active")
    plan.active_unit_id = selected.unit_id
    append_plan_event(
        plan,
        "active_unit_selected",
        unit_id=selected.unit_id,
        status_before=before,
        status_after=selected.status,
        reason=selected.reason or "Selected as the active migration unit.",
        short_message="Active migration unit selected.",
    )
    return selected


def mark_unit_completed(plan: MigrationPlan, unit_id: str, reason: str = "Migration unit completed by controller.") -> MigrationUnit:
    unit = plan.unit_by_id(unit_id)
    before = unit.status
    unit.transition_to("completed", reason=reason)
    plan.active_unit_id = unit.unit_id
    append_plan_event(
        plan,
        "unit_completed",
        unit_id=unit.unit_id,
        status_before=before,
        status_after=unit.status,
        reason=unit.reason,
        short_message="Migration unit marked completed.",
    )
    return unit


def mark_unit_blocked(plan: MigrationPlan, unit_id: str, reason: str) -> MigrationUnit:
    unit = plan.unit_by_id(unit_id)
    before = unit.status
    unit.transition_to("blocked", reason=reason)
    plan.active_unit_id = unit.unit_id
    append_plan_event(
        plan,
        "unit_blocked",
        unit_id=unit.unit_id,
        status_before=before,
        status_after=unit.status,
        reason=unit.reason,
        short_message="Migration unit marked blocked.",
    )
    return unit


def mark_unit_deferred(plan: MigrationPlan, unit_id: str, reason: str) -> MigrationUnit:
    unit = plan.unit_by_id(unit_id)
    before = unit.status
    unit.transition_to("deferred", reason=reason)
    plan.active_unit_id = unit.unit_id
    append_plan_event(
        plan,
        "unit_deferred",
        unit_id=unit.unit_id,
        status_before=before,
        status_after=unit.status,
        reason=unit.reason,
        short_message="Migration unit marked deferred.",
    )
    return unit


def update_unit_from_runtime(plan: MigrationPlan, unit_id: str, runtime_state: dict[str, Any]) -> MigrationUnit:
    unit = plan.unit_by_id(unit_id)
    before = unit.as_summary()
    unit.changed_paths = sanitize_unit_paths([*(unit.changed_paths or []), *(runtime_state.get("changed_paths") or [])])
    unit.build_status = sanitize_text(runtime_state.get("last_build_status") or unit.build_status, limit=80)
    unit.test_status = sanitize_text(runtime_state.get("last_test_status") or unit.test_status, limit=80)
    summary = sanitize_failure_summary(runtime_state.get("last_failure_summary"))
    if summary:
        unit.last_failure_summary = summary
    if unit.as_summary() != before:
        append_plan_event(
            plan,
            "active_unit_updated",
            unit_id=unit.unit_id,
            status_before=before.get("status", ""),
            status_after=unit.status,
            reason="Migration unit runtime evidence was refreshed.",
            short_message="Runtime changed paths/build/test/failure metadata updated.",
        )
    return unit


def render_active_unit_context(
    plan: MigrationPlan,
    active_unit_switch: dict[str, Any] | None = None,
    manual_unit_status_update: dict[str, Any] | None = None,
) -> str:
    unit = plan.active_unit
    if unit is None:
        return ""
    summary = unit.as_summary()
    counts = plan.counts()
    switch = safe_active_unit_switch_result(active_unit_switch or {})
    status_update = safe_unit_status_update_result(manual_unit_status_update or {})
    lines = [
        "Active Migration Unit",
        "",
        f"- plan_id: {plan.plan_id}",
        f"- unit_id: {summary['unit_id']}",
        f"- title: {summary['title']}",
        f"- unit_type: {summary['unit_type']}",
        f"- status: {summary['status']}",
        f"- reason: {summary['reason'] or 'none'}",
        f"- source_paths: {', '.join(summary['source_paths']) if summary['source_paths'] else 'none'}",
        f"- target_paths: {', '.join(summary['target_paths']) if summary['target_paths'] else 'none'}",
        f"- selected_skills: {', '.join(summary['selected_skill_names']) if summary['selected_skill_names'] else 'none'}",
        f"- plan_counts: completed={counts['completed']} blocked={counts['blocked']} pending={counts['pending']} deferred={counts['deferred']} active={counts['active']} total={counts['total']}",
    ]
    if switch.get("status") == "switched":
        lines.extend(
            [
                f"- manual_switch: requested={switch.get('requested_active_unit_id') or 'none'} previous={switch.get('previous_active_unit_id') or 'none'}",
                f"- manual_switch_reason: {switch.get('reason') or 'none'}",
            ]
        )
    if status_update.get("status") in {"updated", "rejected"} or status_update.get("unit_id"):
        lines.extend(
            [
                f"- manual_status_update: result={status_update.get('status') or 'skipped'} unit={status_update.get('unit_id') or 'none'} requested_status={status_update.get('requested_status') or 'none'} final_status={status_update.get('final_status') or 'none'}",
                f"- manual_status_update_reason: {status_update.get('reason') or status_update.get('message') or 'none'}",
            ]
        )
    lines.extend(
        [
            "",
            "Work inside this active unit first. If it is blocked, completed, or deferred, report that status instead of jumping to another unit.",
        ]
    )
    return "\n".join(lines)


@dataclasses.dataclass
class MigrationUnitScheduler:
    plan: MigrationPlan

    def select_next_unit(self) -> MigrationUnit | None:
        return select_next_unit(self.plan)

    def mark_unit_active(self, unit_id: str) -> MigrationUnit:
        return mark_unit_active(self.plan, unit_id)

    def mark_unit_completed(self, unit_id: str) -> MigrationUnit:
        return mark_unit_completed(self.plan, unit_id)

    def mark_unit_blocked(self, unit_id: str, reason: str) -> MigrationUnit:
        return mark_unit_blocked(self.plan, unit_id, reason)

    def mark_unit_deferred(self, unit_id: str, reason: str) -> MigrationUnit:
        return mark_unit_deferred(self.plan, unit_id, reason)

    def update_unit_from_runtime(self, unit_id: str, runtime_state: dict[str, Any]) -> MigrationUnit:
        return update_unit_from_runtime(self.plan, unit_id, runtime_state)
