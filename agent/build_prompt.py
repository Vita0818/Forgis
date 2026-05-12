#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
from pathlib import Path


def read_text(path: Path) -> str:
    if not path.exists():
        return f"\n[Missing file: {path}]\n"
    return path.read_text(encoding="utf-8", errors="replace")


def collect_tree(root: Path, max_files: int = 200) -> list[str]:
    ignored_dirs = {
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
    }

    files: list[str] = []

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)

        if any(part in ignored_dirs for part in relative.parts):
            continue

        if path.is_file():
            files.append(str(relative))

        if len(files) >= max_files:
            break

    return files


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Forgis migration prompt")

    parser.add_argument("--source", required=True, help="Path to the checked-out Apple source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target output repository")
    parser.add_argument("--rules", required=True, help="Path to Forgis rules directory")
    parser.add_argument("--prompts", required=True, help="Path to Forgis prompts directory")
    parser.add_argument("--platform", required=True, choices=["android", "windows"], help="Target platform")
    parser.add_argument("--output", required=True, help="Path to the generated prompt file")

    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    rules = Path(args.rules).resolve()
    prompts = Path(args.prompts).resolve()
    output = Path(args.output).resolve()

    platform_prompt_name = f"migrate_{args.platform}.md"

    source_tree = collect_tree(source)
    target_tree = collect_tree(target)

    source_tree_text = "\n".join(f"- {item}" for item in source_tree) or "- No source files found."
    target_tree_text = "\n".join(f"- {item}" for item in target_tree) or "- No target files found."

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    content = f"""# Forgis Generated Migration Task

Generated at: {now}

You are running inside Forgis, a cloud-based migration system.

## Current task

Target platform: {args.platform}

Read the Apple source repository information below and update only the target repository.

Do not modify the Apple source repository.

---

# Project Boundary

{read_text(rules / "PROJECT_BOUNDARY.md")}

---

# Agent Instructions

{read_text(rules / "AGENTS.md")}

---

# Platform Migration Prompt

{read_text(prompts / platform_prompt_name)}

---

# Apple Source Repository Tree

Source path: {source}

{source_tree_text}

---

# Target Repository Tree

Target path: {target}

{target_tree_text}

---

# Required Output

Update the target repository according to the platform migration prompt.

Always create or update MIGRATION_REPORT.md.

If the migration cannot be completed safely, write the reason into MIGRATION_REPORT.md and stop.
"""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")

    print(f"Forgis prompt written to: {output}")


if __name__ == "__main__":
    main()
