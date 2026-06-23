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

from deepseek_agent import DeepSeekClient
from forgis_config import resolve_config
from model_env import require_model_env_values


SECRET_SENTINEL = "REDACT_ME_LOCAL_CLI"


def write_local_fixture(root: Path, *, backend: str = "openai-compatible") -> tuple[Path, Path, Path]:
    source = root / "source"
    target = root / "target"
    source.mkdir(parents=True, exist_ok=True)
    (target / "target-output").mkdir(parents=True, exist_ok=True)
    (source / "input.txt").write_text("source\n", encoding="utf-8")
    (target / "FORGIS_TASK.md").write_text("# Task\n", encoding="utf-8")
    config = root / "FORGIS_CONFIG.local.yml"
    config.write_text(
        textwrap.dedent(
            f"""\
            source_repo: local/source
            source_ref: main
            target_branch: forgis/local
            target_base_branch: main
            target_subdir: target-output
            task_prompt_path: FORGIS_TASK.md

            agent_backend: {backend}
            model: local-model
            api_base: https://example.invalid/v1
            api_format: openai-compatible
            request_timeout_seconds: 9
            model_env:
              api_key: FORGIS_MODEL_API_KEY

            execution_mode: tool_loop
            dry_run: true
            run_agent: true
            confirm_real_run: false
            run_report_enabled: true
            run_report_output_dir: reports
            migration_plan_persistence_enabled: false
            """
        ),
        encoding="utf-8",
    )
    return source, target, config


class V7LocalCliTests(unittest.TestCase):
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

    def test_help_and_doctor_do_not_require_secret_or_leak_env_value(self) -> None:
        env = {**os.environ, "FORGIS_MODEL_API_KEY": SECRET_SENTINEL}
        help_result = self.run_cmd([sys.executable, "-m", "agent.cli", "help"], env=env)
        self.assertIn("doctor", help_result.stdout)
        self.assertIn("smoke", help_result.stdout)
        self.assertNotIn(SECRET_SENTINEL, help_result.stdout)

        doctor = self.run_cmd([sys.executable, "-m", "agent.cli", "doctor"], env=env)
        self.assertIn("Forgis local doctor", doctor.stdout)
        self.assertIn("FORGIS_MODEL_API_KEY: set", doctor.stdout)
        self.assertIn("No API calls were made.", doctor.stdout)
        self.assertNotIn(SECRET_SENTINEL, doctor.stdout)

    def test_run_config_reads_external_config_and_writes_summary_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target, config = write_local_fixture(root)
            summary = root / "summary.md"
            runtime = root / "runtime"
            env = {key: value for key, value in os.environ.items() if key != "FORGIS_MODEL_API_KEY"}
            env["GITHUB_WORKSPACE"] = str(runtime)
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
                    "local/target",
                    "--config",
                    str(config),
                    "--summary-output",
                    str(summary),
                    "--dry-run",
                    "--report-output-dir",
                    "reports",
                ],
                env=env,
            )
            self.assertIn('"executed": false', result.stdout)
            self.assertIn('"status": "skipped-dry-run"', result.stdout)
            self.assertTrue(summary.is_file())
            self.assertIn("Request timeout seconds: 9", summary.read_text(encoding="utf-8"))
            self.assertEqual(list((target / "target-output").iterdir()), [])
            self.assertNotIn(SECRET_SENTINEL, result.stdout + summary.read_text(encoding="utf-8"))

    def test_missing_model_env_reports_env_name_only(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            _source, target, config = write_local_fixture(root)
            resolved = resolve_config(target_root=target, target_repo="local/target", config_path=str(config))
            with self.assertRaisesRegex(ValueError, "FORGIS_MODEL_API_KEY") as caught:
                require_model_env_values(resolved.model_env, {})
            self.assertNotIn(SECRET_SENTINEL, str(caught.exception))

    def test_external_config_examples_parse_for_local_runs(self) -> None:
        for example in (
            REPO_ROOT / "examples" / "FORGIS_CONFIG.local.openai-compatible.yml",
            REPO_ROOT / "examples" / "FORGIS_CONFIG.local.smoke.yml",
        ):
            with self.subTest(example=example.name), tempfile.TemporaryDirectory() as dirname:
                target = Path(dirname) / "target"
                (target / "target-output").mkdir(parents=True)
                (target / "FORGIS_TASK.md").write_text("# Task\n", encoding="utf-8")
                resolved = resolve_config(target_root=target, target_repo="local/target", config_path=str(example))
                self.assertIn(resolved.agent_backend, {"deepseek", "openai-compatible"})
                self.assertEqual(resolved.api_format, "openai-compatible")

    def test_deepseek_backend_still_uses_local_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            _source, target, config = write_local_fixture(root, backend="deepseek")
            resolved = resolve_config(target_root=target, target_repo="local/target", config_path=str(config))
            client = DeepSeekClient.from_config(resolved, {"FORGIS_MODEL_API_KEY": SECRET_SENTINEL})
            self.assertEqual(client.model, "local-model")
            self.assertNotIn(SECRET_SENTINEL, repr(client))


if __name__ == "__main__":
    unittest.main()
