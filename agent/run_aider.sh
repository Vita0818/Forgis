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

if [[ -z "${TASK_PROMPT_PATH:-}" ]]; then
  echo "TASK_PROMPT_PATH is required." >&2
  exit 1
fi

TARGET_SUBDIR="${TARGET_SUBDIR:-forgis-output}"
CONFIG_PATH="${CONFIG_PATH:-FORGIS_CONFIG.yml}"
RUN_LOG_PATH="${RUN_LOG_PATH:-$TARGET_SUBDIR/FORGIS_LOG.md}"
SOURCE_REPO="${SOURCE_REPO:-}"
TARGET_REPO="${TARGET_REPO:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

if [[ ! -f "$FORGIS_PROMPT_FILE" ]]; then
  echo "Forgis prompt file does not exist: $FORGIS_PROMPT_FILE" >&2
  exit 1
fi

PATH_INFO="$(
  python3 - "$TARGET_REPO_DIR" "$TASK_PROMPT_PATH" "$TARGET_SUBDIR" "$CONFIG_PATH" "$RUN_LOG_PATH" <<'PY'
import sys
import shlex
from pathlib import Path

target = Path(sys.argv[1]).resolve()
task_prompt_input = sys.argv[2]
target_subdir_input = sys.argv[3]
config_input = sys.argv[4]
run_log_input = sys.argv[5]


def resolve_inside_target(value: str, label: str, allow_root: bool = False) -> tuple[Path, str]:
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

    if resolved == target and not allow_root:
        raise SystemExit(f"{label} must not resolve to the target repository root.")

    return resolved, resolved.relative_to(target).as_posix()


task_prompt_abs, task_prompt_rel = resolve_inside_target(task_prompt_input, "TASK_PROMPT_PATH")
target_subdir_abs, target_subdir_rel = resolve_inside_target(target_subdir_input, "TARGET_SUBDIR")
config_abs, config_rel = resolve_inside_target(config_input, "CONFIG_PATH")
run_log_abs, run_log_rel = resolve_inside_target(run_log_input, "RUN_LOG_PATH")

if run_log_abs == target_subdir_abs or not run_log_abs.is_relative_to(target_subdir_abs):
    raise SystemExit(f"RUN_LOG_PATH must be inside TARGET_SUBDIR '{target_subdir_rel}/': {run_log_input}")

if not task_prompt_abs.is_file():
    raise SystemExit(f"Task prompt file does not exist in target repository: {task_prompt_rel}")

if task_prompt_abs.stat().st_size == 0:
    raise SystemExit(f"Task prompt file is empty in target repository: {task_prompt_rel}")

target_subdir_created = not target_subdir_abs.exists()
target_subdir_abs.mkdir(parents=True, exist_ok=True)

print(f"TASK_PROMPT_ABS={shlex.quote(str(task_prompt_abs))}")
print(f"TASK_PROMPT_REL={shlex.quote(task_prompt_rel)}")
print(f"TARGET_SUBDIR_ABS={shlex.quote(str(target_subdir_abs))}")
print(f"TARGET_SUBDIR_REL={shlex.quote(target_subdir_rel)}")
print(f"CONFIG_ABS={shlex.quote(str(config_abs))}")
print(f"CONFIG_REL={shlex.quote(config_rel)}")
print(f"CONFIG_FOUND={'yes' if config_abs.is_file() else 'no'}")
print(f"RUN_LOG_ABS={shlex.quote(str(run_log_abs))}")
print(f"RUN_LOG_REL={shlex.quote(run_log_rel)}")
print(f"TARGET_SUBDIR_CREATED={'yes' if target_subdir_created else 'no'}")
PY
)"

eval "$PATH_INFO"

READONLY_SNAPSHOT_DIR="${RUNNER_TEMP:-$TARGET_SUBDIR_ABS}"
mkdir -p "$READONLY_SNAPSHOT_DIR"
READONLY_SNAPSHOT="$READONLY_SNAPSHOT_DIR/forgis-readonly-snapshot.json"
GITIGNORE_SNAPSHOT="$READONLY_SNAPSHOT_DIR/forgis-root-gitignore-snapshot.json"
python3 "$SCRIPT_DIR/guardrails.py" snapshot-readonly \
  --target "$TARGET_REPO_DIR" \
  --config-path "$CONFIG_REL" \
  --task-prompt-path "$TASK_PROMPT_REL" \
  --output "$READONLY_SNAPSHOT"
