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

## FORGIS_CONFIG.yml Configuration Guide

`FORGIS_CONFIG.yml` must exist at the target repository root, must be non-empty YAML, and must use only supported Forgis fields. Unknown fields fail during the Resolve Forgis config step before the model runs.

Keep three kinds of information separate:

- **GitHub Actions input / CLI, not config:** `target_repo`.
- **`FORGIS_CONFIG.yml`:** repository refs, output branch/subdir, task file path, DeepSeek connection fields, run switches, skills, reports, repair-loop settings, migration-plan settings, and non-secret visual-validation switches.
- **`FORGIS_TASK.md`:** product and migration instructions, such as Android / Kotlin / Jetpack Compose, target stack, UI style, information architecture, migration scope, privacy rules, and "write only inside `target_subdir`" business constraints.

Do not put these fields or values in `FORGIS_CONFIG.yml`:

- `target_repo`; pass it through the workflow input or CLI `--target-repo`.
- `target_stack`; describe Android / Kotlin / Jetpack Compose in `FORGIS_TASK.md`.
- `source_branch`; use `source_ref`.
- `target_repo_url`, `source_repo_url`, `target_path`, or `source_path`.
- `agent_backend: aider`; Forgis currently supports only `agent_backend: deepseek`.
- `build_command: []` or `test_command: []`; omit the field when no command is configured.
- `model: deepseek/deepseek-v4-pro`; use DeepSeek's accepted model id `deepseek-v4-pro` or `deepseek-v4-flash`.
- Qwen API keys, tokens, evidence roots, screenshot file paths, or secret local paths in `FORGIS_CONFIG.yml`. v6.0 accepts only the non-secret `visual_validation` control block documented below; reference/actual screenshot directories must be target-repo-relative read-only inputs. Qwen credentials/base/model may be supplied only through explicit runtime environment variables and are never written to reports.

Minimum runnable config:

```yaml
source_repo: Vita0818/Kikaria
source_ref: main
target_branch: forgis/kikaria-android
target_base_branch: main
target_subdir: Kikaria-Android
task_prompt_path: FORGIS_TASK.md

agent_backend: deepseek
model: deepseek-v4-pro
api_base: https://api.deepseek.com
api_format: openai-compatible
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

execution_mode: tool_loop
dry_run: false
run_agent: true
confirm_real_run: true

run_report_enabled: true
```

Recommended first-run config for migrating Kikaria to Android / Kotlin / Jetpack Compose:

```yaml
source_repo: Vita0818/Kikaria
source_ref: main

target_branch: forgis/kikaria-android
target_base_branch: main
target_subdir: Kikaria-Android
task_prompt_path: FORGIS_TASK.md

agent_backend: deepseek
model: deepseek-v4-pro
api_base: https://api.deepseek.com
api_format: openai-compatible
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY

execution_mode: tool_loop
dry_run: false
run_agent: true
confirm_real_run: true

skills_enabled: true
auto_select_skills: false
selected_skills:
  - migration_general
  - swiftui_to_compose
  - ui_style_preservation
  - build_repair

run_report_enabled: true

migration_scheduler_enabled: true
migration_plan_persistence_enabled: true
migration_plan_resume_enabled: false
migration_plan_auto_update_enabled: true
migration_plan_auto_complete_on_success: false
migration_plan_audit_summary_enabled: true

repair_loop_enabled: false
```

Optional Qwen Visual Evidence Mode control block for v6.0:

```yaml
visual_validation:
  enabled: auto
  provider: qwen
  mode: reference_guidance
  reference_screenshot_dirs:
    - forgis-reference-screenshots
  actual_screenshot_dirs: []
  max_visual_iterations: 2
  require_reference_first: true
  require_actual_for_full_validation: false
  upload_visual_artifact: false
```

For a config-only smoke test, keep the same fields but use:

```yaml
dry_run: true
run_agent: false
confirm_real_run: false
```

Required values:

- `source_repo`
- `target_branch`
- workflow input or CLI value `target_repo`

Common defaults:

