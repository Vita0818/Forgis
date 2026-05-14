#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TARGET_REPO_DIR:-}" ]]; then
  echo "TARGET_REPO_DIR is required." >&2
  exit 1
fi

if [[ -z "${SOURCE_REPO_DIR:-}" ]]; then
  echo "SOURCE_REPO_DIR is required." >&2
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

TARGET_SUBDIR="${TARGET_SUBDIR:-target-output}"
CONFIG_PATH="${CONFIG_PATH:-FORGIS_CONFIG.yml}"
TASK_PROMPT_PATH="${TASK_PROMPT_PATH:-FORGIS_TASK.md}"
RUN_LOG_PATH="${RUN_LOG_PATH:-$TARGET_SUBDIR/FORGIS_LOG.md}"
DRY_RUN="${DRY_RUN:-true}"
RUN_AGENT="${RUN_AGENT:-false}"
SOURCE_REPO="${SOURCE_REPO:-}"
TARGET_REPO="${TARGET_REPO:-}"
SOURCE_CONTEXT_FILE="${SOURCE_CONTEXT_FILE:-}"
SUCCESS_CHECKS_JSON="${SUCCESS_CHECKS_JSON:-[]}"
if [[ -z "${MODEL_ENV_JSON:-}" ]]; then
  MODEL_ENV_JSON="{}"
fi
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "DRY_RUN is true. Refusing to invoke Aider." >&2
  exit 1
fi

if [[ "$RUN_AGENT" != "true" ]]; then
  echo "RUN_AGENT is not true. Refusing to invoke Aider." >&2
  exit 1
fi

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

if [[ ! -d "$SOURCE_REPO_DIR" ]]; then
  echo "Source repository directory does not exist: $SOURCE_REPO_DIR" >&2
  exit 1
fi

if [[ ! -f "$FORGIS_PROMPT_FILE" ]]; then
  echo "Forgis Aider message file does not exist: $FORGIS_PROMPT_FILE" >&2
  exit 1
fi

PATH_INFO="$(
  python3 - "$TARGET_REPO_DIR" "$TASK_PROMPT_PATH" "$TARGET_SUBDIR" "$CONFIG_PATH" "$RUN_LOG_PATH" <<'PY'
import shlex
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
task_prompt_input = sys.argv[2]
target_subdir_input = sys.argv[3]
config_input = sys.argv[4]
run_log_input = sys.argv[5]


def resolve_inside_target(value: str, label: str) -> tuple[Path, str]:
    if not value.strip():
        raise SystemExit(f"{label} is required.")

    raw = Path(value.strip())
    if raw.is_absolute():
        raise SystemExit(f"{label} must be relative to the target repository root: {value}")

    if any(part in {"", ".", "..", ".git"} for part in raw.parts):
        raise SystemExit(f"{label} contains an unsafe path segment: {value}")

    resolved = (target / raw).resolve()
    if not resolved.is_relative_to(target):
        raise SystemExit(f"{label} escapes the target repository root: {value}")

    if resolved == target:
        raise SystemExit(f"{label} must not resolve to the target repository root.")

    return resolved, resolved.relative_to(target).as_posix()


task_prompt_abs, task_prompt_rel = resolve_inside_target(task_prompt_input, "TASK_PROMPT_PATH")
target_subdir_abs, target_subdir_rel = resolve_inside_target(target_subdir_input, "TARGET_SUBDIR")
config_abs, config_rel = resolve_inside_target(config_input, "CONFIG_PATH")
run_log_abs, run_log_rel = resolve_inside_target(run_log_input, "RUN_LOG_PATH")

if run_log_abs == target_subdir_abs or not run_log_abs.is_relative_to(target_subdir_abs):
    raise SystemExit(f"RUN_LOG_PATH must be inside TARGET_SUBDIR '{target_subdir_rel}/': {run_log_input}")

if not config_abs.is_file():
    raise SystemExit(f"Config file does not exist in target repository: {config_rel}")

if not task_prompt_abs.is_file():
    raise SystemExit(f"Task file does not exist in target repository: {task_prompt_rel}")

if not task_prompt_abs.read_text(encoding="utf-8", errors="replace").strip():
    raise SystemExit(f"Task file is empty in target repository: {task_prompt_rel}")

