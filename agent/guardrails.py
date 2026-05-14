#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

from forgis_config import resolve_inside_root, resolve_target_subdir
from model_env import parse_model_env_json


def sha256_file(path: Path) -> str:
    if path_kind_no_follow(path) == "symlink":
        raise ValueError(f"Refusing to hash symlink target: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def path_kind_no_follow(path: Path) -> str:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def snapshot_paths(target: Path, relative_paths: list[str]) -> dict[str, dict[str, Any]]:
    snapshot: dict[str, dict[str, Any]] = {}
    for value in relative_paths:
        path, relative = resolve_inside_root(target, value, "read-only path")
        kind = path_kind_no_follow(path)
        exists = kind != "missing"
        snapshot[relative] = {
            "exists": exists,
            "kind": kind,
            "sha256": sha256_file(path) if kind == "file" else None,
        }
    return snapshot


def changed_read_only_paths(target: Path, snapshot: dict[str, dict[str, Any]]) -> list[str]:
    changed: list[str] = []
    for relative, expected in snapshot.items():
        path, normalized = resolve_inside_root(target, relative, "read-only path")
        kind = path_kind_no_follow(path)
        exists = kind != "missing"
        digest = sha256_file(path) if kind == "file" else None

        expected_kind = expected.get("kind")
        if exists != expected.get("exists") or digest != expected.get("sha256") or (
            expected_kind is not None and kind != expected_kind
        ):
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


def classify_status(status: str) -> str:
    if status == "??":
        return "new"
    if "R" in status:
        return "renamed"
    if "D" in status:
        return "deleted"
    if "A" in status:
        return "added"
    if "M" in status:
        return "modified"
    if "C" in status:
        return "copied"
    if "U" in status:
        return "unmerged"
    return "changed"


def paths_from_status_line(line: str) -> list[str]:
    if len(line) < 4:
        return []

    path_text = line[3:]
    if " -> " in path_text:
        parts = path_text.split(" -> ", 1)
    else:
        parts = [path_text]

    return [part.strip().strip('"') for part in parts if part.strip()]


def status_entries(status_lines: list[str]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for line in status_lines:
        if len(line) < 4:
            continue
        status = line[:2]
        for path in paths_from_status_line(line):
            entries.append(
                {
                    "status": status,
                    "kind": classify_status(status),
                    "path": path,
                }
            )
    return entries


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


def secret_values_from_model_env(model_env_json: str, environ: dict[str, str]) -> list[str]:
    values: list[str] = []
    for _runtime_env, secret_env in parse_model_env_json(model_env_json):
        value = environ.get(secret_env, "")
        if len(value) >= 8:
            values.append(value)
    return sorted(set(values))


def scan_secret_leaks(root: Path, secret_values: list[str]) -> list[str]:
    if not secret_values or not root.exists():
        return []
    leaks: list[str] = []
    for path in sorted(root.rglob("*")):
        if path_kind_no_follow(path) != "file":
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(value in text for value in secret_values):
            leaks.append(path.relative_to(root).as_posix())
    return leaks


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

    status = git_status_lines(target)
    entries = status_entries(status)
    changed_paths = [entry["path"] for entry in entries]
    violations = target_scope_violations(changed_paths, target_subdir, read_only_paths)

    if violations:
        entry_by_path = {entry["path"]: entry for entry in entries}
        print("ERROR: target repository has changes outside the allowed writable scope:", file=sys.stderr)
        for path in violations:
            entry = entry_by_path.get(path, {"kind": "changed", "status": "??"})
            print(
                f"  {path} ({entry['kind']}, status={entry['status']})",
                file=sys.stderr,
            )
        print(f"Allowed writable scope: {target_subdir}/", file=sys.stderr)
        if read_only_paths:
            print("Explicit read-only target inputs:", file=sys.stderr)
            for path in sorted(set(read_only_paths)):
                print(f"  {path}", file=sys.stderr)
        print("Fix suggestion: keep generated files inside the configured target_subdir.", file=sys.stderr)
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


def command_check_dry_run_clean(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    status = git_status_lines(target)
    if status:
        print("ERROR: dry_run modified the target repository:", file=sys.stderr)
        for line in status:
            print(f"  {line}", file=sys.stderr)
        sys.exit(1)
    print("Dry run target write verification passed.")


def command_check_secret_leaks(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    target_subdir_path, target_subdir = resolve_target_subdir(target, args.target_subdir)
    values = secret_values_from_model_env(args.model_env_json, dict(os.environ))
    leaks = scan_secret_leaks(target_subdir_path, values)
    if leaks:
        print("ERROR: secret-like model value was found in target_subdir output:", file=sys.stderr)
        for path in leaks:
            print(f"  {target_subdir}/{path}", file=sys.stderr)
        sys.exit(1)
    print("Secret leak verification passed.")


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

    dry_run_clean = subparsers.add_parser("check-dry-run-clean")
    dry_run_clean.add_argument("--target", required=True)
    dry_run_clean.set_defaults(func=command_check_dry_run_clean)

    secret_leaks = subparsers.add_parser("check-secret-leaks")
    secret_leaks.add_argument("--target", required=True)
    secret_leaks.add_argument("--target-subdir", required=True)
    secret_leaks.add_argument("--model-env-json", default="{}")
    secret_leaks.set_defaults(func=command_check_secret_leaks)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
