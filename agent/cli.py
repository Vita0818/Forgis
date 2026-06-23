#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Any


AGENT_DIR = Path(__file__).resolve().parent
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))


API_ENV_CANDIDATES = (
    "FORGIS_MODEL_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "QWEN_API_KEY",
)


def write_json(path: str, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def force_dry_run_config(config: Any) -> Any:
    return dataclasses.replace(
        config,
        dry_run=True,
        confirm_real_run=False,
        real_run_allowed=False,
        run_agent=False,
    )


def command_run(args: argparse.Namespace) -> int:
    from forge import build_summary, ensure_directory
    from forgis_config import resolve_config
    from tool_loop import STAGED_TRANSLATION_MODE, run_tool_loop, safe_log, write_status

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")
    config = resolve_config(target_root=target, target_repo=args.target_repo, config_path=args.config)
    if args.dry_run:
        config = force_dry_run_config(config)

    summary = build_summary(source=source, target=target, config=config)
    if args.summary_output:
        summary_output = Path(args.summary_output).resolve()
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(summary, encoding="utf-8")

    report_allowed_root = Path(os.environ.get("GITHUB_WORKSPACE", "") or Path.cwd()).resolve()
    report_output_dir = args.report_output_dir or config.run_report_output_dir
    result = run_tool_loop(
        config=config,
        source_root=source,
        target_root=target,
        environ=dict(os.environ),
        report_output_dir=report_output_dir,
        report_allowed_root=report_allowed_root,
        run_metadata={"target_repo": args.target_repo, "mode": "local_cli"},
    )
    write_status(args.status_output, result)
    write_json(args.operation_log_output, result.operation_log)
    write_json(args.tool_loop_summary_output, result.as_dict())
    setattr(args, "result_status", result.status)
    if getattr(args, "print_result", True):
        print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False, sort_keys=True))

    if result.status == "low-impact":
        raise RuntimeError(result.final_summary)
    if result.status == "max-iterations" and (
        config.execution_mode != STAGED_TRANSLATION_MODE or config.strict_mode
    ):
        raise RuntimeError(result.final_summary)
    if result.status == "max-iterations":
        safe_log("WARNING: staged_translation reached max_iterations; continuing with partial progress.")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("python", sys.version_info >= (3, 11), platform.python_version()))
    checks.append(("cwd", True, str(Path.cwd())))
    checks.append(("module_dir", AGENT_DIR.is_dir(), str(AGENT_DIR)))

    try:
        import yaml  # type: ignore

        checks.append(("pyyaml", True, getattr(yaml, "__version__", "installed")))
    except Exception as exc:
        checks.append(("pyyaml", False, exc.__class__.__name__))

    for module_name in ("openai_compatible_client", "forgis_config", "deepseek_agent", "tool_loop"):
        try:
            __import__(module_name)
            checks.append((f"import:{module_name}", True, "ok"))
        except Exception as exc:
            missing = getattr(exc, "name", "")
            detail = f"{exc.__class__.__name__}:{missing}" if missing else exc.__class__.__name__
            checks.append((f"import:{module_name}", False, detail))

    help_text = build_parser().format_help()
    checks.append(("cli_help", "run" in help_text and "doctor" in help_text, "ok"))

    print("Forgis local doctor")
    for name, ok, detail in checks:
        status = "ok" if ok else "fail"
        print(f"- {name}: {status} ({detail})")
    print("- api env:")
    for name in API_ENV_CANDIDATES:
        print(f"  - {name}: {'set' if os.environ.get(name) else 'unset'}")
    print("No API calls were made.")

    if args.strict and any(not ok for _name, ok, _detail in checks):
        return 1
    return 0


