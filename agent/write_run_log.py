#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

from forgis_config import DEFAULT_RUN_LOG_FILENAME, parse_bool, require_path_inside_subdir


def append_run_log(
    *,
    target: Path,
    target_subdir: str,
    run_log_path: str,
    entry: str,
    preview_output: str | None,
    append_target_log: bool,
) -> Path:
    log_path, _ = require_path_inside_subdir(
        target,
        target_subdir,
        run_log_path,
        "run_log_path",
    )
    if append_target_log:
        log_path.parent.mkdir(parents=True, exist_ok=True)

        existing = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
        separator = "\n\n" if existing and not existing.endswith("\n\n") else ""
        log_path.write_text(existing + separator + entry, encoding="utf-8")

    if preview_output:
        preview_path = Path(preview_output).resolve()
        preview_path.parent.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(entry, encoding="utf-8")

    return log_path


def markdown_entry(args: argparse.Namespace, run_log_relative: str) -> str:
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    dry_run = parse_bool(args.dry_run, "dry_run")
    run_aider = parse_bool(args.run_aider, "run_aider")
    run_aider_config = parse_bool(args.run_aider_config, "run_aider_config")
    confirm_real_run = parse_bool(args.confirm_real_run, "confirm_real_run")
    run_mode = "dry-run" if dry_run else "live"
    real_migration_allowed = (not dry_run) and run_aider_config and confirm_real_run and run_aider

    if dry_run:
        pr_result = "Skipped because dry_run is true."
    elif not run_aider:
        pr_result = "Skipped because run_aider is false."
    else:
        pr_result = args.pr_result

    warnings: list[str] = []
    if dry_run and run_aider_config:
        warnings.append("dry_run=true, Aider execution is disabled.")
    if not dry_run and not confirm_real_run:
        warnings.append("Real AI migration requires confirm_real_run: true in FORGIS_CONFIG.yml.")
    if args.warning:
        warnings.append(args.warning)

    warnings_text = "\n".join(f"- {item}" for item in warnings) if warnings else "- None."
    read_only_files = [
        f"- Source repository: `{args.source_repo}` at `{args.source_ref}`",
        "- Entire source checkout",
        f"- Target repository outside `{args.target_subdir}/`",
        f"- Config file: `{args.config_path}`",
        f"- Task prompt file: `{args.task_prompt_path}`",
    ]

    return f"""## Forgis Run - {now}

| Field | Value |
|---|---|
| Run time | `{now}` |
| Run URL | `{args.run_url or '[not provided]'}` |
| Run mode | `{run_mode}` |
| dry_run config value | `{str(dry_run).lower()}` |
| run_aider config value | `{str(run_aider_config).lower()}` |
| confirm_real_run config value | `{str(confirm_real_run).lower()}` |
| Effective dry_run | `{str(dry_run).lower()}` |
| Effective run_aider | `{str(run_aider).lower()}` |
| Real migration allowed | `{str(real_migration_allowed).lower()}` |
| Source repo | `{args.source_repo}` |
| Source ref | `{args.source_ref}` |
| Target repo | `{args.target_repo}` |
| Target base branch | `{args.target_base_branch}` |
| Target branch | `{args.target_branch}` |
| Target platform | `{args.target_platform}` |
| Target stack | `{args.target_stack}` |
| Migration profile | `{args.migration_profile}` |
| Target subdir | `{args.target_subdir}` |
| Task prompt path | `{args.task_prompt_path}` |
| Config path | `{args.config_path}` |
| Model | `{args.model}` |
| Aider writable scope | `{args.target_subdir}/` |
| Run log path | `{run_log_relative}` |
| Build / check result | `{args.build_result}` |
| PR result | `{pr_result}` |

### Read-Only Files

{chr(10).join(read_only_files)}

### Summary

{args.summary}

### Warnings

{warnings_text}

### Next Steps

{args.next_steps}
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="Append a long-term Forgis markdown run log")
    parser.add_argument("--target", required=True)
    parser.add_argument("--source-repo", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--target-repo", required=True)
    parser.add_argument("--target-base-branch", required=True)
    parser.add_argument("--target-branch", required=True)
    parser.add_argument("--target-platform", required=True)
    parser.add_argument("--target-stack", required=True)
    parser.add_argument("--migration-profile", required=True)
    parser.add_argument("--target-subdir", required=True)
    parser.add_argument("--task-prompt-path", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-log-path", required=False, default="")
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--run-aider", required=True)
    parser.add_argument("--run-aider-config", required=True)
    parser.add_argument("--confirm-real-run", required=True)
    parser.add_argument("--append-target-log", default="false")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--build-result", default="See workflow logs.")
    parser.add_argument("--pr-result", default="Pending push and pull request step.")
    parser.add_argument("--summary", default="Forgis run completed its configured local steps.")
    parser.add_argument("--warning", default="")
    parser.add_argument("--next-steps", default="- Review generated changes and workflow logs.")
    parser.add_argument("--preview-output", default="")

    args = parser.parse_args()

    target = Path(args.target).resolve()
    run_log_input = args.run_log_path or f"{args.target_subdir.rstrip('/')}/{DEFAULT_RUN_LOG_FILENAME}"
    _, run_log_relative = require_path_inside_subdir(
        target,
        args.target_subdir,
        run_log_input,
        "run_log_path",
    )
    entry = markdown_entry(args, run_log_relative)
    dry_run = parse_bool(args.dry_run, "dry_run")
    append_target_log = parse_bool(args.append_target_log, "append_target_log") and not dry_run
    log_path = append_run_log(
        target=target,
        target_subdir=args.target_subdir,
        run_log_path=run_log_input,
        entry=entry,
        preview_output=args.preview_output or None,
        append_target_log=append_target_log,
    )

    print("Forgis long-term run log entry:")
    print(entry)
    if append_target_log:
        print(f"Long-term run log appended to: {log_path}")
    else:
        print(f"Long-term run log preview only; target repository was not modified: {log_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
