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


def build_summary(
    *,
    source: Path,
    target: Path,
    source_repo: str,
    source_ref: str,
    target_repo: str,
    target_branch: str,
    target_base_branch: str,
    task_prompt_path: str,
    target_subdir: str,
    config_path: str,
    run_log_path: str,
    agent_backend: str,
    model: str,
    dry_run: bool,
    run_agent: bool,
    confirm_real_run: bool,
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
- Config path: {config_path}
- Task prompt path: {task_prompt_path}
- Target writable directory: {target_subdir}
- Run log path: {run_log_path}
- Agent backend: {agent_backend}
- Model: {model}
- Dry run: {dry_run}
- Run agent: {run_agent}
- Confirm real run: {confirm_real_run}

## Safety Boundaries

- Source repository: read-only.
- Target repository writable scope: `{target_subdir}/`.
- Target repository outside `{target_subdir}/`: read-only.
- Config and task files: read-only.
- Long-term run log: `{run_log_path}`.

## Status

Forgis controller checks completed successfully.

This summary was generated before any optional agent step.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Forgis controller")

    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target repository")
    parser.add_argument("--source-repo", required=False, default="")
    parser.add_argument("--source-ref", required=False, default="")
    parser.add_argument("--target-repo", required=False, default="")
    parser.add_argument("--target-branch", required=True, help="Target output branch")
    parser.add_argument("--target-base-branch", required=False, default="main")
    parser.add_argument("--config-path", required=False, default="FORGIS_CONFIG.yml")
    parser.add_argument("--task-prompt-path", required=False, default="FORGIS_TASK.md")
    parser.add_argument("--target-subdir", required=False, default="target-output")
    parser.add_argument("--run-log-path", required=False, default="")
    parser.add_argument("--agent-backend", required=False, default="aider")
    parser.add_argument("--model", required=False, default="provider/model-name")
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--run-agent", required=True)
    parser.add_argument("--confirm-real-run", required=False, default="false")
    parser.add_argument("--summary-output", required=False, default="")

    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()

    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")

    dry_run = parse_bool(args.dry_run, "dry_run")
    run_agent = parse_bool(args.run_agent, "run_agent")
    confirm_real_run = parse_bool(args.confirm_real_run, "confirm_real_run")

    if args.agent_backend != "aider":
        raise ValueError("Only agent_backend=aider is currently supported.")

    if not dry_run and not confirm_real_run:
        raise ValueError("Real Forgis runs require confirm_real_run: true.")

    run_log_path = args.run_log_path.strip() or f"{args.target_subdir.rstrip('/')}/{DEFAULT_RUN_LOG_FILENAME}"
    _, run_log_relative = require_path_inside_subdir(
        target,
        args.target_subdir,
        run_log_path,
        "run_log_path",
    )

    summary = build_summary(
        source=source,
        target=target,
        source_repo=args.source_repo or "[not provided]",
        source_ref=args.source_ref or "[not provided]",
        target_repo=args.target_repo or "[not provided]",
        target_branch=args.target_branch,
        target_base_branch=args.target_base_branch,
        task_prompt_path=args.task_prompt_path,
        target_subdir=args.target_subdir,
        config_path=args.config_path,
        run_log_path=run_log_relative,
        agent_backend=args.agent_backend,
        model=args.model,
        dry_run=dry_run,
        run_agent=run_agent,
        confirm_real_run=confirm_real_run,
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
