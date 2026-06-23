#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from forgis_config import ResolvedConfig, resolve_config


def ensure_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")


def build_summary(
    *,
    source: Path,
    target: Path,
    config: ResolvedConfig,
) -> str:
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    agent_status = "enabled" if config.run_agent else "disabled"
    if config.dry_run:
        agent_status = "disabled by dry_run"

    return f"""# Forgis Run Summary

Generated at: {now}

## Configuration

- Source repository: {config.source_repo}
- Source ref: {config.source_ref}
- Source repository path: {source}
- Target repository: {config.target_repo}
- Target repository path: {target}
- Target base branch: {config.target_base_branch}
- Target branch: {config.target_branch}
- Config path: {config.config_path}
- Task prompt path: {config.task_prompt_path}
- Target writable directory: {config.target_subdir}
- Run log path: {config.run_log_path}
- Agent backend: {config.agent_backend}
- Model: {config.model}
- Request timeout seconds: {config.request_timeout_seconds}
- Execution mode: {config.execution_mode}
- Dry run: {config.dry_run}
- Run agent: {config.run_agent}
- Confirm real run: {config.confirm_real_run}
- Max iterations: {config.max_iterations}
- Max tool result chars: {config.max_tool_result_chars}

## Safety Boundaries

- Source repository: read-only.
- Target repository writable scope: `{config.target_subdir}/`.
- Target repository outside `{config.target_subdir}/`: read-only.
- Config and task files: read-only.
- Long-term run log: `{config.run_log_path}`.

## Status

Forgis controller checks completed successfully.

DeepSeek tool loop is {agent_status}.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Forgis controller")
    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target repository")
    parser.add_argument("--target-repo", required=True, help="Target repository, for example owner/target-repo")
    parser.add_argument("--config", default="", help="Optional config file path; defaults to target/FORGIS_CONFIG.yml")
    parser.add_argument("--summary-output", required=False, default="")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()

    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")
    config = resolve_config(target_root=target, target_repo=args.target_repo, config_path=args.config)

    summary = build_summary(source=source, target=target, config=config)
    if args.summary_output:
        summary_output = Path(args.summary_output).resolve()
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(summary, encoding="utf-8")
        print(f"Forgis run summary written to: {summary_output}")

    print("Forgis controller checks completed.")
    print(f"Agent backend: {config.agent_backend}")
    print(f"Target writable scope: {config.target_subdir}/")
    print(f"Long-term run log path: {config.run_log_path}")
    if config.dry_run:
        print("dry_run=true; model calls, target writes, push, and PR are disabled.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
