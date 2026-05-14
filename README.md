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
target_repo: Vita0818/Outposts
```

Optionally override only the source repository:

```text
source_repo: Vita0818/Kikaria
```

All other migration parameters come from the target repository root file:

```text
FORGIS_CONFIG.yml
```

The main workflow fixes the config path to `FORGIS_CONFIG.yml`. It does not expose `config_path`, `dry_run`, `run_aider`, model, branch, prompt, log, or target directory fields in the manual UI.

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

dry_run: true
run_aider: false
confirm_real_run: false
```

If `run_log_path` is omitted, Forgis uses:

```text
{target_subdir}/FORGIS_LOG.md
```

For example:

```text
Kikaria-Android/FORGIS_LOG.md
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

1. Non-empty `source_repo` workflow input, only for `source_repo`
2. `FORGIS_CONFIG.yml`
3. Safe default, where one exists

`target_repo` always comes from the workflow input. Every other migration parameter comes from `FORGIS_CONFIG.yml`.

Required config fields are:

- `source_repo`, unless provided as the workflow override
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
- task prompt marker checks
- forbidden stale greeting prompt checks
- Aider command summary without secrets

For Kikaria Android runs, the message file must contain `Kikaria Android Migration Task`, `Vita0818/Kikaria`, `Vita0818/Outposts`, `Kikaria-Android`, and `FORGIS_TASK.md`. If stale greeting example text appears, Forgis fails before calling Aider.

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
- `source_repo`: optional source repository override

No deprecated alias or advanced override inputs are shown in the main manual run UI.

## Required Secrets

API keys must be stored in GitHub Actions Secrets, not in repository files.

Required GitHub Actions secrets:

- `DEEPSEEK_API_KEY`
  - Used only for DeepSeek API access when effective `run_aider` is true.
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
