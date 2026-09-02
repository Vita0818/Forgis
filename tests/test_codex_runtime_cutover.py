from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INTATIS_PIN = "e8ba63554daa57455193772c6ba0abe08f04c0a0"


class CodexRuntimeCutoverTests(unittest.TestCase):
    def test_swift_package_exports_single_codex_runtime_cli(self) -> None:
        manifest = (REPO_ROOT / "Package.swift").read_text(encoding="utf-8")
        self.assertIn('.executable(name: "forgis-runtime"', manifest)
        self.assertIn('.product(name: "IntatisCodexRuntime"', manifest)
        self.assertIn('.product(name: "IntatisProtocol"', manifest)
        self.assertIn('.product(name: "IntatisProviders"', manifest)

    def test_workflows_use_exact_intatis_kernel_without_python_agent_loop(self) -> None:
        migration = (REPO_ROOT / ".github/workflows/migrate.yml").read_text(
            encoding="utf-8"
        )
        validation = (
            REPO_ROOT / ".github/workflows/validate-forgis.yml"
        ).read_text(encoding="utf-8")
        for workflow in (migration, validation):
            self.assertIn("runs-on: xcode-27", workflow)
            self.assertIn(INTATIS_PIN, workflow)
            self.assertIn("forgis-runtime", workflow)
        self.assertIn("Run Intatis Codex kernel", migration)
        self.assertNotIn("python forgis/agent/tool_loop.py", migration)
        self.assertNotIn("ubuntu-latest", migration)

    def test_python_runtime_production_path_is_explicitly_retired(self) -> None:
        source = (REPO_ROOT / "agent/tool_loop.py").read_text(encoding="utf-8")
        self.assertIn("Python AgentLoop production path is retired", source)
        self.assertIn("if client_factory is None", source)
        cli = (REPO_ROOT / "agent/cli.py").read_text(encoding="utf-8")
        self.assertIn("os.execve", cli)
        self.assertIn("no return path or legacy", cli)

    def test_exact_runtime_doctor_and_offline_session_smoke(self) -> None:
        host = os.environ.get("FORGIS_RUNTIME_EXECUTABLE", "")
        runtime = os.environ.get("FORGIS_CODEX_RUNTIME", "")
        self.assertTrue(host, "FORGIS_RUNTIME_EXECUTABLE is required")
        self.assertTrue(runtime, "FORGIS_CODEX_RUNTIME is required")

        doctor = subprocess.run(
            [host, "doctor", "--codex-runtime", runtime],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stdout)
        self.assertIn('"runtime_version" : "0.145.0-intatis.4"', doctor.stdout)
        self.assertIn('"host_api_major_version" : 1', doctor.stdout)

        smoke = subprocess.run(
            [host, "smoke", "--codex-runtime", runtime],
            cwd=REPO_ROOT,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self.assertEqual(smoke.returncode, 0, smoke.stdout)
        self.assertIn('"network_requests" : 0', smoke.stdout)
        self.assertIn('"runtime_version" : "0.145.0-intatis.4"', smoke.stdout)


if __name__ == "__main__":
    unittest.main()
