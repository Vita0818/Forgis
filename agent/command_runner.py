from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any


class CommandRunnerError(ValueError):
    pass


DANGEROUS_COMMANDS = {
    "bash",
    "chmod",
    "chown",
    "curl",
    "fish",
    "ftp",
    "git",
    "nc",
    "netcat",
    "osascript",
    "perl",
    "pwsh",
    "rm",
    "rsync",
    "scp",
    "sh",
    "ssh",
    "sudo",
    "wget",
    "zsh",
}

BASIC_ALLOWED_COMMANDS = {
    "echo",
    "false",
    "printf",
    "pwd",
    "sleep",
    "true",
}

PYTHON_VERSION_ARGS = {
    ("--version",),
    ("-V",),
}

SAFE_UNITTEST_TOKENS = {
    "discover",
    "-s",
    "-p",
    "-t",
    "-v",
    "-q",
}
SAFE_PATH_OPTION_PREVIOUS = {"-s", "-p", "-t"}
COMMAND_PROFILES = {"basic", "build_test"}
MAX_COMMAND_OUTPUT_CHARS_LIMIT = 2_000_000


def command_basename(value: str) -> str:
    return Path(value).name.casefold()


def is_safe_command_path_token(value: str) -> bool:
    text = value.strip().replace("\\", "/")
    if not text:
        return False
    if any(char in text for char in "\x00\n\r"):
        return False
    if any(char in text for char in "*?[]{};$|&`><"):
        return False
    if text.startswith("/") or text.startswith("~"):
        return False
    parts = PurePosixPath(text).parts
    if any(part in {"", ".", "..", ".git"} for part in parts):
        return False
    lowered_parts = [part.casefold() for part in parts]
    if any(
        part in {".env", ".netrc", ".npmrc", ".pypirc"}
        or part.endswith((".pem", ".key", ".p12", ".pfx"))
        or any(word in part for word in ("secret", "credential", "private-key", "private_key", "token"))
        for part in lowered_parts
    ):
        return False
    return True


def validate_py_compile_args(args: list[str]) -> None:
    if len(args) < 4:
        raise CommandRunnerError("python -m py_compile requires at least one relative file path.")
    for value in args[3:]:
        if value.startswith("-"):
            raise CommandRunnerError("python -m py_compile options are not allowed in Forgis v3.1.")
        if not is_safe_command_path_token(value):
            raise CommandRunnerError(f"Unsafe py_compile path argument: {value}")


def validate_unittest_args(args: list[str]) -> None:
    values = args[3:]
    if not values:
        return
    previous = ""
    for value in values:
        if previous in SAFE_PATH_OPTION_PREVIOUS:
            if not is_safe_command_path_token(value):
                raise CommandRunnerError(f"Unsafe unittest path/pattern argument: {value}")
            previous = value
            continue
        if value in SAFE_UNITTEST_TOKENS:
            previous = value
            continue
        if value.startswith("-"):
            raise CommandRunnerError(f"Unsupported unittest option: {value}")
        if "/" in value or "\\" in value:
            if not is_safe_command_path_token(value):
                raise CommandRunnerError(f"Unsafe unittest path argument: {value}")
        elif any(char in value for char in "*?[]{};$|&`><"):
            raise CommandRunnerError(f"Unsafe unittest argument: {value}")
        previous = value


def validate_python_build_test_command(args: list[str]) -> bool:
    if len(args) < 3 or args[1] != "-m":
        return False
    module = args[2]
    if module == "py_compile":
        validate_py_compile_args(args)
        return True
    if module == "unittest":
        validate_unittest_args(args)
        return True
    return False


def validate_command(command: Any, *, profile: str = "basic") -> list[str]:
    if profile not in COMMAND_PROFILES:
        raise CommandRunnerError(f"Unsupported command profile: {profile}")
    if not isinstance(command, list) or not command:
        raise CommandRunnerError("command must be a non-empty array of strings.")
    args: list[str] = []
    for index, item in enumerate(command):
        if not isinstance(item, str) or not item:
            raise CommandRunnerError(f"command[{index}] must be a non-empty string.")
        if "\x00" in item or "\n" in item or "\r" in item:
            raise CommandRunnerError(f"command[{index}] contains an unsafe character.")
        args.append(item)

    name = command_basename(args[0])
    if name in DANGEROUS_COMMANDS:
        raise CommandRunnerError(f"Command is not allowed: {name}")
    if name == "sleep":
        if len(args) != 2:
            raise CommandRunnerError("sleep is only allowed with one duration argument.")
        try:
            duration = float(args[1])
        except ValueError as exc:
            raise CommandRunnerError("sleep duration must be numeric.") from exc
        if duration < 0 or duration > 300:
            raise CommandRunnerError("sleep duration must be between 0 and 300 seconds.")
        return args
    if name in BASIC_ALLOWED_COMMANDS:
        return args
    if name.startswith("python") and tuple(args[1:]) in PYTHON_VERSION_ARGS:
        return args
    if profile == "build_test" and name.startswith("python") and validate_python_build_test_command(args):
        return args
    raise CommandRunnerError(
        "Command is not in the conservative Forgis allowlist. "
        "Allowed examples: echo, pwd, true, false, python3 --version"
        + (", python3 -m py_compile <file>, python3 -m unittest discover." if profile == "build_test" else ".")
    )


def truncate_stream(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    note = f"\n[Forgis command output truncated after {max_chars} characters.]\n"
    keep = max(0, max_chars - len(note))
    return note + text[-keep:], True


def safe_run_command(
    *,
    cwd: Path,
    command: Any,
    timeout_seconds: int = 10,
    max_output_chars: int = 8_000,
    profile: str = "basic",
) -> dict[str, Any]:
    args = validate_command(command, profile=profile)
    timeout = max(1, min(int(timeout_seconds), 60))
    output_limit = max(100, min(int(max_output_chars), MAX_COMMAND_OUTPUT_CHARS_LIMIT))
    started = time.monotonic()

    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", ""),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(cwd / ".forgis-pycache"),
    }
    env = {key: value for key, value in env.items() if value}

    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            check=False,
            shell=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.monotonic() - started
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stdout, stdout_truncated = truncate_stream(stdout, output_limit)
        stderr, stderr_truncated = truncate_stream(stderr, output_limit)
        return {
            "ok": False,
            "cwd": "target_subdir",
            "command": [command_basename(args[0]), *args[1:]],
            "exit_code": None,
            "timed_out": True,
            "timeout_seconds": timeout,
            "duration_seconds": round(duration, 3),
            "stdout": stdout,
            "stderr": stderr,
            "truncated": stdout_truncated or stderr_truncated,
        }

    duration = time.monotonic() - started
    stdout, stdout_truncated = truncate_stream(result.stdout, output_limit)
    stderr, stderr_truncated = truncate_stream(result.stderr, output_limit)
    return {
        "ok": result.returncode == 0,
        "cwd": "target_subdir",
        "command": [command_basename(args[0]), *args[1:]],
        "exit_code": result.returncode,
        "timed_out": False,
        "timeout_seconds": timeout,
        "duration_seconds": round(duration, 3),
        "stdout": stdout,
        "stderr": stderr,
        "truncated": stdout_truncated or stderr_truncated,
    }
