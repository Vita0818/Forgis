# Forgis v5.0

Forgis v5.0 final freezes the current safe report and migration-plan surfaces:

- `FORGIS_RUN_REPORT.json` uses `forgis.run_report.v5.0`.
- `FORGIS_MIGRATION_PLAN.json` writes `forgis.migration_plan.v5.0`.
- Plan loading remains compatible with `forgis.migration_plan.v4.8`, `v3.9`, `v3.8`, and `v3.7`.

Main included capabilities:

- DeepSeek tool loop with safe virtual-path file tools.
- Clarified `FORGIS_CONFIG.yml` guidance for v5.0: `target_repo` is workflow/CLI input, `source_ref` replaces unsupported `source_branch`, target-stack instructions belong in `FORGIS_TASK.md`, DeepSeek examples use `deepseek-v4-pro` / `deepseek-v4-flash`, and omitted build/test commands are represented by leaving `build_command` / `test_command` unset.
- Long-run sizing fields keep moderate defaults but allow much larger explicit values: `max_iterations` up to `5000`, `max_tool_result_chars` up to `5000000`, `max_command_output_chars` up to `2000000`, `run_report_max_events` up to `10000`, and `run_report_max_chars` up to `20000000`.
- Safe PR branch collision handling: if `origin/$target_branch` already exists, `create_pr.sh` pushes the current run to `${target_branch}-run-${GITHUB_RUN_ID}-${GITHUB_RUN_ATTEMPT}` and uses that fallback branch as the PR head instead of force-pushing over the existing branch.
- Bounded search, diff, edit, command, build, and test feedback tools.
- Limited repair loop, repair events, Markdown/JSON reports, and GitHub Step Summary.
- Local dynamic skills, migration units, plan persistence/resume, manual active-unit switch, manual unit status update, and Migration Plan Audit Summary.
- Report fixtures/golden samples for active, blocked, deferred, and completed plan states.
- Reports-only GitHub Actions artifact scope: v5.0 final uploads only `forgis-runtime/reports/**`, intended for `FORGIS_RUN_REPORT.md`, `FORGIS_RUN_REPORT.json`, and `FORGIS_MIGRATION_PLAN.json` when enabled.

Non-goals for v5.0:

- Full Claude Code parity.
- Multi-unit automatic execution.
- Model-controlled plan reordering.
- Complex RAG.
- External skill downloads or skills read from business repositories.
- Arbitrary shell access.
- Aider.
- Legacy runtime diagnostics artifacts; these should only be reconsidered after explicit redaction, bounding, and regression tests.
- Target repository snapshot artifacts, business source code, full diffs, secrets, or unredacted model output.

Release checklist:

- `python3 -m py_compile agent/*.py`
- `python3 -m unittest`
- `bash -n agent/create_pr.sh`
- `bash -n agent/build_target.sh`
- `git diff --check`
