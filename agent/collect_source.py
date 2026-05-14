#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_EXCLUDE = (".git/**",)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_json_list(raw: str, label: str) -> tuple[str, ...]:
    if not raw.strip():
        return ()
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(loaded, list):
        raise ValueError(f"{label} must be a JSON list.")
    values: list[str] = []
    for index, item in enumerate(loaded):
        text = str(item).strip()
        if not text or "\n" in text or "\r" in text:
            raise ValueError(f"{label}[{index}] must be a non-empty single-line string.")
        values.append(text)
    return tuple(values)


def matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def iter_source_files(
    source: Path,
    *,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> list[Path]:
    files: list[Path] = []
    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source).as_posix()
        if exclude and matches_any(relative, exclude):
            continue
        if include and not matches_any(relative, include):
            continue
        files.append(path)
    return files


def read_text_lossy(path: Path, max_chars: int) -> tuple[str, bool]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def truncate_lines(lines: list[str], max_chars: int) -> str:
    text = "\n".join(lines) + "\n"
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars] + f"\n\n[Forgis note: source context truncated after {max_chars} characters.]\n"


def build_tree_context(source: Path, files: list[Path], max_chars: int) -> str:
    lines = [
        "# Forgis Source Context",
        "",
        "Mode: tree",
        f"Source path: {source}",
        "",
        "## Files",
        "",
    ]
    lines.extend(f"- {path.relative_to(source).as_posix()}" for path in files)
    return truncate_lines(lines, max_chars)


def build_selected_files_context(source: Path, files: list[Path], max_chars: int) -> str:
    lines = [
        "# Forgis Source Context",
        "",
        "Mode: selected_files",
        f"Source path: {source}",
        "",
    ]
    remaining = max_chars
    for path in files:
        relative = path.relative_to(source).as_posix()
        size = path.stat().st_size
        digest = sha256_file(path)
        header = [
            "---",
            "",
            f"## File: {relative}",
            "",
            f"- Size bytes: {size}",
            f"- SHA256: {digest}",
            "",
            "```text",
        ]
        lines.extend(header)
        remaining = max(0, max_chars - len("\n".join(lines)))
        try:
            text, truncated = read_text_lossy(path, remaining)
        except Exception as exc:
            text = f"[Forgis warning: failed to read file: {exc}]"
            truncated = False
        lines.append(text)
        if truncated:
            lines.append(f"[Forgis note: file truncated by source_context.max_chars: {relative}]")
        lines.append("```")
        lines.append("")
        if max_chars > 0 and len("\n".join(lines)) >= max_chars:
            break
    return truncate_lines(lines, max_chars)


def build_none_context(source: Path) -> str:
    return "\n".join(
        [
            "# Forgis Source Context",
            "",
            "Mode: none",
            f"Source path: {source}",
            "",
            "No source files were copied into this context artifact.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build optional generic source context for Forgis")
    parser.add_argument("--source", required=True)
    parser.add_argument("--mode", choices=("none", "tree", "selected_files"), default="none")
    parser.add_argument("--max-chars", type=int, default=100_000)
    parser.add_argument("--include-json", default="[]")
    parser.add_argument("--exclude-json", default=json.dumps(list(DEFAULT_EXCLUDE)))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()
    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Source repository directory not found: {source}")
    if args.max_chars < 0:
        raise ValueError("--max-chars must not be negative.")

    include = parse_json_list(args.include_json, "--include-json")
    exclude = parse_json_list(args.exclude_json, "--exclude-json") or DEFAULT_EXCLUDE
    if args.mode == "selected_files" and not include:
        raise ValueError("--include-json is required for selected_files mode.")

    files = iter_source_files(source, include=include, exclude=exclude)
    if args.mode == "none":
        context = build_none_context(source)
    elif args.mode == "tree":
        context = build_tree_context(source, files, args.max_chars)
    else:
        context = build_selected_files_context(source, files, args.max_chars)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(context, encoding="utf-8")

    print("Forgis source context written:")
    print(f"  mode: {args.mode}")
    print(f"  source: {source}")
    print(f"  output: {output}")
    print(f"  matched files: {len(files)}")
    print(f"  character count: {len(context)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
