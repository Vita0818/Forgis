# Migration Profile: pixel-clone-app

Use this profile when the target platform should visually and behaviorally follow the source app as closely as possible.

## Core goal

The migration should be translation-first and visual-fidelity-first.

The target app should preserve the source app's visual hierarchy, spacing logic, typography intention, color system, interaction flow, state behavior, and product personality as much as the target platform allows.

## Source of truth

Every run must freshly read the selected source repository.

The source repository is authoritative.

The target repository is only an output location. Existing target code may be reused only if it still matches the current source behavior and design.

## Visual fidelity rules

The agent should preserve:

- Page structure
- Screen boundaries
- Navigation flow
- Card hierarchy
- Button hierarchy
- Main colors and gradients
- Rounded corners
- Shadow and glass-like visual intention
- Typography intention
- Empty states
- Loading or placeholder states when present
- Primary interaction gestures and button actions

If an exact source-platform visual effect is not available on the target platform, implement the closest idiomatic target-platform equivalent and document the difference in notes under the target output directory.

## Behavior fidelity rules

The agent should preserve:

- Data model semantics
- Local-first storage behavior
- Review flow
- Reinforcement behavior
- Mastered item behavior
- Daily goal behavior
- Preset switching behavior
- Markdown import and parsing behavior when possible
- User-facing text meaning
- Important constraints and edge cases

## Translation strategy

Prefer copying the source structure conceptually, then translating it into the target stack.

Do not redesign from scratch.

Do not simplify major flows unless the report explicitly marks them as deferred.

Do not invent new product features.

Do not replace local-first logic with network, login, server, or cloud sync.

## Android Kotlin Compose guidance

When target stack is kotlin-compose:

- Translate SwiftUI views into Jetpack Compose composables.
- Translate Swift models into Kotlin data classes.
- Translate source state logic into Kotlin state holders or simple local repositories.
- Preserve source screen names and model names when reasonable.
- Use Material 3 only where it helps implementation, not as a reason to redesign the app.
- Build a runnable Android project before chasing visual polish.
- Keep generated code organized by feature or source responsibility.

## Reporting requirements

Migration notes under the target output directory must include:

- Source commit used
- Source files scanned
- Source files translated
- Target files created or modified
- Features implemented
- Features partially implemented
- Features deferred
- Known visual differences
- Known behavior differences
- Build status if available
