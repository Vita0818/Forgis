# Forgis

Forgis is a generic cloud-based migration forge.

It reads a selected source repository, applies a selected migration profile and target platform configuration, and generates or updates a selected target repository.

Forgis is not tied to any single project.

## Recommended Mode

Put these two files in the target repository root:

- `FORGIS_CONFIG.yml`: machine-readable migration parameters
- `FORGIS_TASK.md`: long-form human task prompt for the current run

Then run the GitHub Action with only the common inputs:

```text
target_repo: owner/target-repo
config_path: FORGIS_CONFIG.yml
dry_run: true
run_aider: false
```

For a live AI migration run:

```text
target_repo: owner/target-repo
config_path: FORGIS_CONFIG.yml
dry_run: false
run_aider: true
```

`dry_run: true` is the safe default and does not call Aider, push, or create a pull request. `run_aider` must be explicitly enabled, and it only takes effect when `dry_run` is false.

## Example Config

```yaml
source_repo: Vita0818/Kikaria
source_ref: main

target_platform: android
target_stack: kotlin-compose
migration_profile: pixel-clone-app

target_subdir: Kikaria-Android
task_prompt_path: FORGIS_TASK.md

model: deepseek/deepseek-v4-pro
target_branch: forgis/kikaria-android-pixel-2
target_base_branch: main

run_log_path: Kikaria-Android/FORGIS_LOG.md
```

If `run_log_path` is omitted, Forgis uses:

```text
{target_subdir}/FORGIS_LOG.md
```

For example:

```text
Kikaria-Android/FORGIS_LOG.md
```

## Configuration Priority

For migration parameters, Forgis resolves values in this order:

1. Non-empty workflow input override
2. `FORGIS_CONFIG.yml`
3. Safe default, where one exists

`dry_run` and `run_aider` are different: they are controlled only by workflow inputs. The target repository config cannot silently enable AI execution, pushes, or pull request creation.

## Target Task Prompt

`task_prompt_path` is resolved relative to the target repository root. The recommended file is:

```text
FORGIS_TASK.md
```

Forgis reads this file after checking out the target repository and embeds it into the generated final prompt. Aider receives it through read-only context and must not edit it.

If the task prompt file is missing or empty, the migration workflow fails instead of falling back to an example task.

Do not put API keys, tokens, certificates, signing material, or private information in `FORGIS_TASK.md` or any other task prompt file.

## Safety Boundaries

Forgis enforces these runtime boundaries:

- `source_repo` is fully read-only.
- The target repository root is read-only.
- Only `target_subdir` inside the target repository is writable.
- Everything outside `target_subdir` is read-only, including other project directories.
- `FORGIS_CONFIG.yml` and `FORGIS_TASK.md` are read-only input files.
- `run_log_path` must be inside `target_subdir`.
- Aider writable scope is `target_subdir`, not the config file or task prompt file.
- The target repository root must not be polluted with generated project files.
- Sibling project directories must not be modified.
- Dry runs do not call AI, push, or create pull requests.
- `run_aider` requires explicit workflow confirmation.

Before Aider runs, Forgis records hashes for the configured config and task prompt files. After Aider returns, Forgis checks the hashes again and fails the workflow if either read-only file changed.

Forgis also checks target git status and fails if any changed file is outside `target_subdir`.

## Long-Term Log

Each run appends a Markdown entry to the long-term log file:

```text
{target_subdir}/FORGIS_LOG.md
```

This file is intentionally inside the writable target output directory, so it can be committed with the migration branch.

In dry run mode, Forgis still prints the proposed log entry to the workflow log and uploads it as an artifact. In live mode, the log file is part of the target repository changes that are pushed and included in the pull request.

## Workflow Inputs

Common inputs:

- `target_repo`
- `config_path`
- `dry_run`
- `run_aider`

Advanced override inputs remain available for compatibility:

- `source_repo`
- `source_ref`
- `target_platform`
- `target_stack`
- `migration_profile`
- `target_subdir`
- `task_prompt_path`
- `run_log_path`
- `target_branch`
- `target_base_branch`
- `model`

Deprecated aliases are still accepted:

- `run_ai` for `run_aider`
- `target_prompt_file` for `task_prompt_path`
- `aider_model` for `model`
- `base_branch` for `target_base_branch`

If `config_path` is missing from the target repository, Forgis can still run in the old parameter mode, but all required migration fields must be supplied through workflow inputs.

## Required Secrets

API keys must be stored in GitHub Actions Secrets, not in repository files.

Required GitHub Actions secrets:

- `DEEPSEEK_API_KEY`
  - Used only for DeepSeek API access when `run_aider` is effective.
- `FORGIS_SOURCE_TOKEN`
  - Used only to check out the source repository.
  - Should have source repository Contents read and Metadata read permissions.
  - Must not have write permissions to the source repository.
- `FORGIS_TARGET_TOKEN`
  - Used only to check out the target repository, push the migration branch, and create pull requests.
  - Should have target repository Contents read/write, Pull requests read/write, and Metadata read permissions.

Do not reuse the target token for source checkout.

## Default AI Model

Forgis uses DeepSeek Pro by default.

Current default Aider model:

- `deepseek/deepseek-v4-pro`
