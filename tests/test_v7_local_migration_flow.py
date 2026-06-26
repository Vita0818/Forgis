from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from migration_plan_store import write_migration_plan
from migration_units import MigrationPlan, MigrationUnit


SECRET_SENTINEL = "REDACT_ME_V7_LOCAL_FLOW"


class V71LocalMigrationFlowTests(unittest.TestCase):
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

    def copy_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        fixture = REPO_ROOT / "examples" / "local_migration_fixture"
        source = root / "source"
        target = root / "target"
        shutil.copytree(fixture / "source", source)
        shutil.copytree(fixture / "target", target)
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
                "local/fixture",
                "--output",
                str(config),
            ]
        )
        return source, target, config

    def status_payload(self, config: Path, *, env: dict[str, str] | None = None) -> dict[str, object]:
        result = self.run_cmd([sys.executable, "-m", "agent.cli", "status", "--config", str(config)], env=env)
        return json.loads(result.stdout)

    def test_run_unit_dry_run_selects_only_requested_unit_without_target_write_or_api(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            _source, target, config = self.copy_fixture(root)
            status = self.status_payload(config)
            unit_id = status["next_unit"]["unit_id"]  # type: ignore[index]
            original_target = (target / "target-output" / "Greeting.kt").read_text(encoding="utf-8")
            summary = root / "summary.md"
            tool_summary = root / "tool_loop_summary.json"
            env = {
                key: value
                for key, value in os.environ.items()
                if key not in {"GITHUB_ENV", "GITHUB_OUTPUT", "GITHUB_WORKSPACE", "FORGIS_MODEL_API_KEY"}
            }
            env["FORGIS_MODEL_API_KEY"] = SECRET_SENTINEL

            result = self.run_cmd(
                [
                    sys.executable,
                    "-m",
                    "agent.cli",
                    "run",
                    "--config",
                    str(config),
                    "--unit",
                    str(unit_id),
                    "--summary-output",
                    str(summary),
                    "--tool-loop-summary-output",
                    str(tool_summary),
                ],
                env=env,
            )
            self.assertIn('"status": "skipped-dry-run"', result.stdout)
            self.assertTrue(summary.is_file())
            self.assertLess(summary.stat().st_size, 20_000)
            self.assertNotIn(SECRET_SENTINEL, result.stdout + summary.read_text(encoding="utf-8"))
            self.assertEqual(original_target, (target / "target-output" / "Greeting.kt").read_text(encoding="utf-8"))
            payload = json.loads(tool_summary.read_text(encoding="utf-8"))
            self.assertEqual(payload["active_unit_id"], unit_id)
            self.assertEqual(payload["migration_plan_active_unit_status"], "active")
            self.assertFalse(payload["executed"])

    def test_resume_reports_active_unit_and_does_not_call_shell(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            _source, _target, config = self.copy_fixture(root)
            unit_id = self.status_payload(config)["next_unit"]["unit_id"]  # type: ignore[index]
            self.run_cmd([sys.executable, "-m", "agent.cli", "run", "--config", str(config), "--unit", str(unit_id)])

            result = self.run_cmd([sys.executable, "-m", "agent.cli", "resume", "--config", str(config)])
            payload = json.loads(result.stdout)
            self.assertEqual(payload["status"], "active-unit-ready")
            self.assertEqual(payload["selected_unit"]["unit_id"], unit_id)
            self.assertIn("--unit", payload["next_run_command"])
            self.assertFalse(payload["api_calls_made"])
            self.assertFalse(payload["shell_called"])

    def test_resume_does_not_skip_failed_unit_without_explicit_flag(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target, config = self.copy_fixture(root)
            plan = MigrationPlan(
                units=[
                    MigrationUnit(unit_id="blocked-unit", title="Blocked", status="blocked", reason="verification failed"),
                    MigrationUnit(unit_id="pending-unit", title="Pending", status="pending", reason="waiting"),
                ],
                active_unit_id="blocked-unit",
            )
            write = write_migration_plan(
                plan,
                "reports",
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(write.status, "written")

            blocked = json.loads(
                self.run_cmd([sys.executable, "-m", "agent.cli", "resume", "--config", str(config)]).stdout
            )
            self.assertEqual(blocked["status"], "blocked-needs-explicit-decision")
            self.assertEqual(blocked["selected_unit"]["unit_id"], "blocked-unit")

            skipped = json.loads(
                self.run_cmd(
                    [sys.executable, "-m", "agent.cli", "resume", "--config", str(config), "--skip-failed"]
                ).stdout
            )
            self.assertEqual(skipped["status"], "pending-unit-ready")
            self.assertEqual(skipped["selected_unit"]["unit_id"], "pending-unit")

    def test_resume_no_recoverable_task_is_clear(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            source, target, config = self.copy_fixture(root)
            plan = MigrationPlan(
                units=[
                    MigrationUnit(unit_id="done-unit", title="Done", status="completed", reason="complete"),
                ],
                active_unit_id="done-unit",
            )
            write = write_migration_plan(
                plan,
                "reports",
                allowed_root=root,
                source_root=source,
                target_root=target,
            )
            self.assertEqual(write.status, "written")
            payload = json.loads(
                self.run_cmd([sys.executable, "-m", "agent.cli", "resume", "--config", str(config)]).stdout
            )
            self.assertEqual(payload["status"], "complete")
            self.assertEqual(payload["next_action"], "All migration units are completed.")
            self.assertEqual(payload["next_run_command"], "")

    def test_examples_fixture_can_drive_local_smoke_flow(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            root = Path(dirname)
            _source, _target, config = self.copy_fixture(root)
            status = self.status_payload(config)
            self.assertGreaterEqual(status["migration_units"]["total"], 1)  # type: ignore[index]
            unit_id = status["next_unit"]["unit_id"]  # type: ignore[index]
            result = self.run_cmd(
                [sys.executable, "-m", "agent.cli", "run", "--config", str(config), "--unit", str(unit_id)]
            )
            self.assertIn("dry_run=true; model was not called", result.stdout)


if __name__ == "__main__":
    unittest.main()
