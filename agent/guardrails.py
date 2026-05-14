#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from forgis_config import resolve_inside_root, resolve_target_subdir


AIDER_GITIGNORE_MARKERS = (
    ".aider",
    "aider",
)
AIDER_TAGS_CACHE_PREFIX = ".aider.tags.cache.v"
AIDER_TAGS_CACHE_ALLOWED_FILES = {
    "cache.db",
    "cache.db-shm",
    "cache.db-wal",
}


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


def git_path_exists_in_head(repo: Path, path: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{path}"],
        cwd=repo,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


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


def changed_paths_from_status(status_lines: list[str]) -> list[str]:
    paths: list[str] = []
    for line in status_lines:
        paths.extend(paths_from_status_line(line))
    return paths


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


def looks_like_aider_gitignore(path: Path) -> bool:
    if not path.is_file():
        return False

    text = path.read_text(encoding="utf-8", errors="replace")
    meaningful_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if not meaningful_lines:
        return False

    return all(any(marker in line.casefold() for marker in AIDER_GITIGNORE_MARKERS) for line in meaningful_lines)


def is_aider_tags_cache_path(path: str) -> bool:
    return path == AIDER_TAGS_CACHE_PREFIX.rstrip(".") or path.startswith(AIDER_TAGS_CACHE_PREFIX)


def root_tags_cache_paths(target: Path) -> list[Path]:
    return sorted(target.glob(f"{AIDER_TAGS_CACHE_PREFIX}*"))


def root_tags_cache_snapshot(target: Path) -> dict[str, Any]:
    paths: dict[str, dict[str, Any]] = {}
    for path in root_tags_cache_paths(target):
        relative = path.relative_to(target).as_posix()
        paths[relative] = {
            "exists": path.exists(),
            "kind": "dir" if path.is_dir() else "file" if path.is_file() else "other",
        }
    return {"paths": paths}


def root_tags_cache_state_text(snapshot: dict[str, Any]) -> str:
    paths = sorted((snapshot.get("paths") or {}).keys())
    if not paths:
        return "none"
    return ", ".join(paths)


def looks_like_new_aider_tags_cache(path: Path) -> bool:
    if not path.is_dir():
        return False

    files = [item for item in path.rglob("*") if item.is_file()]
    if not files:
        return True

    for file_path in files:
        relative = file_path.relative_to(path)
        if len(relative.parts) != 1:
            return False
        if relative.name not in AIDER_TAGS_CACHE_ALLOWED_FILES:
            return False

    return True


def cleanup_aider_tags_cache(target: Path, snapshot: dict[str, Any]) -> list[str]:
    existing = set((snapshot.get("paths") or {}).keys())
    removed: list[str] = []

    for path in root_tags_cache_paths(target):
        relative = path.relative_to(target).as_posix()
        if relative in existing:
            print(f"Root Aider tags cache existed before this run; leaving for guardrail checks: {relative}")
            continue
        if looks_like_new_aider_tags_cache(path):
            shutil.rmtree(path)
            removed.append(relative)
            print(f"Removed root Aider tags cache created during this run: {relative}")
            continue
        print(f"Root Aider tags cache was newly created but did not look safe to remove; leaving it for guardrail failure: {relative}")

    return removed


def root_gitignore_snapshot(target: Path) -> dict[str, Any]:
    path = target / ".gitignore"
    exists = path.is_file()
    return {
        "path": ".gitignore",
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
    }


def root_gitignore_state_text(snapshot: dict[str, Any]) -> str:
    exists = bool(snapshot.get("exists"))
    digest = snapshot.get("sha256")
    return f"exists={'true' if exists else 'false'} sha256={digest if digest else 'null'}"


def cleanup_aider_root_gitignore(target: Path, snapshot: dict[str, Any]) -> bool:
    path = target / ".gitignore"
    existed_before = bool(snapshot.get("exists"))
    if existed_before:
        if path.is_file():
            before_hash = snapshot.get("sha256")
            after_hash = sha256_file(path)
            if before_hash != after_hash:
                print("Root .gitignore existed before this run and was changed; leaving it for guardrail failure.")
        return False

    if not path.exists():
        return False

    if looks_like_aider_gitignore(path):
        path.unlink()
        print("Removed root .gitignore because it was newly created and only contained Aider ignore patterns.")
        return True

    print("Root .gitignore was newly created but did not look like an Aider-only file; leaving it for guardrail failure.")
    return False


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
            abs_path = target / path
            existed_in_head = git_path_exists_in_head(target, path)
            aider_generated = "unknown"
            if path == ".gitignore":
                aider_generated = "yes" if looks_like_aider_gitignore(abs_path) else "no"
            elif is_aider_tags_cache_path(path):
                aider_generated = "yes"
            print(
                f"  {path} ({entry['kind']}, status={entry['status']}, "
                f"existed_before={'yes' if existed_in_head else 'no'}, "
                f"aider_auto_generated={aider_generated})",
                file=sys.stderr,
            )
        print(f"Allowed writable scope: {target_subdir}/", file=sys.stderr)
        if read_only_paths:
            print("Explicit read-only target inputs:", file=sys.stderr)
            for path in sorted(set(read_only_paths)):
                print(f"  {path}", file=sys.stderr)
        print("Fix suggestion: keep generated files, reports, Aider history, and ignore files inside the writable scope.", file=sys.stderr)
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


def command_snapshot_root_gitignore(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    snapshot = root_gitignore_snapshot(target)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Root .gitignore snapshot recorded: {root_gitignore_state_text(snapshot)}")


def command_cleanup_aider_root_gitignore(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    before_state = root_gitignore_state_text(snapshot)
    cleaned = cleanup_aider_root_gitignore(target, snapshot)
    after = root_gitignore_snapshot(target)
    after_state = root_gitignore_state_text(after)
    print(f"Root .gitignore before cleanup: {before_state}")
    print(f"Root .gitignore after cleanup: {after_state}")
    print(f"Root .gitignore cleanup performed: {'yes' if cleaned else 'no'}")


def command_snapshot_aider_tags_cache(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    snapshot = root_tags_cache_snapshot(target)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Root Aider tags cache snapshot recorded: {root_tags_cache_state_text(snapshot)}")


def command_cleanup_aider_tags_cache(args: argparse.Namespace) -> None:
    target = Path(args.target).resolve()
    snapshot = json.loads(Path(args.snapshot).read_text(encoding="utf-8"))
    before_state = root_tags_cache_state_text(snapshot)
    removed = cleanup_aider_tags_cache(target, snapshot)
    after = root_tags_cache_snapshot(target)
    after_state = root_tags_cache_state_text(after)
    print(f"Root Aider tags cache before cleanup: {before_state}")
    print(f"Root Aider tags cache after cleanup: {after_state}")
    print(f"Root Aider tags cache cleanup removed: {', '.join(removed) if removed else '[none]'}")


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

    snapshot_gitignore = subparsers.add_parser("snapshot-root-gitignore")
    snapshot_gitignore.add_argument("--target", required=True)
    snapshot_gitignore.add_argument("--output", required=True)
    snapshot_gitignore.set_defaults(func=command_snapshot_root_gitignore)

    cleanup_gitignore = subparsers.add_parser("cleanup-aider-root-gitignore")
    cleanup_gitignore.add_argument("--target", required=True)
    cleanup_gitignore.add_argument("--snapshot", required=True)
    cleanup_gitignore.set_defaults(func=command_cleanup_aider_root_gitignore)

    snapshot_tags_cache = subparsers.add_parser("snapshot-aider-tags-cache")
    snapshot_tags_cache.add_argument("--target", required=True)
    snapshot_tags_cache.add_argument("--output", required=True)
    snapshot_tags_cache.set_defaults(func=command_snapshot_aider_tags_cache)

    cleanup_tags_cache = subparsers.add_parser("cleanup-aider-tags-cache")
    cleanup_tags_cache.add_argument("--target", required=True)
    cleanup_tags_cache.add_argument("--snapshot", required=True)
    cleanup_tags_cache.set_defaults(func=command_cleanup_aider_tags_cache)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
