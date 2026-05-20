from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from build_feedback import summarize_build_failure, summarize_command_result, summarize_test_failure
from deepseek_agent import build_initial_messages, initial_messages, system_message
from file_tools import FileToolSandbox, ToolError
from forgis_config import resolve_config, require_path_inside_subdir
from guardrails import changed_read_only_paths, scan_secret_leaks, snapshot_paths, target_scope_violations
from model_env import describe_model_env, parse_model_env_json, require_model_env_values
from migration_scheduler import (
    create_units_from_inventory,
    mark_unit_active,
    mark_unit_blocked,
    mark_unit_completed,
    mark_unit_deferred,
    select_next_unit,
)
from migration_state import (
    append_plan_event,
    generate_resume_summary,
    request_active_unit_switch,
    request_unit_status_update,
    safe_active_unit_switch_result,
    safe_unit_status_update_result,
    safe_plan_events,
    validate_manual_unit_status_update,
    validate_active_unit_switch,
    update_active_unit_state,
)
from migration_plan_store import (
    MIGRATION_PLAN_FILENAME,
    deserialize_plan,
    load_migration_plan,
    serialize_plan,
    write_migration_plan,
)
from migration_units import MigrationPlan, MigrationUnit, stable_unit_id
from plan_audit import build_migration_plan_audit_summary, migration_plan_recommended_next_action
from repair_loop import RepairLoopController
from repair_report import (
    render_compact_actions_summary,
    render_repair_report,
    write_github_step_summary,
)
from run_report import (
    RUN_REPORT_JSON_FILENAME,
    RUN_REPORT_MARKDOWN_FILENAME,
    render_run_report_json,
    render_run_report_markdown,
    write_run_reports,
)
from runtime_controller import RuntimeController
from skill_loader import (
    DEFAULT_SKILLS_DIR,
    SkillLoaderError,
    list_available_skills,
    load_skill,
    render_selected_skills,
    select_skills,
)
from source_inventory import bundled_units_for_folder, collect_source_inventory, safe_source_report_name
from tool_loop import run_tool_loop, write_status
from validate_target_output import files_snapshot, meaningful_changes, validate


class FakeDeepSeekClient:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls.append(json.loads(json.dumps({"messages": messages, "tools": tools})))
        if not self.responses:
            raise AssertionError("FakeDeepSeekClient ran out of responses")
        return self.responses.pop(0)