python3 "$SCRIPT_DIR/guardrails.py" snapshot-root-gitignore \
  --target "$TARGET_REPO_DIR" \
  --output "$GITIGNORE_SNAPSHOT"

WRITABLE_SEED="$TARGET_SUBDIR_ABS/.forgis-write-scope.md"
WRITABLE_SEED_CREATED="no"
if [[ ! -e "$WRITABLE_SEED" ]]; then
  cat > "$WRITABLE_SEED" <<'EOF'
# Forgis Writable Scope

This file marks the directory that Forgis is allowed to modify during this run.
Aider may create, update, or remove files inside this directory to complete the task.
EOF
  WRITABLE_SEED_CREATED="yes"
fi

AIDER_HELP="$(aider --help 2>/dev/null || true)"

if ! printf '%s\n' "$AIDER_HELP" | grep -q -- "--subtree-only"; then
  echo "Aider does not support --subtree-only; refusing to run without subtree write isolation." >&2
  exit 1
fi

if ! printf '%s\n' "$AIDER_HELP" | grep -q -- "--read"; then
  echo "Aider does not support --read; refusing to run without read-only task prompt context." >&2
  exit 1
fi

AIDER_RUNTIME_DIR="${RUNNER_TEMP:-$TARGET_SUBDIR_ABS/.forgis-aider-runtime}/aider"
mkdir -p "$AIDER_RUNTIME_DIR"

AIDER_SAFETY_ARGS=()
if printf '%s\n' "$AIDER_HELP" | grep -q -- "--no-gitignore"; then
  AIDER_SAFETY_ARGS+=(--no-gitignore)
else
  echo "Aider does not advertise --no-gitignore; root .gitignore will be snapshotted and checked." >&2
fi

if printf '%s\n' "$AIDER_HELP" | grep -q -- "--input-history-file"; then
  AIDER_SAFETY_ARGS+=(--input-history-file "$AIDER_RUNTIME_DIR/input.history")
fi

if printf '%s\n' "$AIDER_HELP" | grep -q -- "--chat-history-file"; then
  AIDER_SAFETY_ARGS+=(--chat-history-file "$AIDER_RUNTIME_DIR/chat.history.md")
fi

if printf '%s\n' "$AIDER_HELP" | grep -q -- "--llm-history-file"; then
  AIDER_SAFETY_ARGS+=(--llm-history-file "$AIDER_RUNTIME_DIR/llm.history")
fi

python3 "$SCRIPT_DIR/prompt_diagnostics.py" \
  --file "$FORGIS_PROMPT_FILE" \
  --label "Aider Message File" \
  --task-prompt-file "$TASK_PROMPT_ABS" \
  --task-prompt-path "$TASK_PROMPT_REL" \
  --source-repo "$SOURCE_REPO" \
  --target-repo "$TARGET_REPO" \
  --target-subdir "$TARGET_SUBDIR_REL" \
  --required-markers-json "${REQUIRED_PROMPT_MARKERS_JSON:-[]}" \
  --forbidden-markers-json "${FORBIDDEN_PROMPT_MARKERS_JSON:-[]}" \
  --expected-same-as "$FORGIS_PROMPT_FILE" \
  --artifact-output "${FORGIS_AIDER_DIAGNOSTICS_FILE:-}"

echo "Running Aider with Forgis scope:"
echo "  target repository: $TARGET_REPO_DIR"
echo "  target writable scope: $TARGET_SUBDIR_REL"
echo "  target writable scope created: $TARGET_SUBDIR_CREATED"
echo "  read-only config: $CONFIG_REL (found: $CONFIG_FOUND)"
echo "  read-only task prompt: $TASK_PROMPT_REL"
echo "  long-term run log: $RUN_LOG_REL"
echo "  final prompt file: $FORGIS_PROMPT_FILE"
echo "  final prompt character count: $(wc -c < "$FORGIS_PROMPT_FILE" | tr -d ' ')"
echo "  final prompt sha256: $(shasum -a 256 "$FORGIS_PROMPT_FILE" | awk '{print $1}')"
echo "  final prompt first 20 lines:"
sed -n '1,20p' "$FORGIS_PROMPT_FILE" | sed 's/^/    /'
echo "  final prompt contains task prompt path: $(grep -Fq "$TASK_PROMPT_REL" "$FORGIS_PROMPT_FILE" && echo yes || echo no)"
echo "  required prompt markers json: ${REQUIRED_PROMPT_MARKERS_JSON:-[]}"
echo "  forbidden prompt markers json: ${FORBIDDEN_PROMPT_MARKERS_JSON:-[]}"
echo "  Aider --message-file path: $FORGIS_PROMPT_FILE"
echo "  Aider model: $AIDER_MODEL"
echo "  Aider runtime dir: $AIDER_RUNTIME_DIR"
echo "  Aider command summary: aider --model <model> --message-file <forgis_prompt> --read <task_prompt> --read <config_if_present> ${AIDER_SAFETY_ARGS[*]} --subtree-only --yes-always --no-auto-commits --no-show-release-notes <writable_scope_seed>"