- `source_ref: main`
- `target_subdir: target-output`
- `task_prompt_path: FORGIS_TASK.md`
- `agent_backend: deepseek`
- `model: deepseek-v4-pro`
- `api_base: https://api.deepseek.com`
- `api_format: openai-compatible`
- `target_base_branch: main`
- `run_log_path: {target_subdir}/FORGIS_LOG.md`
- `dry_run: true`
- `run_agent: false`
- `confirm_real_run: false`
- `max_iterations: 80`
- `max_tool_result_chars: 20000`
- `execution_mode: tool_loop`
- no `build_command` or `test_command` unless explicitly configured
- `repair_loop_enabled: false`
- `run_report_enabled: true`
- `skills_enabled: true`
- `auto_select_skills: true`
- `migration_scheduler_enabled: false`
- `migration_plan_persistence_enabled: true`
- `migration_plan_resume_enabled: false`
- `migration_plan_auto_complete_on_success: false`
- `migration_plan_audit_summary_enabled: true`
- `visual_validation.enabled: auto`
- `visual_validation.provider: qwen`
- `visual_validation.mode: reference_guidance`
- `visual_validation.reference_screenshot_dirs: []`
- `visual_validation.actual_screenshot_dirs: []`
- `visual_validation.max_visual_iterations: 2`
- `visual_validation.require_reference_first: true`
- `visual_validation.require_actual_for_full_validation: false`
- `visual_validation.upload_visual_artifact: false`

Long-running migrations can explicitly raise runtime sizing fields while the defaults stay moderate:

| Field | Default | Maximum |
| --- | ---: | ---: |
| `max_iterations` | `80` | `5000` |
| `max_tool_result_chars` | `20000` | `5000000` |
| `max_command_output_chars` | `8000` | `2000000` |
| `run_report_max_events` | `100` | `10000` |
| `run_report_max_chars` | `200000` | `20000000` |

Larger values are useful for long real migrations, but they increase log size, report size, memory use, token exposure to the model, and total run time. They do not change tool permissions, command allowlists, report redaction, or the reports-only artifact boundary.

`target_branch` is the output branch in the target repository, not the base branch. Use a feature branch such as `forgis/kikaria-android` for real runs, and keep `target_base_branch: main` for the PR base.

### Build and Test Commands

`build_command` and `test_command` are optional. If you do not want Forgis to run build/test feedback, omit both fields entirely.

When configured, each command must be a non-empty YAML array of command arguments:

```yaml
build_command:
  - python3
  - -m
  - py_compile
  - app.py

test_command:
  - python3
  - -m
  - unittest
  - discover
```

Forgis does not accept shell strings, shell expansion, glob patterns, absolute paths, `..`, pipes, redirects, or command chaining in these arrays. The safe command runner rejects shell interpreters, `rm`, `sudo`, `chmod`, `chown`, `curl`, `wget`, `ssh`, `scp`, `git`, and other uncontrolled commands.

For the first Android migration run, omit `build_command` and `test_command`. The Gradle project may not exist yet, and v5.0 does not recommend putting `./gradlew` into these fields unless the command runner explicitly allows it and tests cover that behavior.

### DeepSeek Model and Secrets

Use one of DeepSeek's accepted model ids:

```yaml
model: deepseek-v4-pro
```

or:

```yaml
model: deepseek-v4-flash
```

Real model calls also need a secret mapping:

```yaml
model_env:
  DEEPSEEK_API_KEY: DEEPSEEK_API_KEY
```

Never put the actual API key value in `FORGIS_CONFIG.yml`.

### Qwen Visual Evidence Mode (v6.0 reference guidance)

Forgis v6.0 connects Qwen Visual Evidence Mode as a reference-guided migration loop; the full contract lives in `docs/QWEN_VISUAL_MODE.md`. The user places source-app reference screenshots in the target repository and declares the directories with `visual_validation.reference_screenshot_dirs`. The main Agent can call `list_visual_references`, then `inspect_visual_reference`, and use Qwen's visual guidance for layout, hierarchy, color, typography, spacing, radius, component relationships, and product feel while DeepSeek/Forgis still performs code edits, builds, tests, and reporting. The run report schema remains `forgis.run_report.v6.0` because `visual_validation` is a stable top-level report block.

The implementation uses `agent/visual_evidence.py` for evidence state/path safety and `agent/qwen_vision.py` for the mockable provider adapter. Automatic screenshot acquisition remains a Phase 8+ concern.

