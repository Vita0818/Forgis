#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path


FORBIDDEN_GREETING_EXAMPLE = " ".join(("make", "the", "greeting", "more", "casual"))
FORBIDDEN_STALE_PROMPT_SNIPPETS = (
    FORBIDDEN_GREETING_EXAMPLE,
    "casual greeting",
    "Which file (or which phrase)",
    "welcome message",
    "toast text",
)
KIKARIA_TASK_MARKER = "Kikaria Android Migration Task"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def should_require_kikaria_marker(source_repo: str, target_subdir: str, required_marker: str) -> bool:
    if required_marker:
        return True
    return "kikaria" in source_repo.casefold() or target_subdir == "Kikaria-Android"


def diagnostic_markdown(
    *,
    label: str,
    path: Path,
    char_count: int,
    digest: str,
    lines: list[str],
    contains_task_marker: bool,
    contains_task_path: bool,
    contains_forbidden_greeting: bool,
    contains_hello: bool,
    contains_hey: bool,
    contains_greeting_word: bool,
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

    first_line_block = "\n".join(lines) if lines else "[empty]"
    return "\n".join(
        [
            f"# {label} Diagnostics",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Path | `{path}` |",
            f"| Character count | `{char_count}` |",
            f"| SHA256 | `{digest}` |",
            f"| Contains {KIKARIA_TASK_MARKER} | `{'yes' if contains_task_marker else 'no'}` |",
            f"| Contains FORGIS_TASK.md | `{'yes' if contains_task_path else 'no'}` |",
            f"| Contains forbidden greeting example | `{'yes' if contains_forbidden_greeting else 'no'}` |",
            f"| Contains Hello | `{'yes' if contains_hello else 'no'}` |",
            f"| Contains Hey | `{'yes' if contains_hey else 'no'}` |",
            f"| Contains greeting | `{'yes' if contains_greeting_word else 'no'}` |",
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect and validate a Forgis final prompt or Aider message file")
    parser.add_argument("--file", required=True, help="Prompt/message file to inspect")
    parser.add_argument("--label", default="Forgis Prompt")
    parser.add_argument("--task-prompt-file", default="")
    parser.add_argument("--task-prompt-path", default="FORGIS_TASK.md")
    parser.add_argument("--source-repo", default="")
    parser.add_argument("--target-repo", default="")
    parser.add_argument("--target-subdir", default="")
    parser.add_argument("--required-marker", default="")
    parser.add_argument("--expected-same-as", default="")
    parser.add_argument("--artifact-output", default="")

    args = parser.parse_args()

    prompt_path = Path(args.file).resolve()
    if not prompt_path.is_file():
        raise FileNotFoundError(f"{args.label} file does not exist: {prompt_path}")

    text = prompt_path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"{args.label} file is empty: {prompt_path}")

    digest = sha256_file(prompt_path)
    lines = first_lines(text, count=20)

    task_text = ""
    task_first_line = ""
    if args.task_prompt_file:
        task_path = Path(args.task_prompt_file).resolve()
        if not task_path.is_file():
            raise FileNotFoundError(f"Task prompt file does not exist: {task_path}")
        task_text = task_path.read_text(encoding="utf-8", errors="replace")
        if not task_text.strip():
            raise ValueError(f"Task prompt file is empty: {task_path}")
        task_first_line = first_nonempty_line(task_text)

    required_marker = args.required_marker
    if should_require_kikaria_marker(args.source_repo, args.target_subdir, required_marker):
        required_marker = required_marker or KIKARIA_TASK_MARKER

    contains_task_marker = contains_casefold(text, KIKARIA_TASK_MARKER)
    contains_task_path = args.task_prompt_path in text
    contains_forbidden_greeting = any(contains_casefold(text, snippet) for snippet in FORBIDDEN_STALE_PROMPT_SNIPPETS)
    contains_hello = contains_casefold(text, "Hello")
    contains_hey = contains_casefold(text, "Hey")
    contains_greeting_word = contains_casefold(text, "greeting")

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
        contains_task_marker=contains_task_marker,
        contains_task_path=contains_task_path,
        contains_forbidden_greeting=contains_forbidden_greeting,
        contains_hello=contains_hello,
        contains_hey=contains_hey,
        contains_greeting_word=contains_greeting_word,
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
    if contains_forbidden_greeting:
        failures.append("message file contains the forbidden greeting example or stale greeting prompt")
    if required_marker and contains_hello:
        failures.append("message file contains stale greeting token: Hello")
    if required_marker and contains_hey:
        failures.append("message file contains stale greeting token: Hey")
    if required_marker and contains_greeting_word:
        failures.append("message file contains stale greeting token: greeting")
    if required_marker and not contains_casefold(text, required_marker):
        failures.append(f"message file does not contain required task marker: {required_marker}")
    if task_first_line and not contains_casefold(text, task_first_line):
        failures.append(f"message file does not include the first task prompt line: {task_first_line}")
    if args.task_prompt_path and args.task_prompt_path not in text:
        failures.append(f"message file does not mention task prompt path: {args.task_prompt_path}")
    if matches_expected is False:
        failures.append("Aider message file content does not match the generated final prompt")
    if required_marker:
        for label, value in (
            ("source_repo", args.source_repo),
            ("target_repo", args.target_repo),
            ("target_subdir", args.target_subdir),
        ):
            if value and value not in text:
                failures.append(f"message file does not contain {label}: {value}")

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
