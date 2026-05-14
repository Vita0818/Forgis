from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from forgis_config import resolve_config, require_path_inside_subdir
from guardrails import changed_read_only_paths, snapshot_paths, target_scope_violations
from validate_target_output import files_snapshot, meaningful_changes


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

    def write_default_config(self, target: Path, extra: str = "") -> None:
        config = textwrap.dedent(
            """\
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
            """
        )
        if extra:
            config += extra if extra.endswith("\n") else extra + "\n"
        (target / "FORGIS_CONFIG.yml").write_text(config, encoding="utf-8")
        (target / "FORGIS_TASK.md").write_text(
            "# Mock Task\n\nCreate the requested output from the mock source.",
            encoding="utf-8",
        )

    def make_fake_aider(self, fake_bin: Path, args_file: Path) -> None:
        fake_bin.mkdir(parents=True, exist_ok=True)
        script = fake_bin / "aider"
        script.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env bash",
                    "set -euo pipefail",
                    "if [[ \"${1:-}\" == \"--version\" ]]; then",
                    "  echo \"aider fake\"",
                    "  exit 0",
                    "fi",
                    "if [[ \"${1:-}\" == \"--help\" ]]; then",
                    "  printf '%s\\n' 'Usage: aider --read --subtree-only --no-gitignore --input-history-file --chat-history-file --llm-history-file'",
                    "  exit 0",
                    "fi",
                    "printf '%s\\n' \"$@\" > \"$FAKE_AIDER_ARGS\"",
                    "if [[ \"${FAKE_AIDER_ROOT_CACHE:-}\" == \"yes\" ]]; then",
                    "  mkdir -p ../.aider.tags.cache.v4",
                    "  printf '%s\\n' cache > ../.aider.tags.cache.v4/cache.db",
                    "fi",
                    "if [[ \"${FAKE_AIDER_LOG_ONLY:-}\" == \"yes\" ]]; then",
                    "  printf '%s\\n' log-only > FORGIS_LOG.md",
                    "  exit 0",
                    "fi",
                    "mkdir -p result",
                    "printf '%s\\n' generated > result/output.txt",
                    "exit 0",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        script.chmod(0o755)
        args_file.parent.mkdir(parents=True, exist_ok=True)

    def make_run_aider_fixture(self, root: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
        source = root / "source"
        target = root / "target"
        runtime = root / "runtime"
        fake_bin = root / "fake-bin"
        source.mkdir()
        target.mkdir()
        runtime.mkdir()
        (source / "input.txt").write_text("mock source", encoding="utf-8")
        self.init_git_repo(source)
        self.commit_all(source)
        self.write_default_config(
            target,
            extra="dry_run: false\nrun_agent: true\nconfirm_real_run: true\nsuccess_checks:\n  - path_exists: result/output.txt\n",
        )
        self.init_git_repo(target)
        self.commit_all(target)
        message = runtime / "forgis_message.md"
        self.run_cmd(
            [
                sys.executable,
                str(AGENT_DIR / "build_prompt.py"),
                "--source",
                str(source),
                "--target",
                str(target),
                "--config-path",
                "FORGIS_CONFIG.yml",
                "--task-prompt-path",
                "FORGIS_TASK.md",
                "--target-subdir",
                "target-output",
                "--run-log-path",
                "target-output/FORGIS_LOG.md",
                "--require-task-prompt",
                "--output",
                str(message),
            ]
        )
        args_file = runtime / "aider_args.txt"
        self.make_fake_aider(fake_bin, args_file)
        return source, target, runtime, fake_bin, message, args_file

    def test_main_workflow_exposes_only_target_repo(self) -> None:
        workflow = (REPO_ROOT / ".github/workflows/migrate.yml").read_text(encoding="utf-8")
        self.assertIn("target_repo:", workflow)
        forbidden_inputs = [
            "config_path:",
            "source_repo:",
            "target_subdir:",
            "task_prompt_path:",
            "dry_run:",
            "run_agent:",
            "run_aider:",
            "model:",
        ]
        inputs_block = workflow.split("inputs:", 1)[1].split("permissions:", 1)[0]
        for forbidden in forbidden_inputs:
            self.assertNotIn(forbidden, inputs_block)

    def test_forgis_config_is_required_and_only_config_source(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            with self.assertRaises(FileNotFoundError):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            self.write_default_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.source_repo, "owner/source-repo")
            self.assertEqual(resolved.target_repo, "owner/target-repo")
            self.assertEqual(resolved.target_subdir, "target-output")
            self.assertFalse(resolved.run_agent)

    def test_defaults_and_legacy_run_aider_alias(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_default_config(
                target,
                extra="run_agent:\nrun_aider: true\ndry_run: true\nconfirm_real_run: false\n",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertTrue(resolved.run_agent_config)
            self.assertFalse(resolved.run_agent)
            self.assertTrue(resolved.dry_run)

    def test_real_run_requires_confirm_real_run(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_default_config(
                target,
                extra="dry_run: false\nrun_agent: true\nconfirm_real_run: false\n",
            )
            with self.assertRaisesRegex(ValueError, "confirm_real_run"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_run_log_path_must_be_inside_target_subdir(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_default_config(target, extra="run_log_path: FORGIS_LOG.md\n")
            with self.assertRaisesRegex(ValueError, "run_log_path"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_target_stack_and_migration_profile_are_passthrough_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            source = target / "source"
            source.mkdir()
            self.write_default_config(
                target,
                extra="target_stack: arbitrary-user-value\nmigration_profile: another-user-value\n",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(
                dict(resolved.passthrough_config),
                {
                    "target_stack": "arbitrary-user-value",
                    "migration_profile": "another-user-value",
                },
            )
            output = target / "message.md"
            self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "build_prompt.py"),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--config-path",
                    "FORGIS_CONFIG.yml",
                    "--task-prompt-path",
                    "FORGIS_TASK.md",
                    "--target-subdir",
                    "target-output",
                    "--run-log-path",
                    "target-output/FORGIS_LOG.md",
                    "--require-task-prompt",
                    "--output",
                    str(output),
                ]
            )
            message = output.read_text(encoding="utf-8")
            self.assertNotIn("arbitrary-user-value", message)
            self.assertNotIn("another-user-value", message)

    def test_aider_message_is_thin_paths_and_boundaries_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source"
            target = root / "target"
            source.mkdir()
            target.mkdir()
            self.write_default_config(target)
            output = root / "message.md"
            self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "build_prompt.py"),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--config-path",
                    "FORGIS_CONFIG.yml",
                    "--task-prompt-path",
                    "FORGIS_TASK.md",
                    "--target-subdir",
                    "target-output",
                    "--run-log-path",
                    "target-output/FORGIS_LOG.md",
                    "--require-task-prompt",
                    "--output",
                    str(output),
                ]
            )
            message = output.read_text(encoding="utf-8")
            self.assertIn("You are running through Forgis.", message)
            self.assertIn(f"Source repository path: {source.resolve()}", message)
            self.assertIn(f"Target repository path: {target.resolve()}", message)
            self.assertIn("Task file path:", message)
            self.assertIn("Create or modify files only under the writable target path.", message)
            self.assertNotIn("Create the requested output from the mock source.", message)
            self.assertNotIn("Source Bundle", message)
            self.assertNotIn("scaffold", message.casefold())

    def test_write_scope_marker_is_not_in_production_code_or_aider_chat(self) -> None:
        production_files = [
            path
            for path in (REPO_ROOT / "agent").glob("*")
            if path.is_file()
        ]
        for path in production_files:
            self.assertNotIn(".forgis-write-scope.md", path.read_text(encoding="utf-8"))

    def test_no_platform_scaffold_or_output_judgment_in_agent_code(self) -> None:
        files = [
            AGENT_DIR / "build_target.sh",
            AGENT_DIR / "validate_target_output.py",
            AGENT_DIR / "build_prompt.py",
            AGENT_DIR / "run_aider.sh",
        ]
        banned = (
            "AndroidManifest",
            "MainActivity",
            "com.android",
            "Gradle settings",
            "kotlin-compose",
            "package.json",
            "Cargo.toml",
            "pyproject.toml",
        )
        for path in files:
            text = path.read_text(encoding="utf-8")
            for marker in banned:
                self.assertNotIn(marker, text)

    def test_target_scope_outside_subdir_fails(self) -> None:
        changed = ["target-output/file.txt", "README.md", "FORGIS_TASK.md"]
        violations = target_scope_violations(
            changed,
            "target-output",
            read_only_paths=["FORGIS_TASK.md"],
        )
        self.assertEqual(violations, ["FORGIS_TASK.md", "README.md"])

    def test_config_and_task_hash_changes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            snapshot = snapshot_paths(target, ["FORGIS_CONFIG.yml", "FORGIS_TASK.md"])
            (target / "FORGIS_TASK.md").write_text("changed", encoding="utf-8")
            self.assertEqual(changed_read_only_paths(target, snapshot), ["FORGIS_TASK.md"])

    def test_source_repo_readonly_guardrail(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            source = Path(dirname)
            source.mkdir(exist_ok=True)
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

    def test_model_env_does_not_print_secret_value(self) -> None:
        secret = "super-secret-value"
        result = self.run_cmd(
            [
                sys.executable,
                str(AGENT_DIR / "model_env.py"),
                "--json",
                json.dumps({"PROVIDER_API_KEY": "PROVIDER_API_KEY"}),
            ],
            env={**os.environ, "PROVIDER_API_KEY": secret},
        )
        self.assertIn("PROVIDER_API_KEY\tPROVIDER_API_KEY", result.stdout)
        self.assertNotIn(secret, result.stdout)

    def test_run_aider_false_and_dry_run_do_not_call_aider(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_default_config(
                target,
                extra="run_agent: false\ndry_run: false\nconfirm_real_run: true\n",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertFalse(resolved.run_agent)

            self.write_default_config(
                target,
                extra="run_agent: true\ndry_run: true\nconfirm_real_run: false\n",
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertFalse(resolved.run_agent)

    def test_run_aider_invocation_uses_no_marker_file_and_creates_output(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target, runtime, fake_bin, message, args_file = self.make_run_aider_fixture(root)
            env = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "RUNNER_TEMP": str(runtime / "runner-temp"),
                "FAKE_AIDER_ARGS": str(args_file),
                "SOURCE_REPO_DIR": str(source),
                "TARGET_REPO_DIR": str(target),
                "FORGIS_PROMPT_FILE": str(message),
                "AIDER_MODEL": "provider/model-name",
                "TARGET_SUBDIR": "target-output",
                "CONFIG_PATH": "FORGIS_CONFIG.yml",
                "TASK_PROMPT_PATH": "FORGIS_TASK.md",
                "RUN_LOG_PATH": "target-output/FORGIS_LOG.md",
                "DRY_RUN": "false",
                "RUN_AGENT": "true",
                "MODEL_ENV_JSON": "{}",
                "SUCCESS_CHECKS_JSON": json.dumps([{"path_exists": "result/output.txt"}]),
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "run_aider.sh")], env=env)
            self.assertEqual(result.returncode, 0)
            args_text = args_file.read_text(encoding="utf-8")
            self.assertIn("--message-file", args_text)
            self.assertIn("--read", args_text)
            self.assertNotIn(".forgis-write-scope.md", args_text)
            self.assertTrue((target / "target-output/result/output.txt").is_file())

    def test_aider_root_cache_is_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target, runtime, fake_bin, message, args_file = self.make_run_aider_fixture(root)
            env = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "RUNNER_TEMP": str(runtime / "runner-temp"),
                "FAKE_AIDER_ARGS": str(args_file),
                "FAKE_AIDER_ROOT_CACHE": "yes",
                "SOURCE_REPO_DIR": str(source),
                "TARGET_REPO_DIR": str(target),
                "FORGIS_PROMPT_FILE": str(message),
                "AIDER_MODEL": "provider/model-name",
                "TARGET_SUBDIR": "target-output",
                "CONFIG_PATH": "FORGIS_CONFIG.yml",
                "TASK_PROMPT_PATH": "FORGIS_TASK.md",
                "RUN_LOG_PATH": "target-output/FORGIS_LOG.md",
                "DRY_RUN": "false",
                "RUN_AGENT": "true",
                "MODEL_ENV_JSON": "{}",
                "SUCCESS_CHECKS_JSON": json.dumps([{"path_exists": "result/output.txt"}]),
            }
            self.run_cmd(["bash", str(AGENT_DIR / "run_aider.sh")], env=env)
            self.assertFalse((target / ".aider.tags.cache.v4").exists())

    def test_log_only_aider_output_fails(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target, runtime, fake_bin, message, args_file = self.make_run_aider_fixture(root)
            env = {
                **os.environ,
                "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"],
                "RUNNER_TEMP": str(runtime / "runner-temp"),
                "FAKE_AIDER_ARGS": str(args_file),
                "FAKE_AIDER_LOG_ONLY": "yes",
                "SOURCE_REPO_DIR": str(source),
                "TARGET_REPO_DIR": str(target),
                "FORGIS_PROMPT_FILE": str(message),
                "AIDER_MODEL": "provider/model-name",
                "TARGET_SUBDIR": "target-output",
                "CONFIG_PATH": "FORGIS_CONFIG.yml",
                "TASK_PROMPT_PATH": "FORGIS_TASK.md",
                "RUN_LOG_PATH": "target-output/FORGIS_LOG.md",
                "DRY_RUN": "false",
                "RUN_AGENT": "true",
                "MODEL_ENV_JSON": "{}",
                "SUCCESS_CHECKS_JSON": "[]",
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "run_aider.sh")], env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("no non-log, non-cache changes", result.stdout)

    def test_validation_commands_are_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_default_config(
                target,
                extra='validation_commands:\n  - "test -f result/output.txt"\n',
            )
            (target / "target-output/result").mkdir(parents=True)
            (target / "target-output/result/output.txt").write_text("ok", encoding="utf-8")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            env = {
                **os.environ,
                "TARGET_REPO_DIR": str(target),
                "TARGET_SUBDIR": "target-output",
                "VALIDATION_COMMANDS_JSON": json.dumps(list(resolved.validation_commands)),
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "build_target.sh")], env=env)
            self.assertIn("Configured validation_commands completed successfully.", result.stdout)

    def test_success_checks_are_config_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            output = target / "target-output/result/output.txt"
            output.parent.mkdir(parents=True)
            output.write_text("ok", encoding="utf-8")
            snapshot = target / "before.json"
            snapshot.write_text("{}\n", encoding="utf-8")
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
                    "--success-checks-json",
                    json.dumps([{"path_exists": "result/output.txt"}]),
                ]
            )
            self.assertIn("Generic target output validation passed.", result.stdout)

    def test_no_success_or_validation_checks_means_no_platform_assumption(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            subdir = target / "target-output"
            subdir.mkdir()
            before = files_snapshot(subdir)
            (subdir / "plain.txt").write_text("ok", encoding="utf-8")
            changed = meaningful_changes(
                sorted(set(before) | set(files_snapshot(subdir))),
                "FORGIS_LOG.md",
            )
            self.assertEqual(changed, ["plain.txt"])

    def test_source_context_selected_files_uses_only_config_patterns(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source"
            source.mkdir()
            (source / "include.txt").write_text("include me", encoding="utf-8")
            (source / "skip.txt").write_text("skip me", encoding="utf-8")
            (source / "nested").mkdir()
            (source / "nested/include.md").write_text("include nested", encoding="utf-8")
            output = root / "source_context.md"
            self.run_cmd(
                [
                    sys.executable,
                    str(AGENT_DIR / "collect_source.py"),
                    "--source",
                    str(source),
                    "--mode",
                    "selected_files",
                    "--max-chars",
                    "100000",
                    "--include-json",
                    json.dumps(["include.txt", "nested/*.md"]),
                    "--exclude-json",
                    json.dumps(["skip.txt"]),
                    "--output",
                    str(output),
                ]
            )
            text = output.read_text(encoding="utf-8")
            self.assertIn("include.txt", text)
            self.assertIn("nested/include.md", text)
            self.assertNotIn("skip.txt", text)

    def test_no_real_business_hardcoding(self) -> None:
        banned = (
            "Sample App",
            "sample-output",
            "pixel-clone",
            "deepseek/deepseek",
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
