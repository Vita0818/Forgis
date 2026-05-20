from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from build_feedback import redact_secrets


MAX_REPORT_CHARS = 12_000
MAX_COMPACT_CHARS = 900
MAX_TEXT_CHARS = 240
MAX_SUMMARY_CHARS = 700
MAX_PATHS = 40
MAX_ATTEMPTS = 12
SECRET_PATH_WORDS = re.compile(
    r"(secret|token|credential|password|api[_-]?key|private|\.env|\.npmrc|\.pypirc|\.netrc)",
    re.IGNORECASE,
)
ABSOLUTE_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9._~-])(?P<path>(?:/[A-Za-z0-9._~+\-][^\s`'\"<>)]*|[A-Za-z]:[\\/][^\s`'\"<>)]*))"
)
DIFF_TEXT_RE = re.compile(r"(?is)\bdiff --git\b.*")
DIFF_LINE_RE = re.compile(r"^\s*(diff --git|@@ |--- |\+\+\+ )")


def _single_line(text: Any) -> str:
    return str(text if text is not None else "").replace("\x00", "").replace("\r", " ").replace("\n", " ")


def sanitize_text(value: Any, *, limit: int = MAX_TEXT_CHARS) -> str:
    text = redact_secrets(_single_line(value)).strip()
    text = DIFF_TEXT_RE.sub("[diff-redacted]", text)

    def replace_absolute(match: re.Match[str]) -> str:
        raw = match.group("path").replace("\\", "/")
        name = PurePosixPath(raw).name
        if name and not SECRET_PATH_WORDS.search(name):
            return f"[path-redacted]/{name}"
        return "[path-redacted]"

    text = ABSOLUTE_PATH_RE.sub(replace_absolute, text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 24)].rstrip() + " ... [truncated]"


def sanitize_markdown(value: Any, *, limit: int = MAX_REPORT_CHARS) -> str:
    text = redact_secrets(str(value if value is not None else "")).replace("\x00", "")
    text = DIFF_TEXT_RE.sub("[diff-redacted]", text)
    text = "\n".join("[diff-redacted]" if DIFF_LINE_RE.match(line) else line for line in text.splitlines())

    def replace_absolute(match: re.Match[str]) -> str:
        raw = match.group("path").replace("\\", "/")
        name = PurePosixPath(raw).name
        if name and not SECRET_PATH_WORDS.search(name):
            return f"[path-redacted]/{name}"
        return "[path-redacted]"

    text = ABSOLUTE_PATH_RE.sub(replace_absolute, text)
    return _limit_markdown(text, limit=limit)


def sanitize_path(value: Any, *, limit: int = 160) -> str:
    text = _single_line(value).strip().replace("\\", "/")
    if not text:
        return ""
    text = redact_secrets(text)
    if text.startswith("/") or re.match(r"^[A-Za-z]:/", text):
        name = PurePosixPath(text).name
        text = f"[path-redacted]/{name}" if name else "[path-redacted]"
    parts: list[str] = []
    for part in PurePosixPath(text.strip("/")).parts:
        if part in {"", ".", "..", ".git"}:
            continue
        parts.append("[redacted]" if SECRET_PATH_WORDS.search(part) else part)
    cleaned = "/".join(parts) or "[root]"
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:80] + ".../" + cleaned[-60:]


def sanitize_paths(values: Any, *, limit: int = MAX_PATHS) -> list[str]:
    if values is None:
        return []
    raw_values = values if isinstance(values, (list, tuple, set)) else [values]
    paths: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        path = sanitize_path(raw)
        if not path or path in seen:
            continue
        seen.add(path)
        paths.append(path)
        if len(paths) >= limit:
            break
    return paths


def sanitize_failure_summary(summary: Any, *, limit: int = MAX_SUMMARY_CHARS) -> dict[str, Any] | None:
    if not isinstance(summary, dict):
        text = sanitize_text(summary, limit=limit)
        return {"message": text} if text else None

    cleaned: dict[str, Any] = {}
    for key in ("error_type", "status", "exit_code", "message", "tail"):
        if key not in summary or summary.get(key) is None:
            continue
        if key == "exit_code":
            cleaned[key] = summary.get(key)
        else:
            cleaned[key] = sanitize_text(
                summary.get(key),
                limit=120 if key in {"error_type", "status"} else limit // 2,
            )
    return cleaned or None


def summary_message(summary: Any) -> str:
    cleaned = sanitize_failure_summary(summary)
    if not cleaned:
        return "none"
    message = cleaned.get("message") or cleaned.get("error_type") or cleaned.get("status") or "failure"
    tail = cleaned.get("tail")
    if tail and tail != message:
        return sanitize_text(f"{message} | {tail}", limit=MAX_SUMMARY_CHARS)
    return sanitize_text(message, limit=MAX_SUMMARY_CHARS)


def event_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    if hasattr(event, "as_dict"):
        return event.as_dict()
    return {}


