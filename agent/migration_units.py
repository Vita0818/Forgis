from __future__ import annotations

import dataclasses
import hashlib
import re
from pathlib import PurePosixPath
from typing import Any

from repair_report import SECRET_PATH_WORDS, sanitize_failure_summary, sanitize_text


UNIT_TYPES = {"ui", "model", "service", "asset", "test", "config", "unknown"}
UNIT_STATUSES = {"pending", "active", "blocked", "completed", "deferred"}
MAX_UNIT_PATHS = 12
MAX_UNIT_ID_CHARS = 96
MAX_UNIT_TITLE_CHARS = 120
MAX_UNIT_REASON_CHARS = 240
MAX_UNIT_PATH_CHARS = 160

LEGAL_STATUS_TRANSITIONS = {
    "pending": {"pending", "active", "blocked", "completed", "deferred"},
    "active": {"active", "pending", "blocked", "completed", "deferred"},
    "blocked": {"blocked", "active", "deferred"},
    "completed": {"completed"},
    "deferred": {"deferred", "active"},
}


def _safe_slug(value: Any, *, limit: int = 14) -> str:
    text = sanitize_unit_path(value, limit=limit * 4).casefold()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:limit].strip("-") or "unit")


def sanitize_unit_path(value: Any, *, limit: int = MAX_UNIT_PATH_CHARS) -> str:
    text = str(value if value is not None else "").replace("\x00", "").replace("\r", " ").replace("\n", " ")
    text = text.strip().replace("\\", "/")
    if not text:
        return ""
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        name = PurePosixPath(text).name
        text = f"[path-redacted]/{name}" if name else "[path-redacted]"
    parts: list[str] = []
    for part in PurePosixPath(text.strip("/")).parts:
        if part in {"", ".", "..", ".git"}:
            continue
        parts.append("[redacted]" if SECRET_PATH_WORDS.search(part) else part)
    cleaned = "/".join(parts) or "[root]"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:80] + ".../" + cleaned[-60:]


def sanitize_unit_paths(values: Any, *, limit: int = MAX_UNIT_PATHS) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    paths: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        path = sanitize_unit_path(raw)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def _safe_unit_id(value: Any) -> str:
    text = str(value if value is not None else "").replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    text = re.sub(r"(?i)(secret|token|credential|password|api[_-]?key|private)", "redacted", text)
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip(".-_")
    if len(text) <= MAX_UNIT_ID_CHARS:
        return text
    return text[: MAX_UNIT_ID_CHARS - 9].rstrip(".-_") + "-" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


def _safe_unit_type(value: Any) -> str:
    text = sanitize_text(value or "unknown", limit=40).casefold()
    return text if text in UNIT_TYPES else "unknown"


def _safe_status(value: Any) -> str:
    text = sanitize_text(value or "pending", limit=40).casefold()
    if text not in UNIT_STATUSES:
        raise ValueError(f"migration unit status is not supported: {value}")
    return text


def stable_unit_id(
    *,
    title: str = "",
    source_paths: list[str] | tuple[str, ...] | None = None,
    target_paths: list[str] | tuple[str, ...] | None = None,
    unit_type: str = "unknown",
) -> str:
    safe_type = _safe_unit_type(unit_type)
    safe_sources = sanitize_unit_paths(source_paths or [], limit=MAX_UNIT_PATHS)
    safe_targets = sanitize_unit_paths(target_paths or [], limit=MAX_UNIT_PATHS)
    readable_basis = safe_sources[0] if safe_sources else safe_targets[0] if safe_targets else title
    slug = _safe_slug(readable_basis)
    digest_basis = "\n".join([safe_type, sanitize_text(title, limit=MAX_UNIT_TITLE_CHARS), *safe_sources, *safe_targets])
    digest = hashlib.sha1(digest_basis.encode("utf-8")).hexdigest()[:8]
    unit_id = f"{safe_type}-{slug}-{digest}"
    return _safe_unit_id(unit_id)


def stable_plan_id(units: list["MigrationUnit"] | tuple["MigrationUnit", ...]) -> str:
    digest_basis = "\n".join(unit.unit_id for unit in units)
    digest = hashlib.sha1(digest_basis.encode("utf-8")).hexdigest()[:10]
    return f"migration-plan-{digest}"


