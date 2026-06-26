from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_SENTINEL = "REDACT_ME_V7_LOCAL_INIT_STATUS"


class V71LocalInitStatusTests(unittest.TestCase):
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

    def make_local_repos(self, root: Path) -> tuple[Path, Path]:
        source = root / "source"
        target = root / "target"
        (source / "Views").mkdir(parents=True)
        (target / "target-output").mkdir(parents=True)
        (source / "Views" / "GreetingView.swift").write_text('Text("Hello")\n', encoding="utf-8")
        (target / "FORGIS_TASK.md").write_text(
            "# Task\n\nMigrate `source/Views/GreetingView.swift`.\n",
            encoding="utf-8",
        )
        return source, target

    def test_init_generates_minimal_config_without_writing_source_or_target(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_local_repos(root)
            before_source = sorted(path.relative_to(source).as_posix() for path in source.rglob("*"))
            before_target = sorted(path.relative_to(target).as_posix() for path in target.rglob("*"))
            config = root / "FORGIS_CONFIG.local.yml"

            result = self.run_cmd(
                [
                    sys.executable,
                    "-m",
                    "agent.cli",
                    "init",
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--target-repo",
                    "local/my-migration",
                    "--output",
                    str(config),
                ]
            )
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "written")
            self.assertTrue(config.is_file())
            text = config.read_text(encoding="utf-8")
            self.assertIn("local_source_path:", text)
            self.assertIn("local_target_path:", text)
            self.assertIn("local_target_repo:", text)
            self.assertIn("target_subdir:", text)
            self.assertIn("dry_run: true", text)
            self.assertIn("run_agent: false", text)
            self.assertIn("confirm_real_run: false", text)
            self.assertIn("FORGIS_MODEL_API_KEY", text)
            self.assertNotIn(SECRET_SENTINEL, text)
            self.assertEqual(before_source, sorted(path.relative_to(source).as_posix() for path in source.rglob("*")))
            self.assertEqual(before_target, sorted(path.relative_to(target).as_posix() for path in target.rglob("*")))

    def test_init_rejects_output_inside_source_or_target(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_local_repos(root)
            result = self.run_cmd(
                [
                    sys.executable,
                    "-m",
                    "agent.cli",
                    "init",
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--target-repo",
                    "local/my-migration",
                    "--output",
                    str(target / "FORGIS_CONFIG.local.yml"),
                ],
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the source and target", result.stdout)

    def test_status_reads_local_config_and_does_not_leak_secret(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target = self.make_local_repos(root)
            config = root / "FORGIS_CONFIG.local.yml"
            self.run_cmd(
                [
                    sys.executable,
                    "-m",
                    "agent.cli",
                    "init",
                    "--source",
                    str(source),
                    "--target",
                    str(target),
                    "--target-repo",
                    "local/my-migration",
                    "--output",
                    str(config),
                ]
            )
            env = {**os.environ, "FORGIS_MODEL_API_KEY": SECRET_SENTINEL}
            result = self.run_cmd(
                [sys.executable, "-m", "agent.cli", "status", "--config", str(config)],
                env=env,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(Path(payload["source_path"]).resolve(), source.resolve())
            self.assertEqual(Path(payload["target_path"]).resolve(), target.resolve())
            self.assertEqual(payload["target_subdir"], "target-output")
            self.assertEqual(payload["agent_backend"], "openai-compatible")
            self.assertTrue(payload["api_base_configured"])
            self.assertEqual(payload["api_key_env"][0]["secret_env"], "FORGIS_MODEL_API_KEY")
            self.assertEqual(payload["api_key_env"][0]["status"], "set")
            self.assertGreaterEqual(payload["migration_units"]["total"], 1)
            self.assertFalse(payload["api_calls_made"])
            self.assertNotIn(SECRET_SENTINEL, result.stdout)


if __name__ == "__main__":
    unittest.main()