Qwen is a visual understanding provider, not a code migration agent. Qwen reads only approved screenshot images through sandboxed virtual paths; it must not read source code, modify files, run commands, or receive secrets, tokens, `.env`, certificates, private keys, provisioning profiles, raw image bytes/base64 in reports, or private local configuration. `actual_screenshot_dirs` and `compare_visual_screenshots` are optional enhancements when the user already has rendered target screenshots. Reference-only guidance is valid migration guidance, but it is not full rendered visual validation. Unit tests mock the provider and do not access the network; real Qwen HTTP calls occur only when `QWEN_API_KEY` is explicitly present, with optional `QWEN_API_BASE` and `QWEN_VISION_MODEL`. Forgis still does not implement automatic simulator/device/window screenshots, visual artifact upload, multi-provider support, arbitrary shell, or a UI dashboard.

`visual_validation.enabled=auto` is deterministic and conservative: it becomes required when `qwen_visual_mode` is selected, after any visual tool is called, or when `reference_screenshot_dirs` are configured and task text contains strong visual/UI/screenshot keywords. Pure code, backend, config, build, or unit-test-only tasks do not become visually gated unless one of those signals appears.

### FORGIS_TASK.md Example

Put target-stack and product instructions in `FORGIS_TASK.md`, not in config:

```markdown
# Kikaria Android Migration

Migrate current Kikaria to Android Kotlin Jetpack Compose.

Write generated code only under `Kikaria-Android`.

Preserve information architecture, core flows, visual hierarchy, and interaction intent.

Do not hard-code user names, local paths, secrets, or private data.

First run scope: create the Android/Compose foundation and core screens; leave TODOs for deferred areas.
```

## Optional Staged Translation Mode

Set `execution_mode: staged_translation` when a task needs a controller-enforced migration run: overview first, then one queued source file or source unit at a time through feed/write/readonly-compare/revise gates, then stabilization. This mode still uses the same DeepSeek client, file tools, logging, and guardrails. It does not add platform-specific migration intelligence; the strategy still comes from `FORGIS_TASK.md`, repository docs, and the user's task.

See [中文文档](README.zh-CN.md) for the full staged mode configuration and workflow.

## Forgis v3.0 Phase 1 Runtime

Forgis v3.0 phase 1 adds a minimal Claude Code-like agent runtime kernel without replacing the existing v2 tool loop or `staged_translation` mode. DeepSeek can now observe repository state more directly, make smaller edits, inspect its own diff, and run a very small set of safe commands.

New phase 1 capabilities:

- `search_text` for bounded source/target text search
- `git_status` for a target workspace status summary
- `git_diff` for bounded target workspace diff self-checks
- `edit_file` and `apply_patch` for small target-side edits
- `run_command` for conservative allowlisted commands inside `target_subdir`
- a lightweight runtime controller state skeleton that records whether the run read files, modified target files, viewed diff, or ran commands

This is not complete Claude Code parity. Full build orchestration, automatic repair scheduling, migration schedulers, remote skill discovery, and a fuller controller state machine are still future work.

## Forgis v3.1 Build/Test Feedback

Forgis v3.1 adds the first minimal verification feedback loop. It does not force every task to build or test, and it does not automatically run a repair loop. It gives DeepSeek two dedicated tools backed by configured command arrays:

- `run_build` runs `build_command` when configured
- `run_tests` runs `test_command` when configured

Both tools execute inside `target_subdir`, use the same safe command runner policy, avoid `shell=True`, enforce a timeout, and return a short structured result:

- `status`: `success`, `failed`, `skipped`, `rejected`, or `timeout`
- `exit_code`
- `stdout_tail` / `stderr_tail`
- `duration_seconds`
- `summary` for failures

The feedback summarizer recognizes Python `SyntaxError`, `ImportError`, `ModuleNotFoundError`, unittest failures, rejected commands, timeouts, and generic nonzero exits. The runtime controller records the latest build/test status, latest failure summary, and whether a target edit happened after a failed check.

Commands are configured as arrays, not shell strings:

```yaml
build_command:
  - python3
  - -m
  - py_compile
  - app.py

test_command:
  - python3
  - -m
  - unittest
  - discover
```

Glob expansion is intentionally not supported in command arrays for v3.1. Add explicit relative paths or use a safe test discovery command.

## Forgis v3.2 Limited Repair Loop

Forgis v3.2 adds the first restricted repair loop controller. It is disabled by default and only records/enforces state when explicitly enabled:

```yaml
repair_loop_enabled: true
max_repair_attempts: 2
repair_requires_diff_check: true
repair_requires_build_or_test: true
repair_stop_on_success: true
```