class ForgisConfigTests(unittest.TestCase):
    def run_cmd(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            args,
            cwd=cwd or REPO_ROOT,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if check and result.returncode != 0:
            raise AssertionError(
                f"command failed with exit {result.returncode}: {' '.join(args)}\n{result.stdout}"
            )
        return result

    def init_git_repo(self, root: Path) -> None:
        self.run_cmd(["git", "init", "-q"], cwd=root)
        self.run_cmd(["git", "config", "user.name", "test"], cwd=root)
        self.run_cmd(["git", "config", "user.email", "test@example.invalid"], cwd=root)

    def commit_all(self, root: Path, message: str = "initial") -> None:
        self.run_cmd(["git", "add", "."], cwd=root)
        self.run_cmd(["git", "commit", "-q", "-m", message], cwd=root)

    def workflow_step_block(self, workflow: str, name: str) -> str:
        marker = f"      - name: {name}\n"
        start = workflow.index(marker)
        next_start = workflow.find("\n      - name: ", start + len(marker))
        return workflow[start:] if next_start == -1 else workflow[start:next_start]

    def write_config(self, target: Path, extra: str = "", *, task_text: str = "# Mock Task\n\nUse mock files only.") -> None:
        target.mkdir(parents=True, exist_ok=True)
        config = textwrap.dedent(
            """\
            source_repo: owner/source-repo
            source_ref: main
            target_subdir: target-output
            task_prompt_path: FORGIS_TASK.md
            agent_backend: deepseek
            model: provider/model-name
            target_branch: forgis/output
            target_base_branch: main
            run_log_path: target-output/FORGIS_LOG.md
            dry_run: true
            run_agent: false
            confirm_real_run: false
            max_iterations: 8
            max_tool_result_chars: 1000
            model_env:
              DEEPSEEK_API_KEY: DEEPSEEK_API_KEY
            validation_commands: []
            success_checks: []
            """
        )
        if extra:
            config += extra if extra.endswith("\n") else extra + "\n"
        (target / "FORGIS_CONFIG.yml").write_text(config, encoding="utf-8")
        (target / "FORGIS_TASK.md").write_text(task_text, encoding="utf-8")

    def staged_extra(
        self,
        *,
        max_iterations: int = 12,
        min_total_iterations: int = 0,
        min_processed_units: int = 0,
        max_units_per_run: int = 12,
        overview_min: int = 0,
        per_file_min: int = 0,
        stabilization_min: int = 0,
        include_globs: list[str] | None = None,
        folder_max_bundle_chars: int = 80000,
        strict_mode: bool | None = None,
    ) -> str:
        selected_globs = ["**/*"] if include_globs is None else include_globs
        include_lines = "\n".join(f"      - {item!r}" for item in selected_globs)
        if not include_lines:
            include_lines = "      []"
        return textwrap.dedent(
            f"""\
            dry_run: false
            run_agent: true
            confirm_real_run: true
            {"strict_mode: " + str(strict_mode).lower() if strict_mode is not None else ""}
            execution_mode: staged_translation
            max_iterations: {max_iterations}
            staged_translation:
              min_total_iterations: {min_total_iterations}
              min_processed_units: {min_processed_units}
              max_units_per_run: {max_units_per_run}
              phases:
                overview:
                  min_iterations: {overview_min}
                  max_iterations: {max(overview_min, max_iterations)}
                per_file:
                  min_iterations: {per_file_min}
                  max_iterations: {max(per_file_min, max_iterations)}
                stabilization:
                  min_iterations: {stabilization_min}
                  max_iterations: {max(stabilization_min, max_iterations)}
              folder_batch_review:
                enabled: true
                max_bundle_chars: {folder_max_bundle_chars}
              source_inventory:
                include_globs:
            {include_lines}
            """
        )

    def tool_response(
        self,
        *calls: tuple[str, str, dict[str, Any]],
        reasoning_content: str | None = None,
    ) -> dict[str, Any]:
        message: dict[str, Any] = {
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(arguments),
                    },
                }
                for call_id, name, arguments in calls
            ]
        }
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content
        return {"choices": [{"message": message}]}

    def final_response(self, summary: str, *, reasoning_content: str | None = None) -> dict[str, Any]:
        message: dict[str, Any] = {"content": json.dumps({"final_summary": summary})}
        if reasoning_content is not None:
            message["reasoning_content"] = reasoning_content
        return {"choices": [{"message": message}]}

    def tool_results_seen_by_fake_client(self, fake: FakeDeepSeekClient) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for call in fake.calls:
            for message in call["messages"]:
                if message.get("role") != "tool":
                    continue
                tool_id = str(message.get("tool_call_id", ""))
                if tool_id in seen_ids:
                    continue
                seen_ids.add(tool_id)
                results.append(json.loads(message["content"]))
        return results

    def staged_overview_response(self) -> dict[str, Any]:
        return self.tool_response(
            (
                "plan",
                "write_file",
                {"path": "target_subdir/FORGIS_TRANSLATION_PLAN.md", "content": "# Plan\n"},
            ),
            (
                "map",
                "write_file",
                {"path": "target_subdir/FORGIS_SOURCE_TARGET_MAP.md", "content": "| Source | Target |\n"},
            ),
            (
                "progress",
                "write_file",
                {"path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md", "content": "# Progress\n"},
            ),
        )

    def command_config_extra(
        self,
        *,
        build_command: list[str] | None = None,
        test_command: list[str] | None = None,
        build_timeout_seconds: int | None = None,
        test_timeout_seconds: int | None = None,
        max_command_output_chars: int | None = None,
    ) -> str:
        lines: list[str] = []
        for field, command in (("build_command", build_command), ("test_command", test_command)):
            if command is None:
                continue
            lines.append(f"{field}:")
            lines.extend(f"  - {json.dumps(item)}" for item in command)
        if build_timeout_seconds is not None:
            lines.append(f"build_timeout_seconds: {build_timeout_seconds}")
        if test_timeout_seconds is not None:
            lines.append(f"test_timeout_seconds: {test_timeout_seconds}")
        if max_command_output_chars is not None:
            lines.append(f"max_command_output_chars: {max_command_output_chars}")
        return "\n".join(lines) + ("\n" if lines else "")

    def make_source_target(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        target = root / "target"
        source.mkdir()
        target.mkdir()
        (source / "input.txt").write_text("mock source", encoding="utf-8")
        self.write_config(target)
        return source, target

    def switch_config(self, **overrides: Any) -> SimpleNamespace:
        values: dict[str, Any] = {
            "migration_scheduler_enabled": True,
            "migration_plan_allow_switch_from_blocked": True,
            "migration_plan_allow_switch_from_completed": False,
            "migration_plan_allow_switch_from_deferred": True,
            "migration_plan_switch_requires_resume": True,
            "migration_plan_switch_reason": "",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def status_update_config(self, **overrides: Any) -> SimpleNamespace:
        values: dict[str, Any] = {
            "migration_scheduler_enabled": True,
            "migration_plan_requested_unit_status_reason": "",
            "migration_plan_allow_manual_complete": True,
            "migration_plan_allow_manual_block": True,
            "migration_plan_allow_manual_defer": True,
            "migration_plan_allow_manual_activate": True,
            "migration_plan_status_update_requires_resume": True,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def make_sandbox(self, root: Path, *, max_chars: int = 1000) -> FileToolSandbox:
        source, target = self.make_source_target(root)
        (target / "target-output").mkdir()
        (target / "target-output/existing.txt").write_text("old\n", encoding="utf-8")
        return FileToolSandbox(
            source_root=source,
            target_root=target,
            target_subdir="target-output",
            config_path="FORGIS_CONFIG.yml",
            task_path="FORGIS_TASK.md",
            max_result_chars=max_chars,
        )

    def make_configured_sandbox(
        self,
        root: Path,
        *,
        extra: str = "",
        max_chars: int = 1000,
    ) -> tuple[FileToolSandbox, Path, Path]:
        source, target = self.make_source_target(root)
        (target / "target-output").mkdir()
        self.write_config(target, extra=extra)
        resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
        sandbox = FileToolSandbox(
            source_root=source,
            target_root=target,
            target_subdir=resolved.target_subdir,
            config_path=resolved.config_path,
            task_path=resolved.task_prompt_path,
            max_result_chars=max_chars,
            build_command=resolved.build_command,
            test_command=resolved.test_command,
            build_timeout_seconds=resolved.build_timeout_seconds,
            test_timeout_seconds=resolved.test_timeout_seconds,
            max_command_output_chars=resolved.max_command_output_chars,
        )
        return sandbox, source, target

    def test_main_workflow_exposes_only_target_repo_and_secret_candidates(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/migrate.yml").read_text(encoding="utf-8")
        inputs_block = workflow.split("inputs:", 1)[1].split("permissions:", 1)[0]
        self.assertIn("target_repo:", inputs_block)
        forbidden_inputs = [
            "config_path:",
            "source_repo:",
            "target_subdir:",
            "task_prompt_path:",
            "dry_run:",
            "run_agent:",
            "model:",
            "api key:",
        ]
        for forbidden in forbidden_inputs:
            self.assertNotIn(forbidden, inputs_block)
        for secret_name in (
            "FORGIS_MODEL_API_KEY",
            "DEEPSEEK_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
        ):
            self.assertIn(secret_name, workflow)

    def test_workflow_gates_snapshot_dependent_steps_after_prerequisites(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/migrate.yml").read_text(encoding="utf-8")

        validate_block = self.workflow_step_block(workflow, "Validate DeepSeek target changes")
        self.assertNotIn("always()", validate_block)
        self.assertIn("steps.snapshot_target_output.outcome == 'success'", validate_block)
        self.assertIn("steps.tool_loop.outcome == 'success'", validate_block)

        readonly_block = self.workflow_step_block(workflow, "Verify read-only target inputs")
        self.assertNotIn("always()", readonly_block)
        self.assertIn("steps.snapshot_readonly.outcome == 'success'", readonly_block)
        self.assertIn("steps.tool_loop.outcome == 'success'", readonly_block)

        target_scope_block = self.workflow_step_block(workflow, "Verify target writable scope")
        self.assertNotIn("always()", target_scope_block)
        self.assertIn("steps.run_controller.outcome == 'success'", target_scope_block)
        self.assertIn("steps.tool_loop.outcome == 'success'", target_scope_block)

        log_block = self.workflow_step_block(workflow, "Append long-term Forgis log")
        self.assertNotIn("always()", log_block)
        self.assertIn("steps.run_controller.outcome == 'success'", log_block)
        self.assertIn("steps.validation_commands.outcome == 'success'", log_block)

        pr_block = self.workflow_step_block(workflow, "Create pull request")
        self.assertIn("steps.resolve_base.outputs.dry_run == 'false'", pr_block)
        self.assertIn("steps.check_readonly.outcome == 'success'", pr_block)
        self.assertIn("steps.check_secret_leaks.outcome == 'success'", pr_block)

        self.assertIn("strict_mode=false; target output validation failures", validate_block)
        validation_block = self.workflow_step_block(workflow, "Run configured validation commands")
        self.assertIn("validation_commands failed and strict_mode=true", validation_block)
        self.assertIn("continuing because strict_mode=false", validation_block)

        diff_block = self.workflow_step_block(workflow, "Show target repository diff")
        self.assertIn("if: always()", diff_block)
        self.assertIn("Target repository checkout is unavailable", diff_block)

        self.assertIn('--report-output-dir "$GITHUB_WORKSPACE/forgis-runtime/reports"', workflow)
        self.assertEqual(workflow.count("uses: actions/upload-artifact@v4"), 1)
        reports_artifact_block = self.workflow_step_block(workflow, "Upload Forgis reports")
        self.assertIn("name: forgis-reports", reports_artifact_block)
        self.assertIn("path: forgis-runtime/reports/**", reports_artifact_block)
        for legacy_artifact_path in (
            "forgis-runtime/resolved_config.md",
            "forgis-runtime/run_summary.md",
            "forgis-runtime/tool_loop_summary.json",
            "forgis-runtime/tool_operations.json",
            "forgis-runtime/deepseek_status.env",
            "forgis-runtime/forgis_log_entry.md",
            "forgis-runtime/target-repo-snapshot.tar.gz",
            "source-repo",
            "target-repo",
            "target-output",
        ):
            self.assertNotIn(legacy_artifact_path, reports_artifact_block)
        self.assertNotIn("Upload resolved config summary", workflow)
        self.assertNotIn("Upload run summary", workflow)
        self.assertNotIn("Upload DeepSeek tool loop summary", workflow)
        self.assertNotIn("Upload generated long log preview", workflow)
        self.assertNotIn("Package target output snapshot", workflow)
        self.assertNotIn("Upload target output snapshot", workflow)
        self.assertNotIn("target-repo-snapshot.tar.gz", workflow)
        self.assertNotIn("forgis-target-repo", workflow)

    def test_aider_related_files_and_backend_are_removed(self) -> None:
        removed = [
            "agent/aider_compat.py",
            "agent/build_prompt.py",
            "agent/collect_source.py",
            "agent/prompt_diagnostics.py",
            "agent/run_aider.sh",
        ]
        for relative in removed:
            self.assertFalse((REPO_ROOT / relative).exists(), relative)
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target, extra="agent_backend: aider\n")
            with self.assertRaisesRegex(ValueError, "deepseek"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_forgis_config_is_required_and_target_repo_is_workflow_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            with self.assertRaises(FileNotFoundError):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.source_repo, "owner/source-repo")
            self.assertEqual(resolved.target_repo, "owner/target-repo")
            self.assertEqual(resolved.target_subdir, "target-output")
            self.assertFalse(resolved.run_agent)
            self.assertFalse(resolved.strict_mode)

            (target / "FORGIS_CONFIG.yml").write_text(
                (target / "FORGIS_CONFIG.yml").read_text(encoding="utf-8")
                + "target_repo: owner/should-not-be-read\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_strict_mode_can_be_enabled_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target, extra="strict_mode: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertTrue(resolved.strict_mode)
            self.assertEqual(resolved.env()["STRICT_MODE"], "true")

    def test_execution_mode_defaults_to_tool_loop_and_staged_defaults_parse(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.execution_mode, "tool_loop")
            self.assertEqual(resolved.env()["EXECUTION_MODE"], "tool_loop")

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    execution_mode: staged_translation
                    max_iterations: 120
                    """
                ),
            )
            staged = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(staged.execution_mode, "staged_translation")
            self.assertEqual(staged.staged_translation.min_total_iterations, 120)
            self.assertEqual(staged.staged_translation.min_processed_units, 3)
            self.assertEqual(staged.staged_translation.max_units_per_run, 12)
            self.assertTrue(staged.staged_translation.enforce_micro_phases)
            self.assertTrue(staged.staged_translation.require_target_effect_or_deferred_reason)
            self.assertTrue(staged.staged_translation.low_impact_warning.enabled)
            self.assertEqual(staged.staged_translation.overview.min_iterations, 20)
            self.assertEqual(staged.staged_translation.progress_files.plan, "FORGIS_TRANSLATION_PLAN.md")
            self.assertIn("STAGED_TRANSLATION_JSON", staged.env())

    def test_build_and_test_command_config_is_optional_and_array_based(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.build_command, ())
            self.assertEqual(resolved.test_command, ())
            self.assertEqual(resolved.build_timeout_seconds, 60)
            self.assertEqual(resolved.test_timeout_seconds, 60)
            self.assertEqual(resolved.max_command_output_chars, 8000)

            self.write_config(
                target,
                extra=self.command_config_extra(
                    build_command=[sys.executable, "-m", "py_compile", "ok.py"],
                    test_command=[sys.executable, "-m", "unittest", "discover"],
                    build_timeout_seconds=3,
                    test_timeout_seconds=4,
                    max_command_output_chars=120,
                ),
            )
            configured = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(configured.build_command, (sys.executable, "-m", "py_compile", "ok.py"))
            self.assertEqual(configured.test_command, (sys.executable, "-m", "unittest", "discover"))
            self.assertEqual(configured.build_timeout_seconds, 3)
            self.assertEqual(configured.test_timeout_seconds, 4)
            self.assertEqual(configured.max_command_output_chars, 120)
            self.assertIn("BUILD_COMMAND_JSON", configured.env())

            self.write_config(target, extra="build_command: python -m py_compile ok.py\n")
            with self.assertRaisesRegex(ValueError, "build_command"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_repair_loop_config_defaults_and_bounds_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertFalse(resolved.repair_loop_enabled)
            self.assertEqual(resolved.max_repair_attempts, 2)
            self.assertTrue(resolved.repair_requires_diff_check)
            self.assertTrue(resolved.repair_requires_build_or_test)
            self.assertTrue(resolved.repair_stop_on_success)
            self.assertEqual(resolved.env()["REPAIR_LOOP_ENABLED"], "false")

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    repair_loop_enabled: true
                    max_repair_attempts: 3
                    repair_requires_diff_check: false
                    repair_requires_build_or_test: false
                    repair_stop_on_success: false
                    """
                ),
            )
            configured = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertTrue(configured.repair_loop_enabled)
            self.assertEqual(configured.max_repair_attempts, 3)
            self.assertFalse(configured.repair_requires_diff_check)
            self.assertFalse(configured.repair_requires_build_or_test)
            self.assertFalse(configured.repair_stop_on_success)
            self.assertEqual(configured.env()["MAX_REPAIR_ATTEMPTS"], "3")

            self.write_config(target, extra="repair_loop_enabled: true\nmax_repair_attempts: 6\n")
            with self.assertRaisesRegex(ValueError, "max_repair_attempts"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_run_report_config_defaults_custom_values_and_path_safety(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertTrue(resolved.run_report_enabled)
            self.assertEqual(resolved.run_report_output_dir, ".forgis/reports")
            self.assertTrue(resolved.run_report_include_events)
            self.assertEqual(resolved.run_report_max_events, 100)
            self.assertEqual(resolved.run_report_max_chars, 200000)
            self.assertFalse(resolved.run_report_required)
            self.assertEqual(resolved.env()["RUN_REPORT_ENABLED"], "true")

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    run_report_enabled: false
                    run_report_output_dir: forgis-runtime/reports
                    run_report_include_events: false
                    run_report_max_events: 12
                    run_report_max_chars: 50000
                    run_report_required: true
                    """
                ),
            )
            configured = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertFalse(configured.run_report_enabled)
            self.assertEqual(configured.run_report_output_dir, "forgis-runtime/reports")
            self.assertFalse(configured.run_report_include_events)
            self.assertEqual(configured.run_report_max_events, 12)
            self.assertEqual(configured.run_report_max_chars, 50000)
            self.assertTrue(configured.run_report_required)

            for unsafe in (
                "/tmp/reports",
                "../reports",
                "target-repo/reports",
                "source-repo/reports",
                "target-output/reports",
                "secret/reports",
            ):
                self.write_config(target, extra=f"run_report_output_dir: {json.dumps(unsafe)}\n")
                with self.assertRaisesRegex(ValueError, "run_report_output_dir"):
                    resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_skill_config_defaults_custom_values_and_safety(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertTrue(resolved.skills_enabled)
            self.assertEqual(resolved.selected_skills, ())
            self.assertTrue(resolved.auto_select_skills)
            self.assertEqual(resolved.max_skill_chars, 12000)
            self.assertEqual(resolved.max_total_skill_chars, 30000)
            self.assertEqual(resolved.env()["SKILLS_ENABLED"], "true")

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    skills_enabled: false
                    selected_skills:
                      - build_repair
                      - migration_general
                    auto_select_skills: false
                    max_skill_chars: 1000
                    max_total_skill_chars: 2000
                    """
                ),
            )
            configured = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertFalse(configured.skills_enabled)
            self.assertEqual(configured.selected_skills, ("build_repair", "migration_general"))
            self.assertFalse(configured.auto_select_skills)
            self.assertEqual(configured.max_skill_chars, 1000)
            self.assertEqual(configured.max_total_skill_chars, 2000)
            self.assertIn("SELECTED_SKILLS_JSON", configured.env())

            for extra in (
                "selected_skills:\n  - ../migration_general\n",
                "selected_skills:\n  - /tmp/migration_general\n",
                "selected_skills:\n  - secret_rules\n",
                "max_skill_chars: 99\n",
                "max_total_skill_chars: 100001\n",
            ):
                self.write_config(target, extra=extra)
                with self.assertRaises(ValueError):
                    resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_migration_scheduler_config_defaults_custom_values_and_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertFalse(resolved.migration_scheduler_enabled)
            self.assertEqual(resolved.max_migration_units, 50)
            self.assertEqual(resolved.migration_unit_strategy, "inventory")
            self.assertTrue(resolved.migration_unit_prioritize_ui)
            self.assertTrue(resolved.migration_unit_include_tests)
            self.assertTrue(resolved.migration_unit_include_assets)
            self.assertTrue(resolved.migration_plan_persistence_enabled)
            self.assertEqual(resolved.migration_plan_output_dir, ".forgis/reports")
            self.assertEqual(resolved.migration_plan_filename, "FORGIS_MIGRATION_PLAN.json")
            self.assertFalse(resolved.migration_plan_resume_enabled)
            self.assertFalse(resolved.migration_plan_required)
            self.assertTrue(resolved.migration_plan_auto_update_enabled)
            self.assertTrue(resolved.migration_plan_resume_summary_enabled)
            self.assertEqual(resolved.migration_plan_event_log_max_events, 100)
            self.assertTrue(resolved.migration_plan_audit_summary_enabled)
            self.assertEqual(resolved.migration_plan_audit_max_events, 10)
            self.assertFalse(resolved.migration_plan_auto_complete_on_success)
            self.assertEqual(resolved.migration_plan_requested_active_unit_id, "")
            self.assertTrue(resolved.migration_plan_allow_switch_from_blocked)
            self.assertFalse(resolved.migration_plan_allow_switch_from_completed)
            self.assertTrue(resolved.migration_plan_allow_switch_from_deferred)
            self.assertTrue(resolved.migration_plan_switch_requires_resume)
            self.assertEqual(resolved.migration_plan_switch_reason, "")
            self.assertEqual(resolved.migration_plan_requested_unit_status_unit_id, "")
            self.assertEqual(resolved.migration_plan_requested_unit_status, "")
            self.assertEqual(resolved.migration_plan_requested_unit_status_reason, "")
            self.assertTrue(resolved.migration_plan_allow_manual_complete)
            self.assertTrue(resolved.migration_plan_allow_manual_block)
            self.assertTrue(resolved.migration_plan_allow_manual_defer)
            self.assertTrue(resolved.migration_plan_allow_manual_activate)
            self.assertTrue(resolved.migration_plan_status_update_requires_resume)
            self.assertEqual(resolved.env()["MIGRATION_SCHEDULER_ENABLED"], "false")

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    migration_scheduler_enabled: true
                    max_migration_units: 12
                    migration_unit_strategy: task_text
                    migration_unit_prioritize_ui: false
                    migration_unit_include_tests: false
                    migration_unit_include_assets: false
                    migration_plan_persistence_enabled: false
                    migration_plan_output_dir: forgis-runtime/plans
                    migration_plan_filename: CUSTOM_MIGRATION_PLAN.json
                    migration_plan_resume_enabled: true
                    migration_plan_required: true
                    migration_plan_auto_update_enabled: false
                    migration_plan_resume_summary_enabled: false
                    migration_plan_event_log_max_events: 12
                    migration_plan_audit_summary_enabled: false
                    migration_plan_audit_max_events: 7
                    migration_plan_auto_complete_on_success: true
                    migration_plan_requested_active_unit_id: ui-login-12345678
                    migration_plan_allow_switch_from_blocked: false
                    migration_plan_allow_switch_from_completed: true
                    migration_plan_allow_switch_from_deferred: false
                    migration_plan_switch_requires_resume: false
                    migration_plan_switch_reason: Manual reviewer selected login unit
                    migration_plan_requested_unit_status_unit_id: ui-settings-12345678
                    migration_plan_requested_unit_status: completed
                    migration_plan_requested_unit_status_reason: Manual review verified settings unit
                    migration_plan_allow_manual_complete: false
                    migration_plan_allow_manual_block: false
                    migration_plan_allow_manual_defer: false
                    migration_plan_allow_manual_activate: false
                    migration_plan_status_update_requires_resume: false
                    """
                ),
            )
            configured = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertTrue(configured.migration_scheduler_enabled)
            self.assertEqual(configured.max_migration_units, 12)
            self.assertEqual(configured.migration_unit_strategy, "task_text")
            self.assertFalse(configured.migration_unit_prioritize_ui)
            self.assertFalse(configured.migration_unit_include_tests)
            self.assertFalse(configured.migration_unit_include_assets)
            self.assertFalse(configured.migration_plan_persistence_enabled)
            self.assertEqual(configured.migration_plan_output_dir, "forgis-runtime/plans")
            self.assertEqual(configured.migration_plan_filename, "CUSTOM_MIGRATION_PLAN.json")
            self.assertTrue(configured.migration_plan_resume_enabled)
            self.assertTrue(configured.migration_plan_required)
            self.assertFalse(configured.migration_plan_auto_update_enabled)
            self.assertFalse(configured.migration_plan_resume_summary_enabled)
            self.assertEqual(configured.migration_plan_event_log_max_events, 12)
            self.assertFalse(configured.migration_plan_audit_summary_enabled)
            self.assertEqual(configured.migration_plan_audit_max_events, 7)
            self.assertTrue(configured.migration_plan_auto_complete_on_success)
            self.assertEqual(configured.migration_plan_requested_active_unit_id, "ui-login-12345678")
            self.assertFalse(configured.migration_plan_allow_switch_from_blocked)
            self.assertTrue(configured.migration_plan_allow_switch_from_completed)
            self.assertFalse(configured.migration_plan_allow_switch_from_deferred)
            self.assertFalse(configured.migration_plan_switch_requires_resume)
            self.assertEqual(configured.migration_plan_switch_reason, "Manual reviewer selected login unit")
            self.assertEqual(configured.migration_plan_requested_unit_status_unit_id, "ui-settings-12345678")
            self.assertEqual(configured.migration_plan_requested_unit_status, "completed")
            self.assertEqual(configured.migration_plan_requested_unit_status_reason, "Manual review verified settings unit")
            self.assertFalse(configured.migration_plan_allow_manual_complete)
            self.assertFalse(configured.migration_plan_allow_manual_block)
            self.assertFalse(configured.migration_plan_allow_manual_defer)
            self.assertFalse(configured.migration_plan_allow_manual_activate)
            self.assertFalse(configured.migration_plan_status_update_requires_resume)
            self.assertEqual(configured.env()["MIGRATION_PLAN_REQUESTED_UNIT_STATUS"], "completed")
            self.assertEqual(configured.env()["MIGRATION_PLAN_AUDIT_MAX_EVENTS"], "7")

            self.write_config(target, extra="max_migration_units: 201\n")
            with self.assertRaisesRegex(ValueError, "max_migration_units"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            self.write_config(target, extra="migration_unit_strategy: everywhere\n")
            with self.assertRaisesRegex(ValueError, "migration_unit_strategy"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            for extra in (
                "migration_plan_output_dir: /tmp/reports\n",
                "migration_plan_output_dir: ../reports\n",
                "migration_plan_output_dir: target-output/reports\n",
                "migration_plan_output_dir: secret/reports\n",
                "migration_plan_filename: ../FORGIS_MIGRATION_PLAN.json\n",
                "migration_plan_filename: secret-token.json\n",
                "migration_plan_filename: FORGIS_MIGRATION_PLAN.md\n",
                "migration_plan_event_log_max_events: 501\n",
                "migration_plan_audit_max_events: 51\n",
                "migration_plan_requested_active_unit_id: ../escape\n",
                "migration_plan_requested_active_unit_id: secret-unit\n",
                "migration_plan_switch_reason: |\n  bad\n  reason\n",
                "migration_plan_requested_unit_status_unit_id: ../escape\n",
                "migration_plan_requested_unit_status_unit_id: secret-unit\n",
                "migration_plan_requested_unit_status: |\n  bad\n  status\n",
                "migration_plan_requested_unit_status_reason: |\n  bad\n  reason\n",
            ):
                self.write_config(target, extra=extra)
                with self.assertRaisesRegex(ValueError, "migration_plan"):
                    resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_migration_unit_model_sanitizes_and_enforces_status_transitions(self) -> None:
        unit_id_1 = stable_unit_id(
            title="Login token=secret",
            source_paths=["/Users/test/Secret/LoginView.swift"],
            unit_type="ui",
        )
        unit_id_2 = stable_unit_id(
            title="Login token=secret",
            source_paths=["/Users/test/Secret/LoginView.swift"],
            unit_type="ui",
        )
        self.assertEqual(unit_id_1, unit_id_2)
        self.assertIn("ui-", unit_id_1)

        unit = MigrationUnit(
            title="Very long TOKEN=secret-value " + ("x" * 300),
            source_paths=["/Users/test/Secret/LoginView.swift", "target-output/passwords.yml"],
            target_paths=["target_subdir/LoginView.kt"],
            unit_type="ui",
            status="pending",
            reason="Blocked by API_KEY=super-secret-value",
        )
        summary = json.dumps(unit.as_summary(), ensure_ascii=False)
        self.assertLessEqual(len(unit.title), 120)
        self.assertIn("[redacted]", summary)
        self.assertNotIn("super-secret-value", summary)
        self.assertNotIn("/Users/test", summary)
        unit.transition_to("active")
        unit.transition_to("completed", reason="verified by runtime evidence")
        with self.assertRaisesRegex(ValueError, "illegal"):
            unit.transition_to("blocked")

    def test_migration_scheduler_generates_prioritized_bounded_units_without_file_reads(self) -> None:
        class InventoryItem:
            def __init__(self, path: str) -> None:
                self.path = path

        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target, extra="migration_scheduler_enabled: true\nmax_migration_units: 2\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            inventory = [
                InventoryItem("Sources/DataModel.swift"),
                InventoryItem("Sources/LoginView.swift"),
                InventoryItem("Sources/AuthService.swift"),
                InventoryItem("Tests/LoginViewTests.swift"),
            ]
            with mock.patch("pathlib.Path.read_text", side_effect=AssertionError("scheduler read file content")):
                plan = create_units_from_inventory(inventory, resolved, task_text="")

            self.assertEqual(len(plan.units), 2)
            self.assertEqual(plan.units[0].unit_type, "ui")
            self.assertIn("LoginView.swift", plan.units[0].source_paths[0])
            self.assertEqual(plan.pending_count, 2)

            first = select_next_unit(plan)
            self.assertIsNotNone(first)
            active = mark_unit_active(plan, first.unit_id)
            self.assertEqual(active.status, "active")
            mark_unit_completed(plan, active.unit_id)
            self.assertEqual(plan.completed_count, 1)

            second = select_next_unit(plan)
            self.assertIsNotNone(second)
            mark_unit_active(plan, second.unit_id)
            mark_unit_blocked(plan, second.unit_id, "Missing target support TOKEN=secret-token")
            self.assertEqual(plan.blocked_count, 1)
            self.assertNotIn("secret-token", json.dumps(plan.as_summary(), ensure_ascii=False))
            self.assertIsNone(select_next_unit(plan))

            mark_unit_active(plan, second.unit_id)
            mark_unit_deferred(plan, second.unit_id, "Defer until target API exists")
            self.assertEqual(plan.deferred_count, 1)

    def test_migration_scheduler_task_text_paths_can_create_units(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    migration_scheduler_enabled: true
                    migration_unit_strategy: task_text
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            plan = create_units_from_inventory(
                [],
                resolved,
                task_text="Migrate `source/App/LoginScreen.swift` and update `target_subdir/App/LoginScreen.kt`.",
            )
            self.assertEqual(len(plan.units), 2)
            self.assertEqual(plan.units[0].unit_type, "ui")
            rendered = json.dumps(plan.as_summary(), ensure_ascii=False)
            self.assertIn("source/App/LoginScreen.swift", rendered)
            self.assertIn("target_subdir/App/LoginScreen.kt", rendered)

    def test_migration_plan_serialization_round_trips_safely(self) -> None:
        unit = MigrationUnit(
            title="Login TOKEN=secret-token-value " + ("source code " * 80),
            source_paths=["/Users/example/Secret/LoginView.swift", "../escape.swift", ".git/config"],
            target_paths=["target_subdir/App/Login.kt"],
            unit_type="ui",
            status="blocked",
            reason="Blocked by PASSWORD=hunter2",
            selected_skill_names=["migration_general", "secret_skill"],
            last_failure_summary={
                "message": "Build failed API_KEY=super-secret-value",
                "tail": "diff --git a/Login.kt b/Login.kt\n+full source or diff",
                "stdout": "do not serialize stdout",
            },
            changed_paths=["/Users/example/project/target-output/Login.kt"],
            build_status="failed",
            test_status="skipped",
        )
        plan = MigrationPlan(units=[unit], plan_id="plan-token-secret", active_unit_id=unit.unit_id)

        payload = serialize_plan(plan)
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["schema_version"], "forgis.migration_plan.v5.0")
        self.assertEqual(payload["active_unit_id"], unit.unit_id)
        self.assertEqual(payload["units"][0]["status"], "blocked")
        self.assertEqual(payload["units"][0]["unit_type"], "ui")
        self.assertIn("[path-redacted]", rendered)
        self.assertIn("[redacted]", rendered)
        self.assertNotIn("/Users/example", rendered)
        self.assertNotIn("secret-token-value", rendered)
        self.assertNotIn("super-secret-value", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("diff --git", rendered)
        self.assertNotIn("do not serialize stdout", rendered)
        self.assertLessEqual(len(payload["units"][0]["title"]), 120)
        self.assertIn("[truncated]", payload["units"][0]["title"])

        restored = deserialize_plan(payload)
        self.assertEqual(restored.plan_id, payload["plan_id"])
        self.assertEqual(restored.active_unit_id, unit.unit_id)
        self.assertEqual(restored.units[0].status, "blocked")
        self.assertEqual(restored.units[0].unit_type, "ui")

        payload["units"][0]["status"] = "surprising"
        payload["units"][0]["unit_type"] = "new-kind"
        payload["units"][0]["source_paths"] = ["/Users/example/private/API_KEY/Login.swift"]
        downgraded = deserialize_plan(payload)
        self.assertEqual(downgraded.units[0].status, "pending")
        self.assertEqual(downgraded.units[0].unit_type, "unknown")
        self.assertNotIn("/Users/example", json.dumps(downgraded.as_summary(), ensure_ascii=False))

    def test_migration_plan_persistence_writes_loads_and_rejects_unsafe_paths(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source-repo"
            target = root / "target-repo"
            source.mkdir()
            target.mkdir()
            unit = MigrationUnit(title="Feature", source_paths=["FeatureView.swift"], unit_type="ui", status="active")
            plan = MigrationPlan(units=[unit], active_unit_id=unit.unit_id)

            written = write_migration_plan(
                plan,
                "forgis-runtime/reports",
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(written.status, "written")
            self.assertEqual(Path(written.path).name, MIGRATION_PLAN_FILENAME)
            self.assertTrue(Path(written.path).is_file())

            loaded = load_migration_plan(written.path, allowed_root=root, source_root=source, target_root=target)
            self.assertEqual(loaded.status, "loaded")
            self.assertIsNotNone(loaded.plan)
            self.assertEqual(loaded.plan.active_unit_id, unit.unit_id)
            self.assertEqual(loaded.plan.units[0].status, "active")

            missing = load_migration_plan(
                root / "forgis-runtime/reports/missing.json",
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(missing.status, "skipped")

            broken_path = root / "forgis-runtime/reports/broken.json"
            broken_path.write_text("{not json", encoding="utf-8")
            broken = load_migration_plan(broken_path, allowed_root=root, source_root=source, target_root=target)
            self.assertEqual(broken.status, "failed")
            self.assertIn("invalid", broken.error)

            old_path = root / "forgis-runtime/reports/old.json"
            old_path.write_text(json.dumps({"schema_version": "forgis.migration_plan.v0", "units": []}), encoding="utf-8")
            old = load_migration_plan(old_path, allowed_root=root, source_root=source, target_root=target)
            self.assertEqual(old.status, "version_mismatch")

            for schema_version in (
                "forgis.migration_plan.v4.8",
                "forgis.migration_plan.v3.9",
                "forgis.migration_plan.v3.8",
                "forgis.migration_plan.v3.7",
            ):
                compat_path = root / f"forgis-runtime/reports/{schema_version.rsplit('.', 1)[-1]}.json"
                compat_path.write_text(
                    json.dumps(
                        {
                            "schema_version": schema_version,
                            "plan_id": "compat-plan",
                            "active_unit_id": unit.unit_id,
                            "units": [unit.as_summary()],
                            "events": [],
                        }
                    ),
                    encoding="utf-8",
                )
                compat = load_migration_plan(compat_path, allowed_root=root, source_root=source, target_root=target)
                self.assertEqual(compat.status, "loaded")
                self.assertIsNotNone(compat.plan)
                self.assertEqual(compat.plan.active_unit_id, unit.unit_id)

            for output_dir in ("../outside", "target-repo/reports", "source-repo/reports", ".git/reports"):
                rejected = write_migration_plan(
                    plan,
                    output_dir,
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                )
                self.assertEqual(rejected.status, "skipped")

            for forbidden in (Path.home() / "Desktop/forgis-plan", Path.home() / "Downloads/forgis-plan", Path.home() / "Documents/forgis-plan"):
                rejected = write_migration_plan(
                    plan,
                    forbidden,
                    allowed_root=Path.home(),
                    source_root=source,
                    target_root=target,
                )
                self.assertEqual(rejected.status, "skipped")

            readonly_file = root / "readonly-file"
            readonly_file.write_text("x", encoding="utf-8")
            failed = write_migration_plan(
                plan,
                "readonly-file/reports",
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(failed.status, "skipped")

    def test_migration_plan_state_update_is_conservative_and_evidence_based(self) -> None:
        active = MigrationUnit(title="Feature", target_paths=["target_subdir/Feature.kt"], unit_type="ui", status="active")
        plan = MigrationPlan(units=[active], active_unit_id=active.unit_id)

        default_result = update_active_unit_state(
            plan,
            {
                "changed_paths": ["target/target-output/Feature.kt"],
                "last_build_status": "success",
                "last_test_status": "skipped",
            },
            auto_complete_on_success=False,
            normal_tool_loop_end=True,
        )
        self.assertEqual(default_result.status_after, "active")
        self.assertIn("auto_complete_on_success=false", active.reason)
        self.assertEqual(active.build_status, "success")
        self.assertEqual(active.changed_paths, ["target/target-output/Feature.kt"])

        completable = MigrationUnit(title="Feature", target_paths=["target_subdir/Feature.kt"], unit_type="ui", status="active")
        complete_plan = MigrationPlan(units=[completable], active_unit_id=completable.unit_id)
        completed = update_active_unit_state(
            complete_plan,
            {
                "changed_paths": ["target_subdir/Feature.kt"],
                "last_build_status": "success",
                "last_test_status": "skipped",
            },
            auto_complete_on_success=True,
            normal_tool_loop_end=True,
        )
        self.assertEqual(completed.status_after, "completed")
        self.assertEqual(complete_plan.completed_count, 1)
        self.assertTrue(completable.reason)

        no_evidence = MigrationUnit(title="Feature", unit_type="ui", status="active")
        no_evidence_plan = MigrationPlan(units=[no_evidence], active_unit_id=no_evidence.unit_id)
        no_evidence_result = update_active_unit_state(
            no_evidence_plan,
            {"last_build_status": "success", "last_test_status": "skipped"},
            auto_complete_on_success=True,
            normal_tool_loop_end=True,
        )
        self.assertEqual(no_evidence_result.status_after, "active")

        blocked_unit = MigrationUnit(title="Feature", unit_type="ui", status="active")
        blocked_plan = MigrationPlan(units=[blocked_unit], active_unit_id=blocked_unit.unit_id)
        blocked = update_active_unit_state(
            blocked_plan,
            {
                "last_build_status": "failed",
                "stopped_reason": "max_attempts_reached",
                "last_failure_summary": {"message": "Build failed API_KEY=super-secret-value"},
            },
            normal_tool_loop_end=True,
        )
        self.assertEqual(blocked.status_after, "blocked")
        self.assertIn("max_attempts_reached", blocked_unit.reason)
        self.assertNotIn("super-secret-value", blocked_unit.reason)

        timeout_unit = MigrationUnit(title="Feature", unit_type="ui", status="active")
        timeout_plan = MigrationPlan(units=[timeout_unit], active_unit_id=timeout_unit.unit_id)
        timeout = update_active_unit_state(timeout_plan, {"last_test_status": "timeout"})
        self.assertEqual(timeout.status_after, "blocked")
        self.assertIn("timeout", timeout_unit.reason)

        deferred_unit = MigrationUnit(title="Feature", unit_type="ui", status="active")
        deferred_plan = MigrationPlan(units=[deferred_unit], active_unit_id=deferred_unit.unit_id)
        missing_reason = update_active_unit_state(deferred_plan, {"migration_unit_deferred_reason": ""})
        self.assertEqual(missing_reason.status_after, "active")
        self.assertIn("without a specific reason", deferred_unit.reason)
        deferred = update_active_unit_state(
            deferred_plan,
            {"migration_unit_deferred_reason": "Need target platform navigation support"},
        )
        self.assertEqual(deferred.status_after, "deferred")
        self.assertTrue(deferred_unit.reason)

    def test_migration_plan_events_are_bounded_and_redacted(self) -> None:
        unit = MigrationUnit(title="Feature", unit_type="ui", status="active")
        plan = MigrationPlan(units=[unit], active_unit_id=unit.unit_id)
        for index, event_type in enumerate(
            [
                "plan_loaded",
                "plan_generated",
                "active_unit_updated",
                "unit_completed",
                "unit_blocked",
                "unit_deferred",
            ]
        ):
            append_plan_event(
                plan,
                event_type,
                unit_id=unit.unit_id,
                status_before="active",
                status_after="blocked" if event_type == "unit_blocked" else "active",
                reason=f"event {index} TOKEN=secret-token-value diff --git a/app.py b/app.py",
                short_message="PASSWORD=hunter2",
                max_events=3,
            )
        events = safe_plan_events(plan.events, max_events=3)
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertEqual(len(events), 3)
        self.assertEqual([event["event_type"] for event in events], ["unit_completed", "unit_blocked", "unit_deferred"])
        self.assertNotIn("secret-token-value", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("diff --git", rendered)

    def test_resume_summary_recommends_next_steps_and_redacts(self) -> None:
        blocked_unit = MigrationUnit(
            title="Blocked",
            target_paths=["target_subdir/Feature.kt"],
            unit_type="ui",
            status="blocked",
            reason="Missing target support TOKEN=secret-token-value",
            changed_paths=["/Users/example/private/Feature.kt"],
        )
        plan = MigrationPlan(units=[blocked_unit], active_unit_id=blocked_unit.unit_id)
        summary = generate_resume_summary(plan)
        rendered = json.dumps(summary, ensure_ascii=False)
        self.assertEqual(summary["last_active_unit_status"], "blocked")
        self.assertIn("Review the blocked reason", summary["next_step"])
        self.assertNotIn("secret-token-value", rendered)
        self.assertNotIn("/Users/example", rendered)

        completed = MigrationUnit(title="Done", unit_type="ui", status="completed", reason="Verified")
        all_done = generate_resume_summary(MigrationPlan(units=[completed], active_unit_id=completed.unit_id))
        self.assertIn("full CI", all_done["next_step"])

    def test_migration_plan_audit_summary_prioritizes_manual_actions_and_redacts(self) -> None:
        active = MigrationUnit(title="Active", unit_type="ui", status="active")
        blocked = MigrationUnit(
            title="Blocked",
            unit_type="ui",
            status="blocked",
            reason="Blocked by PASSWORD=hunter2",
        )
        deferred = MigrationUnit(title="Deferred", unit_type="asset", status="deferred", reason="Wait for assets")
        completed = MigrationUnit(title="Completed", unit_type="model", status="completed", reason="Verified")
        pending = MigrationUnit(title="Pending", unit_type="service", status="pending")
        plan = MigrationPlan(units=[active, blocked, deferred, completed, pending], active_unit_id=active.unit_id)
        for index in range(12):
            append_plan_event(
                plan,
                "unit_completed" if index % 2 else "plan_write_succeeded",
                unit_id=completed.unit_id,
                status_after="completed",
                reason=f"event {index} TOKEN=secret-token-value diff --git a/app.py b/app.py",
                short_message="PASSWORD=hunter2",
            )

        summary = build_migration_plan_audit_summary(
            migration_scheduler_enabled=True,
            plan=plan,
            manual_unit_status_update={
                "status": "updated",
                "unit_id": blocked.unit_id,
                "previous_status": "active",
                "requested_status": "blocked",
                "final_status": "blocked",
                "reason": "Manual status PASSWORD=hunter2",
                "message": "blocked with TOKEN=secret-token-value",
            },
            max_events=3,
        )
        rendered = json.dumps(summary, ensure_ascii=False)
        self.assertEqual(summary["latest_action_type"], "manual_unit_status_update")
        self.assertEqual(summary["latest_action_status"], "updated")
        self.assertEqual(summary["latest_unit_id"], blocked.unit_id)
        self.assertEqual(summary["blocked_units_count"], 1)
        self.assertEqual(summary["deferred_units_count"], 1)
        self.assertEqual(summary["completed_units_count"], 1)
        self.assertLessEqual(len(summary["recent_events"]), 3)
        self.assertNotIn("secret-token-value", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("diff --git", rendered)

    def test_migration_plan_audit_summary_switch_and_scheduler_disabled(self) -> None:
        old = MigrationUnit(title="Old", unit_type="ui", status="active")
        requested = MigrationUnit(title="Requested", unit_type="ui", status="pending")
        plan = MigrationPlan(units=[old, requested], active_unit_id=requested.unit_id)
        switch_summary = build_migration_plan_audit_summary(
            migration_scheduler_enabled=True,
            plan=plan,
            active_unit_switch={
                "status": "switched",
                "requested_active_unit_id": requested.unit_id,
                "previous_active_unit_id": old.unit_id,
                "active_unit_id": requested.unit_id,
                "reason": "Manual reviewer selected unit",
                "message": "Active unit switched",
            },
        )
        self.assertEqual(switch_summary["latest_action_type"], "active_unit_switch")
        self.assertEqual(switch_summary["latest_action_status"], "switched")
        self.assertEqual(switch_summary["latest_unit_id"], requested.unit_id)

        disabled = build_migration_plan_audit_summary(migration_scheduler_enabled=False)
        self.assertEqual(disabled["status"], "skipped")
        self.assertEqual(disabled["latest_action_type"], "none")
        self.assertEqual(disabled["active_unit_id"], "")
        self.assertIn("Enable migration_scheduler_enabled", disabled["recommended_next_action"])

    def test_migration_plan_recommended_next_action_rules(self) -> None:
        def plan_for(status: str, *, pending: bool = True) -> dict[str, Any]:
            kwargs = {"reason": "Manual reason"} if status in {"blocked", "completed", "deferred"} else {}
            unit = MigrationUnit(title=status, unit_type="ui", status=status, **kwargs)
            units = [unit]
            if pending:
                units.append(MigrationUnit(title="Pending", unit_type="ui", status="pending"))
            return MigrationPlan(units=units, active_unit_id=unit.unit_id).as_summary()

        self.assertIn(
            "Continue the current active unit",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=True,
                plan_summary=plan_for("active"),
            ),
        )
        self.assertIn(
            "blocked reason",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=True,
                plan_summary=plan_for("blocked"),
            ),
        )
        self.assertIn(
            "deferred condition",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=True,
                plan_summary=plan_for("deferred"),
            ),
        )
        self.assertIn(
            "Manually switch",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=True,
                plan_summary=plan_for("completed", pending=True),
            ),
        )
        no_active = MigrationPlan(
            units=[MigrationUnit(title="Pending", unit_type="ui", status="pending")],
            active_unit_id=None,
        ).as_summary()
        self.assertIn(
            "migration_plan_requested_active_unit_id",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=True,
                plan_summary=no_active,
            ),
        )
        all_done_unit = MigrationUnit(title="Done", unit_type="ui", status="completed", reason="Verified")
        all_done = MigrationPlan(units=[all_done_unit], active_unit_id=all_done_unit.unit_id).as_summary()
        self.assertIn(
            "full CI",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=True,
                plan_summary=all_done,
            ),
        )
        self.assertIn(
            "Enable migration_scheduler_enabled",
            migration_plan_recommended_next_action(
                migration_scheduler_enabled=False,
                plan_summary=plan_for("active"),
            ),
        )

    def test_active_unit_switch_validation_rules(self) -> None:
        active = MigrationUnit(title="Active", unit_type="ui", status="active")
        pending = MigrationUnit(title="Pending", unit_type="ui", status="pending")
        blocked = MigrationUnit(title="Blocked", unit_type="ui", status="blocked", reason="Manual blocker")
        deferred = MigrationUnit(title="Deferred", unit_type="ui", status="deferred", reason="Wait for platform support")
        completed = MigrationUnit(title="Completed", unit_type="ui", status="completed", reason="Verified")
        plan = MigrationPlan(
            units=[active, pending, blocked, deferred, completed],
            active_unit_id=active.unit_id,
        )
        config = self.switch_config()

        self.assertEqual(validate_active_unit_switch(plan, "", config, resume_loaded=True).status, "skipped")
        missing = validate_active_unit_switch(plan, "ui-missing-1234", config, resume_loaded=True)
        self.assertEqual(missing.status, "rejected")
        self.assertIn("not found", missing.message)
        current = validate_active_unit_switch(plan, active.unit_id, config, resume_loaded=True)
        self.assertEqual(current.status, "skipped")
        self.assertIn("already", current.message)
        self.assertEqual(validate_active_unit_switch(plan, pending.unit_id, config, resume_loaded=True).status, "allowed")
        self.assertEqual(validate_active_unit_switch(plan, blocked.unit_id, config, resume_loaded=True).status, "allowed")
        self.assertEqual(validate_active_unit_switch(plan, deferred.unit_id, config, resume_loaded=True).status, "allowed")
        rejected_completed = validate_active_unit_switch(plan, completed.unit_id, config, resume_loaded=True)
        self.assertEqual(rejected_completed.status, "rejected")
        self.assertIn("completed", rejected_completed.message)
        allowed_completed = validate_active_unit_switch(
            plan,
            completed.unit_id,
            self.switch_config(migration_plan_allow_switch_from_completed=True),
            resume_loaded=True,
        )
        self.assertEqual(allowed_completed.status, "allowed")
        requires_resume = validate_active_unit_switch(plan, pending.unit_id, config, resume_loaded=False)
        self.assertEqual(requires_resume.status, "rejected")
        self.assertIn("resumed", requires_resume.message)
        scheduler_disabled = validate_active_unit_switch(
            plan,
            pending.unit_id,
            self.switch_config(migration_scheduler_enabled=False),
            resume_loaded=True,
        )
        self.assertEqual(scheduler_disabled.status, "rejected")
        self.assertIn("migration_scheduler_enabled", scheduler_disabled.message)

    def test_active_unit_switch_updates_state_without_reordering_or_auto_advancing(self) -> None:
        active = MigrationUnit(title="Active", source_paths=["Active.swift"], unit_type="ui", status="active")
        pending = MigrationUnit(title="Pending", source_paths=["Pending.swift"], unit_type="ui", status="pending")
        other = MigrationUnit(title="Other", source_paths=["Other.swift"], unit_type="ui", status="pending")
        plan = MigrationPlan(units=[active, pending, other], active_unit_id=active.unit_id)
        original_order = [unit.unit_id for unit in plan.units]

        result = request_active_unit_switch(
            plan,
            pending.unit_id,
            self.switch_config(migration_plan_switch_reason="Manual reviewer selected pending unit"),
            resume_loaded=True,
        )

        self.assertEqual(result.status, "switched")
        self.assertEqual(result.previous_active_unit_id, active.unit_id)
        self.assertEqual(plan.active_unit_id, pending.unit_id)
        self.assertEqual(pending.status, "active")
        self.assertEqual(active.status, "active")
        self.assertNotIn(active.status, {"completed", "blocked"})
        self.assertEqual(other.status, "pending")
        self.assertEqual([unit.unit_id for unit in plan.units], original_order)
        self.assertEqual(plan.active_unit.unit_id, pending.unit_id)

    def test_active_unit_switch_events_are_recorded_and_redacted(self) -> None:
        active = MigrationUnit(title="Active", unit_type="ui", status="active")
        pending = MigrationUnit(title="Pending", unit_type="ui", status="pending")
        completed = MigrationUnit(title="Done", unit_type="ui", status="completed", reason="Verified")
        plan = MigrationPlan(units=[active, pending, completed], active_unit_id=active.unit_id)

        switched = request_active_unit_switch(
            plan,
            pending.unit_id,
            self.switch_config(migration_plan_switch_reason="TOKEN=secret-token-value diff --git a/x b/x"),
            resume_loaded=True,
        )
        self.assertEqual(switched.status, "switched")
        skipped = request_active_unit_switch(plan, pending.unit_id, self.switch_config(), resume_loaded=True)
        self.assertEqual(skipped.status, "skipped")
        rejected = request_active_unit_switch(plan, completed.unit_id, self.switch_config(), resume_loaded=True)
        self.assertEqual(rejected.status, "rejected")

        events = safe_plan_events(plan.events, max_events=20)
        event_types = [event["event_type"] for event in events]
        self.assertIn("active_unit_switch_requested", event_types)
        self.assertIn("active_unit_switch_succeeded", event_types)
        self.assertIn("active_unit_switch_skipped", event_types)
        self.assertIn("active_unit_switch_rejected", event_types)
        succeeded = next(event for event in events if event["event_type"] == "active_unit_switch_succeeded")
        self.assertEqual(succeeded["requested_unit_id"], pending.unit_id)
        self.assertEqual(succeeded["previous_active_unit_id"], active.unit_id)
        self.assertEqual(succeeded["active_unit_id"], pending.unit_id)
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("secret-token-value", rendered)
        self.assertNotIn("diff --git", rendered)

    def test_active_unit_switch_can_target_completed_when_explicitly_allowed(self) -> None:
        active = MigrationUnit(title="Active", unit_type="ui", status="active")
        completed = MigrationUnit(title="Done", unit_type="ui", status="completed", reason="Verified")
        plan = MigrationPlan(units=[active, completed], active_unit_id=active.unit_id)

        result = request_active_unit_switch(
            plan,
            completed.unit_id,
            self.switch_config(
                migration_plan_allow_switch_from_completed=True,
                migration_plan_switch_reason="Manual review reopened a completed unit",
            ),
            resume_loaded=True,
        )

        self.assertEqual(result.status, "switched")
        self.assertEqual(plan.active_unit_id, completed.unit_id)
        self.assertEqual(completed.status, "completed")
        self.assertIn("Manual review", completed.reason)

    def test_manual_unit_status_update_validation_rules(self) -> None:
        active = MigrationUnit(title="Active", unit_type="ui", status="active")
        pending = MigrationUnit(title="Pending", unit_type="ui", status="pending")
        plan = MigrationPlan(units=[active, pending], active_unit_id=active.unit_id)
        config = self.status_update_config()

        no_request = validate_manual_unit_status_update(plan, "", "", config, resume_loaded=True)
        self.assertEqual(no_request.status, "skipped")

        invalid = validate_manual_unit_status_update(plan, pending.unit_id, "done", config, resume_loaded=True)
        self.assertEqual(invalid.status, "rejected")
        self.assertIn("one of", invalid.message)

        missing_reason = validate_manual_unit_status_update(plan, pending.unit_id, "completed", config, resume_loaded=True)
        self.assertEqual(missing_reason.status, "rejected")
        self.assertIn("reason", missing_reason.message)

        missing_unit = validate_manual_unit_status_update(
            plan,
            "ui-missing-1234",
            "blocked",
            config,
            reason="Manual blocker",
            resume_loaded=True,
        )
        self.assertEqual(missing_unit.status, "rejected")
        self.assertIn("not found", missing_unit.message)

        requires_resume = validate_manual_unit_status_update(
            plan,
            pending.unit_id,
            "blocked",
            config,
            reason="Manual blocker",
            resume_loaded=False,
        )
        self.assertEqual(requires_resume.status, "rejected")
        self.assertIn("resumed", requires_resume.message)

        for status, flag in (
            ("completed", "migration_plan_allow_manual_complete"),
            ("blocked", "migration_plan_allow_manual_block"),
            ("deferred", "migration_plan_allow_manual_defer"),
            ("active", "migration_plan_allow_manual_activate"),
        ):
            denied = validate_manual_unit_status_update(
                plan,
                pending.unit_id,
                status,
                self.status_update_config(**{flag: False}),
                reason="Manual reviewer decision",
                resume_loaded=True,
            )
            self.assertEqual(denied.status, "rejected")
            self.assertIn(flag, denied.message)

    def test_manual_unit_status_update_state_effects_without_reordering_or_auto_advancing(self) -> None:
        active = MigrationUnit(title="Active", source_paths=["Active.swift"], unit_type="ui", status="active")
        pending = MigrationUnit(title="Pending", source_paths=["Pending.swift"], unit_type="ui", status="pending")
        other = MigrationUnit(title="Other", source_paths=["Other.swift"], unit_type="ui", status="pending")
        plan = MigrationPlan(units=[active, pending, other], active_unit_id=active.unit_id)
        original_order = [unit.unit_id for unit in plan.units]

        completed = request_unit_status_update(
            plan,
            active.unit_id,
            "completed",
            self.status_update_config(),
            "Manual review verified active unit",
            resume_loaded=True,
        )
        self.assertEqual(completed.status, "updated")
        self.assertEqual(active.status, "completed")
        self.assertIn("Manual review", active.reason)
        self.assertEqual(plan.active_unit_id, active.unit_id)
        self.assertEqual(plan.active_unit.unit_id, active.unit_id)
        self.assertEqual(pending.status, "pending")
        self.assertEqual([unit.unit_id for unit in plan.units], original_order)

        blocked = request_unit_status_update(
            plan,
            pending.unit_id,
            "blocked",
            self.status_update_config(),
            "Waiting on target API",
            resume_loaded=True,
        )
        self.assertEqual(blocked.final_status, "blocked")
        self.assertEqual(pending.status, "blocked")
        self.assertEqual(plan.active_unit_id, active.unit_id)

        deferred = request_unit_status_update(
            plan,
            other.unit_id,
            "deferred",
            self.status_update_config(),
            "Defer until platform support exists",
            resume_loaded=True,
        )
        self.assertEqual(deferred.final_status, "deferred")
        self.assertEqual(other.status, "deferred")
        self.assertEqual(plan.active_unit_id, active.unit_id)

        activated = request_unit_status_update(
            plan,
            other.unit_id,
            "active",
            self.status_update_config(),
            "Manual reviewer reactivated deferred unit",
            resume_loaded=True,
        )
        self.assertEqual(activated.final_status, "active")
        self.assertEqual(other.status, "active")
        self.assertEqual(plan.active_unit_id, other.unit_id)
        self.assertEqual(plan.active_unit.unit_id, other.unit_id)
        self.assertEqual([unit.unit_id for unit in plan.units], original_order)

    def test_manual_unit_status_update_events_are_recorded_and_redacted(self) -> None:
        active = MigrationUnit(title="Active", unit_type="ui", status="active")
        pending = MigrationUnit(title="Pending", unit_type="ui", status="pending")
        plan = MigrationPlan(units=[active, pending], active_unit_id=active.unit_id)

        updated = request_unit_status_update(
            plan,
            pending.unit_id,
            "completed",
            self.status_update_config(),
            "Manual reason TOKEN=secret-token-value diff --git a/x b/x",
            resume_loaded=True,
        )
        self.assertEqual(updated.status, "updated")
        skipped = request_unit_status_update(
            plan,
            pending.unit_id,
            "completed",
            self.status_update_config(),
            "Manual reason TOKEN=secret-token-value diff --git a/x b/x",
            resume_loaded=True,
        )
        self.assertEqual(skipped.status, "skipped")
        rejected = request_unit_status_update(
            plan,
            active.unit_id,
            "blocked",
            self.status_update_config(migration_plan_allow_manual_block=False),
            "PASSWORD=hunter2",
            resume_loaded=True,
        )
        self.assertEqual(rejected.status, "rejected")

        events = safe_plan_events(plan.events, max_events=20)
        event_types = [event["event_type"] for event in events]
        self.assertIn("unit_status_update_requested", event_types)
        self.assertIn("unit_status_update_succeeded", event_types)
        self.assertIn("unit_status_update_skipped", event_types)
        self.assertIn("unit_status_update_rejected", event_types)
        succeeded = next(event for event in events if event["event_type"] == "unit_status_update_succeeded")
        self.assertEqual(succeeded["unit_id"], pending.unit_id)
        self.assertEqual(succeeded["previous_status"], "pending")
        self.assertEqual(succeeded["requested_status"], "completed")
        self.assertEqual(succeeded["final_status"], "completed")
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("secret-token-value", rendered)
        self.assertNotIn("hunter2", rendered)
        self.assertNotIn("diff --git", rendered)

    def test_skill_loader_lists_loads_and_rejects_unsafe_names(self) -> None:
        names = list_available_skills()
        self.assertIn("migration_general", names)
        self.assertIn("build_repair", names)

        skill = load_skill("migration_general")
        self.assertEqual(skill.name, "migration_general")
        self.assertEqual(skill.path, "skills/migration_general.md")
        self.assertIn("Migration General", skill.content)

        for unsafe in ("bad/name", "../migration_general", "/tmp/migration_general", "secret_rules"):
            with self.assertRaises(SkillLoaderError):
                load_skill(unsafe)

        with self.assertRaises(SkillLoaderError):
            list_available_skills(DEFAULT_SKILLS_DIR.parent)
        with self.assertRaisesRegex(SkillLoaderError, "max_skill_chars"):
            load_skill("migration_general", max_chars=10)

    def test_skill_selection_auto_rules_explicit_priority_and_limits(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")

            default_selection = select_skills(resolved, task_text="Migrate this project carefully.")
            self.assertEqual(default_selection.selected_skill_names, ("migration_general",))

            compose = select_skills(resolved, task_text="Migrate SwiftUI screens to Android Jetpack Compose Kotlin.")
            self.assertIn("migration_general", compose.selected_skill_names)
            self.assertIn("swiftui_to_compose", compose.selected_skill_names)

            harmony = select_skills(resolved, task_text="迁移到 HarmonyOS ArkUI 鸿蒙。")
            self.assertIn("swiftui_to_harmonyos", harmony.selected_skill_names)

            ui = select_skills(resolved, task_text="保持 UI 界面 组件 风格。")
            self.assertIn("ui_style_preservation", ui.selected_skill_names)

            build = select_skills(resolved, task_text="build test error failure repair")
            self.assertIn("build_repair", build.selected_skill_names)

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    selected_skills:
                      - build_repair
                    """
                ),
            )
            explicit = resolve_config(target_root=target, target_repo="owner/target-repo")
            explicit_selection = select_skills(
                explicit,
                task_text="Android Compose UI build error should not auto add more skills.",
            )
            self.assertEqual(explicit_selection.selected_skill_names, ("build_repair",))

            self.write_config(target, extra="selected_skills:\n  - missing_skill\n")
            missing = resolve_config(target_root=target, target_repo="owner/target-repo")
            missing_selection = select_skills(missing, task_text="anything")
            self.assertEqual(missing_selection.selected_skill_names, ())
            self.assertEqual(missing_selection.failed_skill_names, ("missing_skill",))

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    max_total_skill_chars: 600
                    """
                ),
            )
            limited = resolve_config(target_root=target, target_repo="owner/target-repo")
            limited_selection = select_skills(
                limited,
                task_text="Android Compose UI build test error HarmonyOS ArkUI 鸿蒙",
            )
            self.assertLessEqual(limited_selection.total_skill_chars, limited.max_total_skill_chars)
            self.assertTrue(limited_selection.skipped_skill_names or limited_selection.failed_skill_names)

    def test_context_injects_selected_skills_without_changing_system_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target, task_text="Migrate SwiftUI UI to Android Compose and fix build errors.")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")

            messages, selection = build_initial_messages(resolved, target_root=target)
            user_context = messages[1]["content"]
            self.assertEqual(messages[0]["content"], system_message())
            self.assertIn("Relevant Forgis Skills", user_context)
            self.assertIn("## migration_general", user_context)
            self.assertIn("## swiftui_to_compose", user_context)
            self.assertIn("## ui_style_preservation", user_context)
            self.assertIn("## build_repair", user_context)
            self.assertNotIn("## swiftui_to_harmonyos", user_context)
            self.assertEqual(selection.selected_skill_names.count("migration_general"), 1)
            self.assertIn("First read the task file", system_message())

            disabled_config = textwrap.dedent(
                """\
                skills_enabled: false
                """
            )
            self.write_config(
                target,
                extra=disabled_config,
                task_text="Migrate SwiftUI UI to Android Compose and fix build errors.",
            )
            disabled = resolve_config(target_root=target, target_repo="owner/target-repo")
            disabled_messages, disabled_selection = build_initial_messages(disabled, target_root=target)
            self.assertFalse(disabled_selection.skills_enabled)
            self.assertNotIn("Relevant Forgis Skills", disabled_messages[1]["content"])

            manual_section = render_selected_skills(select_skills(resolved, task_text="UI"))
            manual_messages = initial_messages(resolved, manual_section)
            self.assertIn("Relevant Forgis Skills", manual_messages[1]["content"])

    def test_staged_translation_rejects_conflicting_iteration_config_and_unsafe_progress_paths(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    execution_mode: staged_translation
                    max_iterations: 8
                    """
                ),
            )
            with self.assertRaisesRegex(ValueError, "min_total_iterations"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    execution_mode: staged_translation
                    max_iterations: 120
                    staged_translation:
                      progress_files:
                        progress: ../FORGIS_TRANSLATION_PROGRESS.md
                    """
                ),
            )
            with self.assertRaisesRegex(ValueError, "unsafe path segment"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_task_file_is_required_non_empty_and_configured_path_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            (target / "FORGIS_TASK.md").unlink()
            with self.assertRaises(FileNotFoundError):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            self.write_config(target, task_text="   \n")
            with self.assertRaisesRegex(ValueError, "empty"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            self.write_config(
                target,
                extra="task_prompt_path: docs/TASK.md\n",
                task_text="# ignored root task",
            )
            (target / "docs").mkdir()
            (target / "docs/TASK.md").write_text("# Configured Task\n", encoding="utf-8")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.task_prompt_path, "docs/TASK.md")

    def test_dry_run_does_not_call_deepseek_or_write_target(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")

            def forbidden_factory(_config: Any, _env: dict[str, str]) -> Any:
                raise AssertionError("DeepSeek client should not be created during dry_run")

            result = run_tool_loop(
                config=resolved,
                source_root=source,
                target_root=target,
                environ={},
                client_factory=forbidden_factory,
            )
            self.assertFalse(result.executed)
            self.assertEqual(result.tool_call_count, 0)
            self.assertFalse((target / "target-output/generated.txt").exists())
            self.assertIn("latest none", result.migration_plan_audit_summary_short)
            self.assertIn("Enable migration_scheduler_enabled", result.migration_plan_recommended_next_action)

    def test_real_run_requires_confirm_real_run(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: false\n")
            with self.assertRaisesRegex(ValueError, "confirm_real_run"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_missing_model_secret_fails_before_deepseek_call(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            with self.assertRaisesRegex(ValueError, "Missing required model secret"):
                run_tool_loop(config=resolved, source_root=source, target_root=target, environ={})

    def test_model_env_does_not_leak_secret_values(self) -> None:
        secret = "super-secret-value"
        pairs = parse_model_env_json(json.dumps({"DEEPSEEK_API_KEY": "DEEPSEEK_API_KEY"}))
        description = describe_model_env(pairs, {"DEEPSEEK_API_KEY": secret})
        rendered = json.dumps(description, sort_keys=True)
        self.assertIn("DEEPSEEK_API_KEY", rendered)
        self.assertIn("yes", rendered)
        self.assertNotIn(secret, rendered)
        values = require_model_env_values(pairs, {"DEEPSEEK_API_KEY": secret})
        self.assertEqual(values["DEEPSEEK_API_KEY"], secret)

    def test_real_run_executes_deepseek_tool_loop_with_mock_response(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call-1",
                                            "type": "function",
                                            "function": {
                                                "name": "read_file",
                                                "arguments": json.dumps({"path": "task"}),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call-2",
                                            "type": "function",
                                            "function": {
                                                "name": "write_file",
                                                "arguments": json.dumps(
                                                    {
                                                        "path": "target_subdir/result.txt",
                                                        "content": "done\n",
                                                    }
                                                ),
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                    {"choices": [{"message": {"content": json.dumps({"final_summary": "mock complete"})}}]},
                ]
            )
            result = run_tool_loop(
                config=resolved,
                source_root=source,
                target_root=target,
                environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                client_factory=lambda _config, _env: fake,
            )
            self.assertTrue(result.executed)
            self.assertEqual(result.final_summary, "mock complete")
            self.assertEqual(result.tool_call_count, 2)
            self.assertEqual(result.read_tool_count, 1)
            self.assertEqual(result.write_tool_count, 1)
            self.assertEqual((target / "target-output/result.txt").read_text(encoding="utf-8"), "done\n")

    def test_tool_loop_exposes_run_build_and_records_runtime_build_status(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(
                target,
                extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n"
                + self.command_config_extra(build_command=["echo", "build-ok"]),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(("build", "run_build", {})),
                    self.final_response("done"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            tool_names = {
                item["function"]["name"]
                for item in fake.calls[0]["tools"]
                if item.get("type") == "function"
            }
            self.assertIn("run_build", tool_names)
            self.assertIn("run_tests", tool_names)
            self.assertTrue(result.runtime_state["ran_build"])
            self.assertEqual(result.runtime_state["last_build_status"], "success")

    def test_tool_loop_repair_loop_allows_edit_requires_diff_then_accepts_success(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            (target / "target-output/bad.py").write_text("def broken(:\n", encoding="utf-8")
            self.write_config(
                target,
                extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n"
                "max_tool_result_chars: 20000\n"
                "repair_loop_enabled: true\nmax_repair_attempts: 2\n"
                + self.command_config_extra(build_command=[sys.executable, "-m", "py_compile", "bad.py"]),
            )
            self.init_git_repo(target)
            self.commit_all(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(("build-fail", "run_build", {})),
                    self.tool_response(
                        (
                            "fix",
                            "edit_file",
                            {
                                "path": "target_subdir/bad.py",
                                "old_text": "def broken(:\n",
                                "new_text": "value = 1\n",
                            },
                        )
                    ),
                    self.tool_response(("blocked-build", "run_build", {})),
                    self.tool_response(("diff", "git_diff", {})),
                    self.tool_response(("build-ok", "run_build", {})),
                    self.final_response("repair complete"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            tool_results = self.tool_results_seen_by_fake_client(fake)
            blocked = [item for item in tool_results if item.get("status") == "blocked"]
            self.assertEqual(len(blocked), 1)
            self.assertIn("git_diff", blocked[0]["error"])
            self.assertEqual((target / "target-output/bad.py").read_text(encoding="utf-8"), "value = 1\n")
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.runtime_state["repair_loop_enabled"], True)
            self.assertEqual(result.runtime_state["repair_attempts_used"], 1)
            self.assertTrue(result.runtime_state["repair_success"])
            self.assertEqual(result.runtime_state["stopped_reason"], "success")
            self.assertTrue(result.runtime_state["modified_after_failure"])
            self.assertTrue(result.runtime_state["diff_checked_after_modification"])
            event_types = [event["event_type"] for event in result.runtime_state["repair_events"]]
            self.assertIn("failure_recorded", event_types)
            self.assertIn("edit_after_failure", event_types)
            self.assertIn("diff_checked", event_types)
            self.assertIn("repair_success", event_types)
            self.assertIn("Forgis Runtime Report", result.repair_report)
            self.assertIn("success", result.compact_actions_summary)

    def test_tool_loop_repair_loop_blocks_after_max_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            (target / "target-output/bad.py").write_text("def broken(:\n", encoding="utf-8")
            self.write_config(
                target,
                extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n"
                "max_tool_result_chars: 20000\n"
                "repair_loop_enabled: true\nmax_repair_attempts: 1\n"
                + self.command_config_extra(build_command=[sys.executable, "-m", "py_compile", "bad.py"]),
            )
            self.init_git_repo(target)
            self.commit_all(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(("build-fail", "run_build", {})),
                    self.tool_response(
                        (
                            "still-bad",
                            "edit_file",
                            {
                                "path": "target_subdir/bad.py",
                                "old_text": "def broken(:\n",
                                "new_text": "def still_broken(:\n",
                            },
                        )
                    ),
                    self.tool_response(("diff", "git_diff", {})),
                    self.tool_response(("build-fail-again", "run_build", {})),
                    self.tool_response(
                        (
                            "blocked-edit",
                            "edit_file",
                            {
                                "path": "target_subdir/bad.py",
                                "old_text": "def still_broken(:\n",
                                "new_text": "value = 1\n",
                            },
                        ),
                        ("blocked-build", "run_build", {}),
                    ),
                    self.final_response("blocked by max attempts"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            tool_results = self.tool_results_seen_by_fake_client(fake)
            blocked_errors = [item["error"] for item in tool_results if item.get("status") == "blocked"]
            self.assertEqual(len(blocked_errors), 2)
            self.assertTrue(any("no further repair edits" in error for error in blocked_errors))
            self.assertTrue(any("max_repair_attempts" in error for error in blocked_errors))
            self.assertEqual(result.runtime_state["repair_attempts_used"], 1)
            self.assertFalse(result.runtime_state["repair_success"])
            self.assertEqual(result.runtime_state["stopped_reason"], "max_attempts_reached")
            event_types = [event["event_type"] for event in result.runtime_state["repair_events"]]
            self.assertIn("max_attempts_reached", event_types)
            self.assertIn("max_attempts_reached", result.repair_report)
            self.assertEqual(
                (target / "target-output/bad.py").read_text(encoding="utf-8"),
                "def still_broken(:\n",
            )

    def test_tool_loop_repair_loop_disabled_preserves_old_build_edit_build_flow(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            (target / "target-output/bad.py").write_text("def broken(:\n", encoding="utf-8")
            self.write_config(
                target,
                extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n"
                "max_tool_result_chars: 20000\n"
                + self.command_config_extra(build_command=[sys.executable, "-m", "py_compile", "bad.py"]),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(("build-fail", "run_build", {})),
                    self.tool_response(
                        (
                            "fix",
                            "edit_file",
                            {
                                "path": "target_subdir/bad.py",
                                "old_text": "def broken(:\n",
                                "new_text": "value = 1\n",
                            },
                        ),
                        ("build-ok", "run_build", {}),
                    ),
                    self.final_response("old flow complete"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            tool_results = self.tool_results_seen_by_fake_client(fake)
            self.assertFalse(any(item.get("status") == "blocked" for item in tool_results))
            self.assertFalse(result.runtime_state["repair_loop_enabled"])
            self.assertEqual(result.runtime_state["last_build_status"], "success")
            self.assertIn("Forgis Runtime Report", result.repair_report)

    def test_tool_loop_persists_run_reports_when_output_dir_is_provided(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("report complete")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                    run_metadata={"test": "tool_loop_report"},
                )

            self.assertEqual(result.report_write_status, "written")
            self.assertTrue(Path(result.report_markdown_path).is_file())
            self.assertTrue(Path(result.report_json_path).is_file())
            self.assertIn("FORGIS_RUN_REPORT.md", result.report_markdown_path)
            self.assertIn("FORGIS_RUN_REPORT.json", result.report_json_path)
            payload = result.as_dict()
            self.assertEqual(payload["report_write_status"], "written")
            report_json = json.loads(Path(result.report_json_path).read_text(encoding="utf-8"))
            self.assertEqual(report_json["schema_version"], "forgis.run_report.v5.0")
            self.assertEqual(report_json["tool_loop"]["status"], "completed")
            self.assertFalse(report_json["repair_loop"]["enabled"])
            self.assertTrue(report_json["skills"]["skills_enabled"])
            self.assertEqual(report_json["skills"]["selected_skill_names"], ["migration_general"])

    def test_tool_loop_report_disabled_skips_persistent_write(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(
                target,
                extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\nrun_report_enabled: false\n",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("report disabled")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            self.assertEqual(result.report_write_status, "disabled")
            self.assertEqual(result.report_markdown_path, "")
            self.assertFalse((root / "forgis-runtime/reports").exists())

    def test_tool_loop_migration_scheduler_disabled_keeps_context_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("plain complete")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertNotIn("Active Migration Unit", user_context)
            self.assertFalse(result.runtime_state["migration_scheduler_enabled"])
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.migration_plan_source, "skipped")
            self.assertEqual(result.migration_plan_write_status, "skipped")
            self.assertEqual(result.migration_plan_resume_summary_short, "")
            self.assertFalse((root / "forgis-runtime/reports/FORGIS_MIGRATION_PLAN.json").exists())

    def test_tool_loop_migration_scheduler_injects_active_unit_and_reports_plan(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (source / "FeatureView.swift").write_text("struct FeatureView {}\n", encoding="utf-8")
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    max_migration_units: 5
                    """
                ),
                task_text="Migrate the UI screen source/FeatureView.swift without broad unrelated edits.",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("unit complete")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn("Active Migration Unit", user_context)
            self.assertIn("FeatureView.swift", user_context)
            self.assertTrue(result.runtime_state["migration_scheduler_enabled"])
            plan = result.runtime_state["migration_plan_summary"]
            self.assertEqual(plan["completed_count"], 0)
            self.assertEqual(plan["active_count"], 1)
            self.assertEqual(plan["active_unit"]["status"], "active")
            self.assertIn("No runtime evidence", plan["active_unit"]["reason"])
            self.assertEqual(result.migration_plan_source, "generated")
            self.assertEqual(result.migration_plan_load_status, "disabled")
            self.assertEqual(result.migration_plan_write_status, "written")
            self.assertEqual(result.migration_plan_update_status, "updated")
            self.assertEqual(result.migration_plan_resume_summary_short, "")
            self.assertTrue(Path(result.migration_plan_path).is_file())
            plan_json = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(plan_json["schema_version"], "forgis.migration_plan.v5.0")
            self.assertEqual(plan_json["units"][0]["status"], "active")
            report_markdown = Path(result.report_markdown_path).read_text(encoding="utf-8")
            report_json = json.loads(Path(result.report_json_path).read_text(encoding="utf-8"))
            self.assertIn("Migration Plan", report_markdown)
            self.assertIn("migration_plan_write_status", report_markdown)
            self.assertIn("Active Unit State", report_markdown)
            self.assertIn("Migration Plan Events", report_markdown)
            self.assertTrue(report_json["migration_plan"]["migration_scheduler_enabled"])
            self.assertEqual(report_json["migration_plan"]["completed_count"], 0)
            self.assertEqual(report_json["migration_plan"]["plan_source"], "generated")
            self.assertEqual(report_json["migration_plan"]["plan_write_status"], "written")
            self.assertEqual(report_json["migration_plan"]["active_unit_status"], "active")
            self.assertEqual(report_json["migration_plan"]["active_unit_id"], plan["active_unit_id"])

    def test_tool_loop_updates_active_unit_state_without_auto_running_next_unit(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (source / "FeatureView.swift").write_text("struct FeatureView {}\n", encoding="utf-8")
            (source / "OtherView.swift").write_text("struct OtherView {}\n", encoding="utf-8")
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    max_migration_units: 5
                    build_command:
                      - echo
                      - build-ok
                    """
                ),
                task_text="Migrate source/FeatureView.swift and source/OtherView.swift.",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(
                        (
                            "write",
                            "write_file",
                            {"path": "target_subdir/FeatureView.kt", "content": "feature\n"},
                        ),
                        ("build", "run_build", {}),
                    ),
                    self.final_response("unit verified"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.migration_plan_update_status, "updated")
            self.assertEqual(result.migration_plan_active_unit_status, "active")
            self.assertIn("auto_complete_on_success=false", result.migration_plan_active_unit_reason)
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            active_units = [unit for unit in persisted["units"] if unit["status"] == "active"]
            pending_units = [unit for unit in persisted["units"] if unit["status"] == "pending"]
            completed_units = [unit for unit in persisted["units"] if unit["status"] == "completed"]
            self.assertEqual(len(active_units), 1)
            self.assertGreaterEqual(len(pending_units), 1)
            self.assertEqual(completed_units, [])
            self.assertEqual(active_units[0]["build_status"], "success")
            self.assertIn("target/target-output/FeatureView.kt", active_units[0]["changed_paths"])
            event_types = [event["event_type"] for event in persisted["events"]]
            self.assertIn("active_unit_updated", event_types)
            self.assertIn("plan_write_succeeded", event_types)

    def test_tool_loop_can_auto_complete_active_unit_when_explicitly_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (source / "FeatureView.swift").write_text("struct FeatureView {}\n", encoding="utf-8")
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_auto_complete_on_success: true
                    build_command:
                      - echo
                      - build-ok
                    """
                ),
                task_text="Migrate source/FeatureView.swift.",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(
                        (
                            "write",
                            "write_file",
                            {"path": "target_subdir/FeatureView.kt", "content": "feature\n"},
                        ),
                        ("build", "run_build", {}),
                    ),
                    self.final_response("unit complete"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            self.assertEqual(result.migration_plan_active_unit_status, "completed")
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(persisted["units"][0]["status"], "completed")
            self.assertTrue(persisted["units"][0]["reason"])
            self.assertIn("unit_completed", [event["event_type"] for event in persisted["events"]])

    def test_tool_loop_migration_plan_resume_loads_existing_plan_and_preserves_blocked_status(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            blocked_unit = MigrationUnit(
                title="Blocked feature",
                source_paths=["FeatureView.swift"],
                unit_type="ui",
                status="blocked",
                reason="Missing target navigation support",
            )
            existing_plan = MigrationPlan(units=[blocked_unit], active_unit_id=blocked_unit.unit_id)
            seed = write_migration_plan(
                existing_plan,
                "forgis-runtime/reports",
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(seed.status, "written")
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    """
                ),
                task_text="Migrate source/OtherView.swift.",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("blocked unit reported")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn("status: blocked", user_context)
            self.assertIn("Missing target navigation support", user_context)
            self.assertEqual(result.migration_plan_source, "loaded")
            self.assertEqual(result.migration_plan_load_status, "loaded")
            self.assertEqual(result.migration_plan_write_status, "written")
            self.assertEqual(result.active_unit_id, blocked_unit.unit_id)
            self.assertIn("Review the blocked reason", result.migration_plan_resume_summary_short)
            self.assertEqual(result.migration_plan_active_unit_status, "blocked")
            self.assertEqual(result.runtime_state["migration_plan_summary"]["blocked_count"], 1)
            self.assertEqual(result.runtime_state["resume_summary"]["last_active_unit_status"], "blocked")
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(persisted["units"][0]["status"], "blocked")
            self.assertEqual(persisted["active_unit_id"], blocked_unit.unit_id)
            self.assertIn("plan_loaded", [event["event_type"] for event in persisted["events"]])
            self.assertIn("resume_summary_generated", [event["event_type"] for event in persisted["events"]])

    def test_tool_loop_resume_switches_requested_active_unit_before_context(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            active_unit = MigrationUnit(title="Old active", source_paths=["OldView.swift"], unit_type="ui", status="active")
            pending_unit = MigrationUnit(title="Requested active", source_paths=["RequestedView.swift"], unit_type="ui", status="pending")
            existing_plan = MigrationPlan(units=[active_unit, pending_unit], active_unit_id=active_unit.unit_id)
            self.assertEqual(
                write_migration_plan(
                    existing_plan,
                    "forgis-runtime/reports",
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                ).status,
                "written",
            )
            self.write_config(
                target,
                extra=textwrap.dedent(
                    f"""\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    migration_plan_requested_active_unit_id: {pending_unit.unit_id}
                    migration_plan_switch_reason: Manual reviewer chose requested unit
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("switched unit complete")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn(pending_unit.unit_id, user_context)
            self.assertIn("manual_switch", user_context)
            self.assertIn("RequestedView.swift", user_context)
            self.assertEqual(result.active_unit_id, pending_unit.unit_id)
            self.assertEqual(result.migration_plan_switch_status, "switched")
            self.assertEqual(result.migration_plan_requested_active_unit_id, pending_unit.unit_id)
            self.assertEqual(result.migration_plan_previous_active_unit_id, active_unit.unit_id)
            self.assertIn("Manual reviewer", result.migration_plan_switch_reason)
            self.assertEqual(result.runtime_state["active_unit_switch"]["status"], "switched")
            self.assertIn("Switch requested_unit", result.migration_plan_resume_summary_short)
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            persisted_by_id = {unit["unit_id"]: unit for unit in persisted["units"]}
            self.assertEqual(persisted["active_unit_id"], pending_unit.unit_id)
            self.assertEqual(persisted_by_id[pending_unit.unit_id]["status"], "active")
            self.assertEqual(persisted_by_id[active_unit.unit_id]["status"], "active")
            event_types = [event["event_type"] for event in persisted["events"]]
            self.assertIn("active_unit_switch_requested", event_types)
            self.assertIn("active_unit_switch_succeeded", event_types)
            report_json = json.loads(Path(result.report_json_path).read_text(encoding="utf-8"))
            self.assertEqual(report_json["active_unit_switch"]["status"], "switched")
            self.assertEqual(report_json["migration_plan"]["active_unit_switch"]["requested_active_unit_id"], pending_unit.unit_id)
            report_markdown = Path(result.report_markdown_path).read_text(encoding="utf-8")
            self.assertIn("Active Unit Switch", report_markdown)
            self.assertIn("Manual reviewer", report_markdown)

    def test_tool_loop_switch_rejected_keeps_existing_active_unit(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            active_unit = MigrationUnit(title="Old active", source_paths=["OldView.swift"], unit_type="ui", status="active")
            completed_unit = MigrationUnit(title="Completed", source_paths=["DoneView.swift"], unit_type="ui", status="completed", reason="Verified")
            existing_plan = MigrationPlan(units=[active_unit, completed_unit], active_unit_id=active_unit.unit_id)
            self.assertEqual(
                write_migration_plan(
                    existing_plan,
                    "forgis-runtime/reports",
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                ).status,
                "written",
            )
            self.write_config(
                target,
                extra=textwrap.dedent(
                    f"""\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    migration_plan_requested_active_unit_id: {completed_unit.unit_id}
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("old unit retained")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn(active_unit.unit_id, user_context)
            self.assertNotIn("manual_switch", user_context)
            self.assertEqual(result.active_unit_id, active_unit.unit_id)
            self.assertEqual(result.migration_plan_switch_status, "rejected")
            self.assertIn("completed", result.runtime_state["active_unit_switch"]["message"])
            self.assertIn("Check that the requested unit id exists", result.migration_plan_resume_summary_short)
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            self.assertEqual(persisted["active_unit_id"], active_unit.unit_id)
            persisted_by_id = {unit["unit_id"]: unit for unit in persisted["units"]}
            self.assertEqual(persisted_by_id[completed_unit.unit_id]["status"], "completed")
            self.assertIn("active_unit_switch_rejected", [event["event_type"] for event in persisted["events"]])

    def test_tool_loop_manual_status_update_marks_active_completed_without_advancing(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            active_unit = MigrationUnit(title="Active", source_paths=["ActiveView.swift"], unit_type="ui", status="active")
            pending_unit = MigrationUnit(title="Pending", source_paths=["PendingView.swift"], unit_type="ui", status="pending")
            existing_plan = MigrationPlan(units=[active_unit, pending_unit], active_unit_id=active_unit.unit_id)
            self.assertEqual(
                write_migration_plan(
                    existing_plan,
                    "forgis-runtime/reports",
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                ).status,
                "written",
            )
            self.write_config(
                target,
                extra=textwrap.dedent(
                    f"""\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    migration_plan_requested_unit_status_unit_id: {active_unit.unit_id}
                    migration_plan_requested_unit_status: completed
                    migration_plan_requested_unit_status_reason: Manual reviewer verified active unit
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("manual completed status observed")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn(active_unit.unit_id, user_context)
            self.assertIn("status: completed", user_context)
            self.assertIn("manual_status_update", user_context)
            self.assertNotIn(pending_unit.unit_id, user_context)
            self.assertEqual(result.active_unit_id, active_unit.unit_id)
            self.assertEqual(result.migration_plan_unit_status_update_status, "updated")
            self.assertEqual(result.migration_plan_unit_status_update_unit_id, active_unit.unit_id)
            self.assertEqual(result.migration_plan_unit_status_update_requested_status, "completed")
            self.assertEqual(result.migration_plan_unit_status_update_previous_status, "active")
            self.assertEqual(result.migration_plan_unit_status_update_final_status, "completed")
            self.assertIn("manual_unit_status_update", result.migration_plan_audit_summary_short)
            self.assertIn("next pending unit", result.migration_plan_recommended_next_action)
            self.assertIn("Status update unit", result.migration_plan_resume_summary_short)
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            persisted_by_id = {unit["unit_id"]: unit for unit in persisted["units"]}
            self.assertEqual(persisted["active_unit_id"], active_unit.unit_id)
            self.assertEqual(persisted_by_id[active_unit.unit_id]["status"], "completed")
            self.assertEqual(persisted_by_id[pending_unit.unit_id]["status"], "pending")
            event_types = [event["event_type"] for event in persisted["events"]]
            self.assertIn("unit_status_update_requested", event_types)
            self.assertIn("unit_status_update_succeeded", event_types)
            report_json = json.loads(Path(result.report_json_path).read_text(encoding="utf-8"))
            self.assertEqual(report_json["manual_unit_status_update"]["status"], "updated")
            self.assertEqual(report_json["migration_plan_audit_summary"]["latest_action_status"], "updated")
            self.assertEqual(report_json["migration_plan"]["manual_unit_status_update"]["final_status"], "completed")
            report_markdown = Path(result.report_markdown_path).read_text(encoding="utf-8")
            self.assertIn("Manual Unit Status Update", report_markdown)
            self.assertIn("Migration Plan Audit Summary", report_markdown)
            self.assertIn("Manual reviewer", report_markdown)

    def test_tool_loop_manual_status_update_active_request_controls_context(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            active_unit = MigrationUnit(title="Old active", source_paths=["OldView.swift"], unit_type="ui", status="active")
            pending_unit = MigrationUnit(title="Requested active", source_paths=["RequestedView.swift"], unit_type="ui", status="pending")
            existing_plan = MigrationPlan(units=[active_unit, pending_unit], active_unit_id=active_unit.unit_id)
            self.assertEqual(
                write_migration_plan(
                    existing_plan,
                    "forgis-runtime/reports",
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                ).status,
                "written",
            )
            self.write_config(
                target,
                extra=textwrap.dedent(
                    f"""\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    migration_plan_requested_unit_status_unit_id: {pending_unit.unit_id}
                    migration_plan_requested_unit_status: active
                    migration_plan_requested_unit_status_reason: Manual reviewer activated requested unit
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("manual active unit observed")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn(pending_unit.unit_id, user_context)
            self.assertIn("RequestedView.swift", user_context)
            self.assertEqual(result.active_unit_id, pending_unit.unit_id)
            self.assertEqual(result.migration_plan_unit_status_update_status, "updated")
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            persisted_by_id = {unit["unit_id"]: unit for unit in persisted["units"]}
            self.assertEqual(persisted["active_unit_id"], pending_unit.unit_id)
            self.assertEqual(persisted_by_id[pending_unit.unit_id]["status"], "active")
            self.assertEqual(persisted_by_id[active_unit.unit_id]["status"], "active")

    def test_tool_loop_manual_status_update_rejected_keeps_existing_active_unit(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            active_unit = MigrationUnit(title="Old active", source_paths=["OldView.swift"], unit_type="ui", status="active")
            pending_unit = MigrationUnit(title="Pending", source_paths=["PendingView.swift"], unit_type="ui", status="pending")
            existing_plan = MigrationPlan(units=[active_unit, pending_unit], active_unit_id=active_unit.unit_id)
            self.assertEqual(
                write_migration_plan(
                    existing_plan,
                    "forgis-runtime/reports",
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                ).status,
                "written",
            )
            self.write_config(
                target,
                extra=textwrap.dedent(
                    f"""\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    migration_plan_requested_unit_status_unit_id: {pending_unit.unit_id}
                    migration_plan_requested_unit_status: completed
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("manual update rejected")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            user_context = fake.calls[0]["messages"][1]["content"]
            self.assertIn(active_unit.unit_id, user_context)
            self.assertNotIn("PendingView.swift", user_context)
            self.assertEqual(result.active_unit_id, active_unit.unit_id)
            self.assertEqual(result.migration_plan_unit_status_update_status, "rejected")
            self.assertIn("reason", result.runtime_state["manual_unit_status_update"]["message"])
            self.assertIn("reason is filled", result.migration_plan_resume_summary_short)
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            persisted_by_id = {unit["unit_id"]: unit for unit in persisted["units"]}
            self.assertEqual(persisted["active_unit_id"], active_unit.unit_id)
            self.assertEqual(persisted_by_id[pending_unit.unit_id]["status"], "pending")
            self.assertIn("unit_status_update_rejected", [event["event_type"] for event in persisted["events"]])

    def test_tool_loop_resume_summary_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            active_unit = MigrationUnit(title="Feature", source_paths=["FeatureView.swift"], unit_type="ui", status="active")
            existing_plan = MigrationPlan(units=[active_unit], active_unit_id=active_unit.unit_id)
            self.assertEqual(
                write_migration_plan(
                    existing_plan,
                    "forgis-runtime/reports",
                    allowed_root=root,
                    source_root=source,
                    target_root=target,
                ).status,
                "written",
            )
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    migration_plan_resume_summary_enabled: false
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("resume without summary")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            self.assertEqual(result.migration_plan_source, "loaded")
            self.assertEqual(result.migration_plan_resume_summary_short, "")
            persisted = json.loads(Path(result.migration_plan_path).read_text(encoding="utf-8"))
            self.assertNotIn("resume_summary_generated", [event["event_type"] for event in persisted["events"]])

    def test_tool_loop_migration_plan_resume_bad_json_generates_new_plan(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (source / "FeatureView.swift").write_text("struct FeatureView {}\n", encoding="utf-8")
            plan_dir = root / "forgis-runtime/reports"
            plan_dir.mkdir(parents=True)
            (plan_dir / "FORGIS_MIGRATION_PLAN.json").write_text("{broken json", encoding="utf-8")
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    dry_run: false
                    run_agent: true
                    confirm_real_run: true
                    migration_scheduler_enabled: true
                    migration_plan_resume_enabled: true
                    """
                ),
                task_text="Migrate source/FeatureView.swift.",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.final_response("generated after bad resume")])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            self.assertEqual(result.migration_plan_source, "failed_to_load_generated")
            self.assertEqual(result.migration_plan_load_status, "failed")
            self.assertIn("invalid", result.migration_plan_load_error)
            self.assertEqual(result.migration_plan_write_status, "written")
            self.assertTrue(Path(result.migration_plan_path).is_file())

    def test_deepseek_reasoning_content_round_trips_only_inside_tool_history(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            hidden_reasoning = "hidden reasoning must stay internal"
            final_hidden_reasoning = "final hidden reasoning must not leak"
            tool_call_id = "call-reasoning"
            fake = FakeDeepSeekClient(
                [
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "",
                                    "reasoning_content": hidden_reasoning,
                                    "tool_calls": [
                                        {
                                            "id": tool_call_id,
                                            "type": "function",
                                            "function": {
                                                "name": "read_file",
                                                "arguments": json.dumps({"path": "task"}),
                                            },
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps({"final_summary": "visible summary"}),
                                    "reasoning_content": final_hidden_reasoning,
                                }
                            }
                        ]
                    },
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.final_summary, "visible summary")
            self.assertNotIn(hidden_reasoning, result.final_summary)
            self.assertNotIn(final_hidden_reasoning, result.final_summary)
            self.assertNotIn(hidden_reasoning, json.dumps(result.operation_log))
            self.assertNotIn(hidden_reasoning, stdout.getvalue())

            second_request_messages = fake.calls[1]["messages"]
            assistant_messages = [
                item for item in second_request_messages if item.get("role") == "assistant"
            ]
            self.assertEqual(assistant_messages[-1]["reasoning_content"], hidden_reasoning)
            self.assertEqual(assistant_messages[-1]["content"], "")
            self.assertEqual(assistant_messages[-1]["tool_calls"][0]["id"], tool_call_id)

            tool_messages = [item for item in second_request_messages if item.get("role") == "tool"]
            self.assertEqual(tool_messages[-1]["tool_call_id"], tool_call_id)
            self.assertEqual(tool_messages[-1]["name"], "read_file")

            status_path = root / "status.env"
            write_status(str(status_path), result)
            status_text = status_path.read_text(encoding="utf-8")
            self.assertNotIn(hidden_reasoning, status_text)
            self.assertNotIn(final_hidden_reasoning, status_text)
            self.assertNotIn(hidden_reasoning, json.dumps(result.as_dict(), ensure_ascii=False))

    def test_tool_loop_logs_progress_without_sensitive_content(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(target, extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            hidden_reasoning = "internal hidden reasoning"
            write_content = "do-not-print-write-content"
            fake = FakeDeepSeekClient(
                [
                    {
                        "choices": [
                            {
                                "message": {
                                    "reasoning_content": hidden_reasoning,
                                    "tool_calls": [
                                        {
                                            "id": "call-read",
                                            "type": "function",
                                            "function": {
                                                "name": "read_file",
                                                "arguments": json.dumps({"path": "task"}),
                                            },
                                        },
                                        {
                                            "id": "call-write",
                                            "type": "function",
                                            "function": {
                                                "name": "write_file",
                                                "arguments": json.dumps(
                                                    {
                                                        "path": "target_subdir/progress.txt",
                                                        "content": write_content,
                                                    }
                                                ),
                                            },
                                        },
                                    ],
                                }
                            }
                        ]
                    },
                    {"choices": [{"message": {"content": json.dumps({"final_summary": "visible"})}}]},
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            log = stdout.getvalue()
            self.assertEqual(result.final_summary, "visible")
            self.assertIn("[forgis] tool loop started: max_iterations=", log)
            self.assertIn("[forgis] iteration 1/8: requesting model", log)
            self.assertIn("model returned 2 tool calls", log)
            self.assertIn("tool call 1: iteration=1 read_file path=task", log)
            self.assertIn("tool call 2: iteration=1 write_file path=target_subdir/progress.txt", log)
            self.assertIn("changed_path=target/target-output/progress.txt", log)
            self.assertIn("final_summary received", log)
            self.assertIn("changed_paths=1", log)
            self.assertNotIn(write_content, log)
            self.assertNotIn("# Mock Task", log)
            self.assertNotIn(hidden_reasoning, log)

    def test_staged_translation_runs_three_phases_and_per_file_micro_phases_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=12))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            hidden_reasoning = "hidden staged reasoning"
            write_content = "do-not-print-staged-write-content"
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(
                        (
                            "plan",
                            "write_file",
                            {"path": "target_subdir/FORGIS_TRANSLATION_PLAN.md", "content": "# Plan\n"},
                        ),
                        (
                            "map",
                            "write_file",
                            {
                                "path": "target_subdir/FORGIS_SOURCE_TARGET_MAP.md",
                                "content": "| Source path/unit | Target path/unit | Status | Notes |\n",
                            },
                        ),
                        (
                            "progress",
                            "write_file",
                            {"path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md", "content": "# Progress\n"},
                        ),
                        reasoning_content=hidden_reasoning,
                    ),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "write",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": write_content},
                        )
                    ),
                    self.tool_response(
                        ("compare-read-source", "read_file", {"path": "source/input.txt"}),
                        ("compare-read-target", "read_file", {"path": "target_subdir/generated.py"}),
                        (
                            "compare-report",
                            "write_file",
                            {
                                "path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md",
                                "content": "# Compare\n",
                            },
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": "revised\n"},
                        ),
                        (
                            "revise-progress",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed after compare\n",
                            },
                        ),
                    ),
                    self.tool_response(
                        (
                            "folder",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("staged complete"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            log = stdout.getvalue()
            controls = "\n".join(
                message["content"]
                for call in fake.calls
                for message in call["messages"]
                if message.get("role") == "user" and "[forgis staged control]" in message.get("content", "")
            )
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_summary, "staged complete")
            self.assertEqual(resolved.execution_mode, "staged_translation")
            self.assertIn("staged mode enabled", log)
            self.assertIn("phase=overview", log)
            self.assertIn("current_micro_phase=feed", log)
            self.assertIn("current_micro_phase=write", log)
            self.assertIn("current_micro_phase=readonly_compare", log)
            self.assertIn("current_micro_phase=revise", log)
            self.assertIn("folder review start", log)
            self.assertIn("folder review end", log)
            self.assertIn("progress file update", log)
            self.assertIn("final_summary accepted", log)
            self.assertNotIn(hidden_reasoning, log)
            self.assertNotIn(write_content, log)
            self.assertNotIn("mock source", log)
            self.assertIn("current_micro_phase: feed", controls)
            self.assertIn("current_micro_phase: write", controls)
            self.assertIn("current_micro_phase: readonly_compare", controls)
            self.assertIn("current_micro_phase: revise", controls)
            self.assertIn("current_micro_phase: folder_review", controls)
            self.assertEqual((target / "target-output/generated.py").read_text(encoding="utf-8"), "revised\n")
            self.assertTrue((target / "target-output/FORGIS_COMPARE_REPORTS/input.txt.md").is_file())

    def test_staged_translation_can_record_active_migration_unit_id_when_scheduler_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(
                target,
                extra=self.staged_extra(max_iterations=1) + "migration_scheduler_enabled: true\nmax_migration_units: 1\n",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient([self.staged_overview_response()])

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                    report_output_dir="forgis-runtime/reports",
                    report_allowed_root=root,
                )

            self.assertEqual(result.status, "max-iterations")
            self.assertTrue(result.runtime_state["migration_scheduler_enabled"])
            self.assertTrue(result.runtime_state["active_unit_id"])
            self.assertEqual(
                result.runtime_state["active_unit_id"],
                result.runtime_state["migration_plan_summary"]["active_unit_id"],
            )
            self.assertEqual(result.runtime_state["active_unit_status"], "active")
            self.assertEqual(result.active_unit_id, result.runtime_state["active_unit_id"])
            self.assertEqual(result.migration_plan_active_unit_status, "active")
            self.assertEqual(result.migration_plan_write_status, "written")

    def test_staged_translation_rejects_early_final_summary_until_phase_gates_are_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=10, overview_min=2))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.final_response("too early"),
                    self.tool_response(
                        (
                            "plan",
                            "write_file",
                            {"path": "target_subdir/FORGIS_TRANSLATION_PLAN.md", "content": "# Plan\n"},
                        ),
                        (
                            "map",
                            "write_file",
                            {"path": "target_subdir/FORGIS_SOURCE_TARGET_MAP.md", "content": "| a | b |\n"},
                        ),
                        (
                            "progress",
                            "write_file",
                            {"path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md", "content": "# Progress\n"},
                        ),
                    ),
                    self.final_response("still early"),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "write",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": "translated\n"},
                        )
                    ),
                    self.tool_response(
                        ("compare-source", "read_file", {"path": "source/input.txt"}),
                        ("compare-target", "read_file", {"path": "target_subdir/generated.py"}),
                        (
                            "compare-report",
                            "write_file",
                            {
                                "path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md",
                                "content": "# Compare\n",
                            },
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise-progress",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed\n",
                            },
                        )
                    ),
                    self.tool_response(
                        (
                            "folder-progress",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("accepted"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            log = stdout.getvalue()
            self.assertEqual(result.status, "completed")
            self.assertEqual(result.final_summary, "accepted")
            self.assertIn("final_summary rejected", log)
            self.assertGreaterEqual(len(fake.calls), 4)

    def test_staged_compare_phase_blocks_target_code_writes_but_revision_can_write(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=12))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(
                        (
                            "plan",
                            "write_file",
                            {"path": "target_subdir/FORGIS_TRANSLATION_PLAN.md", "content": "# Plan\n"},
                        ),
                        (
                            "map",
                            "write_file",
                            {"path": "target_subdir/FORGIS_SOURCE_TARGET_MAP.md", "content": "| a | b |\n"},
                        ),
                        (
                            "progress",
                            "write_file",
                            {"path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md", "content": "# Progress\n"},
                        ),
                    ),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "write",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": "translated\n"},
                        )
                    ),
                    self.tool_response(
                        (
                            "blocked-code-write",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": "bad compare write\n"},
                        ),
                        ("compare-source", "read_file", {"path": "source/input.txt"}),
                        ("compare-target", "read_file", {"path": "target_subdir/generated.py"}),
                        (
                            "compare-report",
                            "write_file",
                            {
                                "path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md",
                                "content": "# Report\n",
                            },
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": "revised\n"},
                        ),
                        (
                            "revise-progress",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed\n",
                            },
                        ),
                    ),
                    self.tool_response(
                        (
                            "folder",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("done"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "completed")
            self.assertIn("blocked", stdout.getvalue())
            self.assertEqual((target / "target-output/generated.py").read_text(encoding="utf-8"), "revised\n")
            self.assertTrue((target / "target-output/FORGIS_COMPARE_REPORTS/input.txt.md").is_file())

    def test_folder_batch_review_bundle_respects_max_bundle_chars_and_report_names_are_safe(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source"
            target = root / "target"
            (source / "feature").mkdir(parents=True)
            target.mkdir()
            (source / "feature/a.txt").write_text("a" * 20, encoding="utf-8")
            (source / "feature/b.txt").write_text("b" * 20, encoding="utf-8")
            self.write_config(
                target,
                extra=self.staged_extra(max_iterations=12, folder_max_bundle_chars=25),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")

            units = collect_source_inventory(source, resolved.staged_translation.source_inventory)
            included, omitted = bundled_units_for_folder(units, "feature", max_bundle_chars=25)
            self.assertEqual([unit.path for unit in included], ["feature/a.txt"])
            self.assertEqual([unit.path for unit in omitted], ["feature/b.txt"])
            self.assertEqual(safe_source_report_name("../feature/a.txt"), "feature__a.txt.md")

    def test_source_unit_queue_filters_noise_and_uses_stable_priority_order(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source"
            target = root / "target"
            (source / "docs").mkdir(parents=True)
            (source / "build").mkdir()
            (source / "generated").mkdir()
            target.mkdir()
            (source / "zeta.py").write_text("print('z')\n", encoding="utf-8")
            (source / "alpha.js").write_text("console.log('a')\n", encoding="utf-8")
            (source / "docs/architecture.md").write_text("# Arch\n", encoding="utf-8")
            (source / "image.png").write_bytes(b"\x89PNG\r\n")
            (source / "build/output.py").write_text("ignored\n", encoding="utf-8")
            (source / "generated/cache.py").write_text("ignored\n", encoding="utf-8")
            (source / "package-lock.json").write_text("{}", encoding="utf-8")
            self.write_config(target, extra=self.staged_extra(max_iterations=12))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")

            units = collect_source_inventory(source, resolved.staged_translation.source_inventory)
            self.assertEqual([unit.path for unit in units], ["alpha.js", "zeta.py", "docs/architecture.md"])

    def test_staged_feed_must_read_current_source_unit_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=3))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("wrong-read", "read_file", {"path": "task"})),
                    self.final_response("too soon"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "max-iterations")
            self.assertIn("feed has not read source/input.txt", stdout.getvalue())

    def test_staged_write_requires_target_effect_or_deferred_reason(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=4))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "write-progress",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt considered\n",
                            },
                        )
                    ),
                    self.final_response("too soon"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "max-iterations")
            self.assertIn("no target implementation effect", stdout.getvalue())

    def test_staged_compare_report_missing_blocks_revise(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=5))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "write",
                            "write_file",
                            {"path": "target_subdir/generated.py", "content": "translated\n"},
                        )
                    ),
                    self.tool_response(
                        ("compare-source", "read_file", {"path": "source/input.txt"}),
                        ("compare-target", "read_file", {"path": "target_subdir/generated.py"}),
                    ),
                    self.final_response("too soon"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "max-iterations")
            self.assertIn("compare report or explicit progress compare section is missing", stdout.getvalue())

    def test_staged_final_summary_rejects_when_min_processed_units_not_met(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (source / "second.txt").write_text("second", encoding="utf-8")
            (target / "target-output").mkdir()
            self.write_config(
                target,
                extra=self.staged_extra(max_iterations=14, min_processed_units=2, max_units_per_run=2),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("feed-1", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        ("write-1", "write_file", {"path": "target_subdir/one.py", "content": "one\n"})
                    ),
                    self.tool_response(
                        ("compare-source-1", "read_file", {"path": "source/input.txt"}),
                        ("compare-target-1", "read_file", {"path": "target_subdir/one.py"}),
                        (
                            "report-1",
                            "write_file",
                            {"path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md", "content": "# C\n"},
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise-1",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed\n",
                            },
                        )
                    ),
                    self.tool_response(("feed-2", "read_file", {"path": "source/second.txt"})),
                    self.tool_response(
                        (
                            "defer-2",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/second.txt deferred: no target support yet\n",
                            },
                        )
                    ),
                    self.tool_response(
                        ("compare-source-2", "read_file", {"path": "source/second.txt"}),
                        (
                            "report-2",
                            "write_file",
                            {"path": "target_subdir/FORGIS_COMPARE_REPORTS/second.txt.md", "content": "# C\n"},
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise-2",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/second.txt no_revision_needed\n",
                            },
                        )
                    ),
                    self.tool_response(
                        (
                            "folder",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("too soon"),
                    self.final_response("still too soon"),
                    self.final_response("still blocked"),
                    self.final_response("max"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "max-iterations")
            self.assertIn("min_processed_units not met", stdout.getvalue())

    def test_staged_max_units_per_run_enters_stabilization_after_run_scope(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (source / "second.txt").write_text("second", encoding="utf-8")
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=8, max_units_per_run=1))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        ("write", "write_file", {"path": "target_subdir/one.py", "content": "one\n"})
                    ),
                    self.tool_response(
                        ("compare-source", "read_file", {"path": "source/input.txt"}),
                        ("compare-target", "read_file", {"path": "target_subdir/one.py"}),
                        (
                            "report",
                            "write_file",
                            {"path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md", "content": "# C\n"},
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed\n",
                            },
                        )
                    ),
                    self.tool_response(
                        (
                            "folder",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("done"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "completed")
            self.assertIn("active_source_units=1", stdout.getvalue())
            self.assertIn("staged phase transition: per_file -> stabilization", stdout.getvalue())

    def test_staged_low_impact_warning_is_nonblocking_when_strict_mode_false(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=8, strict_mode=False))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "already",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt already_covered: target has equivalent behavior\n",
                            },
                        )
                    ),
                    self.tool_response(
                        ("compare-source", "read_file", {"path": "source/input.txt"}),
                        (
                            "report",
                            "write_file",
                            {"path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md", "content": "# C\n"},
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed\n",
                            },
                        )
                    ),
                    self.tool_response(
                        (
                            "folder",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("done"),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "completed")
            self.assertIn("LOW IMPACT WARNING", result.final_summary)
            self.assertIn("low-impact warning", stdout.getvalue())

    def test_staged_low_impact_warning_is_failure_status_when_strict_mode_true(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=8, strict_mode=True))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.staged_overview_response(),
                    self.tool_response(("feed", "read_file", {"path": "source/input.txt"})),
                    self.tool_response(
                        (
                            "already",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt already_covered: target has equivalent behavior\n",
                            },
                        )
                    ),
                    self.tool_response(
                        ("compare-source", "read_file", {"path": "source/input.txt"}),
                        (
                            "report",
                            "write_file",
                            {"path": "target_subdir/FORGIS_COMPARE_REPORTS/input.txt.md", "content": "# C\n"},
                        ),
                    ),
                    self.tool_response(
                        (
                            "revise",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nsource/input.txt no_revision_needed\n",
                            },
                        )
                    ),
                    self.tool_response(
                        (
                            "folder",
                            "append_file",
                            {
                                "path": "target_subdir/FORGIS_TRANSLATION_PROGRESS.md",
                                "content": "\nfolder reviewed no_fix_needed\n",
                            },
                        )
                    ),
                    self.final_response("done"),
                ]
            )

            with redirect_stdout(StringIO()):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            self.assertEqual(result.status, "low-impact")
            self.assertIn("LOW IMPACT WARNING", result.final_summary)

    def test_staged_max_iterations_saves_partial_progress(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            (target / "target-output").mkdir()
            self.write_config(target, extra=self.staged_extra(max_iterations=2))
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            fake = FakeDeepSeekClient(
                [
                    self.tool_response(("read-task-1", "read_file", {"path": "task"})),
                    self.tool_response(("read-task-2", "read_file", {"path": "task"})),
                ]
            )

            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_tool_loop(
                    config=resolved,
                    source_root=source,
                    target_root=target,
                    environ={"DEEPSEEK_API_KEY": "mock-secret-value"},
                    client_factory=lambda _config, _env: fake,
                )

            progress = (target / "target-output/FORGIS_TRANSLATION_PROGRESS.md").read_text(encoding="utf-8")
            self.assertEqual(result.status, "max-iterations")
            self.assertIn("Partial progress saved", progress)
            self.assertIn("max_iterations reached", stdout.getvalue())
            self.assertIn("partial progress saved", stdout.getvalue())

    def test_list_dir_only_reads_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            sandbox = self.make_sandbox(Path(dirname))
            result = sandbox.list_dir("source")
            self.assertTrue(result["ok"])
            self.assertIn({"name": "input.txt", "type": "file"}, result["entries"])
            with self.assertRaises(ToolError):
                sandbox.list_dir("../outside")
            with self.assertRaises(ToolError):
                sandbox.list_dir("/tmp")

    def test_tree_only_reads_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            sandbox = self.make_sandbox(Path(dirname))
            result = sandbox.tree("target", max_depth=2)
            self.assertTrue(result["ok"])
            self.assertIn("FORGIS_CONFIG.yml", result["tree"])
            with self.assertRaises(ToolError):
                sandbox.tree("target/../../outside")

    def test_tree_does_not_recurse_into_symlink_directory(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)
            outside_dir = root / "outside-dir"
            outside_dir.mkdir()
            (outside_dir / "leaked.txt").write_text("do not traverse", encoding="utf-8")
            os.symlink(outside_dir, root / "target/target-output/link-dir")

            result = sandbox.tree("target_subdir", max_depth=3)
            self.assertIn("link-dir@", result["tree"])
            self.assertNotIn("  leaked.txt", result["tree"])

    def test_read_file_supports_pagination_and_size_limit(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root, max_chars=80)
            long_file = root / "source/long.txt"
            long_file.write_text("line1\nline2\nline3\n" + ("x" * 200), encoding="utf-8")
            page = sandbox.read_file("source/long.txt", start_line=2, max_lines=1)
            self.assertEqual(page["content"], "line2\n")
            self.assertEqual(page["next_start_line"], 3)
            limited = sandbox.read_file("source/long.txt", start_line=4)
            self.assertTrue(limited["truncated"])
            self.assertIn("truncated", limited["content"])

    def test_read_file_rejects_symlink_file(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            os.symlink(outside, root / "target/target-output/link-file")

            with self.assertRaisesRegex(ToolError, "symlink"):
                sandbox.read_file("target_subdir/link-file")

    def test_file_exists_only_checks_allowed_paths(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            sandbox = self.make_sandbox(Path(dirname))
            self.assertTrue(sandbox.file_exists("config")["exists"])
            self.assertFalse(sandbox.file_exists("target/missing.txt")["exists"])
            with self.assertRaises(ToolError):
                sandbox.file_exists("source/../FORGIS_CONFIG.yml")

    def test_file_exists_reports_symlink_without_resolving_target(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            os.symlink(outside, root / "target/target-output/link-file")

            result = sandbox.file_exists("target_subdir/link-file")
            self.assertTrue(result["exists"])
            self.assertTrue(result["is_symlink"])
            self.assertEqual(result["type"], "symlink")
            self.assertNotIn("outside", json.dumps(result))

    def test_build_feedback_summarizes_common_failures_and_redacts_secret_like_values(self) -> None:
        syntax = summarize_build_failure(
            {
                "status": "failed",
                "exit_code": 1,
                "stderr_tail": '  File "bad.py", line 1\n    def broken(:\nSyntaxError: invalid syntax\n',
            }
        )
        self.assertEqual(syntax["error_type"], "python_syntax_error")

        missing = summarize_build_failure(
            {
                "status": "failed",
                "exit_code": 1,
                "stderr_tail": "ModuleNotFoundError: No module named 'missing_dep'\n",
            }
        )
        self.assertEqual(missing["error_type"], "module_not_found")

        import_error = summarize_build_failure(
            {
                "status": "failed",
                "exit_code": 1,
                "stderr_tail": "ImportError: cannot import name thing\n",
            }
        )
        self.assertEqual(import_error["error_type"], "import_error")

        unittest_failure = summarize_test_failure(
            {
                "status": "failed",
                "exit_code": 1,
                "stderr_tail": "FAIL: test_demo (test_demo.T)\nFAILED (failures=1)\n",
            }
        )
        self.assertEqual(unittest_failure["error_type"], "unittest_failure")

        timeout = summarize_command_result({"status": "timeout", "timed_out": True, "timeout_seconds": 1})
        self.assertEqual(timeout["error_type"], "timeout")

        rejected = summarize_command_result({"status": "rejected", "stderr_tail": "Command is not allowed: rm"})
        self.assertEqual(rejected["error_type"], "command_rejected")

        secret = summarize_build_failure(
            {
                "status": "failed",
                "exit_code": 1,
                "stderr_tail": "DEEPSEEK_API_KEY=super-secret-value Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456\n",
            }
        )
        rendered = json.dumps(secret)
        self.assertNotIn("super-secret-value", rendered)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", rendered)
        self.assertIn("[redacted]", rendered)

    def test_runtime_controller_tracks_build_test_status_and_repair_after_failure(self) -> None:
        controller = RuntimeController()
        controller.observe_tool_result(
            name="run_build",
            arguments={},
            result={
                "ok": False,
                "status": "failed",
                "summary": {"error_type": "python_syntax_error", "message": "Build failed"},
            },
        )
        self.assertTrue(controller.ran_build)
        self.assertEqual(controller.last_build_status, "failed")
        self.assertEqual(controller.last_failure_summary["error_type"], "python_syntax_error")
        self.assertFalse(controller.modified_target_after_failure)

        controller.observe_tool_result(
            name="edit_file",
            arguments={"path": "target_subdir/app.py"},
            result={"ok": True, "path": "target/target-output/app.py"},
        )
        self.assertTrue(controller.modified_target_after_failure)

        controller.observe_tool_result(
            name="run_tests",
            arguments={},
            result={"ok": True, "status": "success", "summary": {"error_type": "success"}},
        )
        self.assertTrue(controller.ran_tests)
        self.assertEqual(controller.last_test_status, "success")
        self.assertNotIn("_pending_failed_check", controller.as_dict())

    def test_repair_loop_state_machine_tracks_allowed_diff_success_and_max_attempts(self) -> None:
        controller = RepairLoopController(enabled=True, max_attempts=2)
        controller.observe_tool_result(
            name="run_build",
            result={
                "ok": False,
                "status": "failed",
                "summary": {"error_type": "python_syntax_error", "message": "Build failed"},
            },
        )
        self.assertTrue(controller.repair_allowed)
        self.assertEqual(controller.current_attempt, 0)
        self.assertEqual(controller.last_check_type, "build")
        self.assertEqual(controller.last_failure_summary["error_type"], "python_syntax_error")

        controller.observe_tool_result(
            name="edit_file",
            result={"ok": True, "path": "target/target-output/app.py"},
        )
        self.assertTrue(controller.modified_after_failure)
        self.assertFalse(controller.diff_checked_after_modification)
        self.assertIn("git_diff", controller.block_reason_for_tool("run_build"))

        controller.observe_tool_result(name="git_diff", result={"ok": True, "diff": "diff"})
        self.assertTrue(controller.diff_checked_after_modification)
        self.assertIsNone(controller.block_reason_for_tool("run_build"))

        controller.observe_tool_result(
            name="run_build",
            result={"ok": True, "status": "success", "summary": {"error_type": "success"}},
        )
        summary = controller.as_dict()
        self.assertEqual(summary["repair_attempts_used"], 1)
        self.assertTrue(summary["repair_success"])
        self.assertEqual(summary["stopped_reason"], "success")

        maxed = RepairLoopController(enabled=True, max_attempts=1)
        maxed.observe_tool_result(name="run_tests", result={"ok": False, "status": "failed"})
        maxed.observe_tool_result(name="apply_patch", result={"ok": True, "path": "target/target-output/app.py"})
        maxed.observe_tool_result(name="git_diff", result={"ok": True, "diff": "diff"})
        maxed.observe_tool_result(name="run_tests", result={"ok": False, "status": "failed"})
        self.assertFalse(maxed.repair_allowed)
        self.assertEqual(maxed.stopped_reason, "max_attempts_reached")
        self.assertIn("max_repair_attempts", maxed.block_reason_for_tool("apply_patch"))

        disabled = RepairLoopController(enabled=False, max_attempts=1)
        disabled.observe_tool_result(name="run_build", result={"ok": False, "status": "failed"})
        disabled.observe_tool_result(name="edit_file", result={"ok": True, "path": "target/target-output/app.py"})
        self.assertFalse(disabled.as_dict()["repair_loop_enabled"])
        self.assertIsNone(disabled.block_reason_for_tool("run_build"))

    def test_repair_event_log_records_core_events_safely_and_limits_length(self) -> None:
        controller = RepairLoopController(enabled=True, max_attempts=2, event_log_limit=20)
        secret_tail = (
            "/Users/example/private/project/app.py:1 "
            "API_KEY=super-secret-value Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456"
        )
        controller.observe_tool_started(name="run_build")
        controller.observe_tool_result(
            name="run_build",
            result={
                "ok": False,
                "status": "failed",
                "summary": {
                    "error_type": "python_syntax_error",
                    "message": "Build failed",
                    "tail": secret_tail,
                },
            },
        )
        controller.observe_tool_result(
            name="edit_file",
            result={"ok": True, "path": "target/target-output/app.py"},
        )
        controller.observe_tool_result(name="git_diff", result={"ok": True, "diff": "diff --git a/app.py b/app.py"})
        controller.observe_tool_started(name="run_build")
        controller.observe_tool_result(
            name="run_build",
            result={"ok": True, "status": "success", "summary": {"error_type": "success"}},
        )

        events = controller.events_as_dict()
        event_types = [event["event_type"] for event in events]
        self.assertIn("build_started", event_types)
        self.assertIn("build_finished", event_types)
        self.assertIn("failure_recorded", event_types)
        self.assertIn("repair_allowed", event_types)
        self.assertIn("edit_after_failure", event_types)
        self.assertIn("diff_checked", event_types)
        self.assertIn("repair_recheck_started", event_types)
        self.assertIn("repair_success", event_types)
        rendered = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("super-secret-value", rendered)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz123456", rendered)
        self.assertNotIn("/Users/example", rendered)
        self.assertIn("[redacted]", rendered)
        self.assertIn("target/target-output/app.py", rendered)

        limited = RepairLoopController(enabled=True, max_attempts=2, event_log_limit=3)
        for index in range(6):
            limited.record_event(
                event_type="failure_recorded",
                status="failed",
                short_message=f"failure {index}",
            )
        limited_events = limited.events_as_dict()
        self.assertEqual(len(limited_events), 3)
        self.assertEqual(limited_events[0]["event_id"], 4)

    def test_repair_event_log_records_max_attempts_and_diff_gate_block(self) -> None:
        controller = RepairLoopController(enabled=True, max_attempts=1)
        controller.observe_tool_result(name="run_tests", result={"ok": False, "status": "failed"})
        controller.observe_tool_result(name="apply_patch", result={"ok": True, "path": "target/target-output/app.py"})
        reason = controller.block_reason_for_tool("run_tests")
        self.assertIsNotNone(reason)
        blocked = controller.blocked_tool_result("run_tests", reason or "")
        self.assertEqual(blocked["summary"]["error_type"], "diff_check_required")
        controller.observe_tool_result(name="git_diff", result={"ok": True})
        controller.observe_tool_result(name="run_tests", result={"ok": False, "status": "failed"})
        event_types = [event["event_type"] for event in controller.events_as_dict()]
        self.assertIn("repair_blocked", event_types)
        self.assertIn("max_attempts_reached", event_types)

    def test_repair_markdown_report_covers_success_blocked_skipped_and_safety(self) -> None:
        success_state = {
            "build_runs": 1,
            "test_runs": 0,
            "repair_loop_enabled": True,
            "repair_attempts_used": 1,
            "repair_success": True,
            "stopped_reason": "success",
            "last_build_status": "success",
            "last_test_status": None,
        }
        success_report = render_repair_report(
            success_state,
            events=[
                {
                    "event_id": 1,
                    "event_type": "repair_success",
                    "attempt_index": 1,
                    "check_type": "build",
                    "status": "success",
                    "short_message": "repair recheck succeeded",
                }
            ],
            changed_paths=["target/target-output/app.py"],
        )
        self.assertIn("Forgis Runtime Report", success_report)
        self.assertIn("success", success_report)
        self.assertIn("target/target-output/app.py", success_report)

        maxed_report = render_repair_report(
            {"stopped_reason": "max_attempts_reached", "repair_attempts_used": 2},
            events=[
                {
                    "event_id": 2,
                    "event_type": "max_attempts_reached",
                    "attempt_index": 2,
                    "check_type": "tests",
                    "status": "blocked",
                    "short_message": "max_attempts_reached",
                }
            ],
        )
        self.assertIn("max_attempts_reached", maxed_report)

        blocked_report = render_repair_report(
            {"stopped_reason": None},
            events=[
                {
                    "event_id": 3,
                    "event_type": "repair_blocked",
                    "attempt_index": 1,
                    "check_type": "build",
                    "status": "blocked",
                    "short_message": "diff_check_required: run git_diff first",
                }
            ],
        )
        self.assertIn("diff_check_required", blocked_report)
        self.assertIn("blocked", blocked_report)

        skipped_report = render_repair_report(
            {"build_runs": 1, "test_runs": 1, "last_build_status": "skipped", "last_test_status": "skipped"},
        )
        self.assertIn("Configure build_command/test_command", skipped_report)

        unsafe_report = render_repair_report(
            {
                "last_failure_summary": {
                    "message": "Build failed with TOKEN=secret-token-value",
                    "tail": "diff --git a/app.py b/app.py\n+API_KEY=super-secret-value",
                }
            },
            events=[
                {
                    "event_id": 4,
                    "event_type": "failure_recorded",
                    "attempt_index": 0,
                    "check_type": "build",
                    "status": "failed",
                    "short_message": "failed",
                    "failure_summary": {"message": "PASSWORD=hunter2"},
                    "diff": "diff --git a/app.py b/app.py\n+full diff should be ignored",
                }
            ],
            changed_paths=["/Users/example/private/secret-token.txt"],
            max_chars=2000,
        )
        self.assertNotIn("secret-token-value", unsafe_report)
        self.assertNotIn("super-secret-value", unsafe_report)
        self.assertNotIn("hunter2", unsafe_report)
        self.assertNotIn("diff --git", unsafe_report)
        self.assertNotIn("full diff should be ignored", unsafe_report)
        self.assertNotIn("/Users/example", unsafe_report)
        self.assertIn("[redacted]", unsafe_report)

        long_report = render_repair_report(
            {"last_failure_summary": {"message": "x" * 5000}},
            events=[],
            max_chars=1000,
        )
        self.assertLessEqual(len(long_report), 1000)
        compact = render_compact_actions_summary(success_state, changed_paths=["target/target-output/app.py"])
        self.assertIn("Forgis v3.3", compact)

    def load_report_fixture(self, name: str) -> dict[str, Any]:
        path = REPO_ROOT / "tests" / "fixtures" / "reports" / f"{name}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def report_fixture_config(self, target: Path):
        self.write_config(
            target,
            extra=textwrap.dedent(
                """\
                migration_scheduler_enabled: true
                migration_plan_resume_enabled: true
                migration_plan_event_log_max_events: 3
                migration_plan_audit_max_events: 2
                run_report_max_events: 3
                run_report_max_chars: 20000
                """
            ),
        )
        return resolve_config(target_root=target, target_repo="owner/target-repo")

    def render_report_fixture(
        self,
        config,
        fixture: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        markdown = render_run_report_markdown(
            config=config,
            runtime_state=fixture["runtime_state"],
            repair_report_markdown=fixture.get("repair_report_markdown", ""),
            final_summary=fixture.get("final_summary", ""),
            status=fixture.get("status", "completed"),
            executed=bool(fixture.get("executed", True)),
            iterations=int(fixture.get("iterations", 1)),
            tool_call_count=int(fixture.get("tool_call_count", 1)),
            read_tool_count=int(fixture.get("read_tool_count", 0)),
            write_tool_count=int(fixture.get("write_tool_count", 0)),
            operation_log=fixture.get("operation_log") or [],
        )
        report_json = render_run_report_json(
            config=config,
            runtime_state=fixture["runtime_state"],
            repair_report_markdown=fixture.get("repair_report_markdown", ""),
            final_summary=fixture.get("final_summary", ""),
            status=fixture.get("status", "completed"),
            executed=bool(fixture.get("executed", True)),
            iterations=int(fixture.get("iterations", 1)),
            tool_call_count=int(fixture.get("tool_call_count", 1)),
            read_tool_count=int(fixture.get("read_tool_count", 0)),
            write_tool_count=int(fixture.get("write_tool_count", 0)),
            operation_log=fixture.get("operation_log") or [],
        )
        return markdown, report_json

    def assert_report_fixture_sections(self, markdown: str) -> None:
        for section in (
            "## Overview",
            "## Config Summary",
            "## Migration Plan",
            "## Migration Plan Audit Summary",
            "## Resume Summary",
            "## Active Unit State",
            "## Migration Plan Events",
            "## Build / Test",
            "## Changed Paths",
            "## Final Summary",
        ):
            self.assertIn(section, markdown)

    def assert_report_fixture_schema_version(self, report_json: dict[str, Any], fixture: dict[str, Any]) -> None:
        self.assertEqual(
            report_json["schema_version"],
            fixture["expect"].get("report_schema_version", "forgis.run_report.v5.0"),
        )

    def test_report_fixture_active_status_golden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            config = self.report_fixture_config(target)
            fixture = self.load_report_fixture("active")

            markdown, report_json = self.render_report_fixture(config, fixture)

            self.assert_report_fixture_sections(markdown)
            self.assert_report_fixture_schema_version(report_json, fixture)
            self.assertIn("Migration Plan Audit Summary", markdown)
            self.assertIn("migration_plan_audit_summary", report_json)
            self.assertIn("audit_summary", report_json["migration_plan"])
            self.assertEqual(report_json["migration_plan"]["active_unit_id"], "ui-homeview-swift")
            self.assertEqual(report_json["migration_plan_audit_summary"]["active_unit_id"], "ui-homeview-swift")
            recommendation = report_json["migration_plan_recommended_next_action"].casefold()
            for keyword in fixture["expect"]["recommended_keywords"]:
                self.assertIn(keyword, recommendation)
            self.assertLessEqual(len(report_json["plan_events"]), config.migration_plan_event_log_max_events)
            self.assertLessEqual(
                len(report_json["migration_plan_audit_summary"]["recent_events"]),
                config.migration_plan_audit_max_events,
            )

    def test_report_fixture_blocked_status_golden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            config = self.report_fixture_config(target)
            fixture = self.load_report_fixture("blocked")

            markdown, report_json = self.render_report_fixture(config, fixture)

            reason = fixture["expect"]["reason"]
            rendered_json = json.dumps(report_json, ensure_ascii=False)
            self.assert_report_fixture_sections(markdown)
            self.assert_report_fixture_schema_version(report_json, fixture)
            self.assertIn(reason, markdown)
            self.assertIn(reason, rendered_json)
            self.assertEqual(report_json["migration_plan"]["blocked_count"], 1)
            self.assertEqual(report_json["migration_plan_audit_summary"]["blocked_units_count"], 1)
            recommendation = report_json["migration_plan_recommended_next_action"].casefold()
            for keyword in fixture["expect"]["recommended_keywords"]:
                self.assertIn(keyword, recommendation)

    def test_report_fixture_deferred_status_golden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            config = self.report_fixture_config(target)
            fixture = self.load_report_fixture("deferred")

            markdown, report_json = self.render_report_fixture(config, fixture)

            reason = fixture["expect"]["reason"]
            rendered_json = json.dumps(report_json, ensure_ascii=False)
            self.assert_report_fixture_sections(markdown)
            self.assert_report_fixture_schema_version(report_json, fixture)
            self.assertIn(reason, markdown)
            self.assertIn(reason, rendered_json)
            self.assertEqual(report_json["migration_plan"]["deferred_count"], 1)
            self.assertEqual(report_json["migration_plan_audit_summary"]["deferred_units_count"], 1)
            recommendation = report_json["migration_plan_recommended_next_action"].casefold()
            for keyword in fixture["expect"]["recommended_keywords"]:
                self.assertIn(keyword, recommendation)

    def test_report_fixture_completed_status_golden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            config = self.report_fixture_config(target)
            fixture = self.load_report_fixture("completed")

            markdown, report_json = self.render_report_fixture(config, fixture)

            reason = fixture["expect"]["reason"]
            rendered_json = json.dumps(report_json, ensure_ascii=False)
            self.assert_report_fixture_sections(markdown)
            self.assert_report_fixture_schema_version(report_json, fixture)
            self.assertIn(reason, markdown)
            self.assertIn(reason, rendered_json)
            self.assertEqual(report_json["migration_plan"]["completed_count"], 1)
            self.assertEqual(report_json["migration_plan_audit_summary"]["completed_units_count"], 1)
            self.assertEqual(report_json["active_unit_status"], "completed")
            recommendation = report_json["migration_plan_recommended_next_action"].casefold()
            for keyword in fixture["expect"]["recommended_keywords"]:
                self.assertIn(keyword, recommendation)

    def test_report_fixture_redaction_safety_and_event_limits(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            config = self.report_fixture_config(target)
            fixture = self.load_report_fixture("active")
            runtime_state = json.loads(json.dumps(fixture["runtime_state"]))
            runtime_state["changed_paths"].append("/Users/example/Private/Forgis/HomeView.swift")
            runtime_state["last_failure_summary"] = {
                "message": "Build failed TOKEN=fake-report-secret",
                "tail": "diff --git a/HomeView.swift b/HomeView.swift\n@@ -1 +1\n+API_KEY=fake-report-key",
            }
            runtime_state["repair_events"] = [
                {
                    "event_id": index,
                    "event_type": "failure_recorded",
                    "attempt_index": index,
                    "check_type": "build",
                    "status": "failed",
                    "short_message": "TOKEN=fake-report-secret",
                    "failure_summary": {
                        "message": "PASSWORD=fake-report-password"
                    },
                    "diff": "diff --git a/HomeView.swift b/HomeView.swift\n+full diff should not appear",
                }
                for index in range(8)
            ]
            fixture = {
                **fixture,
                "runtime_state": runtime_state,
                "repair_report_markdown": (
                    "# Repair\n\n"
                    "diff --git a/HomeView.swift b/HomeView.swift\n"
                    "@@ -1 +1\n"
                    "+API_KEY=fake-report-key\n"
                ),
                "final_summary": "Done TOKEN=fake-report-secret",
                "operation_log": [
                    *fixture.get("operation_log", []),
                    {
                        "tool": "edit_file",
                        "path": "/Users/example/Private/Forgis/HomeView.swift",
                        "content": "struct FullSourceNeverAppears { let value = 1 }",
                        "stdout_tail": "complete stdout should not appear",
                        "stderr_tail": "complete stderr should not appear",
                    },
                ],
            }

            markdown, report_json = self.render_report_fixture(config, fixture)
            rendered_json = json.dumps(report_json, ensure_ascii=False)
            combined = markdown + rendered_json

            self.assertLessEqual(len(report_json["events"]), config.run_report_max_events)
            self.assertLessEqual(len(report_json["plan_events"]), config.migration_plan_event_log_max_events)
            self.assertLessEqual(
                len(report_json["migration_plan_audit_summary"]["recent_events"]),
                config.migration_plan_audit_max_events,
            )
            for unsafe in (
                "fake-report-secret",
                "fake-report-key",
                "fake-report-password",
                "/Users/example",
                "Private/Forgis",
                "diff --git",
                "full diff should not appear",
                "FullSourceNeverAppears",
                "complete stdout should not appear",
                "complete stderr should not appear",
            ):
                self.assertNotIn(unsafe, combined)

    def test_run_report_markdown_and_json_are_bounded_structured_and_safe(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_source_target(root)
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    run_report_max_events: 3
                    run_report_max_chars: 6000
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            runtime_state = {
                "build_runs": 1,
                "test_runs": 1,
                "last_build_status": "failed",
                "last_test_status": "skipped",
                "last_failure_summary": {
                    "message": "Build failed TOKEN=secret-token-value",
                    "tail": "diff --git a/app.py b/app.py\n+API_KEY=super-secret-value",
                },
                "repair_loop_enabled": True,
                "max_repair_attempts": 2,
                "repair_attempts_used": 1,
                "repair_allowed": False,
                "repair_success": False,
                "stopped_reason": "max_attempts_reached",
                "repair_requires_diff_check": True,
                "repair_requires_build_or_test": True,
                "repair_event_count": 6,
                "changed_paths": ["target/target-output/app.py"],
                "skills_enabled": True,
                "auto_select_skills": True,
                "selected_skill_names": ["migration_general", "build_repair"],
                "skipped_skill_names": ["swiftui_to_harmonyos"],
                "failed_skill_names": ["missing_skill"],
                "total_skill_chars": 456,
                "migration_scheduler_enabled": True,
                "active_unit_id": "ui-login-12345678",
                "migration_plan_source": "loaded",
                "migration_plan_path": "forgis-runtime/reports/FORGIS_MIGRATION_PLAN.json",
                "migration_plan_load_status": "loaded",
                "migration_plan_write_status": "written",
                "plan_update_status": "updated",
                "active_unit_status": "blocked",
                "active_unit_reason": "Blocked by PASSWORD=hunter2",
                "active_unit_switch": {
                    "status": "rejected",
                    "requested_active_unit_id": "ui-secret-token-12345678",
                    "previous_active_unit_id": "ui-login-12345678",
                    "active_unit_id": "ui-login-12345678",
                    "reason": "Manual reason TOKEN=secret-token-value",
                    "message": "Switching to completed unit rejected PASSWORD=hunter2",
                },
                "manual_unit_status_update": {
                    "status": "rejected",
                    "unit_id": "ui-login-12345678",
                    "previous_status": "blocked",
                    "requested_status": "completed",
                    "final_status": "blocked",
                    "reason": "Manual status reason TOKEN=secret-token-value",
                    "message": "Manual completed rejected PASSWORD=hunter2",
                },
                "resume_summary": {
                    "plan_id": "migration-plan-safe",
                    "active_unit_id": "ui-login-12345678",
                    "last_active_unit_status": "blocked",
                    "counts": {
                        "completed": 1,
                        "blocked": 1,
                        "pending": 2,
                        "deferred": 1,
                        "active": 1,
                        "total": 5,
                    },
                    "last_stopped_reason": "Blocked by PASSWORD=hunter2",
                    "changed_paths": ["target/target-output/app.py"],
                    "next_step": "Review the blocked reason manually or switch units explicitly.",
                    "summary_short": "Resume plan migration-plan-safe TOKEN=secret-token-value",
                    "active_unit_switch": {
                        "status": "rejected",
                        "requested_active_unit_id": "ui-secret-token-12345678",
                        "previous_active_unit_id": "ui-login-12345678",
                        "active_unit_id": "ui-login-12345678",
                        "reason": "Manual reason TOKEN=secret-token-value",
                        "message": "Switch rejected PASSWORD=hunter2",
                    },
                    "switch_manual_guidance": "Check that the requested unit id exists.",
                    "manual_unit_status_update": {
                        "status": "rejected",
                        "unit_id": "ui-login-12345678",
                        "previous_status": "blocked",
                        "requested_status": "completed",
                        "final_status": "blocked",
                        "reason": "Manual status reason TOKEN=secret-token-value",
                        "message": "Manual completed rejected PASSWORD=hunter2",
                    },
                    "unit_status_update_manual_guidance": "Check that reason is filled.",
                },
                "plan_events": [
                    {
                        "event_type": "unit_status_update_rejected",
                        "unit_id": "ui-login-12345678",
                        "status_before": "blocked",
                        "status_after": "blocked",
                        "previous_status": "blocked",
                        "requested_status": "completed",
                        "final_status": "blocked",
                        "reason": "Blocked by PASSWORD=hunter2",
                        "short_message": "TOKEN=secret-token-value",
                        "order": 1,
                        "timestamp": "2026-01-01T00:00:00Z",
                    }
                ],
                "migration_plan_summary": {
                    "plan_id": "migration-plan-safe",
                    "active_unit_id": "ui-login-12345678",
                    "completed_count": 1,
                    "blocked_count": 1,
                    "pending_count": 2,
                    "deferred_count": 1,
                    "active_count": 1,
                    "unit_count": 5,
                    "active_unit": {
                        "unit_id": "ui-login-12345678",
                        "title": "Login TOKEN=secret-token-value",
                        "source_paths": ["source/LoginView.swift"],
                        "target_paths": ["target_subdir/Login.kt"],
                        "unit_type": "ui",
                        "priority": 100,
                        "status": "blocked",
                        "reason": "Blocked by PASSWORD=hunter2",
                    },
                    "units": [
                        {
                            "unit_id": "ui-login-12345678",
                            "title": "Login TOKEN=secret-token-value",
                            "source_paths": ["source/LoginView.swift"],
                            "target_paths": ["target_subdir/Login.kt"],
                            "unit_type": "ui",
                            "priority": 100,
                            "status": "blocked",
                            "reason": "Blocked by PASSWORD=hunter2",
                        }
                    ],
                },
                "repair_events": [
                    {
                        "event_id": index,
                        "event_type": "failure_recorded",
                        "attempt_index": index,
                        "check_type": "build",
                        "status": "failed",
                        "short_message": f"failure {index}",
                        "failure_summary": {"message": "PASSWORD=hunter2"},
                        "diff": "diff --git a/app.py b/app.py\n+full diff",
                    }
                    for index in range(6)
                ],
            }
            repair_markdown = "# Repair\n\ndiff --git a/app.py b/app.py\n+API_KEY=super-secret-value\n"
            operation_log = [
                {
                    "tool": "edit_file",
                    "path": "target/target-output/app.py",
                    "stdout_tail": "do not keep stdout",
                    "content": "do not keep source",
                }
            ]

            markdown = render_run_report_markdown(
                config=resolved,
                runtime_state=runtime_state,
                repair_report_markdown=repair_markdown,
                final_summary="Done with TOKEN=secret-token-value",
                status="completed",
                executed=True,
                iterations=3,
                tool_call_count=4,
                read_tool_count=1,
                write_tool_count=1,
                operation_log=operation_log,
            )
            self.assertIn("Forgis Run Report", markdown)
            self.assertIn("Build / Test", markdown)
            self.assertIn("Skills", markdown)
            self.assertIn("Migration Plan", markdown)
            self.assertIn("Migration Plan Audit Summary", markdown)
            self.assertIn("Resume Summary", markdown)
            self.assertIn("Migration Plan Events", markdown)
            self.assertIn("Active Unit State", markdown)
            self.assertIn("Active Unit Switch", markdown)
            self.assertIn("Manual Unit Status Update", markdown)
            self.assertIn("Plan Update Status", markdown)
            self.assertIn("migration_plan_persistence_enabled", markdown)
            self.assertIn("migration_plan_resume_enabled", markdown)
            self.assertIn("migration_plan_write_status", markdown)
            self.assertIn("FORGIS_MIGRATION_PLAN.json", markdown)
            self.assertIn("migration-plan-safe", markdown)
            self.assertIn("ui-login-12345678", markdown)
            self.assertIn("migration_general", markdown)
            self.assertIn("build_repair", markdown)
            self.assertIn("swiftui_to_harmonyos", markdown)
            self.assertIn("missing_skill", markdown)
            self.assertIn("456", markdown)
            self.assertIn("Repair", markdown)
            self.assertIn("max_attempts_reached", markdown)
            self.assertIn("target/target-output/app.py", markdown)
            self.assertNotIn("Read or search the relevant source", markdown)
            self.assertNotIn("secret-token-value", markdown)
            self.assertNotIn("super-secret-value", markdown)
            self.assertNotIn("hunter2", markdown)
            self.assertNotIn("diff --git", markdown)
            self.assertLessEqual(len(markdown), resolved.run_report_max_chars)

            report_json = render_run_report_json(
                config=resolved,
                runtime_state=runtime_state,
                repair_report_markdown=repair_markdown,
                final_summary="Done with TOKEN=secret-token-value",
                status="completed",
                executed=True,
                iterations=3,
                tool_call_count=4,
                read_tool_count=1,
                write_tool_count=1,
                operation_log=operation_log,
            )
            rendered_json = json.dumps(report_json, ensure_ascii=False)
            self.assertEqual(report_json["build_test"]["build_runs"], 1)
            self.assertEqual(report_json["repair_loop"]["stopped_reason"], "max_attempts_reached")
            self.assertEqual(report_json["skills"]["selected_skill_names"], ["migration_general", "build_repair"])
            self.assertEqual(report_json["skills"]["skipped_skill_names"], ["swiftui_to_harmonyos"])
            self.assertEqual(report_json["skills"]["failed_skill_names"], ["missing_skill"])
            self.assertEqual(report_json["skills"]["total_skill_chars"], 456)
            self.assertTrue(report_json["migration_plan"]["migration_scheduler_enabled"])
            self.assertEqual(report_json["migration_plan"]["completed_count"], 1)
            self.assertEqual(report_json["migration_plan"]["blocked_count"], 1)
            self.assertEqual(report_json["migration_plan"]["active_unit_id"], "ui-login-12345678")
            self.assertTrue(report_json["migration_plan"]["migration_plan_persistence"]["enabled"])
            self.assertFalse(report_json["migration_plan"]["migration_plan_persistence"]["resume_enabled"])
            self.assertEqual(report_json["migration_plan"]["plan_source"], "loaded")
            self.assertEqual(report_json["migration_plan"]["plan_load_status"], "loaded")
            self.assertEqual(report_json["migration_plan"]["plan_write_status"], "written")
            self.assertEqual(report_json["migration_plan"]["plan_path"], "forgis-runtime/reports/FORGIS_MIGRATION_PLAN.json")
            self.assertEqual(report_json["migration_plan"]["plan_update_status"], "updated")
            self.assertEqual(report_json["active_unit_switch"]["status"], "rejected")
            self.assertEqual(report_json["migration_plan"]["active_unit_switch"]["previous_active_unit_id"], "ui-login-12345678")
            self.assertEqual(report_json["manual_unit_status_update"]["status"], "rejected")
            self.assertEqual(report_json["migration_plan"]["manual_unit_status_update"]["requested_status"], "completed")
            self.assertEqual(report_json["migration_plan_audit_summary"]["latest_action_type"], "manual_unit_status_update")
            self.assertEqual(report_json["migration_plan"]["audit_summary"]["blocked_units_count"], 1)
            self.assertIn("blocked reason", report_json["migration_plan_recommended_next_action"])
            self.assertEqual(report_json["active_unit_status"], "blocked")
            self.assertEqual(report_json["resume_summary"]["last_active_unit_status"], "blocked")
            self.assertEqual(report_json["plan_events"][0]["event_type"], "unit_status_update_rejected")
            self.assertLessEqual(len(report_json["events"]), 3)
            self.assertIn("target/target-output/app.py", report_json["changed_paths"])
            self.assertNotIn("Read or search the relevant source", rendered_json)
            self.assertNotIn("secret-token-value", rendered_json)
            self.assertNotIn("super-secret-value", rendered_json)
            self.assertNotIn("hunter2", rendered_json)
            self.assertNotIn("diff --git", rendered_json)
            self.assertNotIn("do not keep stdout", rendered_json)
            self.assertNotIn("do not keep source", rendered_json)

    def test_write_run_reports_writes_safe_dir_rejects_escape_and_limits_files(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source-repo"
            target = root / "target-repo"
            source.mkdir()
            target.mkdir()
            markdown = "# Report\n\nTOKEN=secret-token-value\n" + ("x" * 5000)
            json_data = {
                "events": [{"event_id": index, "message": "TOKEN=secret-token-value"} for index in range(50)],
                "operation_log": [{"stdout_tail": "do not keep stdout"}],
                "final_summary": "ok",
            }

            written = write_run_reports(
                output_dir="forgis-runtime/reports",
                markdown=markdown,
                json_data=json_data,
                allowed_root=root,
                source_root=source,
                target_root=target,
                max_chars=1200,
            )
            self.assertEqual(written.status, "written")
            markdown_path = Path(written.markdown_path)
            json_path = Path(written.json_path)
            self.assertEqual(markdown_path.name, RUN_REPORT_MARKDOWN_FILENAME)
            self.assertEqual(json_path.name, RUN_REPORT_JSON_FILENAME)
            self.assertLessEqual(len(markdown_path.read_text(encoding="utf-8")), 1201)
            rendered_json = json_path.read_text(encoding="utf-8")
            self.assertLessEqual(len(rendered_json), 1201)
            self.assertNotIn("secret-token-value", markdown_path.read_text(encoding="utf-8"))
            self.assertNotIn("secret-token-value", rendered_json)

            escaped = write_run_reports(
                output_dir="../outside",
                markdown="# Report\n",
                json_data={},
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(escaped.status, "skipped")
            self.assertIn("runtime root", escaped.error)

            source_write = write_run_reports(
                output_dir="source-repo/reports",
                markdown="# Report\n",
                json_data={},
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(source_write.status, "skipped")
            self.assertIn("source repository", source_write.error)

            target_write = write_run_reports(
                output_dir="target-repo/reports",
                markdown="# Report\n",
                json_data={},
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(target_write.status, "skipped")
            self.assertIn("target repository", target_write.error)

            git_write = write_run_reports(
                output_dir=".git/reports",
                markdown="# Report\n",
                json_data={},
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(git_write.status, "skipped")
            self.assertIn("unsafe path segment", git_write.error)

            for forbidden in (
                Path.home() / "Desktop/forgis-report",
                Path.home() / "Downloads/forgis-report",
                Path.home() / "Documents/forgis-report",
            ):
                rejected = write_run_reports(
                    output_dir=forbidden,
                    markdown="# Report\n",
                    json_data={},
                    allowed_root=Path.home(),
                    source_root=source,
                    target_root=target,
                )
                self.assertEqual(rejected.status, "skipped")

            readonly_file = root / "readonly-file"
            readonly_file.write_text("x", encoding="utf-8")
            failed = write_run_reports(
                output_dir="readonly-file/reports",
                markdown="# Report\n",
                json_data={},
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(failed.status, "skipped")

    def test_github_step_summary_writer_is_optional_and_safe(self) -> None:
        self.assertFalse(write_github_step_summary("# Report\n", env={}))
        with tempfile.TemporaryDirectory() as dirname:
            summary_path = Path(dirname) / "summary.md"
            self.assertTrue(
                write_github_step_summary(
                    "# Report\n\nTOKEN=secret-token-value\n",
                    env={"GITHUB_STEP_SUMMARY": str(summary_path)},
                )
            )
            text = summary_path.read_text(encoding="utf-8")
            self.assertIn("# Report", text)
            self.assertNotIn("secret-token-value", text)
            self.assertFalse(
                write_github_step_summary(
                    "# Report\n",
                    env={"GITHUB_STEP_SUMMARY": str(Path(dirname))},
                )
            )

    def test_search_text_finds_matches_with_line_numbers_and_limits_results(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)
            target_file = root / "target/target-output/search.txt"
            target_file.write_text(
                "alpha\nneedle one\nbeta\nneedle two\nneedle three\n",
                encoding="utf-8",
            )

            result = sandbox.search_text("needle", root="target_subdir", max_results=2)

            self.assertTrue(result["ok"])
            self.assertTrue(result["truncated"])
            self.assertEqual(result["match_count"], 2)
            self.assertEqual(result["matches"][0]["path"], "target/target-output/search.txt")
            self.assertEqual(result["matches"][0]["line"], 2)
            self.assertIn("needle one", result["matches"][0]["snippet"])

            regex = sandbox.search_text(r"needle\s+three", root="target_subdir", regex=True)
            self.assertEqual(regex["matches"][0]["line"], 5)

            with self.assertRaises(ToolError):
                sandbox.search_text("needle", root="../outside")

    def test_git_status_and_git_diff_report_target_changes_and_reject_non_git_repos(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)
            target = root / "target"
            self.init_git_repo(target)
            self.commit_all(target)
            (target / "target-output/existing.txt").write_text("old\nchanged\n", encoding="utf-8")

            status = sandbox.git_status()
            rendered_status = "\n".join(status["status_lines"])
            self.assertTrue(status["ok"])
            self.assertIn("M target-output/existing.txt", rendered_status)

            diff = sandbox.git_diff(max_chars=120)
            self.assertTrue(diff["ok"])
            self.assertLessEqual(len(diff["diff"]), 120)
            self.assertTrue(diff["truncated"])
            self.assertIn("existing.txt", diff["diff"])

        with tempfile.TemporaryDirectory() as dirname:
            sandbox = self.make_sandbox(Path(dirname))
            with self.assertRaisesRegex(ToolError, "not a git repository"):
                sandbox.git_status()

    def test_write_tools_only_modify_target_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            sandbox = self.make_sandbox(Path(dirname))
            sandbox.mkdir("target_subdir/nested")
            sandbox.write_file("target_subdir/nested/file.txt", "hello")
            sandbox.append_file("target-output/nested/file.txt", "\nworld")
            content = sandbox.read_file("target/target-output/nested/file.txt")["content"]
            self.assertEqual(content, "hello\nworld")
            sandbox.delete_file("target_subdir/nested/file.txt")
            self.assertFalse(sandbox.file_exists("target_subdir/nested/file.txt")["exists"])
            self.assertEqual([item["tool"] for item in sandbox.operation_log()], ["mkdir", "write_file", "append_file", "delete_file"])

            with self.assertRaises(ToolError):
                sandbox.mkdir("target/root-dir")
            with self.assertRaises(ToolError):
                sandbox.write_file("target/root.txt", "no")
            with self.assertRaises(ToolError):
                sandbox.append_file("source/input.txt", "no")
            with self.assertRaises(ToolError):
                sandbox.delete_file("FORGIS_TASK.md")

    def test_edit_file_and_apply_patch_only_modify_target_subdir_files(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)

            edit = sandbox.edit_file("target_subdir/existing.txt", "old\n", "new\n")
            self.assertTrue(edit["ok"])
            self.assertEqual((root / "target/target-output/existing.txt").read_text(encoding="utf-8"), "new\n")

            patch = "\n".join(
                [
                    "--- a/existing.txt",
                    "+++ b/existing.txt",
                    "@@ -1 +1 @@",
                    "-new",
                    "+patched",
                    "",
                ]
            )
            applied = sandbox.apply_patch("target_subdir/existing.txt", patch)
            self.assertTrue(applied["ok"])
            self.assertEqual(
                (root / "target/target-output/existing.txt").read_text(encoding="utf-8"),
                "patched\n",
            )

            with self.assertRaisesRegex(ToolError, "source repository"):
                sandbox.edit_file("source/input.txt", "mock", "no")
            with self.assertRaises(ToolError):
                sandbox.edit_file("target_subdir/../FORGIS_TASK.md", "x", "y")

            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            os.symlink(outside, root / "target/target-output/link-out")
            with self.assertRaisesRegex(ToolError, "symlink"):
                sandbox.edit_file("target_subdir/link-out", "outside", "no")

    def test_run_command_captures_output_exit_code_timeout_and_blocks_unsafe_use(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)

            version = sandbox.run_command([sys.executable, "--version"])
            self.assertTrue(version["ok"])
            self.assertEqual(version["exit_code"], 0)
            self.assertIn("stdout", version)
            self.assertIn("stderr", version)

            echo = sandbox.run_command(["echo", "hello"])
            self.assertTrue(echo["ok"])
            self.assertEqual(echo["stdout"], "hello\n")

            failed = sandbox.run_command(["false"])
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["exit_code"], 1)

            timed_out = sandbox.run_command(["sleep", "2"], timeout_seconds=1)
            self.assertFalse(timed_out["ok"])
            self.assertTrue(timed_out["timed_out"])

            truncated = sandbox.run_command(["echo", "x" * 500], max_output_chars=100)
            self.assertTrue(truncated["truncated"])
            self.assertLessEqual(len(truncated["stdout"]), 100)

            with self.assertRaisesRegex(ToolError, "not allowed"):
                sandbox.run_command(["rm", "-rf", "."])
            with self.assertRaisesRegex(ToolError, "source repository"):
                sandbox.run_command(["echo", "no"], cwd="source")
            with self.assertRaisesRegex(ToolError, "inside target_subdir"):
                sandbox.run_command(["echo", "no"], cwd="target")

    def test_run_build_skips_succeeds_fails_rejects_times_out_and_truncates(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(Path(dirname))
            skipped = sandbox.run_build()
            self.assertEqual(skipped["status"], "skipped")
            self.assertTrue(skipped["ok"])

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox, _source, target = self.make_configured_sandbox(
                root,
                extra=self.command_config_extra(
                    build_command=[sys.executable, "-m", "py_compile", "ok.py"],
                    max_command_output_chars=200,
                ),
            )
            (target / "target-output/ok.py").write_text("value = 1\n", encoding="utf-8")
            success = sandbox.run_build()
            self.assertEqual(success["status"], "success")
            self.assertEqual(success["exit_code"], 0)
            self.assertIn("duration_seconds", success)

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            extra = self.command_config_extra(
                build_command=[sys.executable, "-m", "py_compile", "bad.py"],
                max_command_output_chars=300,
            )
            sandbox, _source, target = self.make_configured_sandbox(root, extra=extra)
            (target / "target-output/bad.py").write_text("def broken(:\n", encoding="utf-8")
            failed = sandbox.run_build()
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["summary"]["error_type"], "python_syntax_error")
            self.assertIn("SyntaxError", failed["summary"]["message"])

        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(
                Path(dirname),
                extra=self.command_config_extra(build_command=["rm", "-rf", "."]),
            )
            rejected = sandbox.run_build()
            self.assertEqual(rejected["status"], "rejected")
            self.assertEqual(rejected["summary"]["error_type"], "command_rejected")

        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(
                Path(dirname),
                extra=self.command_config_extra(build_command=["sleep", "2"], build_timeout_seconds=1),
            )
            timeout = sandbox.run_build()
            self.assertEqual(timeout["status"], "timeout")
            self.assertEqual(timeout["summary"]["error_type"], "timeout")

        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(
                Path(dirname),
                extra=self.command_config_extra(
                    build_command=["echo", "x" * 500],
                    max_command_output_chars=100,
                ),
            )
            truncated = sandbox.run_build()
            self.assertEqual(truncated["status"], "success")
            self.assertTrue(truncated["truncated"])
            self.assertLessEqual(len(truncated["stdout_tail"]), 100)

    def test_run_tests_skips_succeeds_fails_rejects_and_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(Path(dirname))
            skipped = sandbox.run_tests()
            self.assertEqual(skipped["status"], "skipped")

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            extra = self.command_config_extra(
                test_command=[sys.executable, "-m", "unittest", "discover"],
                max_command_output_chars=400,
            )
            sandbox, _source, target = self.make_configured_sandbox(root, extra=extra)
            (target / "target-output/test_ok.py").write_text(
                "import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            success = sandbox.run_tests()
            self.assertEqual(success["status"], "success")
            self.assertEqual(success["exit_code"], 0)

        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            extra = self.command_config_extra(
                test_command=[sys.executable, "-m", "unittest", "discover"],
                max_command_output_chars=600,
            )
            sandbox, _source, target = self.make_configured_sandbox(root, extra=extra)
            (target / "target-output/test_fail.py").write_text(
                "import unittest\n\nclass T(unittest.TestCase):\n    def test_fail(self):\n        self.assertEqual(1, 2)\n",
                encoding="utf-8",
            )
            failed = sandbox.run_tests()
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["summary"]["error_type"], "unittest_failure")
            self.assertIn("unittest", failed["summary"]["message"])

        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(
                Path(dirname),
                extra=self.command_config_extra(test_command=["ssh", "example.invalid"]),
            )
            rejected = sandbox.run_tests()
            self.assertEqual(rejected["status"], "rejected")

        with tempfile.TemporaryDirectory() as dirname:
            sandbox, _source, _target = self.make_configured_sandbox(
                Path(dirname),
                extra=self.command_config_extra(test_command=["sleep", "2"], test_timeout_seconds=1),
            )
            timeout = sandbox.run_tests()
            self.assertEqual(timeout["status"], "timeout")

    def test_dotdot_and_symlink_escapes_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            sandbox = self.make_sandbox(root)
            outside = root / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            os.symlink(outside, root / "target/target-output/link-out")
            with self.assertRaises(ToolError):
                sandbox.read_file("target_subdir/../FORGIS_TASK.md")
            with self.assertRaises(ToolError):
                sandbox.read_file("target_subdir/link-out")
            with self.assertRaises(ToolError):
                sandbox.write_file("target_subdir/link-out", "overwrite")

    def test_guardrails_secret_scan_does_not_read_symlink_target(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            target_subdir = root / "target-output"
            outside = root / "outside"
            target_subdir.mkdir()
            outside.mkdir()
            secret = "mock-secret-value"
            (outside / "secret.txt").write_text(secret, encoding="utf-8")
            os.symlink(outside / "secret.txt", target_subdir / "linked-secret.txt")

            self.assertEqual(scan_secret_leaks(target_subdir, [secret]), [])

    def test_secret_leak_check_remains_hard_fail_without_printing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            target_subdir = target / "target-output"
            target_subdir.mkdir(parents=True)
            secret = "mock-secret-value"
            (target_subdir / "leak.txt").write_text(f"value={secret}\n", encoding="utf-8")
            env = {
                **os.environ,
                "DEEPSEEK_API_KEY": secret,
            }
            result = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "guardrails.py"),
                    "check-secret-leaks",
                    "--target",
                    str(target),
                    "--target-subdir",
                    "target-output",
                    "--model-env-json",
                    json.dumps({"DEEPSEEK_API_KEY": "DEEPSEEK_API_KEY"}),
                ],
                env=env,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("secret-like model value", result.stdout)
            self.assertIn("target-output/leak.txt", result.stdout)
            self.assertNotIn(secret, result.stdout)

    def test_validate_target_output_does_not_count_symlink_target_as_output(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            target = root / "target"
            subdir = target / "target-output"
            outside = root / "outside"
            subdir.mkdir(parents=True)
            outside.mkdir()
            snapshot = root / "before.json"
            snapshot.write_text(json.dumps(files_snapshot(subdir)), encoding="utf-8")
            (outside / "result.txt").write_text("not target output", encoding="utf-8")
            os.symlink(outside / "result.txt", subdir / "result.txt")

            self.assertEqual(files_snapshot(subdir), {})
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    validate(
                        target=target,
                        target_subdir="target-output",
                        run_log_path="target-output/FORGIS_LOG.md",
                        before_snapshot_path=snapshot,
                        require_meaningful_change=True,
                        success_checks_json="[]",
                    )

    def test_source_repo_modification_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname)
            self.init_git_repo(source)
            (source / "tracked.txt").write_text("clean", encoding="utf-8")
            self.commit_all(source)
            (source / "tracked.txt").write_text("dirty", encoding="utf-8")
            result = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "guardrails.py"),
                    "check-source-clean",
                    "--source",
                    str(source),
                ],
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("source repository was modified", result.stdout)

    def test_target_subdir_outside_modification_is_detected(self) -> None:
        violations = target_scope_violations(
            ["target-output/file.txt", "README.md"],
            "target-output",
            read_only_paths=[],
        )
        self.assertEqual(violations, ["README.md"])

    def test_target_scope_violation_warning_only_can_continue(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            (target / "target-output").mkdir()
            self.init_git_repo(target)
            self.commit_all(target)
            (target / "README.md").write_text("outside target_subdir", encoding="utf-8")

            warning = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "guardrails.py"),
                    "check-target-scope",
                    "--target",
                    str(target),
                    "--target-subdir",
                    "target-output",
                    "--warning-only",
                ],
            )
            self.assertIn("WARNING: target repository has changes outside", warning.stdout)
            self.assertIn("strict_mode=false", warning.stdout)

            strict = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "guardrails.py"),
                    "check-target-scope",
                    "--target",
                    str(target),
                    "--target-subdir",
                    "target-output",
                ],
                check=False,
            )
            self.assertNotEqual(strict.returncode, 0)
            self.assertIn("ERROR: target repository has changes outside", strict.stdout)

    def test_config_and_task_modification_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            snapshot = snapshot_paths(target, ["FORGIS_CONFIG.yml", "FORGIS_TASK.md"])
            (target / "FORGIS_CONFIG.yml").write_text("changed: true\n", encoding="utf-8")
            (target / "FORGIS_TASK.md").write_text("changed\n", encoding="utf-8")
            self.assertEqual(
                changed_read_only_paths(target, snapshot),
                ["FORGIS_CONFIG.yml", "FORGIS_TASK.md"],
            )

    def test_check_readonly_missing_snapshot_has_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target)
            missing = target / "forgis-runtime/read_only_snapshot.json"
            result = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "guardrails.py"),
                    "check-readonly",
                    "--target",
                    str(target),
                    "--snapshot",
                    str(missing),
                ],
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Missing read-only snapshot file", result.stdout)
            self.assertIn("Snapshot read-only target inputs", result.stdout)
            self.assertIn("Check the checkout and snapshot steps above.", result.stdout)
            self.assertNotIn("FileNotFoundError", result.stdout)

    def test_run_log_path_must_be_inside_target_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(target, extra="run_log_path: FORGIS_LOG.md\n")
            with self.assertRaisesRegex(ValueError, "run_log_path"):
                resolve_config(target_root=target, target_repo="owner/target-repo")
            with self.assertRaisesRegex(ValueError, "run_log_path"):
                require_path_inside_subdir(target, "target-output", "FORGIS_LOG.md", "run_log_path")

    def test_real_run_with_only_log_change_fails(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            subdir = target / "target-output"
            subdir.mkdir(parents=True)
            snapshot = target / "before.json"
            snapshot.write_text(json.dumps(files_snapshot(subdir)), encoding="utf-8")
            (subdir / "FORGIS_LOG.md").write_text("log only", encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit):
                    validate(
                        target=target,
                        target_subdir="target-output",
                        run_log_path="target-output/FORGIS_LOG.md",
                        before_snapshot_path=snapshot,
                        require_meaningful_change=True,
                        success_checks_json="[]",
                    )
            self.assertEqual(meaningful_changes(["FORGIS_LOG.md"], "FORGIS_LOG.md"), [])

    def test_validation_commands_and_success_checks_are_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(
                target,
                extra=textwrap.dedent(
                    """\
                    validation_commands:
                      - "test -f result/output.txt"
                    success_checks:
                      - path_exists: result/output.txt
                    """
                ),
            )
            output = target / "target-output/result/output.txt"
            output.parent.mkdir(parents=True)
            output.write_text("ok", encoding="utf-8")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            env = {
                **os.environ,
                "TARGET_REPO_DIR": str(target),
                "TARGET_SUBDIR": "target-output",
                "VALIDATION_COMMANDS_JSON": json.dumps(list(resolved.validation_commands)),
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "build_target.sh")], env=env)
            self.assertIn("Configured validation_commands completed successfully.", result.stdout)

            snapshot = target / "before.json"
            snapshot.write_text("{}\n", encoding="utf-8")
            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                validate(
                    target=target,
                    target_subdir="target-output",
                    run_log_path="target-output/FORGIS_LOG.md",
                    before_snapshot_path=snapshot,
                    require_meaningful_change=False,
                    success_checks_json=json.dumps(list(resolved.success_checks)),
                )

    def test_success_checks_failure_warning_only_can_continue(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            subdir = target / "target-output"
            subdir.mkdir(parents=True)
            snapshot = target / "before.json"
            snapshot.write_text(json.dumps(files_snapshot(subdir)), encoding="utf-8")

            result = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "validate_target_output.py"),
                    "validate",
                    "--target",
                    str(target),
                    "--target-subdir",
                    "target-output",
                    "--run-log-path",
                    "target-output/FORGIS_LOG.md",
                    "--snapshot",
                    str(snapshot),
                    "--require-meaningful-change",
                    "--success-checks-json",
                    json.dumps([{"path_exists": "missing.txt"}]),
                    "--warning-only",
                ],
            )
            self.assertIn("WARNING: generic target output validation failed", result.stdout)
            self.assertIn("Continuing because strict_mode=false.", result.stdout)

            strict = self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "validate_target_output.py"),
                    "validate",
                    "--target",
                    str(target),
                    "--target-subdir",
                    "target-output",
                    "--run-log-path",
                    "target-output/FORGIS_LOG.md",
                    "--snapshot",
                    str(snapshot),
                    "--success-checks-json",
                    json.dumps([{"path_exists": "missing.txt"}]),
                ],
                check=False,
            )
            self.assertNotEqual(strict.returncode, 0)
            self.assertIn("ERROR: generic target output validation failed", strict.stdout)

    def test_success_checks_accept_target_subdir_prefix_or_relative_path(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            subdir = target / "custom-output"
            subdir.mkdir(parents=True)
            (subdir / "result.txt").write_text("ok", encoding="utf-8")
            snapshot = target / "before.json"
            snapshot.write_text(json.dumps(files_snapshot(subdir)), encoding="utf-8")
            checks = [
                {"path_exists": "result.txt"},
                {"path_exists": "custom-output/result.txt"},
            ]

            with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
                validate(
                    target=target,
                    target_subdir="custom-output",
                    run_log_path="custom-output/FORGIS_LOG.md",
                    before_snapshot_path=snapshot,
                    require_meaningful_change=False,
                    success_checks_json=json.dumps(checks),
                )

    def test_create_pr_dry_run_exits_before_git_or_gh(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            target = root / "target"
            fake_bin = root / "fake-bin"
            called = root / "called.txt"
            target.mkdir()
            fake_bin.mkdir()
            for name in ("git", "gh"):
                script = fake_bin / name
                script.write_text(
                    "\n".join(
                        [
                            "#!/usr/bin/env bash",
                            f"printf '%s\\n' {name} >> {called}",
                            "exit 99",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                script.chmod(0o755)

            env = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "TARGET_REPO_DIR": str(target),
                "TARGET_REPO": "owner/target-repo",
                "TARGET_BRANCH": "forgis/output",
                "TARGET_BASE_BRANCH": "main",
                "DRY_RUN": "true",
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "create_pr.sh")], env=env)
            self.assertIn("Skipping git add, commit, push, and pull request creation.", result.stdout)
            self.assertFalse(called.exists())

    def test_no_platform_specific_judgment_in_forgis_body(self) -> None:
        banned = (
            "AndroidManifest",
            "MainActivity",
            "com.android",
            "Gradle settings",
            "kotlin-compose",
            "Cargo.toml",
            "pyproject.toml",
            "target_stack",
            "migration_profile",
            ".forgis-write-scope.md",
            "source bundle",
            "source dossier",
            "scaffold",
        )
        files = [
            path
            for root in (REPO_ROOT / "agent", REPO_ROOT / ".github/workflows")
            for path in root.rglob("*")
            if path.is_file()
        ]
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in banned:
                self.assertNotIn(marker, text, f"{marker} found in {path}")

    def test_readme_mentions_aider_only_as_v5_non_goal(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        release_notes = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for text in (readme, readme_zh, release_notes):
            self.assertIn("Aider", text)
            lowered = text.casefold()
            self.assertNotIn("agent_backend: aider", lowered)
            self.assertNotIn("run_aider", lowered)
            self.assertNotIn("install aider", lowered)
            self.assertNotIn("aider_compat", lowered)

    def test_readme_v49_manual_audit_examples_are_present(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        for text, no_auto_phrase in (
            (readme, "does not automatically execute the next unit"),
            (readme_zh, "不会自动执行下一个 unit"),
        ):
            self.assertIn("migration_plan_audit_summary_enabled: true", text)
            self.assertIn("migration_plan_audit_max_events: 10", text)
            self.assertIn('migration_plan_requested_active_unit_id: "ui-homeview-swift"', text)
            self.assertIn('migration_plan_requested_unit_status_unit_id: "asset-icons"', text)
            self.assertIn('migration_plan_requested_unit_status_unit_id: "model-userprofile"', text)
            self.assertIn("Target platform component is missing; needs manual design decision.", text)
            self.assertIn(no_auto_phrase, text)

    def test_readme_v50_final_release_checklist_is_present(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        readme_zh = (REPO_ROOT / "README.zh-CN.md").read_text(encoding="utf-8")
        release_notes = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for text, no_runtime_phrase, matching_phrase, checklist_phrase in (
            (readme, "without adding new runtime powers", "fragile full-file", "Release checklist"),
            (readme_zh, "不新增运行能力", "不做脆弱", "Release checklist"),
        ):
            self.assertIn("Forgis v5.0", text)
            self.assertIn("forgis.run_report.v5.0", text)
            self.assertIn("forgis.migration_plan.v5.0", text)
            self.assertIn("forgis.migration_plan.v4.8", text)
            self.assertIn("tests/fixtures/reports/", text)
            self.assertIn("report fixtures", text)
            self.assertIn("golden sample", text)
            for status in ("active", "blocked", "deferred", "completed"):
                self.assertIn(f"`{status}`", text)
            self.assertIn("Migration Plan Audit Summary", text)
            self.assertIn("recommended next action", text)
            self.assertIn(matching_phrase, text)
            self.assertIn(no_runtime_phrase, text)
            self.assertIn(checklist_phrase, text)
            self.assertIn("python3 -m py_compile agent/*.py", text)
            self.assertIn("python3 -m unittest", text)
            self.assertIn("bash -n agent/create_pr.sh", text)
            self.assertIn("bash -n agent/build_target.sh", text)
            self.assertIn("git diff --check", text)
            self.assertIn("FORGIS_RUN_REPORT.md", text)
            self.assertIn("FORGIS_RUN_REPORT.json", text)
            self.assertIn("FORGIS_MIGRATION_PLAN.json", text)
            self.assertIn("Aider", text)
        self.assertIn("Forgis v5.0", release_notes)
        self.assertIn("forgis.run_report.v5.0", release_notes)
        self.assertIn("forgis.migration_plan.v5.0", release_notes)

    def test_forgis_body_does_not_contain_real_business_hardcoding(self) -> None:
        banned = (
            "Sample App",
            "sample-output",
            "pixel-clone",
            "show_greeting.py",
            "Change the greeting to be more casual",
        )
        files = [
            path
            for path in REPO_ROOT.rglob("*")
            if path.is_file()
            and ".git" not in path.parts
            and "__pycache__" not in path.parts
            and path.relative_to(REPO_ROOT).parts[0] not in {"tmp", "temp", "tests"}
        ]
        for path in files:
            text = path.read_text(encoding="utf-8", errors="ignore")
            for marker in banned:
                self.assertNotIn(marker, text, f"{marker} found in {path}")


if __name__ == "__main__":
    unittest.main()
