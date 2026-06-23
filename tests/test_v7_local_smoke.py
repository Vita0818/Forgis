from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SECRET_SENTINEL = "REDACT_ME_LOCAL_SMOKE"


class V7LocalSmokeTests(unittest.TestCase):
    def run_cmd(self, args: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            args,
            cwd=REPO_ROOT,
            env=env,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"command failed with exit {result.returncode}: {' '.join(args)}\n{result.stdout}"
            )
        return result

    def test_smoke_creates_local_dry_run_without_api_call_or_target_write(self) -> None:
        with tempfile.TemporaryDirectory() as dirname:
            workdir = Path(dirname) / "smoke"
            env = {**os.environ, "FORGIS_MODEL_API_KEY": SECRET_SENTINEL}
            result = self.run_cmd(
                [sys.executable, "-m", "agent.cli", "smoke", "--workdir", str(workdir)],
                env=env,
            )
            self.assertIn("Smoke mode: dry-run; no API calls were made.", result.stdout)
            self.assertIn("Smoke status: skipped-dry-run", result.stdout)
            self.assertNotIn(SECRET_SENTINEL, result.stdout)
            self.assertTrue((workdir / "summary.md").is_file())
            self.assertTrue((workdir / "FORGIS_CONFIG.local.smoke.yml").is_file())
            self.assertEqual(list((workdir / "target" / "target-output").iterdir()), [])
            self.assertTrue((workdir / "runtime" / "reports").is_dir())


if __name__ == "__main__":
    unittest.main()