When `run_build` or `run_tests` returns `failed`, `rejected`, or `timeout`, the controller records the failure summary and allows a bounded repair pass. After an edit or patch, the model must inspect `git_diff` before it can run build/tests again when `repair_requires_diff_check` is true. A successful recheck stops the loop with `stopped_reason: success`; exhausting the configured attempts stops it with `stopped_reason: max_attempts_reached`; invalid next steps return `status: blocked`.

`max_repair_attempts` is capped at 5. The loop does not call the model by itself, does not run commands automatically, and does not expand the command allowlist. It is a minimal "check, summarize, small repair, diff, recheck" guardrail, not a complete automatic repair scheduler.

## Forgis v3.3 Repair Event Log and Runtime Report

Forgis v3.3 adds observability around the v3.1/v3.2 build, test, and repair flow. It does not add new automation intelligence, is not complete Claude Code, does not schedule migrations, and does not change the push or pull request semantics.

When the tool loop runs, Forgis now keeps a bounded repair event log for enabled repair-loop runs. Events include build/test start and finish, recorded failures, allowed repair attempts, edits after failure, required diff checks, repair rechecks, successful repairs, blocked steps, and max-attempt stops. Each event stores only a short status, attempt index, check type, safe relative changed paths, and a short failure summary.

The tool loop summary JSON now includes a compact runtime report and a Markdown `repair_report`. The report shows:

- build/test run counts and latest statuses
- repair-loop enabled state, attempts used, success flag, and stopped reason
- latest failure summary
- repair attempts, changed paths, diff-check status, and recheck result
- blocked or stopped reason
- next suggested action

If `GITHUB_STEP_SUMMARY` is available, Forgis appends the same safe Markdown report to the GitHub Actions step summary. Missing or unwritable summary files are ignored and do not fail the run.

Reports redact secret-like values, avoid absolute private paths, cap event/report length, and never include full source files or full diffs.

## Forgis v3.4 Persistent Run Reports

Forgis v3.4 persists the v3.3 runtime report into bounded local report files for debugging and GitHub Actions artifacts:

- `FORGIS_RUN_REPORT.md`
- `FORGIS_RUN_REPORT.json`

The Markdown report is a readable run summary with configuration overview, tool statistics, build/test status, repair-loop status, changed paths, the v3.3 repair report, final summary, stopped reason, and next suggested action. The JSON report contains the same information in structured form, including bounded repair events when `run_report_include_events` is true.

Reports are written only to a Forgis runtime output directory. The default configured path is `.forgis/reports`, and the GitHub workflow writes to `forgis-runtime/reports` so the files can be uploaded as artifacts. Report paths must be relative runtime paths; absolute paths, path traversal, source/target checkout directories, `target_subdir`, `.git`, and secret-like path segments are rejected. Write failures are reported in the tool-loop JSON/status output and do not fail the run unless `run_report_required: true`.

The workflow uploads only `forgis-runtime/reports/**` as the Forgis reports artifact. It does not upload legacy runtime diagnostics artifacts such as resolved config summaries, run summaries, tool-loop summaries, operation logs, status env files, or long-log previews. This does not change dry-run, real-run, push, or pull request creation gates.

Persistent reports still do not include full source files, full diffs, API keys, tokens, absolute private paths, or unbounded stdout/stderr. v3.4 is still not complete Claude Code and not a migration scheduler.

## Forgis v3.5 Local Skills Phase 1

Forgis v3.5 adds the first local dynamic skills layer. Skills are short Markdown notes stored in this repository under `skills/`. They let Forgis provide focused migration guidance without growing the system prompt into one large document.

The default local skills are:

- `migration_general`
- `ui_style_preservation`
- `swiftui_to_compose`
- `swiftui_to_harmonyos`
- `build_repair`

Configure explicit skills when a task should use a known subset:

```yaml
selected_skills:
  - migration_general
  - swiftui_to_compose
```

When `selected_skills` is non-empty, Forgis loads only those configured skills. Otherwise, when `auto_select_skills: true`, Forgis chooses a small set from the task text and optional target stack hints:

- Android / Compose / Kotlin -> `swiftui_to_compose`
- HarmonyOS / ArkUI / 鸿蒙 -> `swiftui_to_harmonyos`
- UI / interface / 界面 / 组件 / 风格 -> `ui_style_preservation`
- build / test / repair / failure / error -> `build_repair`
- `migration_general` is loaded by default during auto selection

