#!/usr/bin/env python3

from __future__ import annotations

import argparse
from pathlib import Path


TEXT_EXTENSIONS = {
    ".swift",
    ".h",
    ".m",
    ".mm",
    ".cpp",
    ".c",
    ".hpp",
    ".kt",
    ".kts",
    ".java",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".xml",
    ".plist",
    ".gradle",
    ".toml",
    ".properties",
}

IMPORTANT_FILENAMES = {
    "Package.swift",
    "project.pbxproj",
    "Podfile",
    "Cartfile",
    "Info.plist",
    "README.md",
    "README",
}


def should_ignore(path: Path) -> bool:
    ignored_parts = {
        ".git",
        ".github",
        ".build",
        "build",
        "DerivedData",
        "node_modules",
        ".gradle",
        ".idea",
        ".vscode",
        "__pycache__",
        "xcuserdata",
    }
    return any(part in ignored_parts for part in path.parts)


def is_collectable(path: Path) -> bool:
    return path.suffix in TEXT_EXTENSIONS or path.name in IMPORTANT_FILENAMES


def read_limited(path: Path, max_chars: int) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[Forgis note: file truncated for prompt size control.]\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect source repository content into a bounded markdown bundle")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-files", type=int, default=80)
    parser.add_argument("--max-chars-per-file", type=int, default=12000)
    args = parser.parse_args()

    source = Path(args.source).resolve()
    output = Path(args.output).resolve()

    if not source.exists() or not source.is_dir():
        raise FileNotFoundError(f"Source repository directory not found: {source}")

    files: list[Path] = []

    for path in sorted(source.rglob("*")):
        if not path.is_file():
            continue

        relative = path.relative_to(source)

        if should_ignore(relative):
            continue

        if not is_collectable(path):
            continue

        files.append(path)

        if len(files) >= args.max_files:
            break

    lines: list[str] = []
    lines.append("# Forgis Source Bundle")
    lines.append("")
    lines.append(f"Source path: `{source}`")
    lines.append("")
    lines.append("This bundle contains selected source repository files for migration context.")
    lines.append("")

    for path in files:
        relative = path.relative_to(source)
        lines.append("---")
        lines.append("")
        lines.append(f"## File: `{relative}`")
        lines.append("")
        lines.append("```text")
        try:
            lines.append(read_limited(path, args.max_chars_per_file))
        except Exception as exc:
            lines.append(f"[Forgis warning: failed to read file: {exc}]")
        lines.append("```")
        lines.append("")

    if not files:
        lines.append("[Forgis warning: no collectable source files found.]")
        lines.append("")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")
    print(f"Forgis source bundle written to: {output}")
    print(f"Collected files: {len(files)}")


if __name__ == "__main__":
    main()
