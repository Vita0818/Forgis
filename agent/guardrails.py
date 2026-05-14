#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from forgis_config import resolve_inside_root, resolve_target_subdir


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_paths(target: Path, relative_paths: list[str]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for value in relative_paths:
        path, relative = resolve_inside_root(target, value, "read-only path")
        exists = path.is_file()
        snapshot[relative] = {
            "exists": exists,
            "sha256": sha256_file(path) if exists else None,
        }
    return snapshot


def changed_read_only_paths(target: Path, snapshot: dict[str, dict[str, Any]]) -> list[str]:
    changed: list[str] = []
    for relative, expected in snapshot.items():
        path, normalized = resolve_inside_root(target, relative, "read-only path")
        exists = path.is_file()
        digest = sha256_file(path) if exists else None

        if exists != expected.get("exists") or digest != expected.get("sha256"):
            changed.append(normalized)

    return sorted(changed)


def git_status_lines(repo: Path) -> list[str]:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout.splitlines()


def paths_from_status_line(line: str) -> list[str]:
    if len(line) < 4:
        return []

    path_text = line[3:]
    if " -> " in path_text:
        parts = path_text.split(" -> ", 1)
    else:
        parts = [path_text]

    return [part.strip().strip('"') for part in parts if part.strip()]


def changed_paths_from_status(status_lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in status_lines:
        paths.extend(paths_from_status_line(line))
    return paths


def is_path_inside(path: str, directory: str) -> bool:
    directory = directory.rstrip("/")
    return path == directory or path.startswith(directory + "/")


def target_scope_violations(
    changed_paths: list[str],
    target_subdir: str,
    read_only_paths: list[str] | None = None,
) -> list[str]:
    read_only = {path.rstrip("/") for path in read_only_paths or [] if path}
    violations: list[str] = []

    for path in changed_paths:
        normalized = path.rstrip("/")
        if normalized in read_only:
            violations.append(normalized)
            continue

        if not is_path_inside(normalized, target_subdir):
            violations.append(normalized)

    return sorted(set(violations))


def command_snapshot_readonly(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    paths = [args.config_path, args.task_prompt_path]
    snapshot = snapshot_paths(target, paths)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("Read-only file snapshot recorded:")
    for path, item in snapshot.items():
        state = item["sha256"] if item["exists"] else "missing"
        print(f"  {path}: {state}")


def command_check_readonly(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    changed = changed_read_only_paths(target, snapshot)

    if changed:
        print("ERROR: read-only target input files were modified:", file=sys.stderr)
        for path in changed:
            print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    print("Read-only input hash verification passed.")


def command_check_target_scope(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    _, target_subdir = resolve_target_subdir(target, args.target_subdir)

    read_only_paths: list[str] = []
    for value in args.read_only_path or []:
        if value:
            _, relative = resolve_inside_root(target, value, "read-only path")
            read_only_paths.append(relative)

    changed_paths = changed_paths_from_status(git_status_lines(target))
    violations = target_scope_violations(changed_paths, target_subdir, read_only_paths)

    if violations:
        print("ERROR: target repository has changes outside the allowed writable scope:", file=sys.stderr)
        for path in violations:
            print(f"  {path}", file=sys.stderr)
        print(f"Allowed writable scope: {target_subdir}/", file=sys.stderr)
        if read_only_paths:
            print("Explicit read-only target inputs:", file=sys.stderr)
            for path in sorted(set(read_only_paths)):
                print(f"  {path}", file=sys.stderr)
        sys.exit(1)

    print("Target writable scope verification passed.")
    print(f"  allowed writable scope: {target_subdir}/")
    print(f"  changed paths checked: {len(changed_paths)}")


def command_check_source_clean(args: argparse.Namespace) -> None:
    source = Path(args.source).resolve()
    status = git_status_lines(source)

    if status:
        print("ERROR: source repository was modified during the Forgis run:", file=sys.stderr)
        for line in status:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)

    print("Source repository read-only verification passed.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Forgis read-only and target-scope guardrails")
    subparsers = parser.add_subparsers(dest="command", required=True)

    snapshot = subparsers.add_parser("snapshot-readonly")
    snapshot.add_argument("--target", required=True)
    snapshot.add_argument("--config-path", required=True)
    snapshot.add_argument("--task-prompt-path", required=True)
    snapshot.add_argument("--output", required=True)
    snapshot.set_defaults(func=command_snapshot_readonly)

    check_readonly = subparsers.add_parser("check-readonly")
    check_readonly.add_argument("--target", required=True)
    check_readonly.add_argument("--snapshot", required=True)
    check_readonly.set_defaults(func=command_check_readonly)

    check_scope = subparsers.add_parser("check-target-scope")
    check_scope.add_argument("--target", required=True)
    check_scope.add_argument("--target-subdir", required=True)
    check_scope.add_argument("--read-only-path", action="append", default=[])
    check_scope.set_defaults(func=command_check_target_scope)

    source_clean = subparsers.add_parser("check-source-clean")
    source_clean.add_argument("--source", required=True)
    source_clean.set_defaults(func=command_check_source_clean)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