target_subdir_abs.mkdir(parents=True, exist_ok=True)

print(f"TASK_PROMPT_ABS={shlex.quote(str(task_prompt_abs))}")
print(f"TASK_PROMPT_REL={shlex.quote(task_prompt_rel)}")
print(f"TARGET_SUBDIR_ABS={shlex.quote(str(target_subdir_abs))}")
print(f"TARGET_SUBDIR_REL={shlex.quote(target_subdir_rel)}")
print(f"CONFIG_ABS={shlex.quote(str(config_abs))}")
print(f"CONFIG_REL={shlex.quote(config_rel)}")
print(f"RUN_LOG_ABS={shlex.quote(str(run_log_abs))}")
print(f"RUN_LOG_REL={shlex.quote(run_log_rel)}")
PY
)"

eval "$PATH_INFO"

AIDER_RUNTIME_DIR="${RUNNER_TEMP:-$TARGET_SUBDIR_ABS/.forgis-aider-runtime}/aider"
mkdir -p "$AIDER_RUNTIME_DIR"

READONLY_SNAPSHOT_DIR="${RUNNER_TEMP:-$TARGET_SUBDIR_ABS/.forgis-aider-runtime}"
mkdir -p "$READONLY_SNAPSHOT_DIR"
READONLY_SNAPSHOT="$READONLY_SNAPSHOT_DIR/forgis-readonly-snapshot.json"
GITIGNORE_SNAPSHOT="$READONLY_SNAPSHOT_DIR/forgis-root-gitignore-snapshot.json"
TAGS_CACHE_SNAPSHOT="$READONLY_SNAPSHOT_DIR/forgis-aider-tags-cache-snapshot.json"
AIDER_BEFORE_SNAPSHOT="$READONLY_SNAPSHOT_DIR/forgis-aider-before-output-snapshot.json"

python3 "$SCRIPT_DIR/guardrails.py" snapshot-readonly \
  --target "$TARGET_REPO_DIR" \
  --config-path "$CONFIG_REL" \
  --task-prompt-path "$TASK_PROMPT_REL" \
  --output "$READONLY_SNAPSHOT"
python3 "$SCRIPT_DIR/guardrails.py" snapshot-root-gitignore \
  --target "$TARGET_REPO_DIR" \
  --output "$GITIGNORE_SNAPSHOT"
python3 "$SCRIPT_DIR/guardrails.py" snapshot-aider-tags-cache \
  --target "$TARGET_REPO_DIR" \
  --output "$TAGS_CACHE_SNAPSHOT"
python3 "$SCRIPT_DIR/validate_target_output.py" snapshot \
  --target "$TARGET_REPO_DIR" \
  --target-subdir "$TARGET_SUBDIR_REL" \
  --output "$AIDER_BEFORE_SNAPSHOT"

AIDER_HELP_FILE="$AIDER_RUNTIME_DIR/aider-help.txt"
AIDER_VERSION="$(aider --version 2>&1 || true)"
AIDER_VERSION="${AIDER_VERSION%%$'\n'*}"
aider --help > "$AIDER_HELP_FILE" 2>&1 || true

CAPABILITY_INFO="$(
  python3 "$SCRIPT_DIR/aider_compat.py" \
    --help-file "$AIDER_HELP_FILE" \
    --shell-output
)"
eval "$CAPABILITY_INFO"

if [[ "$AIDER_SUPPORTS_SUBTREE_ONLY" != "yes" ]]; then
  echo "Aider does not support --subtree-only; refusing to run without target_subdir write isolation." >&2
  exit 1
fi

if [[ "$AIDER_SUPPORTS_READ" != "yes" ]]; then
  echo "Aider backend does not support --read; refusing to run because Forgis will not copy task/config/source content into a large prompt." >&2
  exit 1
fi

AIDER_SAFETY_ARGS=()
if [[ "$AIDER_SUPPORTS_NO_GITIGNORE" == "yes" ]]; then
  AIDER_SAFETY_ARGS+=(--no-gitignore)
else
  echo "Aider does not advertise --no-gitignore; root .gitignore will be snapshotted and checked." >&2
fi

if [[ "$AIDER_SUPPORTS_INPUT_HISTORY_FILE" == "yes" ]]; then
  AIDER_SAFETY_ARGS+=(--input-history-file "$AIDER_RUNTIME_DIR/input.history")
