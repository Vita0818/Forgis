#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


DEFAULT_FORBIDDEN_PROMPT_MARKERS = (
    "make the greeting more casual",
    "Which file (or which phrase) should be changed?",
    "casual greeting",
)
TASK_PROMPT_SHA_PREFIX = "Task prompt sha256:"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def first_lines(text: str, count: int = 20) -> list[str]:
    return text.splitlines()[:count]


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""


def contains_casefold(text: str, needle: str) -> bool:
    return needle.casefold() in text.casefold()


def clean_marker(value: Any, label: str) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} must not be empty.")
    if "\n" in text or "\r" in text:
        raise ValueError(f"{label} must be a single-line marker.")
    return text


def parse_marker_json(raw: str, label: str) -> list[str]:
    if not raw.strip():
        return []

    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} must be valid JSON list syntax: {exc}") from exc

    if not isinstance(loaded, list):
        raise ValueError(f"{label} must be a JSON list of strings.")

    return [clean_marker(item, f"{label}[{index}]") for index, item in enumerate(loaded)]


def dedupe_markers(markers: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for marker in markers:
        key = marker.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(marker)
    return tuple(result)


def marker_status(text: str, markers: tuple[str, ...]) -> tuple[list[str], list[str]]:
    present: list[str] = []
    missing: list[str] = []
    for marker in markers:
        if contains_casefold(text, marker):
            present.append(marker)
        else:
            missing.append(marker)
    return present, missing


def diagnostic_markdown(
    *,
    label: str,
    path: Path,
    char_count: int,
    digest: str,
    lines: list[str],
    task_prompt_path: str,
    task_prompt_sha256: str | None,
    task_prompt_sha_marker_found: bool | None,
    task_first_line: str,
    task_first_line_found: bool | None,
    required_markers: tuple[str, ...],
    required_present: list[str],
    required_missing: list[str],
    forbidden_markers: tuple[str, ...],
    forbidden_hits: list[str],
    expected_path: Path | None,
    expected_digest: str | None,
    matches_expected: bool | None,
) -> str:
    expected_lines: list[str] = []
    if expected_path is not None:
        expected_lines.extend(
            [
                f"| Expected same as | `{expected_path}` |",
                f"| Expected sha256 | `{expected_digest}` |",
                f"| Matches expected | `{'yes' if matches_expected else 'no'}` |",
            ]
        )

    task_lines: list[str] = []
    if task_prompt_sha256 is not None:
        task_lines.extend(
            [
                f"| Task prompt sha256 | `{task_prompt_sha256}` |",
                f"| Contains task prompt sha256 marker | `{'yes' if task_prompt_sha_marker_found else 'no'}` |",
            ]
        )
    if task_first_line:
        task_lines.append(
            f"| Contains first task prompt line | `{'yes' if task_first_line_found else 'no'}` |"
        )

    first_line_block = "\n".join(lines) if lines else "[empty]"
    required_text = ", ".join(required_markers) if required_markers else "[none]"
    required_missing_text = ", ".join(required_missing) if required_missing else "[none]"
    required_present_text = ", ".join(required_present) if required_present else "[none]"
    forbidden_text = ", ".join(forbidden_markers) if forbidden_markers else "[none]"
    forbidden_hits_text = ", ".join(forbidden_hits) if forbidden_hits else "[none]"
    contains_task_path = task_prompt_path in read_cached_text(path)

    return "\n".join(
        [
            f"# {label} Diagnostics",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Path | `{path}` |",
            f"| Character count | `{char_count}` |",
            f"| SHA256 | `{digest}` |",
            f"| Task prompt path | `{task_prompt_path}` |",
            f"| Contains task prompt path | `{'yes' if contains_task_path else 'no'}` |",
            *task_lines,
            f"| Required prompt markers | `{required_text}` |",
            f"| Required markers present | `{required_present_text}` |",
            f"| Required markers missing | `{required_missing_text}` |",
            f"| Forbidden prompt markers checked | `{forbidden_text}` |",
            f"| Forbidden marker hits | `{forbidden_hits_text}` |",
            *expected_lines,
            "",
            "## First 20 Lines",
            "",
            "```text",
            first_line_block,
            "```",
            "",
        ]
    )


_TEXT_CACHE: dict[Path, str] = {}


def read_cached_text(path: Path) -> str:
    if path not in _TEXT_CACHE:
        _TEXT_CACHE[path] = path.read_text(encoding="utf-8", errors="replace")
    return _TEXT_CACHE[path]


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and validate a Forgis final prompt or Aider message file")
    parser.add_argument("--file", required=True, help="Prompt/message file to inspect")
    parser.add_argument("--label", default="Forgis Prompt")
    parser.add_argument("--task-prompt-file", default="")
    parser.add_argument("--task-prompt-path", default="FORGIS_TASK.md")
    parser.add_argument("--source-repo", default="")
    parser.add_argument("--target-repo", default="")
    parser.add_argument("--target-subdir", default="")
    parser.add_argument("--required-marker", action="append", default=[])
    parser.add_argument("--required-markers-json", default="")
    parser.add_argument("--forbidden-marker", action="append", default=[])
    parser.add_argument("--forbidden-markers-json", default="")
    parser.add_argument("--expected-same-as", default="")
    parser.add_argument("--artifact-output", default="")

    args = parser.parse_args()

    prompt_path = Path(args.file).resolve()
    if not prompt_path.is_file():
        raise FileNotFoundError(f"{args.label} file does not exist: {prompt_path}")

    text = read_cached_text(prompt_path)
    if not text.strip():
        raise ValueError(f"{args.label} file is empty: {prompt_path}")

    digest = sha256_file(prompt_path)
    lines = first_lines(text, count=20)

    required_markers = dedupe_markers(
        [clean_marker(marker, "--required-marker") for marker in args.required_marker]
        + parse_marker_json(args.required_markers_json, "--required-markers-json")
    )
    forbidden_markers = dedupe_markers(
        list(DEFAULT_FORBIDDEN_PROMPT_MARKERS)
        + parse_marker_json(args.forbidden_markers_json, "--forbidden-markers-json")
        + [clean_marker(marker, "--forbidden-marker") for marker in args.forbidden_marker]
    )

    task_first_line = ""
    task_first_line_found: bool | None = None
    task_prompt_sha256: str | None = None
    task_prompt_sha_marker_found: bool | None = None
    if args.task_prompt_file:
        task_path = Path(args.task_prompt_file).resolve()
        if not task_path.is_file():
            raise FileNotFoundError(f"Task prompt file does not exist: {task_path}")
        task_text = task_path.read_text(encoding="utf-8", errors="replace")
        if not task_text.strip():
            raise ValueError(f"Task prompt file is empty: {task_path}")

        task_first_line = first_nonempty_line(task_text)
        task_first_line_found = contains_casefold(text, task_first_line) if task_first_line else None
        task_prompt_sha256 = sha256_text(task_text)
        task_prompt_sha_marker_found = f"{TASK_PROMPT_SHA_PREFIX} {task_prompt_sha256}" in text

    required_present, required_missing = marker_status(text, required_markers)
    forbidden_hits = [marker for marker in forbidden_markers if contains_casefold(text, marker)]

    expected_path: Path | None = None
    expected_digest: str | None = None
    matches_expected: bool | None = None
    if args.expected_same_as:
        expected_path = Path(args.expected_same_as).resolve()
        if not expected_path.is_file():
            raise FileNotFoundError(f"Expected prompt file does not exist: {expected_path}")
        expected_digest = sha256_file(expected_path)
        matches_expected = digest == expected_digest

    markdown = diagnostic_markdown(
        label=args.label,
        path=prompt_path,
        char_count=len(text),
        digest=digest,
        lines=lines,
        task_prompt_path=args.task_prompt_path,
        task_prompt_sha256=task_prompt_sha256,
        task_prompt_sha_marker_found=task_prompt_sha_marker_found,
        task_first_line=task_first_line,
        task_first_line_found=task_first_line_found,
        required_markers=required_markers,
        required_present=required_present,
        required_missing=required_missing,
        forbidden_markers=forbidden_markers,
        forbidden_hits=forbidden_hits,
        expected_path=expected_path,
        expected_digest=expected_digest,
        matches_expected=matches_expected,
    )
    print(markdown)

    if args.artifact_output:
        artifact_output = Path(args.artifact_output).resolve()
        artifact_output.parent.mkdir(parents=True, exist_ok=True)
        artifact_output.write_text(markdown, encoding="utf-8")

    failures: list[str] = []
    if forbidden_hits:
        failures.append("message file contains forbidden prompt markers: " + ", ".join(forbidden_hits))
    if required_missing:
        failures.append("message file is missing required prompt markers: " + ", ".join(required_missing))
    if task_first_line and not task_first_line_found:
        failures.append(f"message file does not include the first task prompt line: {task_first_line}")
    if task_prompt_sha256 and not task_prompt_sha_marker_found:
        failures.append(f"message file does not contain task prompt sha256 marker: {task_prompt_sha256}")
    if args.task_prompt_path and args.task_prompt_path not in text:
        failures.append(f"message file does not mention task prompt path: {args.task_prompt_path}")
    if matches_expected is False:
        failures.append("Aider message file content does not match the generated final prompt")

    if failures:
        print("ERROR: prompt diagnostics failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
