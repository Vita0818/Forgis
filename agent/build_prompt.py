#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path


DEFAULT_MAX_SOURCE_BUNDLE_CHARS = 900_000
DEFAULT_TARGET_SUBDIR = "forgis-output"
GREETING_EXAMPLE = "make the greeting more casual"


def read_text(path: Path) -> str:
    if not path.exists():
        return f"\n[Missing file: {path}]\n"
    return path.read_text(encoding="utf-8", errors="replace")


def resolve_inside_root(root: Path, relative_path: str, label: str, allow_root: bool = False) -> tuple[Path, str]:
    if not relative_path or not relative_path.strip():
        raise ValueError(f"{label} is required.")

    raw = Path(relative_path.strip())
    if raw.is_absolute():
        raise ValueError(f"{label} must be relative to the target repository root: {relative_path}")

    if any(part in {"", ".", "..", ".git"} for part in raw.parts):
        raise ValueError(f"{label} contains an unsafe path segment: {relative_path}")

    resolved = (root / raw).resolve()
    root_resolved = root.resolve()

    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"{label} escapes the target repository root: {relative_path}")

    if resolved == root_resolved and not allow_root:
        raise ValueError(f"{label} must not resolve to the target repository root.")

    resolved_relative = resolved.relative_to(root_resolved).as_posix()
    return resolved, resolved_relative


def read_target_prompt(path: Path) -> str:
    if not path.is_file():
        return "[No target repository task prompt provided.]"

    return path.read_text(encoding="utf-8", errors="replace")


def print_preview(label: str, text: str, max_lines: int = 10) -> None:
    print(f"{label}:")

    lines = text.splitlines()
    if not lines:
        print("  [empty]")
        return

    for line in lines[:max_lines]:
        print(f"  {line[:240]}")

    if len(lines) > max_lines:
        print(f"  ... [{len(lines) - max_lines} more lines]")


