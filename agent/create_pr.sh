#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TARGET_REPO_DIR:-}" ]]; then
  echo "TARGET_REPO_DIR is required." >&2
  exit 1
fi

if [[ -z "${TARGET_REPO:-}" ]]; then
  echo "TARGET_REPO is required, for example owner/target-repo." >&2
  exit 1
fi

if [[ -z "${TARGET_BRANCH:-}" ]]; then
  echo "TARGET_BRANCH is required." >&2
  exit 1
fi

if [[ -z "${TARGET_BASE_BRANCH:-}" ]]; then
  echo "TARGET_BASE_BRANCH is required." >&2
  exit 1
fi

if [[ -z "${TARGET_PLATFORM:-}" ]]; then
  echo "TARGET_PLATFORM is required." >&2
  exit 1
fi

if [[ -z "${TARGET_STACK:-}" ]]; then
  echo "TARGET_STACK is required." >&2
  exit 1
fi

if [[ -z "${DRY_RUN:-}" ]]; then
  echo "DRY_RUN is required." >&2
  exit 1
fi

TARGET_SUBDIR="${TARGET_SUBDIR:-forgis-output}"
RUN_LOG_PATH="${RUN_LOG_PATH:-$TARGET_SUBDIR/FORGIS_LOG.md}"
CONFIG_PATH="${CONFIG_PATH:-FORGIS_CONFIG.yml}"
TASK_PROMPT_PATH="${TASK_PROMPT_PATH:-FORGIS_TASK.md}"
CONFIRM_REAL_RUN="${CONFIRM_REAL_RUN:-false}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

case "${DRY_RUN,,}" in
  true|1|yes|y|on)
    DRY_RUN_NORMALIZED="true"
    ;;
  false|0|no|n|off)
    DRY_RUN_NORMALIZED="false"
    ;;
  *)
    echo "DRY_RUN must be a boolean-like value, got: $DRY_RUN" >&2
    exit 1
    ;;
esac

cd "$TARGET_REPO_DIR"

git config user.name "forgis-bot"
git config user.email "forgis-bot@users.noreply.github.com"

echo "Preparing target branch: $TARGET_BRANCH"

git fetch origin "$TARGET_BASE_BRANCH:refs/remotes/origin/$TARGET_BASE_BRANCH"
BASE_REF="origin/$TARGET_BASE_BRANCH"

git checkout -B "$TARGET_BRANCH"

python3 "$SCRIPT_DIR/guardrails.py" check-target-scope \
  --target "$TARGET_REPO_DIR" \
  --target-subdir "$TARGET_SUBDIR" \
  --read-only-path "$CONFIG_PATH" \
  --read-only-path "$TASK_PROMPT_PATH"

if [[ -n "$(git status --porcelain)" ]]; then
  git add .

  if git diff --cached --quiet; then
    echo "No staged changes detected after git add."
  else
    git commit -m "Forgis: sync source to $TARGET_PLATFORM using $TARGET_STACK"
  fi
else
  echo "No uncommitted working tree changes detected."
fi

if git diff --quiet "$BASE_REF...HEAD"; then
  echo "No changes detected relative to $TARGET_BASE_BRANCH. Nothing to push."
  exit 0
fi

if [[ "$DRY_RUN_NORMALIZED" == "true" ]]; then
  echo "Dry run enabled. Skipping push and pull request creation."
  exit 0
fi

if [[ "${CONFIRM_REAL_RUN,,}" != "true" ]]; then
  echo "Real AI migration requires confirm_real_run: true in FORGIS_CONFIG.yml." >&2
  exit 1
fi

echo "Pushing branch: $TARGET_BRANCH"
git push -u origin "$TARGET_BRANCH"

echo "Creating pull request..."

if gh pr view "$TARGET_BRANCH" --repo "$TARGET_REPO" >/dev/null 2>&1; then
  echo "Pull request already exists for branch: $TARGET_BRANCH"
else
  gh pr create \
    --repo "$TARGET_REPO" \
    --base "$TARGET_BASE_BRANCH" \
    --head "$TARGET_BRANCH" \
    --title "Forgis sync: source to $TARGET_PLATFORM" \
    --body-file "$RUN_LOG_PATH"
fi
