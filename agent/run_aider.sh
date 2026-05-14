#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TARGET_REPO_DIR:-}" ]]; then
  echo "TARGET_REPO_DIR is required." >&2
  exit 1
fi

if [[ -z "${FORGIS_PROMPT_FILE:-}" ]]; then
  echo "FORGIS_PROMPT_FILE is required." >&2
  exit 1
fi

if [[ -z "${AIDER_MODEL:-}" ]]; then
  echo "AIDER_MODEL is required." >&2
  exit 1
fi

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

if [[ ! -f "$FORGIS_PROMPT_FILE" ]]; then
  echo "Forgis prompt file does not exist: $FORGIS_PROMPT_FILE" >&2
  exit 1
fi

cd "$TARGET_REPO_DIR"

echo "Running Aider in target repository:"
pwd

aider \
  --model "$AIDER_MODEL" \
  --message-file "$FORGIS_PROMPT_FILE" \
  --yes-always \
  --no-auto-commits \
  --no-show-release-notes
