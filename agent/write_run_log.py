#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from forgis_config import DEFAULT_RUN_LOG_FILENAME, parse_bool, require_path_inside_subdir


def git_changed_paths(target: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=target,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) >= 4:
            paths.append(line[3:])
    return sorted(paths)


def json_count(raw: str) -> int:
    if not raw.strip():
        return 0
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return 0
    return len(loaded) if isinstance(loaded, list) else 0


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


def markdown_entry(args: argparse.Namespace, run_log_relative: str, changed_paths: list[str]) -> str:
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    dry_run = parse_bool(args.dry_run, "dry_run")
    run_agent = parse_bool(args.run_agent, "run_agent")
    run_agent_config = parse_bool(args.run_agent_config, "run_agent_config")
    confirm_real_run = parse_bool(args.confirm_real_run, "confirm_real_run")
    aider_executed = parse_bool(args.aider_executed, "aider_executed")
    run_mode = "dry-run" if dry_run else "live"

    if dry_run:
        pr_result = "Skipped because dry_run is true."
    elif not run_agent:
        pr_result = "Skipped because run_agent is false."
    else:
        pr_result = args.pr_result

    warnings: list[str] = []
    if dry_run and run_agent_config:
        warnings.append("dry_run=true, agent execution is disabled.")
    if not dry_run and not confirm_real_run:
        warnings.append("Real Forgis runs require confirm_real_run: true in FORGIS_CONFIG.yml.")
    if args.warning:
        warnings.append(args.warning)

    warnings_text = "\n".join(f"- {item}" for item in warnings) if warnings else "- None."
    changed_text = "\n".join(f"- `{path}`" for path in changed_paths[:80]) if changed_paths else "- None."
    if len(changed_paths) > 80:
        changed_text += f"\n- ... [{len(changed_paths) - 80} more paths]"

    return f"""## Forgis Run - {now}

| Field | Value |
|---|---|
| Run id | `{args.run_id or '[not provided]'}` |
| Run time | `{now}` |
| Run URL | `{args.run_url or '[not provided]'}` |
| Run mode | `{run_mode}` |
| Target repo | `{args.target_repo}` |
| Source repo | `{args.source_repo}` |
| Source ref | `{args.source_ref}` |
| Target base branch | `{args.target_base_branch}` |
| Target branch | `{args.target_branch}` |
| Target subdir | `{args.target_subdir}` |
| Task file path | `{args.task_prompt_path}` |
| Config path | `{args.config_path}` |
| Agent backend | `{args.agent_backend}` |
| Model | `{args.model}` |
| dry_run config value | `{str(dry_run).lower()}` |
| run_agent config value | `{str(run_agent_config).lower()}` |
| confirm_real_run config value | `{str(confirm_real_run).lower()}` |
| Effective run_agent | `{str(run_agent).lower()}` |
| Aider executed | `{str(aider_executed).lower()}` |
| Aider exit status | `{args.aider_exit_status}` |
| Guardrail result | `{args.guardrail_result}` |
| validation_commands | `{json_count(args.validation_commands_json)} configured` |
| success_checks | `{json_count(args.success_checks_json)} configured` |
| Run log path | `{run_log_relative}` |
| Validation result | `{args.validation_result}` |
| PR result | `{pr_result}` |

### Changed Paths

{changed_text}

### Read-Only Inputs

- Source repository checkout
- Target repository outside `{args.target_subdir}/`
- Config file: `{args.config_path}`
- Task file: `{args.task_prompt_path}`

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
    parser.add_argument("--target-subdir", required=True)
    parser.add_argument("--task-prompt-path", required=True)
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--agent-backend", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-log-path", required=False, default="")
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--run-agent", required=True)
    parser.add_argument("--run-agent-config", required=True)
    parser.add_argument("--confirm-real-run", required=True)
    parser.add_argument("--aider-executed", default="false")
    parser.add_argument("--aider-exit-status", default="not-run")
    parser.add_argument("--guardrail-result", default="See workflow logs.")
    parser.add_argument("--validation-commands-json", default="[]")
    parser.add_argument("--success-checks-json", default="[]")
    parser.add_argument("--append-target-log", default="false")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--validation-result", default="See workflow logs.")
    parser.add_argument("--pr-result", default="Pending push and pull request step.")
    parser.add_argument("--summary", default="Forgis resolved config, built the Aider message, and ran the enabled steps.")
    parser.add_argument("--warning", default="")
    parser.add_argument("--next-steps", default="- Review workflow logs and changes inside target_subdir.")
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
    changed_paths = git_changed_paths(target)
    entry = markdown_entry(args, run_log_relative, changed_paths)
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