fi

if [[ "$AIDER_SUPPORTS_CHAT_HISTORY_FILE" == "yes" ]]; then
  AIDER_SAFETY_ARGS+=(--chat-history-file "$AIDER_RUNTIME_DIR/chat.history.md")
fi

if [[ "$AIDER_SUPPORTS_LLM_HISTORY_FILE" == "yes" ]]; then
  AIDER_SAFETY_ARGS+=(--llm-history-file "$AIDER_RUNTIME_DIR/llm.history")
fi

AIDER_READ_ARGS=(--read "$TASK_PROMPT_ABS" --read "$CONFIG_ABS")
if [[ -n "$SOURCE_CONTEXT_FILE" ]]; then
  if [[ ! -f "$SOURCE_CONTEXT_FILE" ]]; then
    echo "SOURCE_CONTEXT_FILE does not exist: $SOURCE_CONTEXT_FILE" >&2
    exit 1
  fi
  AIDER_READ_ARGS+=(--read "$SOURCE_CONTEXT_FILE")
fi

MODEL_ENV_PAIRS="$(python3 "$SCRIPT_DIR/model_env.py" --json "$MODEL_ENV_JSON")"

MODEL_ENV_SUMMARY=()
if [[ -n "$MODEL_ENV_PAIRS" ]]; then
  while IFS=$'\t' read -r runtime_env secret_env; do
    if [[ -z "$runtime_env" ]]; then
      continue
    fi
    secret_value="${!secret_env:-}"
    if [[ -z "$secret_value" ]]; then
      echo "Required model secret env \`$secret_env\` is not available. Add it to the workflow environment or update FORGIS_CONFIG.yml model_env." >&2
      exit 1
    fi
    export "$runtime_env=$secret_value"
    MODEL_ENV_SUMMARY+=("$runtime_env <- $secret_env: present")
  done <<< "$MODEL_ENV_PAIRS"
else
  MODEL_ENV_SUMMARY+=("[none configured]")
fi

python3 "$SCRIPT_DIR/prompt_diagnostics.py" \
  --file "$FORGIS_PROMPT_FILE" \
  --label "Aider Message File" \
  --task-prompt-file "$TASK_PROMPT_ABS" \
  --task-prompt-path "$TASK_PROMPT_REL" \
  --source-path "$SOURCE_REPO_DIR" \
  --target-path "$TARGET_REPO_DIR" \
  --target-subdir "$TARGET_SUBDIR_REL" \
  --forbidden-markers-json "${FORBIDDEN_PROMPT_MARKERS_JSON:-[]}" \
  --expected-same-as "$FORGIS_PROMPT_FILE" \
  --artifact-output "${FORGIS_AIDER_DIAGNOSTICS_FILE:-}"

echo "Running Aider with Forgis scope:"
echo "  source repository path: $SOURCE_REPO_DIR"
echo "  target repository path: $TARGET_REPO_DIR"
echo "  target writable scope: $TARGET_SUBDIR_REL"
echo "  read-only config: $CONFIG_REL"
echo "  read-only task file: $TASK_PROMPT_REL"
echo "  long-term run log: $RUN_LOG_REL"
echo "  message file: $FORGIS_PROMPT_FILE"
echo "  message character count: $(wc -c < "$FORGIS_PROMPT_FILE" | tr -d ' ')"
echo "  Aider version: ${AIDER_VERSION:-[unknown]}"
echo "  Aider supports --read: $AIDER_SUPPORTS_READ"
echo "  Aider supports --subtree-only: $AIDER_SUPPORTS_SUBTREE_ONLY"
echo "  Aider model: $AIDER_MODEL"
echo "  source context file: ${SOURCE_CONTEXT_FILE:-[none]}"
echo "  model env mapping:"
for model_env_line in "${MODEL_ENV_SUMMARY[@]}"; do
  echo "    $model_env_line"
done
echo "  Aider runtime dir: $AIDER_RUNTIME_DIR"
echo "  Aider working directory: $TARGET_SUBDIR_ABS"
echo "  Aider command summary: aider --model <model> --message-file <forgis_message> --read <task> --read <config> ${AIDER_SAFETY_ARGS[*]} --subtree-only --yes-always --no-auto-commits --no-show-release-notes"

