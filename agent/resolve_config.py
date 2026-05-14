#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forgis_config import markdown_summary, resolve_config


def write_key_values(path: str | None, values: dict[str, str]) -> None:
    if not path:
        return

    output = Path(path)
    with output.open("a", encoding="utf-8") as file:
        for key, value in values.items():
            if "\n" in value or "\r" in value:
                raise ValueError(f"Cannot write multi-line value for {key}")
            file.write(f"{key}={value}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve Forgis workflow inputs and target repository config")
    parser.add_argument("--target", required=True, help="Path to the checked-out target repository")
    parser.add_argument("--target-repo", required=True, help="Target repository, for example owner/repo")
    parser.add_argument("--config-path", default="FORGIS_CONFIG.yml", help="Config path relative to target root")

    parser.add_argument("--source-repo", default="")
    parser.add_argument("--source-ref", default="")
    parser.add_argument("--target-platform", default="")
    parser.add_argument("--target-stack", default="")
    parser.add_argument("--migration-profile", default="")
    parser.add_argument("--target-subdir", default="")
    parser.add_argument("--task-prompt-path", default="")
    parser.add_argument("--target-prompt-file", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--aider-model", default="")
    parser.add_argument("--target-branch", default="")
    parser.add_argument("--target-base-branch", default="")
    parser.add_argument("--base-branch", default="")
    parser.add_argument("--run-log-path", default="")
    parser.add_argument("--dry-run", required=True)
    parser.add_argument("--run-aider", required=True)

    parser.add_argument("--github-env", default="", help="Optional $GITHUB_ENV path to append resolved env vars")
    parser.add_argument("--github-output", default="", help="Optional $GITHUB_OUTPUT path to append resolved outputs")
    parser.add_argument("--summary-output", default="", help="Optional markdown summary output path")

    args = parser.parse_args()

    explicit_inputs = {
        "source_repo": args.source_repo,
        "source_ref": args.source_ref,
        "target_platform": args.target_platform,
        "target_stack": args.target_stack,
        "migration_profile": args.migration_profile,
        "target_subdir": args.target_subdir,
        "task_prompt_path": args.task_prompt_path or args.target_prompt_file,
        "model": args.model or args.aider_model,
        "target_branch": args.target_branch,
        "target_base_branch": args.target_base_branch or args.base_branch,
        "run_log_path": args.run_log_path,
    }

    resolved = resolve_config(
        target_root=Path(args.target),
        target_repo=args.target_repo,
        config_path=args.config_path,
        explicit_inputs=explicit_inputs,
        dry_run=args.dry_run,
        run_aider=args.run_aider,
    )

    summary = markdown_summary(resolved)
    print(summary)

    if args.summary_output:
        summary_output = Path(args.summary_output)
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(summary + "\n", encoding="utf-8")

    write_key_values(args.github_env, resolved.env())
    write_key_values(args.github_output, resolved.outputs())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
