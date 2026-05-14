#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from forgis_config import DEFAULT_RUN_LOG_FILENAME, parse_bool, require_path_inside_subdir


def ensure_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")


def collect_basic_tree(root: Path, max_files: int = 120) -> list[str]:
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

    results: list[str] = []

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)

        if any(part in ignored_dirs for part in relative.parts):
            continue

        if path.is_file():
            results.append(str(relative))

        if len(results) >= max_files:
            break

    return results


def format_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- No source files were collected."


def build_summary(
    *,
    source: Path,
    target: Path,
    rules: Path,
    source_repo: str,
    source_ref: str,
    target_repo: str,
    platform: str,
    target_stack: str,
    migration_profile: str,
    target_branch: str,
    target_base_branch: str,
    task_prompt_path: str,
    target_subdir: str,
    config_path: str,
    run_log_path: str,
    model: str,
    dry_run: bool,
    run_aider: bool,
    source_files: list[str],
) -> str:
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

    return f"""# Forgis Run Summary

Generated at: {now}

## Configuration

- Source repository: {source_repo}
- Source ref: {source_ref}
- Source repository path: {source}
- Target repository: {target_repo}
- Target repository path: {target}
- Target base branch: {target_base_branch}
- Target branch: {target_branch}
- Rules path: {rules}
- Target platform: {platform}
- Target stack: {target_stack}
- Migration profile: {migration_profile}
- Config path: {config_path}
- Task prompt path: {task_prompt_path}
- Target output directory: {target_subdir}
- Run log path: {run_log_path}
- Aider model: {model}
- Dry run: {dry_run}
- Run Aider: {run_aider}

## Safety Boundaries

- Source repository: read-only.
- Target repository writable scope: `{target_subdir}/`.
- Target repository outside `{target_subdir}/`: read-only.
- Config and task prompt files: read-only input context.
- Long-term run log: `{run_log_path}`.

## Status

Forgis controller checks completed successfully.

This summary was generated before any optional AI migration step.

## Source repository sample

{format_list(source_files)}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Forgis migration controller")

    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target output repository")
    parser.add_argument("--rules", required=True, help="Path to the Forgis rules directory")
    parser.add_argument("--source-repo", required=False, default="")
    parser.add_argument("--source-ref", required=False, default="")
    parser.add_argument("--target-repo", required=False, default="")
    parser.add_argument("--platform", required=True, help="Target platform")
    parser.add_argument("--target-stack", required=True, help="Target technical stack")
    parser.add_argument("--migration-profile", required=True, help="Migration profile name")
    parser.add_argument("--target-branch", required=True, help="Target migration branch")
    parser.add_argument("--target-base-branch", required=False, default="main")
    parser.add_argument("--config-path", required=False, default="FORGIS_CONFIG.yml")
    parser.add_argument("--task-prompt-path", required=False, default="FORGIS_TASK.md")
    parser.add_argument("--target-subdir", required=False, default="forgis-output")
    parser.add_argument("--run-log-path", required=False, default="")
    parser.add_argument("--model", required=False, default="deepseek/deepseek-v4-pro")
    parser.add_argument("--dry-run", required=True, help="Whether to avoid pushing changes")
    parser.add_argument("--run-ai", required=True, help="Whether Aider migration is enabled")
    parser.add_argument("--summary-output", required=False, default="", help="Optional run summary artifact path")

    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    rules = Path(args.rules).resolve()

    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")
    ensure_directory(rules, "Rules directory")

    dry_run = parse_bool(args.dry_run, "dry_run")
    run_ai = parse_bool(args.run_ai, "run_ai")

    run_log_path = args.run_log_path.strip() or f"{args.target_subdir.rstrip('/')}/{DEFAULT_RUN_LOG_FILENAME}"
    _, run_log_relative = require_path_inside_subdir(
        target,
        args.target_subdir,
        run_log_path,
        "run_log_path",
    )

    source_files = collect_basic_tree(source)
    summary = build_summary(
        source=source,
        target=target,
        rules=rules,
        source_repo=args.source_repo or "[not provided]",
        source_ref=args.source_ref or "[not provided]",
        target_repo=args.target_repo or "[not provided]",
        platform=args.platform,
        target_stack=args.target_stack,
        migration_profile=args.migration_profile,
        target_branch=args.target_branch,
        target_base_branch=args.target_base_branch,
        task_prompt_path=args.task_prompt_path,
        target_subdir=args.target_subdir,
        config_path=args.config_path,
        run_log_path=run_log_relative,
        model=args.model,
        dry_run=dry_run,
        run_aider=run_ai,
        source_files=source_files,
    )

    if args.summary_output:
        summary_output = Path(args.summary_output).resolve()
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(summary, encoding="utf-8")
        print(f"Forgis run summary written to: {summary_output}")

    print("Forgis controller checks completed.")
    print(f"Target writable scope: {args.target_subdir}")
    print(f"Long-term run log path: {run_log_relative}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