def _status(value: Any) -> str:
    return sanitize_text(value or "unknown", limit=80) or "unknown"


def _bool_text(value: Any) -> str:
    return "true" if bool(value) else "false"


def _table_value(value: Any) -> str:
    text = sanitize_text(value, limit=180) or "none"
    return text.replace("|", "\\|")


def _event_summary(events: list[dict[str, Any]], event_type: str, attempt: int) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if event.get("event_type") == event_type and int(event.get("attempt_index") or 0) == attempt
    ]


def _attempt_rows(events: list[dict[str, Any]]) -> list[str]:
    attempts = sorted(
        {
            int(event.get("attempt_index") or 0)
            for event in events
            if int(event.get("attempt_index") or 0) > 0
        }
    )
    if not attempts:
        return ["No repair attempts recorded."]

    lines = [
        "| Attempt | Trigger | Changed Paths | Diff Checked | Recheck | Stop |",
        "|---|---|---|---|---|---|",
    ]
    for attempt in attempts[:MAX_ATTEMPTS]:
        attempt_events = [event for event in events if int(event.get("attempt_index") or 0) == attempt]
        trigger = next(
            (
                summary_message(event.get("failure_summary"))
                for event in attempt_events
                if event.get("event_type") in {"failure_recorded", "repair_allowed"}
                and event.get("failure_summary")
            ),
            "repair allowed",
        )
        changed = sanitize_paths(
            [
                path
                for event in attempt_events
                for path in event.get("affected_paths", [])
                if event.get("event_type") == "edit_after_failure"
            ],
            limit=8,
        )
        diff_checked = "yes" if _event_summary(events, "diff_checked", attempt) else "no"
        rechecks = [
            event
            for event in attempt_events
            if event.get("event_type") in {"build_finished", "tests_finished"}
        ]
        recheck = "none"
        if rechecks:
            last = rechecks[-1]
            recheck = f"{last.get('check_type') or 'check'}:{last.get('status') or 'unknown'}"
        stop_events = [
            event
            for event in attempt_events
            if event.get("event_type") in {"repair_success", "repair_blocked", "max_attempts_reached"}
        ]
        stop = stop_events[-1].get("short_message") if stop_events else "none"
        lines.append(
            "| "
            + " | ".join(
                [
                    str(attempt),
                    _table_value(trigger),
                    _table_value(", ".join(changed) if changed else "none"),
                    diff_checked,
                    _table_value(recheck),
                    _table_value(stop),
                ]
            )
            + " |"
        )
    if len(attempts) > MAX_ATTEMPTS:
        lines.append(f"| ... | {len(attempts) - MAX_ATTEMPTS} more attempts omitted | | | | |")
    return lines


def _last_failure(runtime_state: dict[str, Any], events: list[dict[str, Any]]) -> tuple[str, str]:
    for event in reversed(events):
        if event.get("event_type") == "failure_recorded" and event.get("failure_summary"):
            return str(event.get("check_type") or "check"), summary_message(event.get("failure_summary"))
    summary = runtime_state.get("last_failure_summary")
    if summary:
        return str(runtime_state.get("last_check_type") or "check"), summary_message(summary)
    return "none", "none"


def _stopped_reason(runtime_state: dict[str, Any], events: list[dict[str, Any]]) -> str:
    reason = runtime_state.get("stopped_reason")
    if reason:
        return sanitize_text(reason, limit=100)
    for event in reversed(events):
        if event.get("event_type") == "repair_blocked":
            return sanitize_text(event.get("short_message"), limit=120) or "blocked"
    return "none"


def _next_action(runtime_state: dict[str, Any], stopped_reason: str) -> str:
    if runtime_state.get("repair_success") or stopped_reason == "success":
        return "Review the diff and run the full project CI before merging."
    if stopped_reason == "max_attempts_reached":
        return "Inspect the latest failure summary manually before attempting another focused repair."
    if "diff_check_required" in stopped_reason or "git_diff" in stopped_reason:
        return "Run git_diff, review the changed paths, then rerun the configured build/test check."
    if stopped_reason not in {"none", ""}:
        return "Resolve the blocked reason, then retry a small repair step."
    if runtime_state.get("last_build_status") == "skipped" or runtime_state.get("last_test_status") == "skipped":
        return "Configure build_command/test_command if verification is expected for this target."
    if int(runtime_state.get("build_runs") or 0) == 0 and int(runtime_state.get("test_runs") or 0) == 0:
        return "Configure build_command/test_command or run external CI for stronger verification."
    return "Review the changed paths and run the next project-specific verification."


def _append_section(lines: list[str], title: str, body: list[str]) -> None:
    lines.append("")
    lines.append(f"## {title}")
    lines.extend(body or ["none"])


def _limit_markdown(markdown: str, *, limit: int = MAX_REPORT_CHARS) -> str:
    if len(markdown) <= limit:
        return markdown
    note = f"\n\n[Forgis report truncated after {limit} characters.]"
    return markdown[: max(0, limit - len(note))].rstrip() + note


