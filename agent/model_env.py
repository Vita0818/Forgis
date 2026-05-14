#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys


ALLOWED_SECRET_ENV_NAMES = {
    "FORGIS_MODEL_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
}
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def parse_model_env_json(text: str) -> tuple[tuple[str, str], ...]:
    try:
        mapping = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"MODEL_ENV_JSON is invalid JSON: {exc}") from exc

    if not isinstance(mapping, dict):
        raise ValueError("MODEL_ENV_JSON must be a JSON object.")

    pairs: list[tuple[str, str]] = []
    for runtime_env, secret_env in sorted(mapping.items()):
        if not isinstance(runtime_env, str) or not ENV_NAME_PATTERN.fullmatch(runtime_env):
            raise ValueError(f"Invalid model_env runtime env name: {runtime_env}")
        if not isinstance(secret_env, str) or not ENV_NAME_PATTERN.fullmatch(secret_env):
            raise ValueError(f"Invalid model_env secret env name for {runtime_env}: {secret_env}")
        if secret_env not in ALLOWED_SECRET_ENV_NAMES:
            raise ValueError(
                f"Model secret env `{secret_env}` is not in the main workflow allowlist. "
                "Add it to the workflow candidate secret env list before using it in model_env."
            )
        pairs.append((runtime_env, secret_env))

    return tuple(pairs)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Forgis model env mappings")
    parser.add_argument("--json", default="{}")
    args = parser.parse_args()

    for runtime_env, secret_env in parse_model_env_json(args.json):
        print(f"{runtime_env}\t{secret_env}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