Selected skills enter the model context as a separate `Relevant Forgis Skills` section. They do not change file-tool permissions, dry-run behavior, command allowlists, build/test configuration, push gates, or PR gates. Forgis only reads skills from the repository-local `skills/` directory; it rejects path traversal, absolute paths, secret-like skill names, oversized single skills, and oversized total skill content. It does not download skills and does not read skills from source or target business repositories.

Run reports record only skill names and statistics: `skills_enabled`, `auto_select_skills`, `selected_skill_names`, skipped/failed skill names, and `total_skill_chars`. Reports do not include full skill content.

v3.5 is still not a complete migration scheduler, not complete Claude Code, and not a cross-language build adapter. The task file and repository code remain the source of truth.

## Forgis v3.6 Migration Unit Scheduler Phase 1

Forgis v3.6 adds the first lightweight migration unit scheduler layer. It is disabled by default and does not replace the normal tool loop or `staged_translation`.

When `migration_scheduler_enabled: true`, Forgis builds a bounded `MigrationPlan` from source inventory paths and explicit paths mentioned in the task text. Each `MigrationUnit` stores safe metadata only: unit id, title, source/target virtual paths, unit type, priority, status, reason, selected skill names, latest failure summary, changed paths, and build/test status. It does not store full source files, full diffs, or secret-like content.

The scheduler picks one active unit and injects only that unit summary into the model context. The model is asked to stay focused on that unit, and runtime results can update the unit's changed paths and build/test status. Reports now include a migration plan summary with active unit id and completed/blocked/pending/deferred counts.

Configuration:

```yaml
migration_scheduler_enabled: false
max_migration_units: 50
migration_unit_strategy: inventory
migration_unit_prioritize_ui: true
migration_unit_include_tests: true
migration_unit_include_assets: true
```

`max_migration_units` is capped at 200. The first phase uses simple path rules: UI-like files are prioritized, model/service/config/asset/test paths are classified separately, and task-text explicit paths can seed units when inventory is incomplete. v3.6 is still not a complete automatic migration scheduler, does not do complex planning or RAG, and does not change tool permissions.

## Forgis v3.7 Persistent Migration Plan / Resume Foundation

Forgis v3.7 persists the safe v3.6 `MigrationPlan` metadata as:

- `FORGIS_MIGRATION_PLAN.json`

When the migration scheduler is enabled, Forgis can write this plan to the same safe runtime report/artifact area used by run reports. In GitHub Actions, the workflow passes `forgis-runtime/reports`, so the plan is covered by the existing `forgis-runtime/reports/**` artifact upload. The plan is never written into the source checkout, target checkout, `target_subdir`, `.git`, Desktop, Downloads, Documents, or secret-like paths.

Configuration:

```yaml
migration_plan_persistence_enabled: true
migration_plan_output_dir: .forgis/reports
migration_plan_filename: FORGIS_MIGRATION_PLAN.json
migration_plan_resume_enabled: false
migration_plan_required: false
```

Persistence is enabled by default, but resume is not. Set `migration_plan_resume_enabled: true` explicitly when a later run should load an existing `FORGIS_MIGRATION_PLAN.json`; otherwise Forgis generates a fresh plan. If loading fails or the file is missing, Forgis records the load status and generates a new bounded plan. Plan write failures do not fail the main run unless `migration_plan_required: true`.

The plan JSON stores only safe summaries: schema version, plan id, active unit id, unit counts, unit ids, titles, sanitized source/target virtual paths, unit type, priority, status, reason, selected skill names, last short failure summary, changed paths, and build/test status. It does not store full source files, full diffs, full stdout/stderr, model reasoning, secrets, API keys, or absolute private paths.

v3.7 is still not a full multi-unit automatic scheduler. It does not run multiple migration units across a run, does not do complex RAG, and does not replace `staged_translation`.

## Forgis v3.8 Migration Plan State / Resume Summary Phase 1

Forgis v3.8 makes active unit updates more auditable without turning the scheduler into a multi-unit runner.

New behavior:

