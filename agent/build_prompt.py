#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
from pathlib import Path


DEFAULT_MAX_SOURCE_BUNDLE_CHARS = 900_000


def read_text(path: Path) -> str:
    if not path.exists():
        return f"\n[Missing file: {path}]\n"
    return path.read_text(encoding="utf-8", errors="replace")


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

# Target Repository Tree

Target path: {target}

{target_tree_text}

---

# Required Output

Update the target repository according to the selected platform, stack, and migration profile.

Always create or update MIGRATION_REPORT.md.

If the migration cannot be completed safely, write the reason into MIGRATION_REPORT.md and stop.
"""

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")

    print(f"Forgis prompt written to: {output}")


if __name__ == "__main__":
    main()
