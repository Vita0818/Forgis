# Forgis

Forgis is a generic Agent entrypoint for running Aider against a target repository.

Forgis does not understand a migration task, analyze product logic, generate platform scaffolds, or decide what the target project should become. Those rules belong in the target repository task file and are executed by Aider.

## What Forgis Does

Forgis:

- reads `FORGIS_CONFIG.yml` from the target repository root
- reads the configured task file, usually `FORGIS_TASK.md`
- prepares absolute source and target repository paths
- creates the configured writable target directory when needed
- calls Aider when the run switches allow it
- gives Aider the source path, target path, writable path, and task file path
- enforces generic read/write guardrails
- records a run log at the configured `run_log_path`

Forgis does not include Android, Web, iOS, HarmonyOS, Rust, Python, or any other platform logic. If the task is to migrate or generate one of those outputs, the target repository task file must say so and Aider must perform it.

## Workflow Input

The main workflow exposes only one manual input:

```text
target_repo: owner/target-repo
```

Every other setting comes from `FORGIS_CONFIG.yml` in that target repository.

## Minimal Config

`FORGIS_CONFIG.yml` is fixed at the target repository root. It must exist, must be non-empty YAML, and must contain the required fields.

```yaml
source_repo: owner/source-repo
source_ref: main
target_subdir: target-output
task_prompt_path: FORGIS_TASK.md
agent_backend: aider
model: provider/model-name
target_branch: forgis/output
target_base_branch: main
run_log_path: target-output/FORGIS_LOG.md
dry_run: true
run_agent: false
confirm_real_run: false
model_env:
  PROVIDER_API_KEY: PROVIDER_API_KEY
```

Required values:

- `source_repo`
- `target_branch`
- workflow input `target_repo`

Defaults:

- `source_ref: main`
- `target_subdir: target-output`
- `task_prompt_path: FORGIS_TASK.md`
- `agent_backend: aider`
- `model: provider/model-name`
- `target_base_branch: main`
- `run_log_path: {target_subdir}/FORGIS_LOG.md`
- `dry_run: true`
- `run_agent: false`
- `confirm_real_run: false`

`run_aider` is accepted as a legacy alias for `run_agent`; internally Forgis resolves both to `run_agent`.

## Run Switches

Safe dry run:

```yaml
dry_run: true
run_agent: false
confirm_real_run: false
```

Real Aider run:

```yaml
dry_run: false
run_agent: true
confirm_real_run: true
```

Rules:

- `dry_run: true` never calls Aider, pushes, or opens a pull request.
- `dry_run: false` requires `confirm_real_run: true`.
- Aider runs only when effective `run_agent` is true.
- Push and pull request creation are skipped unless the run is confirmed and not dry.

## Task File

The task file is the source of execution rules for Aider.

Forgis does not rewrite the task into a larger migration prompt. It passes the task file as read-only context when the Aider backend supports that mode, and the thin message tells Aider to read it.

A task file should contain the product rules, migration rules, technical constraints, files to read, files to create, validation strategy, and any platform details needed for that run.

Do not put API keys, tokens, certificates, signing material, or private information in the task file or config file.

## Aider Message

The generated Aider message is intentionally thin. It contains only:

- that Aider is running through Forgis
- absolute source repository path
- absolute target repository path
- absolute writable target path
- absolute task file path
- optional source context file path when configured
- read-only boundaries for source, config, task file, target root, and run log
- instructions to read the task file and work only under the writable target path

It does not contain platform templates, scaffold instructions, source summaries, target stack logic, or migration strategy.

## Optional Source Context

By default, Forgis gives Aider the source repository path and does not copy source content into the message.

`source_context` may be configured for generic file transfer:

```yaml
source_context:
  mode: none
  max_chars: 100000
  include:
    - "**/*"
  exclude:
    - ".git/**"
    - "build/**"
```

Supported modes:

- `none`: no source files are copied
- `tree`: write a generic source file tree artifact
- `selected_files`: copy only files matched by configured include/exclude patterns

Forgis does not choose files by platform or infer business importance.

## Guardrails

Forgis keeps only generic safety logic:

- source repository must remain read-only
- target repository root is read-only
- only `target_subdir` is writable
- `FORGIS_CONFIG.yml` is read-only
- the configured task file is read-only
- `run_log_path` must be inside `target_subdir`
- Aider history, cache, and tags cache must not pollute the target repository root
- any change outside `target_subdir` fails the run
- config/task hashes changing during Aider execution fails the run
- model secret values are never written into the message, log, or artifacts
- dry runs do not call Aider, push, or open pull requests
- real runs require `confirm_real_run: true`

## Generic Result Checks

After Aider runs, Forgis checks:

- source repository was not modified
- target repository changes stayed inside `target_subdir`
- config and task file hashes did not change
- `run_log_path` is inside `target_subdir`
- Aider produced at least one non-log, non-cache change inside `target_subdir`
- configured `validation_commands` ran successfully
- configured `success_checks` passed

If `validation_commands` and `success_checks` are not configured, Forgis does not assume any project type or platform success marker.

Example:

```yaml
validation_commands:
  - "some validation command"

success_checks:
  - path_exists: "some/output/file"
  - command: "some validation command"
```

## Run Log

Forgis writes or previews a Markdown run log at `run_log_path`, which must be inside `target_subdir`.

The log records:

- run id and run URL
- target and source repository identifiers
- source ref
- target subdir
- task file path
- agent backend and model name
- `dry_run`, `run_agent`, and `confirm_real_run`
- whether Aider executed
- Aider exit status when available
- guardrail and validation summaries
- changed paths summary
- `validation_commands` and `success_checks` counts

The log must not contain secrets or business rules.

## Model Environment

`model_env` maps runtime environment variable names to environment variable names made available by the workflow:

```yaml
model_env:
  PROVIDER_API_KEY: PROVIDER_API_KEY
```

Forgis prints only the env variable names and whether the source variable is present. It never prints secret values.
