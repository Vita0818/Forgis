# Target Stack: kotlin-compose

Use this stack for Android applications.

## Preferred technologies

- Kotlin
- Jetpack Compose
- Gradle
- AndroidX
- Material 3 only when appropriate
- Local-first architecture when possible

## Notes

- Prefer simple Compose screens over complex premature abstractions.
- Keep generated code buildable.
- Do not invent signing configs or private keystores.


## Translation style

Prefer direct source-to-target translation.

When translating Swift or SwiftUI code:

- Preserve model names when reasonable.
- Preserve screen boundaries when reasonable.
- Preserve state transitions and user-facing behavior.
- Use Jetpack Compose idioms only as necessary for Android.
- Avoid broad architecture rewrites in the first generated pass.
