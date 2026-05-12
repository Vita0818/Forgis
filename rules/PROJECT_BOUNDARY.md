# Forgis Project Boundary

Forgis must follow these boundaries strictly.

## Allowed to read

Forgis may read only:

- The Forgis repository itself
- The selected Apple source repository
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

- The selected target output repository
- The selected migration branch

## Forbidden to write

Forgis must not write:

- The Apple source repository
- The target repository main branch directly
- Any unrelated repository
- Any credential, token, certificate, or private key file

## Default rule

If a task requires access outside the declared Forgis repository, Apple source repository, and target output repository, Forgis must stop instead of guessing.
