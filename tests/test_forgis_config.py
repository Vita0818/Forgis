from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from file_tools import FileToolSandbox, ToolError
from forgis_config import resolve_config, require_path_inside_subdir
from guardrails import changed_read_only_paths, scan_secret_leaks, snapshot_paths, target_scope_violations
from model_env import describe_model_env, parse_model_env_json, require_model_env_values
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

    def make_source_target(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        target = root / "target"
        source.mkdir()
        target.mkdir()
        (source / "input.txt").write_text("mock source", encoding="utf-8")
        self.write_config(target)
        return source, target

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

        package_block = self.workflow_step_block(workflow, "Package target output snapshot")
        self.assertIn("if: always()", package_block)
        self.assertIn("Target repository checkout is unavailable", package_block)

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

    def test_readme_does_not_contain_aider(self) -> None:
        readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("aider", readme.casefold())

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
