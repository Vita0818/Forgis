from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from build_feedback import redact_secrets, summarize_build_failure, summarize_test_failure
from command_runner import CommandRunnerError, command_basename, safe_run_command


def command_label(command: tuple[str, ...]) -> list[str]:
    if not command:
        return []
    return [command_basename(command[0]), *command[1:]]


def output_tail(text: str, *, max_chars: int) -> tuple[str, bool]:
    clean = redact_secrets(text)
    if len(clean) <= max_chars:
        return clean, False
    note = f"\n[Forgis {max_chars}-char output tail]\n"
    keep = max(0, max_chars - len(note))
    return note + clean[-keep:], True


def skipped_result(tool: str) -> dict[str, Any]:
    return {
        "ok": True,
        "tool": tool,
        "status": "skipped",
        "exit_code": None,
        "duration_seconds": 0.0,
        "stdout_tail": "",
        "stderr_tail": "",
        "truncated": False,
        "summary": {
            "error_type": "skipped",
            "status": "skipped",
            "exit_code": None,
            "message": f"{tool} skipped because no command is configured.",
            "tail": "",
        },
    }


def rejected_result(tool: str, command: tuple[str, ...], message: str, *, duration: float = 0.0) -> dict[str, Any]:
    result = {
        "ok": False,
        "tool": tool,
        "status": "rejected",
        "command": command_label(command),
        "exit_code": None,
        "duration_seconds": round(duration, 3),
        "stdout_tail": "",
        "stderr_tail": redact_secrets(message),
        "truncated": False,
    }
    result["summary"] = summarize_build_failure(result) if tool == "run_build" else summarize_test_failure(result)
    return result


def run_configured_command(
    *,
    tool: str,
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
) -> dict[str, Any]:
    if not command:
        return skipped_result(tool)
    if not cwd.is_dir():
        return rejected_result(tool, command, f"target_subdir does not exist or is not a directory: {cwd}")

    started = time.monotonic()
    try:
        raw = safe_run_command(
            cwd=cwd,
            command=list(command),
            timeout_seconds=timeout_seconds,
            max_output_chars=max_output_chars,
            profile="build_test",
        )
    except CommandRunnerError as exc:
        return rejected_result(tool, command, str(exc), duration=time.monotonic() - started)

    stdout_tail, stdout_truncated = output_tail(raw.get("stdout", ""), max_chars=max_output_chars)
    stderr_tail, stderr_truncated = output_tail(raw.get("stderr", ""), max_chars=max_output_chars)
    if raw.get("timed_out"):
        status = "timeout"
    elif raw.get("exit_code") == 0:
        status = "success"
    else:
        status = "failed"

    result: dict[str, Any] = {
        "ok": status == "success",
        "tool": tool,
        "status": status,
        "command": command_label(command),
        "exit_code": raw.get("exit_code"),
        "duration_seconds": raw.get("duration_seconds", round(time.monotonic() - started, 3)),
        "timeout_seconds": raw.get("timeout_seconds", timeout_seconds),
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "truncated": bool(raw.get("truncated")) or stdout_truncated or stderr_truncated,
    }
    if status == "success":
        result["summary"] = {
            "error_type": "success",
            "status": "success",
            "exit_code": 0,
            "message": f"{tool} completed successfully.",
            "tail": "",
        }
    else:
        result["summary"] = summarize_build_failure(result) if tool == "run_build" else summarize_test_failure(result)
    return result


def run_build(
    *,
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
) -> dict[str, Any]:
    return run_configured_command(
        tool="run_build",
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )


def run_tests(
    *,
    command: tuple[str, ...],
    cwd: Path,
    timeout_seconds: int,
    max_output_chars: int,
) -> dict[str, Any]:
    return run_configured_command(
        tool="run_tests",
        command=command,
        cwd=cwd,
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
