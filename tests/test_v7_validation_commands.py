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

from forgis_config import resolve_config


class V71ValidationCommandsTests(unittest.TestCase):
    def run_cmd(
        self,
        args: list[str],
        *,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
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

    def write_config(self, target: Path, extra: str) -> None:
        (target / "target-output").mkdir(parents=True, exist_ok=True)
        (target / "FORGIS_TASK.md").write_text("# Task\n", encoding="utf-8")
        (target / "FORGIS_CONFIG.yml").write_text(
            textwrap.dedent(
                """\
                source_repo: local/source
                target_branch: forgis/local
                target_subdir: target-output
                model_env:
                  FORGIS_MODEL_API_KEY: FORGIS_MODEL_API_KEY
                """
            )
            + extra,
            encoding="utf-8",
        )

    def test_validation_commands_argv_config_parses_and_runs_through_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(
                target,
                textwrap.dedent(
                    """\
                    validation_commands:
                      - argv: ["python3", "--version"]
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="local/target")
            self.assertEqual(resolved.validation_commands, ({"argv": ("python3", "--version")},))
            env = {
                **os.environ,
                "TARGET_REPO_DIR": str(target),
                "TARGET_SUBDIR": "target-output",
                "VALIDATION_COMMANDS_JSON": json.dumps(list(resolved.validation_commands)),
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "build_target.sh")], env=env)
            self.assertIn("Running validation_commands[0].argv", result.stdout)
            self.assertIn("Configured validation_commands completed successfully.", result.stdout)

    def test_validation_commands_argv_rejects_shell_bypass(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(
                target,
                textwrap.dedent(
                    """\
                    validation_commands:
                      - argv: ["bash", "-lc", "echo bypass"]
                    """
                ),
            )
            with self.assertRaisesRegex(ValueError, "Command is not allowed: bash"):
                resolve_config(target_root=target, target_repo="local/target")

    def test_legacy_shell_string_emits_warning_for_compatibility(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            self.write_config(
                target,
                textwrap.dedent(
                    """\
                    validation_commands:
                      - "test -f existing.txt"
                    """
                ),
            )
            (target / "target-output" / "existing.txt").write_text("ok", encoding="utf-8")
            resolved = resolve_config(target_root=target, target_repo="local/target")
            self.assertEqual(resolved.validation_commands, ("test -f existing.txt",))
            env = {
                **os.environ,
                "TARGET_REPO_DIR": str(target),
                "TARGET_SUBDIR": "target-output",
                "VALIDATION_COMMANDS_JSON": json.dumps(list(resolved.validation_commands)),
            }
            result = self.run_cmd(["bash", str(AGENT_DIR / "build_target.sh")], env=env)
            self.assertIn("legacy shell string mode", result.stdout)
            self.assertIn("Configured validation_commands completed successfully.", result.stdout)

    def test_deepseek_openai_compatible_and_qwen_config_still_parse(self) -> None:
        for backend in ("deepseek", "openai-compatible"):
            with self.subTest(backend=backend), tempfile.TemporaryDirectory() as dirname:
                target = Path(dirname)
                self.write_config(
                    target,
                    textwrap.dedent(
                        f"""\
                        agent_backend: {backend}
                        api_base: https://example.invalid/v1
                        model: local-model
                        visual_validation:
                          enabled: auto
                          provider: qwen
                          mode: reference_guidance
                          reference_screenshot_dirs: []
                          actual_screenshot_dirs: []
                          max_visual_iterations: 2
                          require_reference_first: true
                          require_actual_for_full_validation: false
                          upload_visual_artifact: false
                        validation_commands:
                          - argv: ["python3", "--version"]
                        """
                    ),
                )
                resolved = resolve_config(target_root=target, target_repo="local/target")
                self.assertEqual(resolved.agent_backend, backend)
                self.assertEqual(resolved.api_format, "openai-compatible")
                self.assertEqual(resolved.visual_validation.provider, "qwen")
                self.assertEqual(resolved.validation_commands, ({"argv": ("python3", "--version")},))


if __name__ == "__main__":
    unittest.main()