if [[ -n "${FORGIS_AIDER_COMMAND_SUMMARY_FILE:-}" ]]; then
  mkdir -p "$(dirname "$FORGIS_AIDER_COMMAND_SUMMARY_FILE")"
  {
    echo "# Aider Command Summary"
    echo ""
    echo "- Source repository path: \`$SOURCE_REPO_DIR\`"
    echo "- Target repository path: \`$TARGET_REPO_DIR\`"
    echo "- Writable scope: \`$TARGET_SUBDIR_REL/\`"
    echo "- Read-only task file: \`$TASK_PROMPT_REL\`"
    echo "- Read-only config: \`$CONFIG_REL\`"
    echo "- Message file: \`$FORGIS_PROMPT_FILE\`"
    echo "- Aider version: \`${AIDER_VERSION:-[unknown]}\`"
    echo "- Supports --read: \`$AIDER_SUPPORTS_READ\`"
    echo "- Supports --subtree-only: \`$AIDER_SUPPORTS_SUBTREE_ONLY\`"
    echo "- Source context file: \`${SOURCE_CONTEXT_FILE:-[none]}\`"
    echo "- Runtime dir: \`$AIDER_RUNTIME_DIR\`"
    echo "- Working directory: \`$TARGET_SUBDIR_ABS\`"
    echo "- Command: \`aider --model <model> --message-file <forgis_message> --read <task> --read <config> ${AIDER_SAFETY_ARGS[*]} --subtree-only --yes-always --no-auto-commits --no-show-release-notes\`"
  } > "$FORGIS_AIDER_COMMAND_SUMMARY_FILE"
fi

cd "$TARGET_SUBDIR_ABS"

set +e
aider \
  --model "$AIDER_MODEL" \
  --message-file "$FORGIS_PROMPT_FILE" \
  "${AIDER_READ_ARGS[@]}" \
  "${AIDER_SAFETY_ARGS[@]}" \
  --subtree-only \
  --yes-always \
  --no-auto-commits \
  --no-show-release-notes
AIDER_EXIT=$?
set -e

cd "$TARGET_REPO_DIR"

if [[ -n "${FORGIS_AIDER_STATUS_FILE:-}" ]]; then
  mkdir -p "$(dirname "$FORGIS_AIDER_STATUS_FILE")"
  {
    echo "aider_executed=true"
    echo "aider_exit_status=$AIDER_EXIT"
  } > "$FORGIS_AIDER_STATUS_FILE"
fi

python3 "$SCRIPT_DIR/guardrails.py" cleanup-aider-root-gitignore \
  --target "$TARGET_REPO_DIR" \
  --snapshot "$GITIGNORE_SNAPSHOT"
python3 "$SCRIPT_DIR/guardrails.py" cleanup-aider-tags-cache \
  --target "$TARGET_REPO_DIR" \
  --snapshot "$TAGS_CACHE_SNAPSHOT"

python3 "$SCRIPT_DIR/guardrails.py" check-readonly \
  --target "$TARGET_REPO_DIR" \
  --snapshot "$READONLY_SNAPSHOT"

python3 "$SCRIPT_DIR/guardrails.py" check-target-scope \
  --target "$TARGET_REPO_DIR" \
  --target-subdir "$TARGET_SUBDIR_REL" \
  --read-only-path "$TASK_PROMPT_REL" \
  --read-only-path "$CONFIG_REL"

rm -f "$READONLY_SNAPSHOT"
rm -f "$GITIGNORE_SNAPSHOT"
rm -f "$TAGS_CACHE_SNAPSHOT"

if [[ "$AIDER_EXIT" -ne 0 ]]; then
  echo "Aider exited with status $AIDER_EXIT." >&2
  exit "$AIDER_EXIT"
fi

python3 "$SCRIPT_DIR/validate_target_output.py" validate \
  --target "$TARGET_REPO_DIR" \
  --target-subdir "$TARGET_SUBDIR_REL" \
  --run-log-path "$RUN_LOG_REL" \
  --snapshot "$AIDER_BEFORE_SNAPSHOT" \
  --require-meaningful-change \
  --success-checks-json "$SUCCESS_CHECKS_JSON"

rm -f "$AIDER_BEFORE_SNAPSHOT"
