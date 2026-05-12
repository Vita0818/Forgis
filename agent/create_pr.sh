#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TARGET_REPO_DIR:-}" ]]; then
  echo "TARGET_REPO_DIR is required." >&2
  exit 1
fi

if [[ -z "${TARGET_REPO:-}" ]]; then
  echo "TARGET_REPO is required, for example Vita0818/Kikaria-Android." >&2
  exit 1
fi

if [[ -z "${TARGET_BRANCH:-}" ]]; then
  echo "TARGET_BRANCH is required." >&2
  exit 1
fi

if [[ -z "${TARGET_PLATFORM:-}" ]]; then
  echo "TARGET_PLATFORM is required." >&2
  exit 1
fi

if [[ -z "${DRY_RUN:-}" ]]; then
  echo "DRY_RUN is required." >&2
  exit 1
fi

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

cd "$TARGET_REPO_DIR"

git config user.name "forgis-bot"
git config user.email "forgis-bot@users.noreply.github.com"

echo "Preparing target branch: $TARGET_BRANCH"

git checkout -B "$TARGET_BRANCH"

if git diff --quiet && git diff --cached --quiet; then
  echo "No changes detected. Nothing to commit."
  exit 0
fi

git add .
git commit -m "Forgis: sync Apple source to $TARGET_PLATFORM"

if [[ "$DRY_RUN" == "true" ]]; then
  echo "Dry run enabled. Skipping push and pull request creation."
  exit 0
fi

echo "Pushing branch: $TARGET_BRANCH"
git push --force-with-lease origin "$TARGET_BRANCH"

echo "Creating pull request..."

if gh pr view "$TARGET_BRANCH" --repo "$TARGET_REPO" >/dev/null 2>&1; then
  echo "Pull request already exists for branch: $TARGET_BRANCH"
else
  gh pr create \
    --repo "$TARGET_REPO" \
    --base main \
    --head "$TARGET_BRANCH" \
    --title "Forgis sync: Apple to $TARGET_PLATFORM" \
    --body-file MIGRATION_REPORT.md
fi