def read_text_limited(path: Path, max_chars: int) -> str:
    text = read_text(path)

    if max_chars <= 0 or len(text) <= max_chars:
        return text

    return (
        text[:max_chars]
        + "\n\n"
        + f"[Forgis note: source bundle truncated after {max_chars} characters "
        + "to keep the model prompt bounded. The complete file list, sizes, "
        + "and hashes are preserved in the full source manifest below.]\n"
    )


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

    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target output repository")
    parser.add_argument("--rules", required=True, help="Path to Forgis rules directory")
    parser.add_argument("--prompts", required=True, help="Path to Forgis prompts directory")
    parser.add_argument("--platform", required=True, help="Target platform")
    parser.add_argument("--target-stack", required=True, help="Target technical stack")
    parser.add_argument("--migration-profile", required=True, help="Migration profile name")
    parser.add_argument("--source-bundle", required=False, help="Optional source bundle markdown file")
    parser.add_argument("--source-manifest", required=False, help="Optional source manifest markdown file")
    parser.add_argument("--task-prompt-path", required=False, help="Task prompt path relative to the target repository root")
    parser.add_argument("--target-prompt-file", required=False, help="Deprecated alias for --task-prompt-path")
    parser.add_argument(
        "--require-task-prompt",
        action="store_true",
        help="Fail if the target repository task prompt is missing or empty.",
    )
    parser.add_argument(
        "--target-subdir",
        required=False,
        default=DEFAULT_TARGET_SUBDIR,
        help="Target output directory relative to the target repository root.",
    )
    parser.add_argument(
        "--max-source-bundle-chars",
        required=False,
        type=int,
        default=DEFAULT_MAX_SOURCE_BUNDLE_CHARS,
        help="Maximum source bundle characters to embed in the prompt. Use 0 for no limit.",
    )
    parser.add_argument("--output", required=True, help="Path to the generated prompt file")

    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    rules = Path(args.rules).resolve()
    prompts = Path(args.prompts).resolve()
    output = Path(args.output).resolve()

    source_tree = collect_tree(source)
    target_tree = collect_tree(target)

    source_tree_text = "\n".join(f"- {item}" for item in source_tree) or "- No source files found."
    target_tree_text = "\n".join(f"- {item}" for item in target_tree) or "- No target files found."

    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    source_bundle_text = ""
    if args.source_bundle:
        source_bundle_path = Path(args.source_bundle).resolve()
        source_bundle_text = read_text_limited(source_bundle_path, args.max_source_bundle_chars)

    source_manifest_text = ""
    if args.source_manifest:
        source_manifest_path = Path(args.source_manifest).resolve()
        source_manifest_text = read_text(source_manifest_path)

    task_prompt_input = args.task_prompt_path or args.target_prompt_file
    target_prompt_text = "[No target repository task prompt provided.]"
    target_prompt_path: Path | None = None
    target_prompt_relative = "[not provided]"
    target_prompt_found = False

    if task_prompt_input:
        target_prompt_path, target_prompt_relative = resolve_inside_root(
            target,
            task_prompt_input,
            "Task prompt path",
        )
        target_prompt_found = target_prompt_path.is_file()
        target_prompt_text = read_target_prompt(target_prompt_path)
    elif args.require_task_prompt:
        raise ValueError("Task prompt path is required.")

    target_subdir_path, target_subdir_relative = resolve_inside_root(
        target,
        args.target_subdir,
        "Target output directory",
    )

    print("Forgis migration prompt inputs:")
    print(f"  source path: {source}")
    print(f"  target path: {target}")
    print(f"  target platform: {args.platform}")
    print(f"  target stack: {args.target_stack}")
    print(f"  migration profile: {args.migration_profile}")
    print(f"  task_prompt_path input: {task_prompt_input if task_prompt_input else '[not provided]'}")
    print(f"  task prompt resolved relative path: {target_prompt_relative}")
    print(f"  task prompt resolved absolute path: {target_prompt_path if target_prompt_path else '[not provided]'}")
    print(f"  task prompt found: {'yes' if target_prompt_found else 'no'}")
    print(f"  task prompt character count: {len(target_prompt_text)}")
    print_preview("  task prompt preview", target_prompt_text, max_lines=10)
    print(f"  target writable scope relative path: {target_subdir_relative}")
    print(f"  target writable scope absolute path: {target_subdir_path}")

    if args.require_task_prompt and not target_prompt_found:
        raise FileNotFoundError(f"Target repository task prompt does not exist: {target_prompt_path}")

    if args.require_task_prompt and not target_prompt_text.strip():
        raise ValueError(f"Target repository task prompt is empty: {target_prompt_path}")

    if GREETING_EXAMPLE in target_prompt_text.casefold():
        raise ValueError("Target repository task prompt contains the forbidden greeting example prompt.")

    content = f"""# Forgis Generated Migration Task

Generated at: {now}

You are running inside Forgis, a generic cloud-based migration system.

## Current task

Target platform: {args.platform}
Target stack: {args.target_stack}
Migration profile: {args.migration_profile}

Read the source repository information below and update only the target repository.

Do not modify the source repository.

---

# Project Boundary

{read_text(rules / "PROJECT_BOUNDARY.md")}

---

# Agent Instructions

{read_text(rules / "AGENTS.md")}

---

# Translation Strategy

{read_text(rules / "TRANSLATION_STRATEGY.md")}

---

# Generic Migration Prompt

{read_text(prompts / "migrate_generic.md")}

---

# Platform Prompt

{read_text(prompts / "platforms" / f"{args.platform}.md")}

---

# Target Stack Rules

{read_text(rules / "stacks" / f"{args.target_stack}.md")}

---

# Migration Profile

{read_text(rules / "profiles" / f"{args.migration_profile}.md")}

---

# Source Repository Tree

Source path: {source}

{source_tree_text}

---

# Source Bundle

{source_bundle_text if source_bundle_text else "[No source bundle provided.]"}

---

# Source Manifest

{source_manifest_text if source_manifest_text else "[No source manifest provided.]"}

---

# Source Freshness Requirement

The source repository has been freshly checked out and scanned for this run.

Use the current source repository tree, source manifest, and source bundle as the source of truth.

Do not rely on stale target repository code as a substitute for the current source repository.

If the target repository contains older generated code, update it according to the current source state.

---

# Target Repository Task Prompt

This section is loaded from the target repository root.

Default file: FORGIS_TASK.md

Loaded file: {target_prompt_relative}

It is the human instruction for the current Forgis run.

It defines the concrete migration task for this run.

It must be followed unless it conflicts with:
- project boundary rules
- source repository read-only rules
- target repository write restrictions
- secret-safety rules
- GitHub token permission boundaries

{target_prompt_text}

---

# Target Writable Scope

Target output directory relative to target repository root: {target_subdir_relative}

Write generated or modified project files only under this target output directory.

Do not edit the task prompt file `{target_prompt_relative}`.

Do not scatter target project files into the target repository root.

`MIGRATION_REPORT.md` may be updated at the target repository root for run reporting.

---

# Target Repository Tree

Target path: {target}

{target_tree_text}

---

# Required Output

Update the target repository according to the selected platform, stack, and migration profile.

Always create or update MIGRATION_REPORT.md.

If the migration cannot be completed safely, write the reason into MIGRATION_REPORT.md and stop.
"""

    if GREETING_EXAMPLE in target_prompt_text.casefold():
        raise ValueError("Final prompt would contain the forbidden greeting example as the task prompt.")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")

    print(f"Forgis prompt written to: {output}")
    print(f"Final prompt character count: {len(content)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