def write_smoke_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def command_smoke(args: argparse.Namespace) -> int:
    workdir = Path(args.workdir).resolve() if args.workdir else Path(tempfile.mkdtemp(prefix="forgis-smoke-")).resolve()
    source = workdir / "source"
    target = workdir / "target"
    runtime = workdir / "runtime"
    source.mkdir(parents=True, exist_ok=True)
    (target / "target-output").mkdir(parents=True, exist_ok=True)
    runtime.mkdir(parents=True, exist_ok=True)

    write_smoke_file(source / "README.md", "# Smoke Source\n")
    write_smoke_file(
        target / "FORGIS_TASK.md",
        "# Local Smoke\n\nVerify Forgis local CLI dry-run wiring without calling a model.\n",
    )
    config_path = workdir / "FORGIS_CONFIG.local.smoke.yml"
    write_smoke_file(
        config_path,
        """source_repo: local/smoke-source
source_ref: main
target_branch: forgis/local-smoke
target_base_branch: main
target_subdir: target-output
task_prompt_path: FORGIS_TASK.md

agent_backend: openai-compatible
model: local-smoke-model
api_base: https://example.invalid/v1
api_format: openai-compatible
request_timeout_seconds: 5
model_env:
  FORGIS_MODEL_API_KEY: FORGIS_MODEL_API_KEY

execution_mode: tool_loop
dry_run: true
run_agent: true
confirm_real_run: false

run_report_enabled: true
run_report_output_dir: reports
migration_plan_persistence_enabled: false
""",
    )

    previous_workspace = os.environ.get("GITHUB_WORKSPACE")
    os.environ["GITHUB_WORKSPACE"] = str(runtime)
    try:
        run_args = argparse.Namespace(
            source=str(source),
            target=str(target),
            target_repo="local/forgis-smoke",
            config=str(config_path),
            dry_run=True,
            summary_output=str(workdir / "summary.md"),
            status_output="",
            operation_log_output=str(workdir / "tool_operations.json"),
            tool_loop_summary_output=str(workdir / "tool_loop_summary.json"),
            report_output_dir="reports",
            print_result=False,
        )
        status = command_run(run_args)
    finally:
        if previous_workspace is None:
            os.environ.pop("GITHUB_WORKSPACE", None)
        else:
            os.environ["GITHUB_WORKSPACE"] = previous_workspace

    print(f"Smoke workdir: {workdir}")
    print(f"Smoke summary: {workdir / 'summary.md'}")
    print(f"Smoke status: {getattr(run_args, 'result_status', status)}")
    print("Smoke mode: dry-run; no API calls were made.")
    return status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m agent.cli",
        description="Forgis local CLI for safe code migration runs.",
    )
    subparsers = parser.add_subparsers(dest="command")

    run = subparsers.add_parser("run", help="Run Forgis controller checks and the gated tool loop")
    run.add_argument("--source", required=True, help="Path to the checked-out source repository")
    run.add_argument("--target", required=True, help="Path to the checked-out target repository")
    run.add_argument("--target-repo", required=True, help="Target repository, for example owner/target-repo")
    run.add_argument("--config", default="", help="Optional config file path; defaults to target/FORGIS_CONFIG.yml")
    run.add_argument("--dry-run", action="store_true", help="Force a local dry-run without model calls or target writes")
    run.add_argument("--summary-output", default="", help="Optional controller summary markdown output path")
    run.add_argument("--status-output", default="", help="Optional env-style status output path")
    run.add_argument("--operation-log-output", default="", help="Optional JSON operation log output path")
    run.add_argument("--tool-loop-summary-output", default="", help="Optional JSON tool loop summary output path")
    run.add_argument("--report-output-dir", default="", help="Optional Forgis runtime report output directory")
    run.set_defaults(func=command_run)

    subparsers.add_parser("help", help="Show this help")
    doctor = subparsers.add_parser("doctor", help="Check local Forgis runtime prerequisites without side effects")
    doctor.add_argument("--strict", action="store_true", help="Exit non-zero when any diagnostic check fails")
    doctor.set_defaults(func=command_doctor)

    smoke = subparsers.add_parser("smoke", help="Run a local dry-run smoke test in a temporary workdir")
    smoke.add_argument("--workdir", default="", help="Optional smoke workdir; defaults to a system temp directory")
    smoke.set_defaults(func=command_smoke)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in {None, "help"}:
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
