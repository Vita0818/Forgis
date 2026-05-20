from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

from migration_state import (
    DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
    MAX_PLAN_EVENT_LOG_MAX_EVENTS,
    safe_plan_events,
)
from migration_units import (
    MAX_UNIT_PATHS,
    UNIT_STATUSES,
    UNIT_TYPES,
    MigrationPlan,
    MigrationUnit,
    sanitize_unit_path,
    sanitize_unit_paths,
)
from repair_report import SECRET_PATH_WORDS, sanitize_failure_summary, sanitize_text
from run_report import _is_forbidden_home_path, _safe_output_dir


MIGRATION_PLAN_FILENAME = "FORGIS_MIGRATION_PLAN.json"
MIGRATION_PLAN_SCHEMA_VERSION = "forgis.migration_plan.v5.0"
SUPPORTED_MIGRATION_PLAN_SCHEMA_VERSIONS = {
    MIGRATION_PLAN_SCHEMA_VERSION,
    "forgis.migration_plan.v4.8",
    "forgis.migration_plan.v3.9",
    "forgis.migration_plan.v3.8",
    "forgis.migration_plan.v3.7",
}
MAX_PLAN_UNITS = 200
MAX_PLAN_FILE_CHARS = 300_000
MAX_PLAN_TEXT_CHARS = 1_000
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
DROP_TEXT_KEYS = {
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
}


@dataclasses.dataclass(frozen=True)
class MigrationPlanWriteResult:
    status: str
    path: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"status": self.status, "path": self.path, "error": self.error}


@dataclasses.dataclass(frozen=True)
class MigrationPlanLoadResult:
    status: str
    plan: MigrationPlan | None = None
    path: str = ""
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"status": self.status, "path": self.path, "error": self.error}


def safe_migration_plan_filename(value: Any = MIGRATION_PLAN_FILENAME) -> str:
    text = sanitize_text(value or MIGRATION_PLAN_FILENAME, limit=140)
    if not text or "/" in text or "\\" in text:
        raise ValueError("migration_plan_filename must be a safe file name, not a path.")
    if text in {".", "..", ".git"} or text.startswith(".") or not SAFE_FILENAME_RE.fullmatch(text):
        raise ValueError("migration_plan_filename must be a safe JSON file name.")
    lowered = text.casefold()
    if not lowered.endswith(".json"):
        raise ValueError("migration_plan_filename must end with .json.")
    if SECRET_PATH_WORDS.search(text):
        raise ValueError("migration_plan_filename must not contain secret-like words.")
    return text


def _safe_plan_file_path(
    path: str | Path,
    *,
    allowed_root: Path,
    source_root: Path | None = None,
    target_root: Path | None = None,
) -> Path:
    raw_text = str(path).strip()
    if not raw_text:
        raise ValueError("migration plan path is empty.")
    if "\x00" in raw_text or "\n" in raw_text or "\r" in raw_text:
        raise ValueError("migration plan path contains an unsafe character.")

    raw = Path(raw_text)
    root = allowed_root.resolve()
    candidate = raw.expanduser().resolve() if raw.is_absolute() else (root / raw).resolve()
    parent = candidate.parent
    if candidate == root or parent == root:
        raise ValueError("migration plan path must be below the runtime root.")
    if not candidate.is_relative_to(root):
        raise ValueError("migration plan path must stay inside the Forgis runtime root.")
    if source_root is not None:
        source = source_root.resolve()
        if candidate == source or candidate.is_relative_to(source):
            raise ValueError("migration plan path must not be inside the source repository.")
    if target_root is not None:
        target = target_root.resolve()
        if candidate == target or candidate.is_relative_to(target):
            raise ValueError("migration plan path must not be inside the target repository.")
    if _is_forbidden_home_path(candidate):
        raise ValueError("migration plan path must not be Desktop, Downloads, or Documents.")
    for part in candidate.relative_to(root).parts:
        if part in {"", ".", "..", ".git"} or SECRET_PATH_WORDS.search(part):
            raise ValueError("migration plan path contains an unsafe path segment.")
    safe_migration_plan_filename(candidate.name)
    return candidate


def migration_plan_file_path(
    output_dir: str | Path,
    *,
    filename: str = MIGRATION_PLAN_FILENAME,
    allowed_root: Path,
    source_root: Path | None = None,
    target_root: Path | None = None,
) -> Path:
    safe_name = safe_migration_plan_filename(filename)
    destination = _safe_output_dir(
        output_dir,
        allowed_root=allowed_root,
        source_root=source_root,
        target_root=target_root,
    )
    return destination / safe_name


def _safe_status(value: Any) -> str:
    text = sanitize_text(value or "pending", limit=40).casefold()
    return text if text in UNIT_STATUSES else "pending"


