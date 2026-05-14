#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TARGET_REPO_DIR:-}" ]]; then
  echo "TARGET_REPO_DIR is required." >&2
  exit 1
fi

TARGET_SUBDIR="${TARGET_SUBDIR:-target-output}"
VALIDATION_COMMANDS_JSON="${VALIDATION_COMMANDS_JSON:-[]}"

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

PATH_INFO="$(
  python3 - "$TARGET_REPO_DIR" "$TARGET_SUBDIR" <<'PY'
import shlex
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
target_subdir_input = sys.argv[2]

raw = Path(target_subdir_input.strip())
if not target_subdir_input.strip():
    raise SystemExit("TARGET_SUBDIR is required.")
if raw.is_absolute():
    raise SystemExit(f"TARGET_SUBDIR must be relative to the target repository root: {target_subdir_input}")
if any(part in {"", ".", "..", ".git"} for part in raw.parts):
    raise SystemExit(f"TARGET_SUBDIR contains an unsafe path segment: {target_subdir_input}")

resolved = (target / raw).resolve()
if not resolved.is_relative_to(target) or resolved == target:
    raise SystemExit(f"TARGET_SUBDIR must stay inside the target repository and not be the root: {target_subdir_input}")

print(f"TARGET_BUILD_DIR={shlex.quote(str(resolved))}")
print(f"TARGET_SUBDIR_REL={shlex.quote(resolved.relative_to(target).as_posix())}")
PY
)"

eval "$PATH_INFO"
mkdir -p "$TARGET_BUILD_DIR"

echo "Forgis validation command scope:"
echo "  target repository: $TARGET_REPO_DIR"
echo "  target output directory: $TARGET_SUBDIR_REL"

python3 - "$TARGET_BUILD_DIR" "$VALIDATION_COMMANDS_JSON" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

cwd = Path(sys.argv[1]).resolve()
raw = sys.argv[2]
try:
    commands = json.loads(raw or "[]")
except json.JSONDecodeError as exc:
    raise SystemExit(f"VALIDATION_COMMANDS_JSON is invalid JSON: {exc}")

if not isinstance(commands, list):
    raise SystemExit("VALIDATION_COMMANDS_JSON must be a JSON list.")

if not commands:
    print("No validation_commands configured. Skipping generic target validation commands.")
    raise SystemExit(0)

for index, command in enumerate(commands):
    if not isinstance(command, str) or not command.strip():
        raise SystemExit(f"validation_commands[{index}] must be a non-empty string.")
    print(f"Running validation_commands[{index}]: {command}")
    result = subprocess.run(
        ["bash", "-lc", command],
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.returncode != 0:
        raise SystemExit(f"validation_commands[{index}] failed with exit {result.returncode}.")

print("Configured validation_commands completed successfully.")
PY