- `migration_plan_auto_update_enabled: true` lets Forgis write runtime evidence back to the active unit: sanitized changed paths, build status, test status, and short failure summary.
- `migration_plan_auto_complete_on_success: false` is the safe default. Even when target changes and build/test verification pass, Forgis keeps the unit `active` and records that verification passed but explicit completion is still required. Set it to `true` only when you want evidence-backed automatic completion.
- Active units become `blocked` only from runtime evidence such as max repair attempts, blocked repair state, rejected/timeout verification, or fatal runtime failure. `deferred` also requires a concrete reason.
- The plan event log records bounded, redacted events such as `plan_loaded`, `plan_generated`, `active_unit_selected`, `active_unit_updated`, `unit_completed`, `unit_blocked`, `unit_deferred`, `plan_write_succeeded`, `plan_write_failed`, and `resume_summary_generated`.
- When resume is explicitly enabled and an existing plan loads, Forgis generates a user-facing resume summary with the plan id, active unit id/status, status counts, last stopped reason, changed path summary, and recommended next step.

`tool_loop` final output and `FORGIS_RUN_REPORT.md` / `FORGIS_RUN_REPORT.json` now include plan update status, active unit state, plan events, and resume summary. `staged_translation` only records the active unit id/status in its summary; it does not let the scheduler drive staged micro-phases.

v3.8 still does not automatically execute the next unit, does not run a multi-unit loop, and does not add complex RAG or broader command permissions.

## Forgis v3.9 Manual Active Unit Switch

Forgis v3.9 adds a safe manual interface for selecting the active migration unit from an existing resumed plan. It is still disabled unless `migration_scheduler_enabled: true`, and by default it also requires `migration_plan_resume_enabled: true` plus a successfully loaded plan.

Configuration:

```yaml
migration_plan_requested_active_unit_id: ""
migration_plan_allow_switch_from_blocked: true
migration_plan_allow_switch_from_completed: false
migration_plan_allow_switch_from_deferred: true
migration_plan_switch_requires_resume: true
migration_plan_switch_reason: ""
```

When `migration_plan_requested_active_unit_id` is empty, v3.9 keeps the v3.8 behavior. When it is set, Forgis validates that the unit id exists in `plan.units`, that scheduler/resume requirements are met, and that the target status is allowed. Switching to `blocked` and `deferred` units is allowed by default; switching back to `completed` units is rejected unless explicitly enabled.

Switch attempts are recorded as bounded, redacted plan events: `active_unit_switch_requested`, `active_unit_switch_succeeded`, `active_unit_switch_rejected`, and `active_unit_switch_skipped`. `tool_loop` context is rendered after the switch attempt, so a successful manual switch becomes the active unit context; a rejected switch keeps the previous active unit. Reports include an **Active Unit Switch** section and JSON `active_unit_switch` object with status, requested id, previous active id, active id, and reason/message.

v3.9 does not let the model reorder the plan, does not automatically execute the next unit, and is still not a full multi-unit automatic scheduler. `staged_translation` records the active unit as summary context only; it does not let this switch drive staged phases.

## Forgis v4.8 Manual Unit Status Updates

Forgis v4.8 adds a controlled manual interface for marking one migration unit `completed`, `blocked`, `deferred`, or `active` through configuration. It is still gated by `migration_scheduler_enabled: true`; by default it also requires a successfully resumed persisted plan so a fresh generated plan is not changed by accident.

Configuration:

```yaml
migration_plan_requested_unit_status_unit_id: ""
migration_plan_requested_unit_status: ""
migration_plan_requested_unit_status_reason: ""
migration_plan_allow_manual_complete: true
migration_plan_allow_manual_block: true
migration_plan_allow_manual_defer: true
migration_plan_allow_manual_activate: true
migration_plan_status_update_requires_resume: true
```

When either the unit id or requested status is empty, v4.8 skips the manual status update. Invalid requested statuses are rejected. `completed`, `blocked`, and `deferred` require a non-empty reason; `active` may use the configured reason or a safe default. Each target status is controlled by its `migration_plan_allow_manual_*` flag.

`tool_loop` processes resumed plan load first, then manual active-unit switch, then manual unit status update. A status update to `active` sets `plan.active_unit_id` to that unit. A status update to `completed`, `blocked`, or `deferred` does not select or execute another unit; if that unit was active, the active id remains pointed at it and the context/report show the terminal status until the next explicit instruction.

Attempts are recorded as bounded, redacted plan events: `unit_status_update_requested`, `unit_status_update_succeeded`, `unit_status_update_rejected`, and `unit_status_update_skipped`. `FORGIS_RUN_REPORT.md` / `FORGIS_RUN_REPORT.json` include **Manual Unit Status Update** with unit id, previous status, requested status, final status, result, reason, and message.

