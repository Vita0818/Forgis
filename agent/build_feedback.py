from __future__ import annotations

import re
from typing import Any


MAX_TAIL_LINES = 12
MAX_TAIL_CHARS = 1_200
SECRET_VALUE_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|CREDENTIAL|API[_-]?KEY|PRIVATE)[A-Z0-9_]*)\s*[:=]\s*([^\s,;]+)"
)
AUTH_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
LONG_TOKEN_RE = re.compile(r"\b[A-Za-z0-9_./+=-]{32,}\b")
SECRET_WORD_RE = re.compile(r"(?i)(secret|token|credential|password|api[_-]?key|private)")


def _redact_long_token(match: re.Match[str]) -> str:
    value = match.group(0)
    if value.startswith("migration_plan_"):
        return value
    if value.startswith("FORGIS_") and value.endswith(".json"):
        return value
    if "/" in value and not SECRET_WORD_RE.search(value):
        return value
    return "[redacted]"


def redact_secrets(text: str) -> str:
    redacted = SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    redacted = AUTH_RE.sub(lambda match: f"{match.group(1)} [redacted]", redacted)
    return LONG_TOKEN_RE.sub(_redact_long_token, redacted)


def tail_lines(text: str, *, max_lines: int = MAX_TAIL_LINES, max_chars: int = MAX_TAIL_CHARS) -> str:
    clean = redact_secrets(str(text if text is not None else ""))
    lines = clean.splitlines()
    selected = "\n".join(lines[-max_lines:])
    if len(selected) <= max_chars:
        return selected
    note = f"[Forgis summary tail truncated after {max_chars} characters]\n"
    keep = max(0, max_chars - len(note))
    return note + selected[-keep:]


def combined_output(result: dict[str, Any]) -> str:
    stdout = result.get("stdout_tail", result.get("stdout", ""))
    stderr = result.get("stderr_tail", result.get("stderr", ""))
    return "\n".join(part for part in (str(stdout or ""), str(stderr or "")) if part)


def classify_command_result(result: dict[str, Any]) -> str:
    status = str(result.get("status", "")).casefold()
    output = combined_output(result)
    lowered = output.casefold()

    if status == "timeout" or result.get("timed_out"):
        return "timeout"
    if status == "rejected" or "not in the conservative forgis allowlist" in lowered or "not allowed" in lowered:
        return "command_rejected"
    if "syntaxerror" in lowered:
        return "python_syntax_error"
    if "modulenotfounderror" in lowered:
        return "module_not_found"
    if "importerror" in lowered:
        return "import_error"
    if "failed (failures=" in lowered or "failed (errors=" in lowered or "\nfail:" in lowered or "\nerror:" in lowered:
        return "unittest_failure"
    if result.get("exit_code") not in (0, None) or status == "failed":
        return "nonzero_exit"
    return "success"


def summary_message(error_type: str, result: dict[str, Any], *, label: str) -> str:
    exit_code = result.get("exit_code")
    status = result.get("status", "unknown")
    if error_type == "timeout":
        return f"{label} timed out after {result.get('timeout_seconds')}s."
    if error_type == "command_rejected":
        return f"{label} command was rejected by the Forgis command allowlist."
    if error_type == "python_syntax_error":
        return f"{label} failed with a Python SyntaxError."
    if error_type == "module_not_found":
        return f"{label} failed with ModuleNotFoundError."
    if error_type == "import_error":
        return f"{label} failed with ImportError."
    if error_type == "unittest_failure":
        return f"{label} failed with unittest failures or errors."
    if error_type == "nonzero_exit":
        return f"{label} exited nonzero with exit_code={exit_code}."
    return f"{label} status={status}."


def summarize_command_result(result: dict[str, Any], *, label: str = "Command") -> dict[str, Any]:
    error_type = classify_command_result(result)
    return {
        "error_type": error_type,
        "status": result.get("status", "unknown"),
        "exit_code": result.get("exit_code"),
        "message": summary_message(error_type, result, label=label),
        "tail": tail_lines(combined_output(result)),
    }


def summarize_build_failure(result: dict[str, Any]) -> dict[str, Any]:
    return summarize_command_result(result, label="Build")


def summarize_test_failure(result: dict[str, Any]) -> dict[str, Any]:
    return summarize_command_result(result, label="Tests")
