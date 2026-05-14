from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from forgis_config import resolve_config
from guardrails import (
    changed_read_only_paths,
    cleanup_aider_root_gitignore,
    root_gitignore_snapshot,
    snapshot_paths,
    target_scope_violations,
)


class ForgisConfigTests(unittest.TestCase):
    def make_temp_target(self) -> tempfile.TemporaryDirectory[str]:
        tmp_root = REPO_ROOT / "tmp"
        tmp_root.mkdir(exist_ok=True)
        return tempfile.TemporaryDirectory(dir=tmp_root)

    def write_default_config(self, target: Path) -> None:
        (target / "FORGIS_CONFIG.yml").write_text(
            "\n".join(
                [
                    "source_repo: Vita0818/Kikaria",
                    "source_ref: main",
                    "target_platform: android",
                    "target_stack: kotlin-compose",
                    "migration_profile: pixel-clone-app",
                    "target_subdir: Kikaria-Android",
                    "task_prompt_path: FORGIS_TASK.md",
                    "model: deepseek/deepseek-v4-pro",
                    "target_branch: forgis/kikaria-android-pixel-2",
                    "target_base_branch: main",
                    "dry_run: true",
                    "run_aider: false",
                    "confirm_real_run: false",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        (target / "FORGIS_TASK.md").write_text("Build the Android target project.", encoding="utf-8")

    def test_reads_target_repo_config_and_defaults_log_path(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)

            resolved = resolve_config(
                target_root=target,
                target_repo="Vita0818/Outposts",
                config_path="FORGIS_CONFIG.yml",
                explicit_inputs={},
            )

            self.assertEqual(resolved.source_repo, "Vita0818/Kikaria")
            self.assertEqual(resolved.task_prompt_path, "FORGIS_TASK.md")
            self.assertEqual(resolved.target_subdir, "Kikaria-Android")
            self.assertEqual(resolved.run_log_path, "Kikaria-Android/FORGIS_LOG.md")
            self.assertTrue(resolved.dry_run)
            self.assertFalse(resolved.run_aider_config)
            self.assertFalse(resolved.confirm_real_run)
            self.assertFalse(resolved.run_aider)

    def test_config_drives_dry_run_run_aider_and_confirm_real_run(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            with (target / "FORGIS_CONFIG.yml").open("a", encoding="utf-8") as file:
                file.write("run_aider: true\n")

            resolved = resolve_config(
                target_root=target,
                target_repo="Vita0818/Outposts",
                config_path="FORGIS_CONFIG.yml",
                explicit_inputs={},
            )

            self.assertTrue(resolved.dry_run)
            self.assertTrue(resolved.run_aider_config)
            self.assertFalse(resolved.run_aider)
            self.assertFalse(resolved.real_run_allowed)

    def test_dry_run_false_requires_confirm_real_run(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            with (target / "FORGIS_CONFIG.yml").open("a", encoding="utf-8") as file:
                file.write("dry_run: false\n")
                file.write("run_aider: true\n")

            with self.assertRaisesRegex(
                ValueError,
                "Real AI migration requires confirm_real_run: true in FORGIS_CONFIG.yml.",
            ):
                resolve_config(
                    target_root=target,
                    target_repo="Vita0818/Outposts",
                    config_path="FORGIS_CONFIG.yml",
                    explicit_inputs={},
                )

    def test_real_ai_migration_requires_all_three_config_flags(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            with (target / "FORGIS_CONFIG.yml").open("a", encoding="utf-8") as file:
                file.write("dry_run: false\n")
                file.write("run_aider: true\n")
                file.write("confirm_real_run: true\n")

            resolved = resolve_config(
                target_root=target,
                target_repo="Vita0818/Outposts",
                config_path="FORGIS_CONFIG.yml",
                explicit_inputs={},
            )

            self.assertFalse(resolved.dry_run)
            self.assertTrue(resolved.run_aider_config)
            self.assertTrue(resolved.confirm_real_run)
            self.assertTrue(resolved.real_run_allowed)
            self.assertTrue(resolved.run_aider)

    def test_missing_config_requires_configured_fields(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)

            with self.assertRaisesRegex(ValueError, "Missing required Forgis migration parameters"):
                resolve_config(
                    target_root=target,
                    target_repo="owner/target",
                    config_path="FORGIS_CONFIG.yml",
                    explicit_inputs={"source_repo": "owner/source"},
                )

    def test_source_repo_workflow_override_is_the_only_config_override(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)

            resolved = resolve_config(
                target_root=target,
                target_repo="Vita0818/Outposts",
                config_path="FORGIS_CONFIG.yml",
                explicit_inputs={
                    "source_repo": "Override/Source",
                    "target_stack": "ignored-stack",
                    "target_branch": "ignored-branch",
                },
            )

            self.assertEqual(resolved.source_repo, "Override/Source")
            self.assertEqual(resolved.target_stack, "kotlin-compose")
            self.assertEqual(resolved.target_branch, "forgis/kikaria-android-pixel-2")

    def test_run_log_must_be_inside_target_subdir(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            with (target / "FORGIS_CONFIG.yml").open("a", encoding="utf-8") as file:
                file.write("run_log_path: FORGIS_LOG.md\n")

            with self.assertRaisesRegex(ValueError, "run_log_path must be located inside target_subdir"):
                resolve_config(
                    target_root=target,
                    target_repo="Vita0818/Outposts",
                    config_path="FORGIS_CONFIG.yml",
                    explicit_inputs={},
                )

    def test_empty_and_invalid_config_fail_clearly(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            (target / "FORGIS_CONFIG.yml").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                resolve_config(
                    target_root=target,
                    target_repo="owner/target",
                    config_path="FORGIS_CONFIG.yml",
                    explicit_inputs={},
                )

            (target / "FORGIS_CONFIG.yml").write_text("source_repo: [", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid YAML"):
                resolve_config(
                    target_root=target,
                    target_repo="owner/target",
                    config_path="FORGIS_CONFIG.yml",
                    explicit_inputs={},
                )

    def test_guardrails_detect_readonly_file_changes(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            snapshot = snapshot_paths(target, ["FORGIS_CONFIG.yml", "FORGIS_TASK.md"])

            (target / "FORGIS_TASK.md").write_text("Changed task.", encoding="utf-8")

            self.assertEqual(changed_read_only_paths(target, snapshot), ["FORGIS_TASK.md"])

    def test_guardrails_reject_target_changes_outside_subdir(self) -> None:
        changed = [
            "Kikaria-Android/app/src/main/MainActivity.kt",
            "README.md",
            "FORGIS_TASK.md",
            "OtherProject/build.gradle.kts",
        ]

        violations = target_scope_violations(
            changed,
            "Kikaria-Android",
            ["FORGIS_CONFIG.yml", "FORGIS_TASK.md"],
        )

        self.assertEqual(
            violations,
            ["FORGIS_TASK.md", "OtherProject/build.gradle.kts", "README.md"],
        )

    def test_generated_prompt_uses_config_task_and_target_subdir_without_example_prompt(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            source = target / "source"
            source.mkdir()
            (source / "README.md").write_text("Source fixture.", encoding="utf-8")
            self.write_default_config(target)
            output = target / "forgis_prompt.md"

            subprocess.run(
                [
                    sys.executable,
                    str(AGENT_DIR / "build_prompt.py"),
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--rules",
                    str(REPO_ROOT / "rules"),
                    "--prompts",
                    str(REPO_ROOT / "prompts"),
                    "--source-repo",
                    "Vita0818/Kikaria",
                    "--target-repo",
                    "Vita0818/Outposts",
                    "--platform",
                    "android",
                    "--target-stack",
                    "kotlin-compose",
                    "--migration-profile",
                    "pixel-clone-app",
                    "--config-path",
                    "FORGIS_CONFIG.yml",
                    "--task-prompt-path",
                    "FORGIS_TASK.md",
                    "--require-task-prompt",
                    "--target-subdir",
                    "Kikaria-Android",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                check=True,
                text=True,
            )

            prompt = output.read_text(encoding="utf-8")
            self.assertIn("Build the Android target project.", prompt)
            self.assertIn("Source repository: Vita0818/Kikaria", prompt)
            self.assertIn("Target repository: Vita0818/Outposts", prompt)
            self.assertIn("Target output directory relative to target repository root: Kikaria-Android", prompt)
            self.assertIn("Config file path relative to target repository root: FORGIS_CONFIG.yml", prompt)
            self.assertIn("Forgis will append the long-term run log at `Kikaria-Android/FORGIS_LOG.md`", prompt)
            self.assertNotIn(" ".join(("make", "the", "greeting", "more", "casual")), prompt)

    def test_build_prompt_fails_when_task_prompt_missing_or_empty(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            source = target / "source"
            source.mkdir()
            (source / "README.md").write_text("Source fixture.", encoding="utf-8")

            base_command = [
                sys.executable,
                str(AGENT_DIR / "build_prompt.py"),
                "--source",
                str(source),
                "--target",
                str(target),
                "--rules",
                str(REPO_ROOT / "rules"),
                "--prompts",
                str(REPO_ROOT / "prompts"),
                "--platform",
                "android",
                "--target-stack",
                "kotlin-compose",
                "--migration-profile",
                "pixel-clone-app",
                "--task-prompt-path",
                "FORGIS_TASK.md",
                "--require-task-prompt",
                "--target-subdir",
                "Kikaria-Android",
                "--output",
                str(target / "forgis_prompt.md"),
            ]

            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(base_command, cwd=REPO_ROOT, check=True, text=True)

            (target / "FORGIS_TASK.md").write_text("", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(base_command, cwd=REPO_ROOT, check=True, text=True)

    def test_prompt_diagnostics_requires_kikaria_task_and_blocks_stale_greeting(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            task = target / "FORGIS_TASK.md"
            task.write_text("# Kikaria Android Migration Task\n\nBuild the target.", encoding="utf-8")
            prompt = target / "forgis_prompt.md"
            prompt.write_text(
                "\n".join(
                    [
                        "# Forgis Generated Migration Task",
                        "Source repository: Vita0818/Kikaria",
                        "Target repository: Vita0818/Outposts",
                        "Loaded file: FORGIS_TASK.md",
                        "Target output directory relative to target repository root: Kikaria-Android",
                        "# Kikaria Android Migration Task",
                    ]
                ),
                encoding="utf-8",
            )

            subprocess.run(
                [
                    sys.executable,
                    str(AGENT_DIR / "prompt_diagnostics.py"),
                    "--file",
                    str(prompt),
                    "--label",
                    "Aider Message File",
                    "--task-prompt-file",
                    str(task),
                    "--task-prompt-path",
                    "FORGIS_TASK.md",
                    "--source-repo",
                    "Vita0818/Kikaria",
                    "--target-repo",
                    "Vita0818/Outposts",
                    "--target-subdir",
                    "Kikaria-Android",
                    "--expected-same-as",
                    str(prompt),
                ],
                cwd=REPO_ROOT,
                check=True,
                text=True,
            )

            prompt.write_text(prompt.read_text(encoding="utf-8") + "\nmake the greeting more casual\n", encoding="utf-8")
            with self.assertRaises(subprocess.CalledProcessError):
                subprocess.run(
                    [
                        sys.executable,
                        str(AGENT_DIR / "prompt_diagnostics.py"),
                        "--file",
                        str(prompt),
                        "--task-prompt-file",
                        str(task),
                        "--source-repo",
                        "Vita0818/Kikaria",
                        "--target-repo",
                        "Vita0818/Outposts",
                        "--target-subdir",
                        "Kikaria-Android",
                    ],
                    cwd=REPO_ROOT,
                    check=True,
                    text=True,
                )

    def test_root_gitignore_violation_and_safe_aider_cleanup(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            subprocess.run(["git", "init"], cwd=target, check=True, stdout=subprocess.PIPE, text=True)
            (target / "Kikaria-Android").mkdir()

            snapshot = root_gitignore_snapshot(target)
            (target / ".gitignore").write_text(".aider*\n.aider.chat.history.md\n", encoding="utf-8")
            self.assertTrue(cleanup_aider_root_gitignore(target, snapshot))
            self.assertFalse((target / ".gitignore").exists())

            (target / ".gitignore").write_text("user-rule\n", encoding="utf-8")
            snapshot = root_gitignore_snapshot(target)
            (target / ".gitignore").write_text("user-rule\n.aider*\n", encoding="utf-8")
            self.assertFalse(cleanup_aider_root_gitignore(target, snapshot))
            self.assertTrue((target / ".gitignore").exists())

            violations = target_scope_violations([".gitignore"], "Kikaria-Android", [])
            self.assertEqual(violations, [".gitignore"])

    def test_main_workflow_ui_only_exposes_target_and_source_repo(self) -> None:
        workflow = yaml.load(
            (REPO_ROOT / ".github/workflows/migrate.yml").read_text(encoding="utf-8"),
            Loader=yaml.BaseLoader,
        )

        inputs = workflow["on"]["workflow_dispatch"]["inputs"]

        self.assertEqual(list(inputs.keys()), ["target_repo", "source_repo"])
        self.assertEqual(inputs["target_repo"]["required"], "true")
        self.assertEqual(inputs["source_repo"]["required"], "false")
        for hidden_input in [
            "config_path",
            "source_ref",
            "dry_run",
            "run_aider",
            "target_platform",
            "target_stack",
            "migration_profile",
            "target_subdir",
            "task_prompt_path",
            "run_log_path",
            "model",
            "target_branch",
            "target_base_branch",
            "target_prompt_file",
            "task_prompt_file",
            "aider_model",
            "base_branch",
        ]:
            self.assertNotIn(hidden_input, inputs)

    def test_main_workflow_uses_fixed_config_path(self) -> None:
        workflow_text = (REPO_ROOT / ".github/workflows/migrate.yml").read_text(encoding="utf-8")

        self.assertIn("FORGIS_CONFIG.yml", workflow_text)
        self.assertNotIn("${{ inputs.config_path }}", workflow_text)

    def test_dry_run_log_is_preview_only_and_does_not_modify_target_repo(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            preview = target / "preview.md"

            subprocess.run(
                [
                    sys.executable,
                    str(AGENT_DIR / "write_run_log.py"),
                    "--target",
                    str(target),
                    "--source-repo",
                    "owner/source",
                    "--source-ref",
                    "main",
                    "--target-repo",
                    "owner/target",
                    "--target-base-branch",
                    "main",
                    "--target-branch",
                    "forgis/test",
                    "--target-platform",
                    "android",
                    "--target-stack",
                    "kotlin-compose",
                    "--migration-profile",
                    "default",
                    "--target-subdir",
                    "Kikaria-Android",
                    "--task-prompt-path",
                    "FORGIS_TASK.md",
                    "--config-path",
                    "FORGIS_CONFIG.yml",
                    "--model",
                    "deepseek/deepseek-v4-pro",
                    "--dry-run",
                    "true",
                    "--run-aider",
                    "false",
                    "--run-aider-config",
                    "true",
                    "--confirm-real-run",
                    "false",
                    "--append-target-log",
                    "true",
                    "--preview-output",
                    str(preview),
                ],
                cwd=REPO_ROOT,
                check=True,
                text=True,
            )

            self.assertTrue(preview.is_file())
            self.assertIn("dry_run=true, Aider execution is disabled.", preview.read_text(encoding="utf-8"))
            self.assertFalse((target / "Kikaria-Android" / "FORGIS_LOG.md").exists())


if __name__ == "__main__":
    unittest.main()
