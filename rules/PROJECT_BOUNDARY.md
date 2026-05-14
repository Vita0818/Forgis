# Forgis Project Boundary

Forgis must follow these boundaries strictly.

## Allowed to read

Forgis may read only:

- The Forgis repository itself
- The selected source repository
- The selected target output repository
- Files explicitly checked out by GitHub Actions during the current workflow run

## Forbidden to read

Forgis must not read:

- Any local Mac files
- iCloud files
- Keychain data
- Desktop, Downloads, Documents, or unrelated folders
- Any repository not explicitly provided to the workflow
- Secret files, certificates, private keys, or untracked environment files

## Allowed to write

Forgis may write only:

- The configured `target_subdir` inside the selected target output repository
- The configured `run_log_path`, which must be inside `target_subdir`
- The selected migration branch

## Forbidden to write

Forgis must not write:

- The source repository
- The target repository root
- Target repository files outside `target_subdir`
- `FORGIS_CONFIG.yml`, `FORGIS_TASK.md`, or any configured config/task prompt file
- The target repository main branch directly
- Any unrelated repository
- Any credential, token, certificate, or private key file

## Default rule

If a task requires access outside the declared Forgis repository, source repository, and target output repository, Forgis must stop instead of guessing.
