from __future__ import annotations

import fnmatch
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from forgis_config import SourceInventoryConfig


@dataclass(frozen=True)
class SourceUnit:
    path: str
    folder: str
    size_chars: int


def path_kind_no_follow(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def glob_matches(path: str, pattern: str) -> bool:
    if pattern == "**/*":
        return True
    if fnmatch.fnmatchcase(path, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:]):
        return True
    return False


def included_by_globs(path: str, include_globs: tuple[str, ...]) -> bool:
    return any(glob_matches(path, pattern) for pattern in include_globs)


def excluded_by_globs(path: str, exclude_globs: tuple[str, ...]) -> bool:
    return any(glob_matches(path, pattern) for pattern in exclude_globs)


def safe_source_report_name(source_path: str, *, max_length: int = 180) -> str:
    normalized = source_path.replace("\\", "/").strip("/")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "__", normalized)
    safe = safe.strip("._-") or "source_unit"
    if safe in {".", ".."}:
        safe = "source_unit"
    if len(safe) > max_length:
        safe = safe[:max_length].rstrip("._-") or "source_unit"
    return f"{safe}.md"


def collect_source_inventory(source_root: Path, config: SourceInventoryConfig) -> list[SourceUnit]:
    root = source_root.resolve()
    units: list[SourceUnit] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().casefold()):
        if path_kind_no_follow(path) != "file":
            continue
        relative = path.relative_to(root).as_posix()
        if not included_by_globs(relative, config.include_globs):
            continue
        if excluded_by_globs(relative, config.exclude_globs):
            continue
        try:
            size_chars = len(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            size_chars = 0
        folder = Path(relative).parent.as_posix()
        if folder == ".":
            folder = ""
        units.append(SourceUnit(path=relative, folder=folder, size_chars=size_chars))
    return units


def folder_direct_units(units: list[SourceUnit], folder: str) -> list[SourceUnit]:
    return [unit for unit in units if unit.folder == folder]


def bundled_units_for_folder(
    units: list[SourceUnit],
    folder: str,
    *,
    max_bundle_chars: int,
) -> tuple[list[SourceUnit], list[SourceUnit]]:
    included: list[SourceUnit] = []
    omitted: list[SourceUnit] = []
    used = 0
    for unit in folder_direct_units(units, folder):
        if not included or used + unit.size_chars <= max_bundle_chars:
            included.append(unit)
            used += unit.size_chars
            continue
        omitted.append(unit)
    return included, omitted
