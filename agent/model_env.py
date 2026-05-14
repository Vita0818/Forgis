#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping


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
        pairs.append((runtime_env, secret_env))

    return tuple(pairs)


def resolve_model_env_values(
    pairs: tuple[tuple[str, str], ...],
    environ: Mapping[str, str],
) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    missing: list[str] = []
    for runtime_env, secret_env in pairs:
        value = environ.get(secret_env, "")
        if value:
            values[runtime_env] = value
        else:
            missing.append(secret_env)
    return values, sorted(set(missing))


def require_model_env_values(
    pairs: tuple[tuple[str, str], ...],
    environ: Mapping[str, str],
) -> dict[str, str]:
    if not pairs:
        raise ValueError("model_env must map at least one runtime env name before DeepSeek is called.")
    values, missing = resolve_model_env_values(pairs, environ)
    if missing:
        raise ValueError("Missing required model secret env var(s): " + ", ".join(missing))
    return values


def describe_model_env(
    pairs: tuple[tuple[str, str], ...],
    environ: Mapping[str, str],
) -> list[dict[str, str]]:
    description: list[dict[str, str]] = []
    for runtime_env, secret_env in pairs:
        description.append(
            {
                "runtime_env": runtime_env,
                "secret_env": secret_env,
                "present": "yes" if bool(environ.get(secret_env, "")) else "no",
            }
        )
    return description


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Forgis model env mappings without printing values")
    parser.add_argument("--json", default="{}")
    parser.add_argument("--require-present", action="store_true")
    args = parser.parse_args()

    pairs = parse_model_env_json(args.json)
    if args.require_present:
        require_model_env_values(pairs, os.environ)

    for item in describe_model_env(pairs, os.environ):
        print(f"{item['runtime_env']}\t{item['secret_env']}\t{item['present']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