v4.8 is still not a full multi-unit automatic scheduler. It does not let the model freely rewrite all unit states, does not reorder the plan, does not run a multi-unit loop, and does not automatically execute the next unit. `staged_translation` continues to record active unit information as summary context only.

## Forgis v4.9 Manual Migration Audit Summary

Forgis v4.9 adds a compact **Migration Plan Audit Summary** to `FORGIS_RUN_REPORT.md`, `FORGIS_RUN_REPORT.json`, and the tool loop runtime outputs. It summarizes the latest manual action, active unit, unit counts, recent key plan events, and a short suggested next action. The suggestion is only guidance; Forgis does not auto-switch, auto-run, or auto-execute the next migration unit.

Audit summary config:

```yaml
migration_plan_audit_summary_enabled: true
migration_plan_audit_max_events: 10
```

`migration_plan_audit_max_events` is capped at 50. The audit summary is redacted and bounded; it does not include full source, full diffs, full logs, secrets, or private absolute paths.

Copyable examples:

Enable scheduler, persistence, and resume:

```yaml
migration_scheduler_enabled: true
migration_plan_resume_enabled: true
migration_plan_persistence_enabled: true
```

Manually switch the active unit:

```yaml
migration_plan_requested_active_unit_id: "ui-homeview-swift"
migration_plan_switch_reason: "Continue the HomeView migration first."
```

Manually mark a unit blocked:

```yaml
migration_plan_requested_unit_status_unit_id: "ui-homeview-swift"
migration_plan_requested_unit_status: "blocked"
migration_plan_requested_unit_status_reason: "Target platform component is missing; needs manual design decision."
```

Manually mark a unit deferred:

```yaml
migration_plan_requested_unit_status_unit_id: "asset-icons"
migration_plan_requested_unit_status: "deferred"
migration_plan_requested_unit_status_reason: "Asset conversion will be handled after UI structure is stable."
```

Manually mark a unit completed:

```yaml
migration_plan_requested_unit_status_unit_id: "model-userprofile"
migration_plan_requested_unit_status: "completed"
migration_plan_requested_unit_status_reason: "Implementation reviewed and build/test passed in the previous run."
```

Switch a unit back to active:

```yaml
migration_plan_requested_unit_status_unit_id: "ui-homeview-swift"
migration_plan_requested_unit_status: "active"
migration_plan_requested_unit_status_reason: "Required design decision has been resolved."
```

`completed`, `blocked`, and `deferred` require `migration_plan_requested_unit_status_reason`. These controls only affect migration plan state. They do not expand `run_command`, `run_build`, or `run_tests` permissions, do not allow arbitrary shell, and do not automatically execute the next unit.

## Forgis v5.0 Final Schema Freeze and Release Checklist

Forgis v5.0 final freezes the v5 report/report-plan surface without adding new runtime powers. The run report schema is `forgis.run_report.v5.0`; the migration plan write schema is `forgis.migration_plan.v5.0`. Plan loading remains backward compatible with `forgis.migration_plan.v4.8`, `v3.9`, `v3.8`, and `v3.7` so older persisted plans can still resume safely.

v5.0 includes:

- DeepSeek tool loop foundation
- safe file tools scoped to Forgis virtual paths
- `search_text`, `git_status`, `git_diff`, `edit_file`, and `apply_patch`
- safe `run_command` inside `target_subdir`
- configured `run_build` and `run_tests`
- build/test feedback summaries
- limited repair loop
- repair event log
- runtime Markdown report and GitHub Step Summary
- persistent `FORGIS_RUN_REPORT.md` and `FORGIS_RUN_REPORT.json`
- reports-only Actions artifact upload through `forgis-runtime/reports/**`
- dynamic local skills
- migration units
- migration plan persistence and explicit resume
- manual active unit switch
- manual unit status update
- Migration Plan Audit Summary
- report fixtures / golden samples

v5.0 does not include:

- full Claude Code parity
- automatic multi-unit execution
- model-controlled plan reordering
- complex RAG
- external skill downloads
- reading skills from source or target business repositories
- arbitrary shell
- cross-language build adapters
- a UI console
- Aider

Report fixtures and golden samples live under `tests/fixtures/reports/` and cover:

- `active`
- `blocked`
- `deferred`
- `completed`

