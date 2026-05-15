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


SKIP_PATH_PARTS = {
    ".git",
    ".cache",
    ".gradle",
    "build",
    "cache",
    "deriveddata",
    "dist",
    "generated",
    "node_modules",
    "out",
}
SKIP_NAME_WORDS = {
    "credential",
    "private",
    "secret",
    "token",
}
SKIP_SUFFIXES = {
    ".7z",
    ".bmp",
    ".class",
    ".dll",
    ".dmg",
    ".exe",
    ".gif",
    ".gz",
    ".ico",
    ".jar",
    ".jpeg",
    ".jpg",
    ".lock",
    ".mov",
    ".mp3",
    ".mp4",
    ".o",
    ".pdf",
    ".png",
    ".pyc",
    ".so",
    ".sqlite",
    ".tar",
    ".webp",
    ".zip",
}
SOURCE_HINT_SUFFIXES = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".mjs",
    ".md",
    ".php",
    ".py",
    ".rb",
    ".rs",
    ".rst",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


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


def is_probably_binary(path: Path) -> bool:
    try:
        with path.open("rb") as file:
            chunk = file.read(4096)
    except OSError:
        return True
    return b"\x00" in chunk


def should_skip_source_unit(relative: str, path: Path) -> bool:
    parts = [part.casefold() for part in Path(relative).parts]
    if any(part in SKIP_PATH_PARTS for part in parts[:-1]):
        return True

    name = parts[-1] if parts else ""
    suffix = path.suffix.casefold()
    if suffix in SKIP_SUFFIXES:
        return True
    if name.endswith(".lock") or "lock" in name and name.endswith((".json", ".yaml", ".yml")):
        return True
    if any(word in name for word in SKIP_NAME_WORDS):
        return True
    if suffix and suffix not in SOURCE_HINT_SUFFIXES and is_probably_binary(path):
        return True
    if not suffix and is_probably_binary(path):
        return True
    return False


def source_unit_sort_key(unit: SourceUnit) -> tuple[int, str]:
    suffix = Path(unit.path).suffix.casefold()
    name = Path(unit.path).name.casefold()
    if suffix in {".md", ".rst", ".txt"}:
        priority = 1
    elif suffix in {".json", ".yaml", ".yml", ".toml", ".xml"}:
        priority = 2
    elif suffix in SOURCE_HINT_SUFFIXES:
        priority = 0
    else:
        priority = 3
    if name.startswith("readme") or "architecture" in name or "spec" in name:
        priority = min(priority, 1)
    return priority, unit.path.casefold()


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
        if should_skip_source_unit(relative, path):
            continue
        try:
            size_chars = path.stat().st_size
        except OSError:
            size_chars = 0
        folder = Path(relative).parent.as_posix()
        if folder == ".":
            folder = ""
        units.append(SourceUnit(path=relative, folder=folder, size_chars=size_chars))
    return sorted(units, key=source_unit_sort_key)


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
