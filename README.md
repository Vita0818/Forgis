# Forgis

Forgis is a generic cloud-based migration forge.

It reads a selected source repository, applies a selected migration profile and target platform configuration, and generates or updates a selected target repository.

Forgis is not tied to any single project.

## Recommended Mode

Put these two files in the target repository root:

- `FORGIS_CONFIG.yml`: machine-readable migration parameters and run switches
- `FORGIS_TASK.md`: long-form human task prompt for the current run

Then run the main GitHub Action with only:

```text
target_repo: owner/target-repo
```

All migration parameters other than `target_repo` come from the target repository root file:

```text
FORGIS_CONFIG.yml
```

The main workflow fixes the config path to `FORGIS_CONFIG.yml`. It does not expose `config_path`, `dry_run`, `run_aider`, model, branch, prompt, log, or target directory fields in the manual UI.

## Example Config

```yaml
source_repo: owner/source-repo
source_ref: main

target_platform: android
target_stack: kotlin-compose
migration_profile: pixel-clone-app

target_subdir: sample-output
task_prompt_path: FORGIS_TASK.md

model: provider/model-name
target_branch: forgis/migration-output
target_base_branch: main

run_log_path: sample-output/FORGIS_LOG.md

dry_run: true
run_aider: false
confirm_real_run: false

required_prompt_markers: []
forbidden_prompt_markers: []
```

`required_prompt_markers` is project-specific. Leave it empty unless the target repository wants explicit marker checks for its own migration prompt.

If `run_log_path` is omitted, Forgis uses:

```text
{target_subdir}/FORGIS_LOG.md
```

For example:

```text
sample-output/FORGIS_LOG.md
```

## Run Switches

Safe dry run configuration:

```yaml
dry_run: true
run_aider: false
confirm_real_run: false
```

Formal AI migration configuration:

```yaml
dry_run: false
run_aider: true
confirm_real_run: true
```

Rules:

- Missing fields default to `dry_run: true`, `run_aider: false`, and `confirm_real_run: false`.
- When `dry_run: true`, Forgis does not call AI, push, create a PR, or modify the target repository.
- When `dry_run: true` and `run_aider: true`, Forgis forces effective Aider execution to false and logs `dry_run=true, Aider execution is disabled.`
- When `dry_run: false`, `confirm_real_run: true` is required.
- Real AI migration only happens when `dry_run: false`, `run_aider: true`, and `confirm_real_run: true`.

## Configuration Priority

Forgis resolves values in this order:

1. `target_repo` from the GitHub Actions input
2. `FORGIS_CONFIG.yml` for every migration parameter
3. Safe default, where one exists

`FORGIS_CONFIG.yml` must exist in the target repository root. The main workflow does not expose overrides for `source_repo`, branches, model, prompt, log, target directory, dry-run mode, or Aider execution.

Required config fields are:

- `source_repo`
- `target_platform`
- `target_stack`
- `target_branch`

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
- Dry runs do not call AI, push, create PRs, or modify the target repository.
- Real migration must explicitly set `confirm_real_run: true`.

Before Aider runs, Forgis records hashes for the configured config and task prompt files. After Aider returns, Forgis checks the hashes again and fails the workflow if either read-only file changed.

Forgis also checks target git status and fails if any changed file is outside `target_subdir`.

Forgis asks Aider not to modify the target repository root `.gitignore`. If an older Aider still creates a new root `.gitignore` containing only Aider ignore patterns, Forgis removes that new auto file before guardrail checks. Existing user `.gitignore` files are never removed or restored; any modification to them remains a guardrail failure.

## Prompt Diagnostics

Before Aider runs, Forgis logs and uploads diagnostics for both the generated final prompt and the exact Aider `--message-file`.

Diagnostics include:

- prompt path
- character count
- SHA256
- first 20 lines
- task prompt SHA256 marker checks
- required prompt marker checks
- forbidden stale greeting prompt checks
- Aider command summary without secrets

Forgis is a generic migration tool and does not globally require project-specific text. The generated prompt includes a `Task prompt sha256: ...` marker derived from the target repository task file, and the Aider message file must contain the same marker. The Aider message file must also match the generated final prompt hash.

Project-specific checks are configured with optional markers:

```yaml
required_prompt_markers:
  - Sample App Migration Task
  - owner/source-repo
  - owner/target-repo
  - sample-output
```

If `required_prompt_markers` is omitted, Forgis only checks the generic prompt integrity rules. `forbidden_prompt_markers` can extend the default stale prompt blocklist:

```yaml
forbidden_prompt_markers:
  - Deprecated migration fallback prompt
```

The default forbidden markers block old greeting example prompts such as `make the greeting more casual`, `Which file (or which phrase) should be changed?`, and `casual greeting`. The Validate workflow uses its own `Forgis Validation Smoke Task` marker for smoke testing; that marker does not represent a real migration requirement.

## Long-Term Log

Real migration runs append a Markdown entry to the long-term log file:

```text
{target_subdir}/FORGIS_LOG.md
```

This file is intentionally inside the writable target output directory, so it can be committed with the migration branch.

In dry run mode, Forgis prints the proposed log entry to the workflow log and uploads it as an artifact, but does not write it into the target repository. In live mode, the log file is part of the target repository changes that are pushed and included in the pull request.

## Workflow Inputs

The main workflow exposes only:

- `target_repo`: required target repository containing `FORGIS_CONFIG.yml` and `FORGIS_TASK.md`

No deprecated alias or advanced override inputs are shown in the main manual run UI.

## Required Secrets

API keys must be stored in GitHub Actions Secrets, not in repository files.

Common GitHub Actions secrets:

- `FORGIS_SOURCE_TOKEN`
  - Used only to check out the source repository.
  - Should have source repository Contents read and Metadata read permissions.
  - Must not have write permissions to the source repository.
- `FORGIS_TARGET_TOKEN`
  - Used only to check out the target repository, push the migration branch, and create pull requests.
  - Should have target repository Contents read/write, Pull requests read/write, and Metadata read permissions.

Do not reuse the target token for source checkout.

Provider-specific model API keys should be stored as GitHub Actions secrets and made available to the workflow according to the chosen model provider. Do not store model API keys in `FORGIS_CONFIG.yml`, `FORGIS_TASK.md`, or generated prompt artifacts.

## Default AI Model

The default model placeholder is:

- `provider/model-name`

Set `model` in `FORGIS_CONFIG.yml` before enabling a real Aider run.