@dataclasses.dataclass
class MigrationUnit:
    unit_id: str = ""
    title: str = ""
    source_paths: list[str] = dataclasses.field(default_factory=list)
    target_paths: list[str] = dataclasses.field(default_factory=list)
    unit_type: str = "unknown"
    priority: int = 0
    status: str = "pending"
    reason: str = ""
    selected_skill_names: list[str] = dataclasses.field(default_factory=list)
    last_failure_summary: dict[str, Any] | None = None
    changed_paths: list[str] = dataclasses.field(default_factory=list)
    build_status: str = ""
    test_status: str = ""

    def __post_init__(self) -> None:
        self.unit_type = _safe_unit_type(self.unit_type)
        self.status = _safe_status(self.status)
        self.title = sanitize_text(self.title, limit=MAX_UNIT_TITLE_CHARS) or "Migration unit"
        self.source_paths = sanitize_unit_paths(self.source_paths, limit=MAX_UNIT_PATHS)
        self.target_paths = sanitize_unit_paths(self.target_paths, limit=MAX_UNIT_PATHS)
        self.unit_id = _safe_unit_id(self.unit_id) or stable_unit_id(
            title=self.title,
            source_paths=self.source_paths,
            target_paths=self.target_paths,
            unit_type=self.unit_type,
        )
        self.priority = int(self.priority)
        self.reason = sanitize_text(self.reason, limit=MAX_UNIT_REASON_CHARS)
        self.selected_skill_names = [
            sanitize_text(name, limit=80)
            for name in self.selected_skill_names[:MAX_UNIT_PATHS]
            if sanitize_text(name, limit=80)
        ]
        self.last_failure_summary = sanitize_failure_summary(self.last_failure_summary)
        self.changed_paths = sanitize_unit_paths(self.changed_paths, limit=MAX_UNIT_PATHS)
        self.build_status = sanitize_text(self.build_status, limit=80)
        self.test_status = sanitize_text(self.test_status, limit=80)

    def transition_to(self, status: str, *, reason: str = "") -> "MigrationUnit":
        new_status = _safe_status(status)
        allowed = LEGAL_STATUS_TRANSITIONS[self.status]
        if new_status not in allowed:
            raise ValueError(f"illegal migration unit status transition: {self.status} -> {new_status}")
        clean_reason = sanitize_text(reason, limit=MAX_UNIT_REASON_CHARS)
        if new_status in {"blocked", "completed", "deferred"} and not clean_reason:
            raise ValueError(f"migration unit status transition to {new_status} requires a reason")
        self.status = new_status
        if clean_reason:
            self.reason = clean_reason
        return self

    def as_summary(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "title": self.title,
            "source_paths": list(self.source_paths),
            "target_paths": list(self.target_paths),
            "unit_type": self.unit_type,
            "priority": self.priority,
            "status": self.status,
            "reason": self.reason,
            "selected_skill_names": list(self.selected_skill_names),
            "last_failure_summary": self.last_failure_summary,
            "changed_paths": list(self.changed_paths),
            "build_status": self.build_status,
            "test_status": self.test_status,
        }


@dataclasses.dataclass
class MigrationPlan:
    units: list[MigrationUnit] = dataclasses.field(default_factory=list)
    plan_id: str = ""
    active_unit_id: str | None = None
    events: list[dict[str, Any]] = dataclasses.field(default_factory=list)

    def __post_init__(self) -> None:
        self.units = [unit if isinstance(unit, MigrationUnit) else MigrationUnit(**unit) for unit in self.units]
        self.plan_id = sanitize_text(self.plan_id, limit=120) or stable_plan_id(self.units)
        if self.active_unit_id:
            self.active_unit_id = _safe_unit_id(self.active_unit_id)
        elif self.active_unit is not None:
            self.active_unit_id = self.active_unit.unit_id
        self.events = [dict(event) for event in self.events if isinstance(event, dict)]

    @property
    def active_unit(self) -> MigrationUnit | None:
        if self.active_unit_id:
            for unit in self.units:
                if unit.unit_id == self.active_unit_id:
                    return unit
        for unit in self.units:
            if unit.status == "active":
                return unit
        return None

    @property
    def completed_count(self) -> int:
        return sum(1 for unit in self.units if unit.status == "completed")

    @property
    def blocked_count(self) -> int:
        return sum(1 for unit in self.units if unit.status == "blocked")

    @property
    def pending_count(self) -> int:
        return sum(1 for unit in self.units if unit.status == "pending")

    @property
    def deferred_count(self) -> int:
        return sum(1 for unit in self.units if unit.status == "deferred")

    @property
    def active_count(self) -> int:
        return sum(1 for unit in self.units if unit.status == "active")

    def unit_by_id(self, unit_id: str) -> MigrationUnit:
        clean = _safe_unit_id(unit_id)
        for unit in self.units:
            if unit.unit_id == clean:
                return unit
        raise KeyError(f"migration unit not found: {clean}")

    def counts(self) -> dict[str, int]:
        return {
            "completed": self.completed_count,
            "blocked": self.blocked_count,
            "pending": self.pending_count,
            "deferred": self.deferred_count,
            "active": self.active_count,
            "total": len(self.units),
        }

    def as_summary(self, *, max_units: int = 50, max_events: int = 100) -> dict[str, Any]:
        unit_limit = max(0, min(int(max_units), 200))
        event_limit = max(0, min(int(max_events), 500))
        active = self.active_unit
        return {
            "plan_id": self.plan_id,
            "active_unit_id": active.unit_id if active else self.active_unit_id or "",
            "completed_count": self.completed_count,
            "blocked_count": self.blocked_count,
            "pending_count": self.pending_count,
            "deferred_count": self.deferred_count,
            "active_count": self.active_count,
            "unit_count": len(self.units),
            "active_unit": active.as_summary() if active else None,
            "units": [unit.as_summary() for unit in self.units[:unit_limit]],
            "events": [dict(event) for event in self.events[-event_limit:]],
        }
