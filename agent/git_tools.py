from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class GitToolError(ValueError):
    pass


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    note = f"\n\n[Forgis git output truncated after {max_chars} characters.]\n"
    keep = max(0, max_chars - len(note))
    return text[:keep] + note, True


def run_git(repo: Path, args: list[str], *, timeout_seconds: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
    )


def ensure_git_repo(repo: Path) -> None:
    result = run_git(repo, ["rev-parse", "--is-inside-work-tree"])
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise GitToolError("Target workspace is not a git repository.")


def git_status(repo: Path, *, max_entries: int = 200) -> dict[str, Any]:
    ensure_git_repo(repo)
    limit = max(1, min(int(max_entries), 500))
    result = run_git(repo, ["status", "--short", "--branch", "--untracked-files=all"])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git status failed"
        raise GitToolError(detail)

    lines = result.stdout.splitlines()
    returned = lines[:limit]
    return {
        "ok": True,
        "repo": "target",
        "status_lines": returned,
        "line_count": len(lines),
        "truncated": len(lines) > len(returned),
    }


def git_diff(repo: Path, *, max_chars: int = 20_000) -> dict[str, Any]:
    ensure_git_repo(repo)
    limit = max(100, min(int(max_chars), 200_000))
    result = run_git(repo, ["diff", "--no-ext-diff", "--no-color"])
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git diff failed"
        raise GitToolError(detail)

    diff, truncated = truncate_text(result.stdout, limit)
    return {
        "ok": True,
        "repo": "target",
        "diff": diff,
        "chars": len(diff),
        "truncated": truncated,
    }
