# Forgis

Forgis is a thin DeepSeek-powered file interaction interface.

Documentation:

- [中文文档](README.zh-CN.md)
- [SwiftUI → Kotlin / Jetpack Compose migration guide](docs/DS_GUIDE_Swift_Kotlin.md)

It only does three things:

- reads `FORGIS_CONFIG.yml` and the configured task file from the target repository
- calls DeepSeek when the run switches allow it
- gives DeepSeek controlled file interaction tools

Forgis does not contain project migration intelligence. The target repository task file owns the work instructions.

## Workflow Input

The main workflow exposes one manual input:

```text
target_repo: owner/target-repo
```

Every other setting comes from `FORGIS_CONFIG.yml` at the target repository root.

## Config

`FORGIS_CONFIG.yml` must exist, must be non-empty YAML, and must contain the required values. The configured task file must also exist and be non-empty.

```yaml
source_repo: owner/source-repo
source_ref: main

target_subdir: target-output
task_prompt_path: FORGIS_TASK.md

agent_backend: deepseek
model: provider/model-name
api_base: https://api.deepseek.com
api_format: openai-compatible

target_branch: forgis/output
target_base_branch: main

run_log_path: target-output/FORGIS_LOG.md

dry_run: true
run_agent: false
confirm_real_run: false

model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

max_iterations: 80
max_tool_result_chars: 20000

validation_commands: []
success_checks: []
```

Required values:

- `source_repo`
- `target_branch`
- workflow input `target_repo`

Defaults:

- `source_ref: main`
- `target_subdir: target-output`
- `task_prompt_path: FORGIS_TASK.md`
- `agent_backend: deepseek`
- `api_base: https://api.deepseek.com`
- `api_format: openai-compatible`
- `target_base_branch: main`
- `run_log_path: {target_subdir}/FORGIS_LOG.md`
- `dry_run: true`
- `run_agent: false`
- `confirm_real_run: false`
- `max_iterations: 80`
- `max_tool_result_chars: 20000`

Only `agent_backend: deepseek` is supported. Other backend values fail fast.

## Run Switches

Safe dry run:

```yaml
dry_run: true
run_agent: false
confirm_real_run: false
```

Confirmed model run:

```yaml
dry_run: false
run_agent: true
confirm_real_run: true
```

Rules:

- `dry_run: true` does not call DeepSeek, write the target repository, push, or open a pull request.
- `dry_run: false` requires `confirm_real_run: true`.
- DeepSeek runs only when effective `run_agent` is true.
- Push and pull request creation are skipped unless the run is confirmed and not dry.

## Task File

The task file is the source of execution instructions for DeepSeek. Forgis does not rewrite it into a larger strategy prompt and does not preload source repository contents.

DeepSeek must read the task file through the file tools, then inspect the source and target repositories as needed through those same tools.

Do not put API keys, tokens, certificates, signing material, or private information in the task file or config file.

## DeepSeek

Forgis uses DeepSeek through the OpenAI-compatible Chat Completions API. `model_env` maps runtime environment variable names to GitHub Actions environment variable names that are populated from secrets.

```yaml
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY
```

Forgis prints only environment variable names and presence status. It never prints secret values, puts them in prompts, writes them to logs, or stores them in artifacts.

## File Tools

Read tools:

- `list_dir(path)`
- `tree(path, max_depth?)`
- `read_file(path, start_line?, max_lines?)`
- `file_exists(path)`

Write tools:

- `mkdir(path)`
- `write_file(path, content)`
- `append_file(path, content)`
- `delete_file(path)`

DeepSeek uses virtual paths:

- `task` for the configured task file
- `config` for `FORGIS_CONFIG.yml`
- `source/...` for the checked-out source repository
- `target/...` for the checked-out target repository
- `target_subdir/...` for the writable target output directory

Read results are bounded by `max_tool_result_chars`. Large files should be read with `start_line` and `max_lines`.

## Boundaries

Read access is limited to the checked-out source repository, checked-out target repository, config file, task file, and `target_subdir`.

Write access is limited to files inside target repository `target_subdir/`.

Forgis rejects path traversal, absolute-path escape attempts, symlink escapes, prefix spoofing, workflow writes, config/task writes, and secret-like paths.

## Guardrails

Forgis keeps only generic safety checks:

- source repository stayed read-only
- target repository changes stayed inside `target_subdir`
- config file stayed unchanged
- task file stayed unchanged
- `run_log_path` is inside `target_subdir`
- dry runs did not write the target repository
- model secret values were not written to target output
- confirmed runs produced at least one non-log target output change
- `validation_commands` came only from config
- `success_checks` came only from config

No platform structure or project-specific success marker is built into Forgis.

## Validation

If configured, `validation_commands` run inside `target_subdir`.

```yaml
validation_commands:
  - "some validation command"
```

If configured, `success_checks` are evaluated inside `target_subdir`.

```yaml
success_checks:
  - path_exists: "some/output/file"
  - command: "some validation command"
```

If neither field is configured, Forgis performs no output-shape validation beyond the generic guardrails.

## Run Log

Forgis writes or previews a Markdown log at `run_log_path`, which must be inside `target_subdir`.

The log records run identifiers, source and target repository names, source ref, task path, target subdir, backend, model, run switches, tool call counts, changed paths, guardrail result, validation result, and `final_summary`.

The log does not include secret values, full model payloads, large source dumps, hidden model reasoning, or private user data.
