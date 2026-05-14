#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from forgis_config import require_path_inside_subdir, resolve_inside_root, resolve_target_subdir


IGNORED_CHANGE_PREFIXES = (
    ".aider",
    ".forgis-aider-runtime/",
)
IGNORED_CHANGE_FILES = {
    ".gitignore",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def files_snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def changed_since(before: dict[str, str], after: dict[str, str]) -> list[str]:
    paths = set(before) | set(after)
    return sorted(path for path in paths if before.get(path) != after.get(path))


def is_ignored_change(path: str, run_log_relative_to_subdir: str) -> bool:
    if path == run_log_relative_to_subdir:
        return True
    if path in IGNORED_CHANGE_FILES:
        return True
    return any(path == prefix.rstrip("/") or path.startswith(prefix) for prefix in IGNORED_CHANGE_PREFIXES)


def meaningful_changes(changed_paths: list[str], run_log_relative_to_subdir: str) -> list[str]:
    return [
        path
        for path in changed_paths
        if not is_ignored_change(path, run_log_relative_to_subdir)
    ]


def parse_json_list(raw: str, label: str) -> list[Any]:
    if not raw.strip():
        return []
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(loaded, list):
        raise ValueError(f"{label} must be a JSON list.")
    return loaded


def run_command(command: str, cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.returncode, result.stdout


def validate_success_checks(
    *,
    checks: list[Any],
    target: Path,
    target_subdir_path: Path,
) -> list[str]:
    failures: list[str] = []
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            failures.append(f"success_checks[{index}] is not a mapping")
            continue

        if "path_exists" in item:
            value = str(item["path_exists"]).strip()
            try:
                path, relative = resolve_inside_root(target_subdir_path, value, f"success_checks[{index}].path_exists")
            except Exception as exc:
                failures.append(str(exc))
                continue
            if not path.exists():
                failures.append(f"success_checks[{index}] path does not exist: {relative}")
            continue

        if "command" in item:
            command = str(item["command"]).strip()
            if not command:
                failures.append(f"success_checks[{index}].command is empty")
                continue
            returncode, output = run_command(command, target_subdir_path)
            if returncode != 0:
                failures.append(
                    f"success_checks[{index}] command failed with exit {returncode}: {command}\n{output}"
                )
            continue

        failures.append(f"success_checks[{index}] must contain path_exists or command")
    return failures


def print_summary(
    *,
    target_subdir: str,
    existing_files: list[str],
    changed_paths: list[str],
    meaningful_changed_paths: list[str],
    success_checks_count: int,
) -> None:
    print("Target output validation summary:")
    print(f"  target_subdir: {target_subdir}/")
    print(f"  existing files: {len(existing_files)}")
    print(f"  changed paths since agent started: {len(changed_paths)}")
    print(f"  meaningful changed paths: {len(meaningful_changed_paths)}")
    print(f"  success_checks evaluated: {success_checks_count}")
    for path in meaningful_changed_paths[:40]:
        print(f"    {path}")
    if len(meaningful_changed_paths) > 40:
        print(f"    ... [{len(meaningful_changed_paths) - 40} more files]")


def validate(
    *,
    target: Path,
    target_subdir: str,
    run_log_path: str,
    before_snapshot_path: Path,
    require_meaningful_change: bool,
    success_checks_json: str,
) -> None:
    target = target.resolve()
    target_subdir_path, target_subdir_relative = resolve_target_subdir(target, target_subdir)
    run_log_abs, _ = require_path_inside_subdir(
        target,
        target_subdir_relative,
        run_log_path,
        "run_log_path",
    )
    run_log_relative_to_subdir = run_log_abs.relative_to(target_subdir_path).as_posix()

    before = json.loads(before_snapshot_path.read_text(encoding="utf-8"))
    after = files_snapshot(target_subdir_path)
    existing_files = sorted(after)
    changed_paths = changed_since(before, after)
    meaningful_changed = meaningful_changes(changed_paths, run_log_relative_to_subdir)
    success_checks = parse_json_list(success_checks_json, "success_checks")
    success_failures = validate_success_checks(
        checks=success_checks,
        target=target,
        target_subdir_path=target_subdir_path,
    )

    failures: list[str] = []
    if require_meaningful_change and not meaningful_changed:
        failures.append(
            "Agent produced no non-log, non-cache changes inside target_subdir."
        )
    failures.extend(success_failures)

    print_summary(
        target_subdir=target_subdir_relative,
        existing_files=existing_files,
        changed_paths=changed_paths,
        meaningful_changed_paths=meaningful_changed,
        success_checks_count=len(success_checks),
    )

    if failures:
        print("ERROR: generic target output validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        sys.exit(1)

    print("Generic target output validation passed.")


def command_snapshot(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    target_subdir_path, _ = resolve_target_subdir(target, args.target_subdir)
    snapshot = files_snapshot(target_subdir_path)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Target output snapshot recorded: {len(snapshot)} files")


def command_validate(args: argparse.Namespace) -> None:
    validate(
        target=Path(args.target),
        target_subdir=args.target_subdir,
        run_log_path=args.run_log_path,
        before_snapshot_path=Path(args.snapshot),
        require_meaningful_change=args.require_meaningful_change,
        success_checks_json=args.success_checks_json,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate generic Forgis target output")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot")
    snapshot.add_argument("--target", required=True)
    snapshot.add_argument("--target-subdir", required=True)
    snapshot.add_argument("--output", required=True)
    snapshot.set_defaults(func=command_snapshot)

    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--target", required=True)
    validate_parser.add_argument("--target-subdir", required=True)
    validate_parser.add_argument("--run-log-path", required=True)
    validate_parser.add_argument("--snapshot", required=True)
    validate_parser.add_argument("--require-meaningful-change", action="store_true")
    validate_parser.add_argument("--success-checks-json", default="[]")
    validate_parser.set_defaults(func=command_validate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
