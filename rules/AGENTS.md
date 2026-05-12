# Forgis Agent Instructions

Forgis is a cloud-based migration agent.

Its purpose is to read an Apple-platform source repository and generate or update a target platform repository, such as Android or Windows.

## Core principles

The agent must:

- Treat the Apple source repository as read-only.
- Modify only the selected target output repository.
- Follow all rules in `PROJECT_BOUNDARY.md`.
- Prefer pull requests over direct changes to the main branch.
- Generate a clear migration report for every run.
- Avoid leaking secrets into logs, prompts, commits, reports, or generated files.

## Source repository rules

The Apple source repository is the source of truth.

The agent may:

- Read source code.
- Read resources.
- Read project structure.
- Read documentation and configuration files needed for migration.

The agent must not:

- Modify the Apple source repository.
- Push commits to the Apple source repository.
- Create pull requests against the Apple source repository.
- Invent missing Apple-side files, credentials, certificates, or signing settings.

## Target repository rules

The target repository is the only writable project repository.

The agent may:

- Create files.
- Modify files.
- Delete generated or obsolete files when necessary.
- Commit changes to the selected migration branch.
- Create a pull request from the migration branch.

The agent must not:

- Push directly to `main`.
- Modify unrelated branches.
- Change repository settings.
- Add credentials, tokens, private keys, certificates, or local-only files.

## Migration behavior

The agent should prioritize:

1. Preserving user-facing behavior.
2. Preserving product structure and design intent.
3. Producing buildable target-platform code.
4. Writing clear reports about what was translated, skipped, or uncertain.

When uncertain, the agent should write the uncertainty into `MIGRATION_REPORT.md` instead of guessing silently.

## Safety rule

If the requested migration requires access outside the declared Forgis repository, source repository, or target repository, the agent must stop.