def _safe_unit_type(value: Any) -> str:
    text = sanitize_text(value or "unknown", limit=40).casefold()
    return text if text in UNIT_TYPES else "unknown"


def _safe_int(value: Any, *, default: int = 0, minimum: int = -1_000, maximum: int = 1_000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(number, maximum))


def _safe_name_list(value: Any, *, limit: int = MAX_UNIT_PATHS) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple, set)) else []
    names: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        name = sanitize_text(raw, limit=80)
        if not name:
            continue
        if SECRET_PATH_WORDS.search(name):
            name = "[redacted]"
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) >= limit:
            break
    return names


def _safe_json_value(value: Any, *, text_limit: int = MAX_PLAN_TEXT_CHARS) -> Any:
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, raw in value.items():
            clean_key = sanitize_text(key, limit=80)
            if not clean_key:
                continue
            if clean_key.casefold() in DROP_TEXT_KEYS:
                output[clean_key] = "[redacted]"
                continue
            output[clean_key] = _safe_json_value(raw, text_limit=text_limit)
        return output
    if isinstance(value, (list, tuple)):
        return [_safe_json_value(item, text_limit=text_limit) for item in list(value)[:MAX_PLAN_UNITS]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    return sanitize_text(value, limit=text_limit)


def _unit_from_data(raw: Any) -> MigrationUnit | None:
    if not isinstance(raw, dict):
        return None
    unit = MigrationUnit(
        unit_id=sanitize_text(raw.get("unit_id"), limit=120),
        title=sanitize_text(raw.get("title"), limit=120) or "Migration unit",
        source_paths=sanitize_unit_paths(raw.get("source_paths"), limit=MAX_UNIT_PATHS),
        target_paths=sanitize_unit_paths(raw.get("target_paths"), limit=MAX_UNIT_PATHS),
        unit_type=_safe_unit_type(raw.get("unit_type")),
        priority=_safe_int(raw.get("priority"), default=0),
        status=_safe_status(raw.get("status")),
        reason=sanitize_text(raw.get("reason"), limit=240),
        selected_skill_names=_safe_name_list(raw.get("selected_skill_names")),
        last_failure_summary=sanitize_failure_summary(raw.get("last_failure_summary")),
        changed_paths=sanitize_unit_paths(raw.get("changed_paths"), limit=MAX_UNIT_PATHS),
        build_status=sanitize_text(raw.get("build_status"), limit=80),
        test_status=sanitize_text(raw.get("test_status"), limit=80),
    )
    return unit


def _serialize_unit(unit: MigrationUnit | dict[str, Any]) -> dict[str, Any]:
    raw = unit.as_summary() if isinstance(unit, MigrationUnit) else dict(unit)
    safe = _unit_from_data(raw)
    if safe is None:
        return {}
    return {
        "unit_id": safe.unit_id,
        "title": safe.title,
        "source_paths": list(safe.source_paths),
        "target_paths": list(safe.target_paths),
        "unit_type": safe.unit_type,
        "priority": safe.priority,
        "status": safe.status,
        "reason": safe.reason,
        "selected_skill_names": list(safe.selected_skill_names),
        "last_failure_summary": safe.last_failure_summary,
        "changed_paths": list(safe.changed_paths),
        "build_status": safe.build_status,
        "test_status": safe.test_status,
    }


def serialize_plan(plan: MigrationPlan, *, max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS) -> dict[str, Any]:
    units = [_serialize_unit(unit) for unit in plan.units[:MAX_PLAN_UNITS]]
    units = [unit for unit in units if unit]
    active_unit_ids = {unit["unit_id"] for unit in units}
    active_unit_id = sanitize_text(plan.active_unit_id or "", limit=120)
    if active_unit_id not in active_unit_ids:
        active_unit_id = ""
        for unit in units:
            if unit.get("status") == "active":
                active_unit_id = str(unit.get("unit_id") or "")
                break
    safe_plan = MigrationPlan(units=[MigrationUnit(**unit) for unit in units], active_unit_id=active_unit_id or None)
    safe_plan.plan_id = sanitize_text(plan.plan_id, limit=120) or safe_plan.plan_id
    return _safe_json_value(
        {
            "schema_version": MIGRATION_PLAN_SCHEMA_VERSION,
            "plan_id": safe_plan.plan_id,
            "active_unit_id": safe_plan.active_unit_id or "",
            "counts": safe_plan.counts(),
            "units": [unit.as_summary() for unit in safe_plan.units],
            "events": safe_plan_events(plan.events, max_events=max_events),
        }
    )


def deserialize_plan(data: dict[str, Any]) -> MigrationPlan:
    if not isinstance(data, dict):
        raise ValueError("migration plan JSON must be an object.")
    schema_version = sanitize_text(data.get("schema_version"), limit=80)
    if schema_version and schema_version not in SUPPORTED_MIGRATION_PLAN_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported migration plan schema_version: {schema_version}")
    raw_units = data.get("units")
    if not isinstance(raw_units, list):
        raw_units = []
    units: list[MigrationUnit] = []
    seen: set[str] = set()
    for raw in raw_units[:MAX_PLAN_UNITS]:
        unit = _unit_from_data(raw)
        if unit is None or unit.unit_id in seen:
            continue
        seen.add(unit.unit_id)
        units.append(unit)
    active_unit_id = sanitize_text(data.get("active_unit_id"), limit=120)
    if active_unit_id not in seen:
        active_unit_id = ""
    plan = MigrationPlan(
        units=units,
        plan_id=sanitize_text(data.get("plan_id"), limit=120),
        active_unit_id=active_unit_id or None,
        events=safe_plan_events(data.get("events"), max_events=MAX_PLAN_EVENT_LOG_MAX_EVENTS),
    )
    return plan


def _json_text(plan: MigrationPlan, *, max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS) -> str:
    text = json.dumps(serialize_plan(plan, max_events=max_events), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if len(text) <= MAX_PLAN_FILE_CHARS:
        return text
    reduced = serialize_plan(MigrationPlan(units=plan.units[:50], plan_id=plan.plan_id, active_unit_id=plan.active_unit_id))
    reduced["truncated"] = True
    reduced["truncation_note"] = "FORGIS_MIGRATION_PLAN.json was reduced to stay within the plan artifact size limit."
    return json.dumps(_safe_json_value(reduced), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def write_migration_plan(
    plan: MigrationPlan,
    output_dir: str | Path,
    *,
    filename: str = MIGRATION_PLAN_FILENAME,
    allowed_root: Path | None = None,
    source_root: Path | None = None,
    target_root: Path | None = None,
    required: bool = False,
    max_events: int = DEFAULT_PLAN_EVENT_LOG_MAX_EVENTS,
) -> MigrationPlanWriteResult:
    root = (allowed_root or Path.cwd()).resolve()
    try:
        path = migration_plan_file_path(
            output_dir,
            filename=filename,
            allowed_root=root,
            source_root=source_root,
            target_root=target_root,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_json_text(plan, max_events=max_events), encoding="utf-8")
        return MigrationPlanWriteResult(status="written", path=path.as_posix())
    except Exception as exc:
        message = sanitize_text(exc, limit=300)
        if required:
            raise RuntimeError(message) from exc
        return MigrationPlanWriteResult(status="skipped", error=message)


def load_migration_plan(
    path: str | Path,
    *,
    allowed_root: Path | None = None,
    source_root: Path | None = None,
    target_root: Path | None = None,
) -> MigrationPlanLoadResult:
    root = (allowed_root or Path.cwd()).resolve()
    try:
        safe_path = _safe_plan_file_path(
            path,
            allowed_root=root,
            source_root=source_root,
            target_root=target_root,
        )
    except Exception as exc:
        return MigrationPlanLoadResult(status="failed", error=sanitize_text(exc, limit=300))

    path_text = safe_path.as_posix()
    if not safe_path.exists():
        return MigrationPlanLoadResult(status="skipped", path=path_text)
    if not safe_path.is_file():
        return MigrationPlanLoadResult(status="failed", path=path_text, error="migration plan path is not a file.")
    try:
        raw_text = safe_path.read_text(encoding="utf-8", errors="replace")
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return MigrationPlanLoadResult(
            status="failed",
            path=path_text,
            error=sanitize_text(f"migration plan JSON is invalid: {exc}", limit=300),
        )
    except OSError as exc:
        return MigrationPlanLoadResult(status="failed", path=path_text, error=sanitize_text(exc, limit=300))

    if isinstance(data, dict):
        schema_version = sanitize_text(data.get("schema_version"), limit=80)
        if schema_version and schema_version not in SUPPORTED_MIGRATION_PLAN_SCHEMA_VERSIONS:
            return MigrationPlanLoadResult(
                status="version_mismatch",
                path=path_text,
                error=sanitize_text(f"unsupported migration plan schema_version: {schema_version}", limit=300),
            )
    try:
        plan = deserialize_plan(data)
    except ValueError as exc:
        message = sanitize_text(exc, limit=300)
        if "schema_version" in message:
            return MigrationPlanLoadResult(status="version_mismatch", path=path_text, error=message)
        return MigrationPlanLoadResult(status="failed", path=path_text, error=message)
    return MigrationPlanLoadResult(status="loaded", plan=plan, path=path_text)
