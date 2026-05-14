#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from forgis_config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_RUN_LOG_FILENAME,
    DEFAULT_TASK_PROMPT_PATH,
    DEFAULT_TARGET_SUBDIR,
    require_path_inside_subdir,
    resolve_inside_root,
    resolve_target_subdir,
)


def ensure_directory(path: Path, label: str) -> None:
    if not path.exists():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.is_dir():
        raise NotADirectoryError(f"{label} is not a directory: {path}")


def ensure_task_file(path: Path, label: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(f"{label} does not exist: {path}")
    if not path.read_text(encoding="utf-8", errors="replace").strip():
        raise ValueError(f"{label} is empty: {path}")


def build_message(
    *,
    source: Path,
    target: Path,
    target_subdir_path: Path,
    task_prompt_path: Path,
    config_path: Path,
    run_log_path: Path,
    source_context_path: Path | None,
) -> str:
    lines = [
        "You are running through Forgis.",
        f"Source repository path: {source}",
        f"Target repository path: {target}",
        f"Writable target path: {target_subdir_path}",
        f"Task file path: {task_prompt_path}",
    ]
    if source_context_path is not None:
        lines.append(f"Optional source context file path: {source_context_path}")

    lines.extend(
        [
            "",
            "Read the task file.",
            "Read the source repository as needed.",
            "Create or modify files only under the writable target path.",
            "Do not modify the source repository.",
            "Do not modify the target repository outside the writable target path.",
            f"Do not modify {config_path}.",
            f"Do not modify {task_prompt_path}.",
            f"Do not modify {run_log_path} unless the task file explicitly asks for run-log content.",
            "Do not request that the user specify files again unless the task file itself asks for that.",
            "If the writable target path is empty, create the needed files there according to the task file.",
            "If the writable target path already contains files, modify them according to the task file.",
            "That is all.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the thin Forgis Aider message")
    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target repository")
    parser.add_argument("--source-repo", default="", help="Resolved source repository name, for diagnostics only")
    parser.add_argument("--source-ref", default="", help="Resolved source ref, for diagnostics only")
    parser.add_argument("--target-repo", default="", help="Resolved target repository name, for diagnostics only")
    parser.add_argument("--config-path", default=DEFAULT_CONFIG_PATH)
    parser.add_argument("--task-prompt-path", default=DEFAULT_TASK_PROMPT_PATH)
    parser.add_argument("--target-subdir", default=DEFAULT_TARGET_SUBDIR)
    parser.add_argument("--run-log-path", default="")
    parser.add_argument("--source-context-file", default="")
    parser.add_argument("--require-task-prompt", action="store_true")
    parser.add_argument("--output", required=True)

    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    output = Path(args.output).resolve()
    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")

    config_path, config_relative = resolve_inside_root(target, args.config_path, "config_path")
    task_prompt_path, task_prompt_relative = resolve_inside_root(
        target,
        args.task_prompt_path,
        "task_prompt_path",
    )
    target_subdir_path, target_subdir_relative = resolve_target_subdir(target, args.target_subdir)
    run_log_input = args.run_log_path or f"{target_subdir_relative}/{DEFAULT_RUN_LOG_FILENAME}"
    run_log_path, run_log_relative = require_path_inside_subdir(
        target,
        target_subdir_relative,
        run_log_input,
        "run_log_path",
    )

    if args.require_task_prompt:
        ensure_task_file(task_prompt_path, "Task file")

    source_context_path: Path | None = None
    if args.source_context_file:
        candidate = Path(args.source_context_file).resolve()
        if not candidate.is_file():
            raise FileNotFoundError(f"source_context file does not exist: {candidate}")
        source_context_path = candidate

    target_subdir_path.mkdir(parents=True, exist_ok=True)
    message = build_message(
        source=source,
        target=target,
        target_subdir_path=target_subdir_path,
        task_prompt_path=task_prompt_path,
        config_path=config_path,
        run_log_path=run_log_path,
        source_context_path=source_context_path,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(message, encoding="utf-8")

    print("Forgis Aider message inputs:")
    print(f"  source repository: {args.source_repo or '[not provided]'}")
    print(f"  source ref: {args.source_ref or '[not provided]'}")
    print(f"  target repository: {args.target_repo or '[not provided]'}")
    print(f"  source path: {source}")
    print(f"  target path: {target}")
    print(f"  writable target path: {target_subdir_path}")
    print(f"  config path: {config_relative}")
    print(f"  task file path: {task_prompt_relative}")
    print(f"  run log path: {run_log_relative}")
    print(f"  source context file: {source_context_path if source_context_path else '[none]'}")
    print(f"Forgis Aider message written to: {output}")
    print(f"Message character count: {len(message)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