The tests assert key JSON fields and required Markdown section headings instead of doing fragile full-file Markdown/JSON comparisons. They verify that the Migration Plan Audit Summary exists, recommended next actions remain present, active unit ids and status counts are stable, event logs stay bounded, redaction works, and report write safety still rejects source/target checkout paths, `.git`, home Desktop/Downloads/Documents paths, and paths outside the runtime root.

Release checklist:

- Safety defaults: scheduler default off, resume default off, repair loop default off, no automatic next-unit execution, no arbitrary shell, no expanded command permissions, no report/plan writes into source checkout, target checkout, `target_subdir`, or business directories.
- Required tests: `python3 -m py_compile agent/*.py`, `python3 -m unittest`, `bash -n agent/create_pr.sh`, `bash -n agent/build_target.sh`, and `git diff --check`.
- Report regression: active fixture, blocked fixture, deferred fixture, completed fixture, redaction, path safety, event limits, and write safety.
- Actions artifact: only `forgis-runtime/reports/**` is uploaded. This is intended to contain `FORGIS_RUN_REPORT.md`, `FORGIS_RUN_REPORT.json`, and `FORGIS_MIGRATION_PLAN.json` when enabled. The workflow does not upload legacy runtime diagnostics artifacts, business source code, full diffs, secrets, unredacted model output, or a target repository snapshot as part of v5.0 final.
- Out of scope for v5.0: full Claude Code parity, multi-unit auto-execution, complex RAG, cross-language build adapters, UI console, and Aider.

Legacy runtime diagnostics files may still be generated locally for workflow control and log context, but v5.0 final does not publish them as artifacts. A future version should add explicit redaction, bounding, and regression tests before considering those files for artifact upload again.

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

## Pull Request Branch Collisions

Forgis never uses an unconditional force push. If the configured `target_branch` does not exist on `origin`, `create_pr.sh` keeps the normal behavior: create the local output branch from `target_base_branch`, commit the agent output, push that branch, and open the PR from it.

If `origin/$target_branch` already exists, Forgis pushes the current run to a unique fallback branch instead of overwriting the existing branch. In GitHub Actions the fallback name is:

```text
${target_branch}-run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}
```

The PR head is always the branch that was actually pushed. The log prints the configured target branch, whether the remote branch already existed, the actual push branch, and the PR head branch.

## Pull Request Body Size

Forgis keeps PR bodies short and bounded. `create_pr.sh` generates a summary body capped at 30,000 characters, well below GitHub's GraphQL `createPullRequest` limit. The body includes the configured target branch, actual pushed branch, target base branch, target subdir, commit hash when available, run mode, Actions run link when available, and a pointer to the `forgis-reports` artifact.

Full `FORGIS_RUN_REPORT.md`, `FORGIS_RUN_REPORT.json`, `FORGIS_MIGRATION_PLAN.json`, full diffs, tool operation logs, large model summaries, provider raw responses, screenshot bytes/base64, and large build/test output are not copied into the PR body. The PR body includes only a bounded Visual Validation summary from the run report. Download the `forgis-reports` artifact for the complete safe reports.

If GitHub still rejects the body as too long, Forgis automatically retries once with a minimal body capped at 3,000 characters. This retry still uses the actual pushed branch as the PR head.

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
- `search_text(query, root?, regex?, case_sensitive?, max_results?)`
- `git_status(max_entries?)`
- `git_diff(max_chars?)`

Write tools:

- `mkdir(path)`
- `write_file(path, content)`
- `append_file(path, content)`
- `delete_file(path)`
- `edit_file(path, old_text, new_text, expected_replacements?)`
- `apply_patch(path, patch)`

Safe command tool:

- `run_command(command, cwd?, timeout_seconds?, max_output_chars?)`
- `run_build()`
- `run_tests()`

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

`git_status` and `git_diff` operate only on the target workspace and never commit. `run_command` runs without `shell=True`, only inside `target_subdir`, with timeout and output limits, and starts with a conservative allowlist plus explicit dangerous-command blocking.

`run_build` and `run_tests` do not accept model-supplied commands. They only run configured command arrays, still without `shell=True`, inside `target_subdir`, with timeout and output limits. Dangerous commands such as `rm`, `sudo`, `chmod`, `chown`, `curl`, `wget`, `ssh`, `scp`, `git`, and shell interpreters are rejected.

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
