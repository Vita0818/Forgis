# Forgis

Forgis is a generic cloud-based migration forge.

It reads a selected source repository, applies a selected migration profile and target platform configuration, and generates or updates a selected target repository.

Forgis is not tied to any single project.

## Concept

Forgis is organized around five parts:

- Wrench: migration rules and prompts
- Robotic arm: GitHub Actions and agent scripts
- Power: an external LLM API such as DeepSeek
- Input screw: the selected source repository
- Output screw: the selected target repository

## Core inputs

A Forgis run is configured by workflow inputs:

- `source_repo`: source repository, for example `owner/apple-source-repo`
- `source_ref`: source branch, tag, or commit
- `target_repo`: target output repository, for example `owner/target-output-repo`
- `target_platform`: broad target platform, for example `android`, `windows`, `harmonyos`, or `web`
- `target_stack`: concrete target technology stack, for example `kotlin-compose`, `csharp-avalonia`, `arkts`, or `web-react`
- `migration_profile`: migration strategy profile, for example `default` or `local-first-app`
- `target_branch`: target migration branch
- `target_base_branch`: target repository base branch for pull requests
- `dry_run`: whether to skip push and pull request creation
- `run_ai`: whether to actually call the configured AI model

## Safety

By default:

- `dry_run` is `true`
- `run_ai` is `false`
- the source repository is treated as read-only
- generated changes are written only inside the checked-out target repository
- push and PR creation are disabled unless explicitly enabled

API keys must be stored in GitHub Actions Secrets, not in repository files.

Required GitHub Actions secrets:

- `DEEPSEEK_API_KEY`
  - Used only for DeepSeek API access.
- `FORGIS_SOURCE_TOKEN`
  - Used only to check out the source repository.
  - Should have source repository Contents read and Metadata read permissions.
  - Must not have write permissions to the source repository.
- `FORGIS_TARGET_TOKEN`
  - Used only to check out the target repository, push the migration branch, and create pull requests.
  - Should have target repository Contents read/write, Pull requests read/write, and Metadata read permissions.

Do not reuse the target token for source checkout.

## Default AI model

Forgis uses DeepSeek Pro by default.

Current default Aider model:

- `deepseek/deepseek-v4-pro`
