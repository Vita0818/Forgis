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

if [[ -z "${DRY_RUN:-}" ]]; then
  echo "DRY_RUN is required." >&2
  exit 1
fi

TARGET_SUBDIR="${TARGET_SUBDIR:-target-output}"
RUN_LOG_PATH="${RUN_LOG_PATH:-$TARGET_SUBDIR/FORGIS_LOG.md}"
CONFIG_PATH="${CONFIG_PATH:-FORGIS_CONFIG.yml}"
TASK_PROMPT_PATH="${TASK_PROMPT_PATH:-FORGIS_TASK.md}"
CONFIRM_REAL_RUN="${CONFIRM_REAL_RUN:-false}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

DRY_RUN_LOWER="$(printf '%s' "$DRY_RUN" | tr '[:upper:]' '[:lower:]')"
case "$DRY_RUN_LOWER" in
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

if [[ "$DRY_RUN_NORMALIZED" == "true" ]]; then
  echo "Dry run enabled. Skipping git add, commit, push, and pull request creation."
  exit 0
fi

cd "$TARGET_REPO_DIR"

git config user.name "forgis-bot"
git config user.email "forgis-bot@users.noreply.github.com"

echo "Preparing target branch: $TARGET_BRANCH"

git fetch origin "$TARGET_BASE_BRANCH:refs/remotes/origin/$TARGET_BASE_BRANCH"
BASE_REF="origin/$TARGET_BASE_BRANCH"

REMOTE_TARGET_BRANCH_EXISTS="false"
if git ls-remote --exit-code --heads origin "$TARGET_BRANCH" >/dev/null 2>&1; then
  REMOTE_TARGET_BRANCH_EXISTS="true"
fi

PUSH_BRANCH="$TARGET_BRANCH"
if [[ "$REMOTE_TARGET_BRANCH_EXISTS" == "true" ]]; then
  FALLBACK_RUN_ID="${GITHUB_RUN_ID:-$(date +%s)}"
  FALLBACK_RUN_ATTEMPT="${GITHUB_RUN_ATTEMPT:-1}"
  PUSH_BRANCH="${TARGET_BRANCH}-run-${FALLBACK_RUN_ID}-${FALLBACK_RUN_ATTEMPT}"
  echo "Remote target branch exists: origin/$TARGET_BRANCH"
  echo "Using fallback branch because pushing $TARGET_BRANCH from $TARGET_BASE_BRANCH may be non-fast-forward."
else
  echo "Remote target branch does not exist: origin/$TARGET_BRANCH"
fi
echo "Actual push branch: $PUSH_BRANCH"
echo "PR head branch: $PUSH_BRANCH"

git checkout -B "$PUSH_BRANCH" "$BASE_REF"

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
    git commit -m "Forgis: apply task output"
  fi
else
  echo "No uncommitted working tree changes detected."
fi

if git diff --quiet "$BASE_REF...HEAD"; then
  echo "No changes detected relative to $TARGET_BASE_BRANCH. Nothing to push."
  exit 0
fi

CONFIRM_REAL_RUN_LOWER="$(printf '%s' "$CONFIRM_REAL_RUN" | tr '[:upper:]' '[:lower:]')"
if [[ "$CONFIRM_REAL_RUN_LOWER" != "true" ]]; then
  echo "Real Forgis runs require confirm_real_run: true in FORGIS_CONFIG.yml." >&2
  exit 1
fi

echo "Pushing branch: $PUSH_BRANCH"
git push -u origin "$PUSH_BRANCH"

echo "Creating pull request..."

if gh pr view "$PUSH_BRANCH" --repo "$TARGET_REPO" >/dev/null 2>&1; then
  echo "Pull request already exists for branch: $PUSH_BRANCH"
