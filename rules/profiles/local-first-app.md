# Migration Profile: local-first-app

Use this profile for local-first applications that store user data primarily on device.

## Strategy

- Prefer local storage over cloud services unless the source project clearly requires cloud sync.
- Avoid inventing backend services.
- Keep API keys, tokens, and user data out of generated code.
- Preserve import/export flows when possible.
- Record data model assumptions in `MIGRATION_REPORT.md`.
