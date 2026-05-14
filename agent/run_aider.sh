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

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

if [[ ! -f "$FORGIS_PROMPT_FILE" ]]; then
  echo "Forgis prompt file does not exist: $FORGIS_PROMPT_FILE" >&2
  exit 1
fi

PATH_INFO="$(
  python3 - "$TARGET_REPO_DIR" "$TASK_PROMPT_PATH" "$TARGET_SUBDIR" <<'PY'
import sys
import shlex
from pathlib import Path

target = Path(sys.argv[1]).resolve()
task_prompt_input = sys.argv[2]
target_subdir_input = sys.argv[3]


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
print(f"TARGET_SUBDIR_CREATED={'yes' if target_subdir_created else 'no'}")
PY
)"

eval "$PATH_INFO"

WRITABLE_SEED="$TARGET_SUBDIR_ABS/.forgis-write-scope.md"
if [[ ! -e "$WRITABLE_SEED" ]]; then
  cat > "$WRITABLE_SEED" <<'EOF'
# Forgis Writable Scope

This file marks the directory that Forgis is allowed to modify during this run.
Aider may create, update, or remove files inside this directory to complete the task.
EOF
fi

if ! aider --help 2>/dev/null | grep -q -- "--subtree-only"; then
  echo "Aider does not support --subtree-only; refusing to run without subtree write isolation." >&2
  exit 1
fi

if ! aider --help 2>/dev/null | grep -q -- "--read"; then
  echo "Aider does not support --read; refusing to run without read-only task prompt context." >&2
  exit 1
fi

echo "Running Aider with Forgis scope:"
echo "  target repository: $TARGET_REPO_DIR"
echo "  target writable scope: $TARGET_SUBDIR_REL"
echo "  target writable scope created: $TARGET_SUBDIR_CREATED"
echo "  read-only task prompt: $TASK_PROMPT_REL"
echo "  final prompt file: $FORGIS_PROMPT_FILE"
echo "  final prompt character count: $(wc -c < "$FORGIS_PROMPT_FILE" | tr -d ' ')"
echo "  Aider model: $AIDER_MODEL"
echo "  Aider command summary: aider --model <model> --message-file <forgis_prompt> --read <task_prompt> --subtree-only --yes-always --no-auto-commits --no-show-release-notes <writable_scope_seed>"

cd "$TARGET_SUBDIR_ABS"

aider \
  --model "$AIDER_MODEL" \
  --message-file "$FORGIS_PROMPT_FILE" \
  --read "$TASK_PROMPT_ABS" \
  --subtree-only \
  --yes-always \
  --no-auto-commits \
  --no-show-release-notes \
  "$WRITABLE_SEED"

cd "$TARGET_REPO_DIR"

python3 - "$TARGET_REPO_DIR" "$TARGET_SUBDIR_REL" "$TASK_PROMPT_REL" <<'PY'
import subprocess
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
target_subdir = sys.argv[2].rstrip("/")
task_prompt = sys.argv[3]

status = subprocess.run(
    ["git", "status", "--porcelain"],
    cwd=target,
    check=True,
    text=True,
    stdout=subprocess.PIPE,
).stdout.splitlines()

bad_paths: list[str] = []
task_prompt_changed = False

for line in status:
    if len(line) < 4:
        continue

    path_text = line[3:]
    if " -> " in path_text:
        paths = path_text.split(" -> ", 1)
    else:
        paths = [path_text]

    for path in paths:
        normalized = path.strip().strip('"')
        if normalized == task_prompt:
            task_prompt_changed = True
        if normalized == "MIGRATION_REPORT.md":
            continue
        if normalized == target_subdir or normalized.startswith(target_subdir + "/"):
            continue
        bad_paths.append(normalized)

if task_prompt_changed:
    print(f"ERROR: Aider modified the task prompt file, which is read-only context: {task_prompt}", file=sys.stderr)
    sys.exit(1)

if bad_paths:
    print("ERROR: Aider changed files outside the allowed target writable scope:", file=sys.stderr)
    for path in sorted(set(bad_paths)):
        print(f"  {path}", file=sys.stderr)
    print(f"Allowed scope: {target_subdir}/ plus MIGRATION_REPORT.md", file=sys.stderr)
    sys.exit(1)

scope_root = target / target_subdir
scope_files = [
    path for path in scope_root.rglob("*")
    if path.is_file() and path.name != ".forgis-write-scope.md"
]

if not scope_files:
    print(f"ERROR: Aider completed without creating or retaining files in the target writable scope: {target_subdir}/", file=sys.stderr)
    sys.exit(1)

print("Aider target scope verification passed.")
print(f"  files in writable scope excluding marker: {len(scope_files)}")
PY
