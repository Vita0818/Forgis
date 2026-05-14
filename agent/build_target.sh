#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${TARGET_REPO_DIR:-}" ]]; then
  echo "TARGET_REPO_DIR is required." >&2
  exit 1
fi

if [[ -z "${TARGET_PLATFORM:-}" ]]; then
  echo "TARGET_PLATFORM is required." >&2
  exit 1
fi

if [[ ! -d "$TARGET_REPO_DIR" ]]; then
  echo "Target repository directory does not exist: $TARGET_REPO_DIR" >&2
  exit 1
fi

TARGET_SUBDIR="${TARGET_SUBDIR:-forgis-output}"
RUN_AIDER="${RUN_AIDER:-false}"
DRY_RUN="${DRY_RUN:-true}"

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

cd "$TARGET_BUILD_DIR"

echo "Build target scope:"
echo "  target repository: $TARGET_REPO_DIR"
echo "  target output directory: $TARGET_SUBDIR_REL"
echo "  run_aider: $RUN_AIDER"
echo "  dry_run: $DRY_RUN"

case "$TARGET_PLATFORM" in
  android)
    if [[ -f "./gradlew" ]]; then
      echo "Running Android Gradle build..."
      chmod +x ./gradlew
      ./gradlew assembleDebug
    else
      echo "No Gradle wrapper found. Skipping Android build."
      echo "Expected file: $TARGET_SUBDIR_REL/gradlew"

      if [[ "${RUN_AIDER,,}" =~ ^(true|1|yes|y|on)$ && "${DRY_RUN,,}" =~ ^(false|0|no|n|off)$ ]]; then
        if [[ ! -f "settings.gradle" && ! -f "settings.gradle.kts" && ! -f "app/build.gradle" && ! -f "app/build.gradle.kts" ]]; then
          echo "Android project structure was not generated in $TARGET_SUBDIR_REL." >&2
          echo "Expected at least one of: settings.gradle, settings.gradle.kts, app/build.gradle, app/build.gradle.kts." >&2
          exit 1
        fi
      fi
    fi
    ;;

  windows)
    echo "Windows build is not enabled in the Forgis MVP."
    echo "Skipping Windows build."
    ;;

  harmonyos)
    echo "HarmonyOS build is not enabled in the Forgis MVP."
    echo "Skipping HarmonyOS build."
    ;;

  web)
    if [[ -f "package.json" ]]; then
      echo "Web project detected. Build is not enabled by default in the Forgis MVP."
    else
      echo "No package.json found. Skipping web build."
    fi
    ;;

  *)
    echo "Unsupported target platform: $TARGET_PLATFORM" >&2
    exit 1
    ;;
esac