def render_repair_report(
    runtime_state: dict[str, Any] | None,
    repair_state: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    changed_paths: list[str] | None = None,
    *,
    max_chars: int = MAX_REPORT_CHARS,
) -> str:
    state: dict[str, Any] = {}
    if runtime_state:
        state.update(runtime_state)
    if repair_state:
        state.update(repair_state)

    clean_events = [event_dict(event) for event in (events or state.get("repair_events") or [])]
    clean_events = [event for event in clean_events if event]
    safe_paths = sanitize_paths(changed_paths or state.get("changed_paths") or [])
    failure_type, failure = _last_failure(state, clean_events)
    stopped = _stopped_reason(state, clean_events)

    lines: list[str] = [
        "# Forgis Runtime Report",
        "",
        "v3.3 repair event log",
        "",
        "## Overview",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| build_runs | `{int(state.get('build_runs') or 0)}` |",
        f"| test_runs | `{int(state.get('test_runs') or 0)}` |",
        f"| repair_loop_enabled | `{_bool_text(state.get('repair_loop_enabled'))}` |",
        f"| repair_attempts_used | `{int(state.get('repair_attempts_used') or 0)}` |",
        f"| repair_success | `{_bool_text(state.get('repair_success'))}` |",
        f"| stopped_reason | `{_table_value(stopped)}` |",
        f"| last_build_status | `{_status(state.get('last_build_status'))}` |",
        f"| last_test_status | `{_status(state.get('last_test_status'))}` |",
        f"| event_count | `{len(clean_events)}` |",
    ]

    _append_section(
        lines,
        "Recent Failure Summary",
        [f"- Type: `{_table_value(failure_type)}`", f"- Summary: {_table_value(failure)}"],
    )
    _append_section(lines, "Repair Attempts", _attempt_rows(clean_events))
    _append_section(lines, "Blocked / Stopped Reason", [f"- `{_table_value(stopped)}`"])
    _append_section(
        lines,
        "Changed Paths",
        [f"- `{path}`" for path in safe_paths] if safe_paths else ["- none"],
    )
    _append_section(lines, "Next Suggested Action", [f"- {_next_action(state, stopped)}"])
    _append_section(
        lines,
        "Recent Events",
        [
            (
                f"- #{event.get('event_id')} `{_table_value(event.get('event_type'))}` "
                f"attempt=`{int(event.get('attempt_index') or 0)}` "
                f"check=`{_table_value(event.get('check_type') or 'none')}` "
                f"status=`{_table_value(event.get('status') or 'unknown')}` "
                f"- {_table_value(event.get('short_message') or '')}"
            )
            for event in clean_events[-20:]
        ]
        or ["- none"],
    )

    return _limit_markdown("\n".join(lines).rstrip() + "\n", limit=max_chars)


def render_compact_actions_summary(
    runtime_state: dict[str, Any] | None,
    repair_state: dict[str, Any] | None = None,
    events: list[dict[str, Any]] | None = None,
    changed_paths: list[str] | None = None,
    *,
    max_chars: int = MAX_COMPACT_CHARS,
) -> str:
    state: dict[str, Any] = {}
    if runtime_state:
        state.update(runtime_state)
    if repair_state:
        state.update(repair_state)
    clean_events = [event_dict(event) for event in (events or state.get("repair_events") or [])]
    stopped = _stopped_reason(state, clean_events)
    failure_type, failure = _last_failure(state, clean_events)
    path_count = len(sanitize_paths(changed_paths or state.get("changed_paths") or []))
    text = (
        "Forgis v3.3: "
        f"build={_status(state.get('last_build_status'))} "
        f"tests={_status(state.get('last_test_status'))} "
        f"repair_attempts={int(state.get('repair_attempts_used') or 0)} "
        f"success={_bool_text(state.get('repair_success'))} "
        f"stopped={stopped} "
        f"changed_paths={path_count} "
        f"last_failure={failure_type}:{failure}"
    )
    return sanitize_text(text, limit=max_chars)


def write_github_step_summary(markdown: str, env: dict[str, str] | None = None) -> bool:
    local_env = os.environ if env is None else env
    raw_path = local_env.get("GITHUB_STEP_SUMMARY", "")
    if not raw_path:
        return False
    if "\x00" in raw_path or "\n" in raw_path or "\r" in raw_path:
        return False
    try:
        summary_path = Path(raw_path).expanduser().resolve()
    except OSError:
        return False
    try:
        if summary_path.exists() and summary_path.is_dir():
            return False
        if summary_path.exists() and summary_path.is_symlink():
            return False
        if not summary_path.parent.exists() or not summary_path.parent.is_dir():
            return False
        clean_markdown = sanitize_markdown(markdown, limit=MAX_REPORT_CHARS)
        with summary_path.open("a", encoding="utf-8") as file:
            file.write(clean_markdown.rstrip() + "\n")
        return True
    except OSError:
        return False
