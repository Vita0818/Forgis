#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import shlex
import sys
from pathlib import Path


SUPPORTED_FLAGS = (
    "--read",
    "--subtree-only",
    "--no-gitignore",
    "--input-history-file",
    "--chat-history-file",
    "--llm-history-file",
)


def supports_flag(help_text: str, flag: str) -> bool:
    escaped = re.escape(flag)
    pattern = rf"(^|[\s,]){escaped}($|[\s,=])"
    return re.search(pattern, help_text) is not None


def analyze_help(help_text: str) -> dict[str, bool | str]:
    capabilities: dict[str, bool | str] = {
        "supports_read": supports_flag(help_text, "--read"),
        "supports_subtree_only": supports_flag(help_text, "--subtree-only"),
        "supports_no_gitignore": supports_flag(help_text, "--no-gitignore"),
        "supports_input_history_file": supports_flag(help_text, "--input-history-file"),
        "supports_chat_history_file": supports_flag(help_text, "--chat-history-file"),
        "supports_llm_history_file": supports_flag(help_text, "--llm-history-file"),
    }
    capabilities["context_mode"] = "read-context" if capabilities["supports_read"] else "message-file-only"
    return capabilities


def shell_bool(value: bool | str) -> str:
    return "yes" if value is True else "no"


def shell_assignments(capabilities: dict[str, bool | str]) -> str:
    lines: list[str] = []
    for key, value in capabilities.items():
        env_key = "AIDER_" + key.upper()
        if isinstance(value, bool):
            shell_value = shell_bool(value)
        else:
            shell_value = value
        lines.append(f"{env_key}={shlex.quote(shell_value)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse Aider help text into Forgis capability flags")
    parser.add_argument("--help-file", required=True)
    parser.add_argument("--shell-output", action="store_true")
    args = parser.parse_args()

    help_text = Path(args.help_file).read_text(encoding="utf-8", errors="replace")
    capabilities = analyze_help(help_text)
    if args.shell_output:
        print(shell_assignments(capabilities))
        return

    for key, value in capabilities.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
