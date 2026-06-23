from __future__ import annotations

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

from command_runner import CommandRunnerError, validate_command
from deepseek_agent import DeepSeekClient
from forgis_config import resolve_config
from model_env import require_model_env_values


def write_minimal_config(target: Path, extra: str = "") -> None:
    target.mkdir(parents=True, exist_ok=True)
    (target / "FORGIS_CONFIG.yml").write_text(
        textwrap.dedent(
            """\
            source_repo: owner/source-repo
            target_branch: forgis/output
            model_env:
              FORGIS_MODEL_API_KEY: FORGIS_MODEL_API_KEY
            """
        )
        + (extra if not extra or extra.endswith("\n") else extra + "\n"),
        encoding="utf-8",
    )
    (target / "FORGIS_TASK.md").write_text("# Task\n", encoding="utf-8")


class V7ConfigTests(unittest.TestCase):
    def run_cmd(
        self,
        args: list[str],
        *,
        cwd: Path = REPO_ROOT,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            args,
            cwd=cwd,
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

    def test_deepseek_backend_defaults_remain_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            write_minimal_config(target)
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.agent_backend, "deepseek")
            self.assertEqual(resolved.model, "deepseek-v4-pro")
            self.assertEqual(resolved.api_base, "https://api.deepseek.com")
            self.assertEqual(resolved.api_format, "openai-compatible")
            self.assertEqual(resolved.request_timeout_seconds, 120)
            self.assertEqual(resolved.env()["REQUEST_TIMEOUT_SECONDS"], "120")

    def test_openai_compatible_backend_base_url_alias_and_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            write_minimal_config(
                target,
                textwrap.dedent(
                    """\
                    agent_backend: openai-compatible
                    base_url: https://openrouter.ai/api/v1
                    model: openai/gpt-4o-mini
                    request_timeout_seconds: 33
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.agent_backend, "openai-compatible")
            self.assertEqual(resolved.api_base, "https://openrouter.ai/api/v1")
            self.assertEqual(resolved.model, "openai/gpt-4o-mini")
            self.assertEqual(resolved.request_timeout_seconds, 33)
            self.assertEqual(resolved.outputs()["request_timeout_seconds"], "33")

    def test_api_base_and_base_url_conflict_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            write_minimal_config(
                target,
                "api_base: https://a.example/v1\nbase_url: https://b.example/v1\n",
            )
            with self.assertRaisesRegex(ValueError, "api_base or base_url"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_request_timeout_bounds_and_secret_fields(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            write_minimal_config(target, "request_timeout_seconds: 0\n")
            with self.assertRaisesRegex(ValueError, "request_timeout_seconds"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            write_minimal_config(target, "request_timeout_seconds: 601\n")
            with self.assertRaisesRegex(ValueError, "request_timeout_seconds"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

            write_minimal_config(target, "api_key: REDACT_ME_TEST_VALUE\n")
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                resolve_config(target_root=target, target_repo="owner/target-repo")

    def test_model_env_missing_mentions_only_env_name(self) -> None:
        pairs = (("FORGIS_MODEL_API_KEY", "FORGIS_MODEL_API_KEY"),)
        with self.assertRaisesRegex(ValueError, "FORGIS_MODEL_API_KEY") as caught:
            require_model_env_values(pairs, {})
        self.assertNotIn("REDACT_ME_TEST_VALUE", str(caught.exception))

    def test_deepseek_client_from_config_uses_generic_secret_and_hides_repr(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            write_minimal_config(target, "request_timeout_seconds: 44\n")
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            client = DeepSeekClient.from_config(
                resolved,
                {"FORGIS_MODEL_API_KEY": "REDACT_ME_TEST_VALUE"},
            )
            self.assertEqual(client.api_key, "REDACT_ME_TEST_VALUE")
            self.assertEqual(client.timeout_seconds, 44)
            self.assertNotIn("REDACT_ME_TEST_VALUE", repr(client))

    def test_command_allowlist_is_not_widened_for_v7(self) -> None:
        for command in (["bash", "-lc", "echo hi"], ["sh", "-c", "echo hi"], ["git", "status"]):
            with self.subTest(command=command):
                with self.assertRaises(CommandRunnerError):
                    validate_command(command, profile="build_test")

    def test_validation_commands_remain_config_strings_not_build_command_arrays(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            target = Path(dirname)
            write_minimal_config(
                target,
                textwrap.dedent(
                    """\
                    validation_commands:
                      - "test -f result/output.txt"
                    """
                ),
            )
            resolved = resolve_config(target_root=target, target_repo="owner/target-repo")
            self.assertEqual(resolved.validation_commands, ("test -f result/output.txt",))
            self.assertEqual(resolved.build_command, ())

    def test_local_cli_help(self) -> None:
        result = self.run_cmd([sys.executable, "-m", "agent.cli", "help"])
        self.assertIn("Forgis local CLI", result.stdout)
        self.assertIn("run", result.stdout)

    def test_local_cli_run_dry_run_does_not_write_target_or_require_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source = root / "source"
            target = root / "target"
            runtime = root / "runtime"
            source.mkdir()
            target.mkdir()
            runtime.mkdir()
            (source / "input.txt").write_text("source\n", encoding="utf-8")
            write_minimal_config(
                target,
                textwrap.dedent(
                    """\
                    dry_run: true
                    run_agent: true
                    confirm_real_run: false
                    target_subdir: target-output
                    """
                ),
            )
            (target / "target-output").mkdir()
            env = {**os.environ, "GITHUB_WORKSPACE": str(runtime)}
            result = self.run_cmd(
                [
                    sys.executable,
                    "-m",
                    "agent.cli",
                    "run",
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--target-repo",
                    "owner/target-repo",
                    "--report-output-dir",
                    "reports",
                ],
                env=env,
            )
            self.assertIn('"executed": false', result.stdout)
            self.assertIn('"status": "skipped-dry-run"', result.stdout)
            self.assertEqual(list((target / "target-output").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
