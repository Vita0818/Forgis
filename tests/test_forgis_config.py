from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from forgis_config import resolve_config
from guardrails import changed_read_only_paths, snapshot_paths, target_scope_violations


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
                dry_run=True,
                run_aider=True,
            )

            self.assertEqual(resolved.source_repo, "Vita0818/Kikaria")
            self.assertEqual(resolved.task_prompt_path, "FORGIS_TASK.md")
            self.assertEqual(resolved.target_subdir, "Kikaria-Android")
            self.assertEqual(resolved.run_log_path, "Kikaria-Android/FORGIS_LOG.md")
            self.assertTrue(resolved.dry_run)
            self.assertTrue(resolved.run_aider_requested)
            self.assertFalse(resolved.run_aider)

    def test_workflow_input_overrides_config_but_booleans_do_not_come_from_config(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)
            self.write_default_config(target)
            with (target / "FORGIS_CONFIG.yml").open("a", encoding="utf-8") as file:
                file.write("dry_run: false\n")
                file.write("run_aider: true\n")

            resolved = resolve_config(
                target_root=target,
                target_repo="Vita0818/Outposts",
                config_path="FORGIS_CONFIG.yml",
                explicit_inputs={"target_stack": "custom-stack"},
                dry_run=True,
                run_aider=False,
            )

            self.assertEqual(resolved.target_stack, "custom-stack")
            self.assertTrue(resolved.dry_run)
            self.assertFalse(resolved.run_aider_requested)
            self.assertFalse(resolved.run_aider)

    def test_legacy_inputs_work_without_config_file(self) -> None:
        with self.make_temp_target() as dirname:
            target = Path(dirname)

            resolved = resolve_config(
                target_root=target,
                target_repo="owner/target",
                config_path="FORGIS_CONFIG.yml",
                explicit_inputs={
                    "source_repo": "owner/source",
                    "target_platform": "android",
                    "target_stack": "kotlin-compose",
                    "target_branch": "forgis/android",
                },
                dry_run=True,
                run_aider=False,
            )

            self.assertFalse(resolved.config_found)
            self.assertEqual(resolved.source_ref, "main")
            self.assertEqual(resolved.task_prompt_path, "FORGIS_TASK.md")
            self.assertEqual(resolved.run_log_path, "forgis-output/FORGIS_LOG.md")

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
                    dry_run=True,
                    run_aider=False,
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
                    dry_run=True,
                    run_aider=False,
                )

            (target / "FORGIS_CONFIG.yml").write_text("source_repo: [", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "invalid YAML"):
                resolve_config(
                    target_root=target,
                    target_repo="owner/target",
                    config_path="FORGIS_CONFIG.yml",
                    explicit_inputs={},
                    dry_run=True,
                    run_aider=False,
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
            self.assertIn("Target output directory relative to target repository root: Kikaria-Android", prompt)
            self.assertIn("Config file path relative to target repository root: FORGIS_CONFIG.yml", prompt)
            self.assertIn("Forgis will append the long-term run log at `Kikaria-Android/FORGIS_LOG.md`", prompt)
            self.assertNotIn(" ".join(("make", "the", "greeting", "more", "casual")), prompt)


if __name__ == "__main__":
    unittest.main()
