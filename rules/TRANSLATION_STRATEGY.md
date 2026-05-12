# Forgis Translation Strategy

Forgis uses a translation-first migration strategy.

## Core rule

Every migration run must freshly read and scan the selected source repository.

The source repository is the source of truth.

The target repository is only an output location and must not be treated as the source of truth.

## Strategy

The agent should work in this order:

1. Read the current source repository.
2. Treat the current source code as the authoritative implementation.
3. Translate source structures, models, screens, and behavior into the selected target stack.
4. Replace or update outdated generated target code according to the current source.
5. Make small target-platform adjustments only when necessary.
6. Avoid unnecessary redesign, abstraction, or architecture refactoring.

## Not allowed

The agent must not:

- Rebuild the product from imagination.
- Treat older target repository code as authoritative.
- Redesign the app just because the target platform is different.
- Invent unrelated features.
- Hide unsupported source features without reporting them.
- Skip source files silently.

## Allowed adaptation

The agent may adapt implementation details when the source API has no direct target-platform equivalent.

Examples:

- SwiftUI view structure may become Jetpack Compose composables.
- UserDefaults or Codable JSON may become SharedPreferences, DataStore, or local JSON files.
- WidgetKit features may be reported as unsupported or deferred on Android unless explicitly requested.
- iOS-only APIs may be replaced with the closest Android-native equivalent.

## Reporting

Every run must update `MIGRATION_REPORT.md`.

The report must say:

- Which source commit was used.
- Which source files were translated.
- Which source files were skipped or deferred.
- Which target files were created or modified.
- Which adaptations were necessary.
- Which parts remain uncertain.
