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

- `source_repo`: source repository, for example `owner/source-repo`
- `source_ref`: source branch, tag, or commit
- `target_repo`: target output repository, for example `owner/target-repo`
- `target_platform`: broad target platform, for example `android`, `windows`, `harmonyos`, or `web`
- `target_stack`: concrete target technology stack, for example `kotlin-compose`, `csharp-avalonia`, `arkts`, or `web-react`
- `migration_profile`: migration strategy profile, for example `default` or `local-first-app`
- `target_branch`: target migration branch
- `target_base_branch`: target repository base branch for pull requests
- `dry_run`: whether to skip push and pull request creation
- `run_aider`: whether to actually call Aider with the configured AI model
- `task_prompt_path`: Markdown task prompt file path relative to the target repository root. Defaults to `FORGIS_TASK.md`.
- `target_subdir`: target output directory relative to the target repository root. Defaults to `forgis-output`.
- `model`: Aider model name. Defaults to `deepseek/deepseek-v4-pro`.

Deprecated aliases are still accepted by the workflow for compatibility:

- `run_ai` for `run_aider`
- `target_prompt_file` for `task_prompt_path`
- `aider_model` for `model`
- `base_branch` for `target_base_branch`

## Per-run task prompt

Forgis itself stays generic and does not need to be edited for each migration phase.

Before each run, create or update a Markdown task prompt in the target repository root. The default file is:

```text
FORGIS_TASK.md
```

GitHub Actions checks out the target repository, reads `task_prompt_path` from that target repository root, and embeds the file contents in the final prompt sent to Aider.

For example, a run can use:

- `source_repo`: `owner/source-repo`
- `target_repo`: `owner/target-repo`
- `target_stack`: `kotlin-compose`
- `task_prompt_path`: `FORGIS_TASK.md`
- `target_subdir`: `android-output`

Long task instructions should be written into a `.md` file in the target repository root instead of being pasted into a workflow input box. You may choose another filename by changing `task_prompt_path`, but the path is always resolved relative to the target repository root.

Do not put API keys, tokens, certificates, signing material, or private information in `FORGIS_TASK.md` or any other task prompt file.

If the task prompt file is missing or empty, the migration workflow fails instead of falling back to an example task.

## Target output directory

Forgis uses `target_subdir` to define the project directory Aider may create or modify inside the target repository.

The default is:

```text
forgis-output
```

Aider receives the task prompt as read-only context and runs with the target output directory as its writable scope. Generated project files should stay under `target_subdir`; `MIGRATION_REPORT.md` may be updated at the target repository root for run reporting.

Set `target_subdir` explicitly for real migrations when the target repository should contain a named project directory.

## Safety

By default:

- `dry_run` is `true`
- `run_aider` is `false`
- the source repository is treated as read-only
- generated project changes are written only inside the configured `target_subdir`
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