else
  COMMIT_SHA="$(git rev-parse --short HEAD 2>/dev/null || true)"
  ACTIONS_RUN_URL=""
  if [[ -n "${GITHUB_SERVER_URL:-}" && -n "${GITHUB_REPOSITORY:-}" && -n "${GITHUB_RUN_ID:-}" ]]; then
    ACTIONS_RUN_URL="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"
  fi
  RUN_REPORT_JSON_PATH="${RUN_REPORT_JSON_PATH:-}"
  if [[ -z "$RUN_REPORT_JSON_PATH" && -n "${GITHUB_WORKSPACE:-}" && -f "$GITHUB_WORKSPACE/forgis-runtime/deepseek_status.env" ]]; then
    # shellcheck disable=SC1090
    source "$GITHUB_WORKSPACE/forgis-runtime/deepseek_status.env"
    RUN_REPORT_JSON_PATH="${report_json_path:-}"
  fi
  if [[ -z "$RUN_REPORT_JSON_PATH" && -n "${GITHUB_WORKSPACE:-}" ]]; then
    RUN_REPORT_JSON_PATH="$GITHUB_WORKSPACE/forgis-runtime/reports/FORGIS_RUN_REPORT.json"
  fi

  PR_BODY_TMPDIR="${RUNNER_TEMP:-${TMPDIR:-/tmp}}"
  mkdir -p "$PR_BODY_TMPDIR"
  PR_BODY_FILE="$(mktemp "$PR_BODY_TMPDIR/forgis-pr-body.XXXXXX.md")"
  SHORT_PR_BODY_FILE="$(mktemp "$PR_BODY_TMPDIR/forgis-pr-body-short.XXXXXX.md")"
  PR_CREATE_OUTPUT_FILE="$(mktemp "$PR_BODY_TMPDIR/forgis-pr-create.XXXXXX.log")"
  trap 'rm -f "${PR_BODY_FILE:-}" "${SHORT_PR_BODY_FILE:-}" "${PR_CREATE_OUTPUT_FILE:-}"' EXIT

  python3 "$SCRIPT_DIR/pr_body.py" \
    --output "$PR_BODY_FILE" \
    --target-branch "$TARGET_BRANCH" \
    --push-branch "$PUSH_BRANCH" \
    --target-base-branch "$TARGET_BASE_BRANCH" \
    --target-subdir "$TARGET_SUBDIR" \
    --commit-sha "$COMMIT_SHA" \
    --dry-run "$DRY_RUN_NORMALIZED" \
    --confirm-real-run "$CONFIRM_REAL_RUN" \
    --remote-target-branch-exists "$REMOTE_TARGET_BRANCH_EXISTS" \
    --run-url "$ACTIONS_RUN_URL" \
    --run-log-path "$RUN_LOG_PATH" \
    --run-report-json-path "$RUN_REPORT_JSON_PATH"

  set +e
  gh pr create \
    --repo "$TARGET_REPO" \
    --base "$TARGET_BASE_BRANCH" \
    --head "$PUSH_BRANCH" \
    --title "Forgis task output" \
    --body-file "$PR_BODY_FILE" >"$PR_CREATE_OUTPUT_FILE" 2>&1
  PR_CREATE_STATUS=$?
  set -e
  cat "$PR_CREATE_OUTPUT_FILE"

  if [[ "$PR_CREATE_STATUS" -ne 0 ]]; then
    if grep -qiE "body is too long|maximum is 65536|createPullRequest" "$PR_CREATE_OUTPUT_FILE"; then
      echo "Pull request body was rejected as too long. Retrying with a minimal Forgis body."
      python3 "$SCRIPT_DIR/pr_body.py" \
        --mode short \
        --output "$SHORT_PR_BODY_FILE" \
        --target-branch "$TARGET_BRANCH" \
        --push-branch "$PUSH_BRANCH" \
        --target-base-branch "$TARGET_BASE_BRANCH" \
        --target-subdir "$TARGET_SUBDIR" \
        --commit-sha "$COMMIT_SHA" \
        --run-url "$ACTIONS_RUN_URL" \
        --run-report-json-path "$RUN_REPORT_JSON_PATH"

      gh pr create \
        --repo "$TARGET_REPO" \
        --base "$TARGET_BASE_BRANCH" \
        --head "$PUSH_BRANCH" \
        --title "Forgis task output" \
        --body-file "$SHORT_PR_BODY_FILE"
    else
      exit "$PR_CREATE_STATUS"
    fi
  fi
fi