if [[ -n "${FORGIS_AIDER_COMMAND_SUMMARY_FILE:-}" ]]; then
  mkdir -p "$(dirname "$FORGIS_AIDER_COMMAND_SUMMARY_FILE")"
  cat > "$FORGIS_AIDER_COMMAND_SUMMARY_FILE" <<EOF
# Aider Command Summary

- Target repository: \`$TARGET_REPO_DIR\`
- Writable scope: \`$TARGET_SUBDIR_REL/\`
- Read-only task prompt: \`$TASK_PROMPT_REL\`
- Read-only config: \`$CONFIG_REL\`
- Message file: \`$FORGIS_PROMPT_FILE\`
- Message file sha256: \`$(shasum -a 256 "$FORGIS_PROMPT_FILE" | awk '{print $1}')\`
- Runtime dir: \`$AIDER_RUNTIME_DIR\`
- Command: \`aider --model <model> --message-file <forgis_prompt> --read <task_prompt> --read <config_if_present> ${AIDER_SAFETY_ARGS[*]} --subtree-only --yes-always --no-auto-commits --no-show-release-notes <writable_scope_seed>\`
EOF
fi

cd "$TARGET_SUBDIR_ABS"

AIDER_READ_ARGS=(--read "$TASK_PROMPT_ABS")
if [[ "$CONFIG_FOUND" == "yes" ]]; then
  AIDER_READ_ARGS+=(--read "$CONFIG_ABS")
fi

set +e
aider \
  --model "$AIDER_MODEL" \
  --message-file "$FORGIS_PROMPT_FILE" \
  "${AIDER_READ_ARGS[@]}" \
  "${AIDER_SAFETY_ARGS[@]}" \
  --subtree-only \
  --yes-always \
  --no-auto-commits \
  --no-show-release-notes \
  "$WRITABLE_SEED"
AIDER_EXIT=$?
set -e

cd "$TARGET_REPO_DIR"

python3 "$SCRIPT_DIR/guardrails.py" cleanup-aider-root-gitignore \
  --target "$TARGET_REPO_DIR" \
  --snapshot "$GITIGNORE_SNAPSHOT"

python3 "$SCRIPT_DIR/guardrails.py" check-readonly \
  --target "$TARGET_REPO_DIR" \
  --snapshot "$READONLY_SNAPSHOT"

READ_ONLY_ARGS=(--read-only-path "$TASK_PROMPT_REL")
if [[ "$CONFIG_FOUND" == "yes" ]]; then
  READ_ONLY_ARGS+=(--read-only-path "$CONFIG_REL")
fi

python3 "$SCRIPT_DIR/guardrails.py" check-target-scope \
  --target "$TARGET_REPO_DIR" \
  --target-subdir "$TARGET_SUBDIR_REL" \
  "${READ_ONLY_ARGS[@]}"

rm -f "$READONLY_SNAPSHOT"
rm -f "$GITIGNORE_SNAPSHOT"
if [[ "$WRITABLE_SEED_CREATED" == "yes" ]]; then
  rm -f "$WRITABLE_SEED"
fi

if [[ "$AIDER_EXIT" -ne 0 ]]; then
  echo "Aider exited with status $AIDER_EXIT." >&2
  exit "$AIDER_EXIT"
fi

python3 - "$TARGET_REPO_DIR" "$TARGET_SUBDIR_REL" <<'PY'
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
target_subdir = sys.argv[2].rstrip("/")
scope_root = target / target_subdir
scope_files = [
    path for path in scope_root.rglob("*")
    if path.is_file()
    and path.name not in {".forgis-write-scope.md", ".forgis-readonly-snapshot.json"}
]

if not scope_files:
    print(f"ERROR: Aider completed without creating or retaining files in the target writable scope: {target_subdir}/", file=sys.stderr)
    sys.exit(1)

print("Aider target scope verification passed.")
print(f"  files in writable scope excluding Forgis markers: {len(scope_files)}")
PY
