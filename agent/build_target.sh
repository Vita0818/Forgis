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

cd "$TARGET_REPO_DIR"

case "$TARGET_PLATFORM" in
  android)
    if [[ -f "./gradlew" ]]; then
      echo "Running Android Gradle build..."
      chmod +x ./gradlew
      ./gradlew assembleDebug
    else
      echo "No Gradle wrapper found. Skipping Android build."
      echo "Expected file: ./gradlew"
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
