#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import platform
import re
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
SECRET_PATH_WORDS = re.compile(
    r"(secret|token|credential|password|api[_-]?key|apikey|private-key|private_key|\.env|\.npmrc|\.pypirc|\.netrc)",
    re.IGNORECASE,
)


def safe_single_line(value: str, label: str) -> str:
    text = str(value if value is not None else "").strip()
    if not text:
        raise ValueError(f"{label} is required.")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ValueError(f"{label} must be a single-line value.")
    return text


def read_yaml_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).expanduser().resolve()
    if any(SECRET_PATH_WORDS.search(part) for part in config_path.parts):
        raise ValueError("Config path must not contain secret-like path segments.")
    if not config_path.is_file():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    try:
        import yaml  # type: ignore
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("PyYAML is required to read local Forgis configs.") from exc
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {config_path}")
    return dict(loaded)


def resolve_local_runtime_root(config_path: str | None = None) -> Path:
    workspace = os.environ.get("GITHUB_WORKSPACE", "").strip()
    if workspace:
        return Path(workspace).resolve()
    if config_path:
        return Path(config_path).expanduser().resolve().parent
    return Path.cwd().resolve()


def require_runtime_executable(env_name: str) -> Path:
    raw_value = os.environ.get(env_name, "").strip()
    if not raw_value:
        raise ValueError(
            f"{env_name} must name the absolute executable used by the Intatis Codex runtime cutover."
        )
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        raise ValueError(f"{env_name} must be an absolute path.")
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise ValueError(f"{env_name} does not identify a safe executable file: {resolved}")
    return resolved


def local_config_value(data: dict[str, Any], field: str) -> str:
    value = data.get(field)
    return str(value).strip() if value is not None else ""


def local_paths_from_args(args: argparse.Namespace) -> tuple[Path, Path, str, str]:
    config_data: dict[str, Any] = {}
    config_path = str(getattr(args, "config", "") or "").strip()
    if config_path:
        config_data = read_yaml_config(config_path)

    source_text = str(getattr(args, "source", "") or "").strip() or local_config_value(config_data, "local_source_path")
    target_text = str(getattr(args, "target", "") or "").strip() or local_config_value(config_data, "local_target_path")
    target_repo = str(getattr(args, "target_repo", "") or "").strip() or local_config_value(config_data, "local_target_repo")

    missing = [
        name
        for name, value in (
            ("source", source_text),
            ("target", target_text),
            ("target_repo", target_repo),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "Missing local run parameter(s): "
            + ", ".join(missing)
            + ". Provide CLI flags or generate a local config with `python -m agent.cli init`."
        )

    return Path(source_text).expanduser().resolve(), Path(target_text).expanduser().resolve(), target_repo, config_path


def yaml_string(value: str) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def path_is_inside(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    root_resolved = root.resolve()
    return resolved == root_resolved or resolved.is_relative_to(root_resolved)


def ensure_safe_init_output(output: Path, *, source: Path, target: Path) -> Path:
    resolved = output.expanduser().resolve()
    if any(SECRET_PATH_WORDS.search(part) for part in resolved.parts):
        raise ValueError("output path must not contain secret-like path segments.")
    if path_is_inside(resolved, source) or path_is_inside(resolved, target):
        raise ValueError("init output must be outside the source and target directories.")
    return resolved


def local_repo_slug(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", path.name.strip() or "source").strip(".-_")
    return f"local/{name or 'source'}"


def render_local_config(
    *,
    source: Path,
    target: Path,
    target_repo: str,
    target_subdir: str,
    agent_backend: str,
    model: str,
    api_base: str,
    api_key_env: str,
) -> str:
    source_repo = local_repo_slug(source)
    runtime_env = "FORGIS_MODEL_API_KEY"
    return "\n".join(
        [
            "# Forgis Intatis Codex runtime local migration config.",
            "# Secrets are supplied only through environment variable names below.",
            "# The production Agent kernel is Intatis Codex App Server; no legacy runtime fallback exists.",
            f"local_source_path: {yaml_string(source.as_posix())}",
            f"local_target_path: {yaml_string(target.as_posix())}",
            f"local_target_repo: {yaml_string(target_repo)}",
            "",
            f"source_repo: {yaml_string(source_repo)}",
            "source_ref: main",
            "target_branch: forgis/local-migration",
            "target_base_branch: main",
            f"target_subdir: {yaml_string(target_subdir)}",
            "task_prompt_path: FORGIS_TASK.md",
            "",
            f"agent_backend: {yaml_string(agent_backend)}",
            f"model: {yaml_string(model)}",
            f"api_base: {yaml_string(api_base)}",
            "api_format: responses",
            "request_adapter: openai-compatible",
            "request_timeout_seconds: 120",
            "model_env:",
            f"  {runtime_env}: {yaml_string(api_key_env)}",
            "",
            "execution_mode: codex",
            "dry_run: true",
            "run_agent: false",
            "confirm_real_run: false",
            "",
            "run_report_enabled: true",
            "run_report_output_dir: reports",
            "run_report_include_events: true",
            "run_report_max_events: 100",
            "run_report_max_chars: 200000",
            "",
            "migration_scheduler_enabled: true",
            "migration_unit_strategy: inventory",
            "max_migration_units: 50",
            "migration_plan_persistence_enabled: true",
            "migration_plan_output_dir: reports",
            "migration_plan_filename: FORGIS_MIGRATION_PLAN.json",
            "migration_plan_resume_enabled: true",
            "migration_plan_auto_update_enabled: true",
            "migration_plan_auto_complete_on_success: false",
            "migration_plan_audit_summary_enabled: true",
            "",
            "validation_commands: []",
            "success_checks: []",
            "",
            "visual_validation:",
            "  enabled: auto",
            "  provider: qwen",
            "  mode: reference_guidance",
            "  reference_screenshot_dirs: []",
            "  actual_screenshot_dirs: []",
            "  max_visual_iterations: 2",
            "  require_reference_first: true",
            "  require_actual_for_full_validation: false",
            "  upload_visual_artifact: false",
            "",
        ]
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


def resolve_local_config(args: argparse.Namespace) -> tuple[Path, Path, str, str, Any]:
    from forge import ensure_directory
    from forgis_config import resolve_config

    source, target, target_repo, config_path = local_paths_from_args(args)
    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")
    if config_path and Path(config_path).expanduser().resolve().is_relative_to(source):
        raise ValueError("Config path must not be inside the source repository.")
    config = resolve_config(target_root=target, target_repo=target_repo, config_path=config_path)
    return source, target, target_repo, config_path, config


def with_requested_unit(config: Any, unit_id: str) -> Any:
    unit = safe_single_line(unit_id, "unit")
    return dataclasses.replace(
        config,
        migration_scheduler_enabled=True,
        migration_plan_persistence_enabled=True,
        migration_plan_resume_enabled=True,
        migration_plan_requested_active_unit_id=unit,
        migration_plan_switch_requires_resume=False,
        migration_plan_switch_reason=f"Local CLI requested migration unit {unit}.",
    )


def inspect_migration_plan(
    *,
    config: Any,
    source: Path,
    target: Path,
    runtime_root: Path,
) -> dict[str, Any]:
    from migration_scheduler import select_next_unit

    plan, source_label, load_status, load_error, plan_path = load_or_generate_control_plane_plan(
        config=config,
        source=source,
        target=target,
        runtime_root=runtime_root,
    )

    counts = {"completed": 0, "blocked": 0, "pending": 0, "deferred": 0, "active": 0, "total": 0}
    active_unit = None
    next_unit = None
    units: list[dict[str, Any]] = []
    if plan is not None:
        counts = plan.counts()
        active_unit = plan.active_unit.as_summary() if plan.active_unit is not None else None
        selected_next = select_next_unit(plan)
        next_unit = selected_next.as_summary() if selected_next is not None else None
        units = [unit.as_summary() for unit in plan.units[: config.max_migration_units]]

    return {
        "plan_source": source_label,
        "plan_path": plan_path,
        "plan_load_status": load_status,
        "plan_load_error": load_error,
        "counts": counts,
        "active_unit": active_unit,
        "next_unit": next_unit,
        "units": units,
    }


def load_or_generate_control_plane_plan(
    *,
    config: Any,
    source: Path,
    target: Path,
    runtime_root: Path,
) -> tuple[Any, str, str, str, str]:
    from migration_plan_store import load_migration_plan, migration_plan_file_path
    from migration_scheduler import collect_scheduler_inventory, create_units_from_inventory

    plan = None
    source_label = "disabled"
    load_status = "disabled"
    load_error = ""
    plan_path = ""
    if config.migration_scheduler_enabled and config.migration_plan_persistence_enabled:
        try:
            path = migration_plan_file_path(
                config.migration_plan_output_dir,
                filename=config.migration_plan_filename,
                allowed_root=runtime_root,
                source_root=source,
                target_root=target,
            )
            plan_path = path.as_posix()
            load = load_migration_plan(
                path,
                allowed_root=runtime_root,
                source_root=source,
                target_root=target,
            )
            load_status = load.status
            load_error = load.error
            if load.status == "loaded":
                plan = load.plan
                source_label = "loaded"
        except Exception as exc:
            load_status = "failed"
            load_error = str(exc)

    if plan is None and config.migration_scheduler_enabled:
        task_path = (target / config.task_prompt_path).resolve()
        if not task_path.is_file() or not task_path.is_relative_to(target.resolve()):
            raise ValueError("Migration task prompt is unavailable for plan generation.")
        task_text = task_path.read_text(encoding="utf-8", errors="replace")[:1_000_000]
        inventory: list[Any] = []
        if config.migration_unit_strategy == "inventory":
            inventory = collect_scheduler_inventory(
                source,
                config.staged_translation.source_inventory,
                max_units=config.max_migration_units,
            )
        plan = create_units_from_inventory(inventory, config, task_text)
        source_label = "generated"
    return plan, source_label, load_status, load_error, plan_path


def validate_requested_unit(
    *,
    config: Any,
    source: Path,
    target: Path,
    runtime_root: Path,
    report_output_dir: str | Path | None,
    unit_id: str,
) -> None:
    from migration_state import request_active_unit_switch
    from migration_plan_store import write_migration_plan

    plan, _source_label, load_status, _load_error, _plan_path = load_or_generate_control_plane_plan(
        config=config,
        source=source,
        target=target,
        runtime_root=runtime_root,
    )
    if plan is None or not plan.units:
        raise ValueError("run --unit requires migration_scheduler_enabled=true and at least one migration unit.")
    unit_ids = {unit.unit_id for unit in plan.units}
    if unit_id not in unit_ids:
        raise ValueError(f"migration unit not found: {unit_id}")
    switch = request_active_unit_switch(
        plan,
        unit_id,
        config,
        config.migration_plan_switch_reason,
        resume_loaded=load_status == "loaded",
        max_events=config.migration_plan_event_log_max_events,
    )
    active = plan.active_unit
    if active is None or active.unit_id != unit_id:
        message = switch.message or "requested unit was not selected as active"
        raise ValueError(f"requested migration unit is not runnable as active: {message}")
    write = write_migration_plan(
        plan,
        config.migration_plan_output_dir,
        filename=config.migration_plan_filename,
        allowed_root=runtime_root,
        source_root=source,
        target_root=target,
        required=True,
        max_events=config.migration_plan_event_log_max_events,
    )
    if write.status != "written":
        raise RuntimeError("The selected migration unit could not be persisted before Codex handoff.")


def command_init(args: argparse.Namespace) -> int:
    from forge import ensure_directory
    from forgis_config import SUPPORTED_AGENT_BACKENDS, validate_env_name, resolve_target_subdir

    source = Path(args.source).expanduser().resolve()
    target = Path(args.target).expanduser().resolve()
    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")

    target_repo = safe_single_line(args.target_repo, "target_repo")
    agent_backend = safe_single_line(args.agent_backend, "agent_backend").casefold()
    if agent_backend not in SUPPORTED_AGENT_BACKENDS:
        raise ValueError("agent_backend must be codex-app-server.")
    api_key_env = validate_env_name(args.api_key_env, "api_key_env")
    target_subdir = resolve_target_subdir(target, args.target_subdir)[1]
    output = ensure_safe_init_output(Path(args.output), source=source, target=target)

    config_text = render_local_config(
        source=source,
        target=target,
        target_repo=target_repo,
        target_subdir=target_subdir,
        agent_backend=agent_backend,
        model=safe_single_line(args.model, "model"),
        api_base=safe_single_line(args.api_base, "api_base"),
        api_key_env=api_key_env,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(config_text, encoding="utf-8")

    print(
        json.dumps(
            {
                "status": "written",
                "config": output.as_posix(),
                "source": source.as_posix(),
                "target": target.as_posix(),
                "target_repo": target_repo,
                "target_subdir": target_subdir,
                "api_calls_made": False,
                "notes": [
                    "dry_run=true and run_agent=false by default",
                    "set API key values only through the configured env var",
                    "production Agent execution uses the Intatis Codex App Server kernel with no legacy fallback",
                ],
            },
            indent=2,
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def command_status(args: argparse.Namespace) -> int:
    from run_report import RUN_REPORT_MARKDOWN_FILENAME

    source, target, _target_repo, config_path, config = resolve_local_config(args)
    runtime_root = resolve_local_runtime_root(config_path)
    plan = inspect_migration_plan(config=config, source=source, target=target, runtime_root=runtime_root)
    report_path = (runtime_root / config.run_report_output_dir / RUN_REPORT_MARKDOWN_FILENAME).resolve()
    api_env = [
        {
            "runtime_env": runtime,
            "secret_env": secret,
            "status": "set" if os.environ.get(secret) else "unset",
        }
        for runtime, secret in config.model_env
    ]
    payload = {
        "source_path": source.as_posix(),
        "target_path": target.as_posix(),
        "target_repo": config.target_repo,
        "target_subdir": config.target_subdir,
        "agent_backend": config.agent_backend,
        "model": config.model,
        "api_base_configured": "api_base" in config.config_keys or "base_url" in config.config_keys,
        "api_key_env": api_env,
        "migration_units": {
            "total": int(plan["counts"].get("total") or 0),
            "completed": int(plan["counts"].get("completed") or 0),
            "pending": int(plan["counts"].get("pending") or 0),
            "failed": int(plan["counts"].get("blocked") or 0),
            "blocked": int(plan["counts"].get("blocked") or 0),
            "deferred": int(plan["counts"].get("deferred") or 0),
            "active": int(plan["counts"].get("active") or 0),
        },
        "active_unit": plan["active_unit"],
        "next_unit": plan["next_unit"],
        "migration_plan_source": plan["plan_source"],
        "migration_plan_path": plan["plan_path"],
        "migration_plan_load_status": plan["plan_load_status"],
        "last_report_path": report_path.as_posix() if report_path.is_file() else "",
        "api_calls_made": False,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_resume(args: argparse.Namespace) -> int:
    source, target, _target_repo, config_path, config = resolve_local_config(args)
    runtime_root = resolve_local_runtime_root(config_path)
    plan = inspect_migration_plan(config=config, source=source, target=target, runtime_root=runtime_root)
    units = list(plan["units"])
    active_units = [unit for unit in units if unit.get("status") == "active"]
    failed_units = [unit for unit in units if unit.get("status") == "blocked"]
    pending_units = [unit for unit in units if unit.get("status") == "pending"]

    selected = None
    status = "no-recoverable-task"
    next_action = "No recoverable migration unit is available."
    if failed_units and not args.skip_failed:
        selected = failed_units[0]
        status = "blocked-needs-explicit-decision"
        next_action = "A failed/blocked unit exists; rerun it explicitly with run --unit or pass resume --skip-failed to inspect pending work."
    elif active_units:
        selected = active_units[0]
        status = "active-unit-ready"
        next_action = "Run the current active unit."
    elif pending_units:
        selected = pending_units[0]
        status = "pending-unit-ready"
        next_action = "Run the next pending unit."
    elif failed_units and args.skip_failed:
        status = "no-pending-after-skipping-failed"
        next_action = "Only failed/blocked units remain after --skip-failed; choose one explicitly with run --unit."
    elif units and all(unit.get("status") == "completed" for unit in units):
        status = "complete"
        next_action = "All migration units are completed."

    run_command = ""
    if selected:
        run_command = f"python -m agent.cli run --config {config_path} --unit {selected.get('unit_id')}"
    payload = {
        "status": status,
        "plan_source": plan["plan_source"],
        "plan_load_status": plan["plan_load_status"],
        "migration_units": {
            "total": int(plan["counts"].get("total") or 0),
            "completed": int(plan["counts"].get("completed") or 0),
            "pending": int(plan["counts"].get("pending") or 0),
            "failed": int(plan["counts"].get("blocked") or 0),
            "active": int(plan["counts"].get("active") or 0),
        },
        "selected_unit": selected,
        "next_action": next_action,
        "next_run_command": run_command,
        "api_calls_made": False,
        "shell_called": False,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def command_run(args: argparse.Namespace) -> int:
    from forge import build_summary, ensure_directory
    from forgis_config import resolve_config

    source, target, target_repo, config_path = local_paths_from_args(args)
    ensure_directory(source, "Source repository")
    ensure_directory(target, "Target repository")
    config = resolve_config(target_root=target, target_repo=target_repo, config_path=config_path)
    if args.dry_run:
        config = force_dry_run_config(config)
    unit_id = str(getattr(args, "unit", "") or "").strip()
    if unit_id:
        config = with_requested_unit(config, unit_id)

    summary = build_summary(source=source, target=target, config=config)
    if args.summary_output:
        summary_output = Path(args.summary_output).resolve()
        summary_output.parent.mkdir(parents=True, exist_ok=True)
        summary_output.write_text(summary, encoding="utf-8")

    report_allowed_root = resolve_local_runtime_root(config_path)
    report_output_dir = args.report_output_dir or config.run_report_output_dir
    if unit_id:
        validate_requested_unit(
            config=config,
            source=source,
            target=target,
            runtime_root=report_allowed_root,
            report_output_dir=report_output_dir,
            unit_id=unit_id,
        )
    runtime_executable = require_runtime_executable("FORGIS_RUNTIME_EXECUTABLE")
    codex_runtime = require_runtime_executable("FORGIS_CODEX_RUNTIME")
    runtime_root = (report_allowed_root / ".forgis-runtime").resolve()
    report_output = (runtime_root / report_output_dir).resolve()
    status_output = Path(args.status_output).expanduser().resolve() if args.status_output else runtime_root / "codex_status.env"
    operation_output = (
        Path(args.operation_log_output).expanduser().resolve()
        if args.operation_log_output
        else runtime_root / "codex_tool_operations.json"
    )
    runtime_summary_output = (
        Path(args.runtime_summary_output).expanduser().resolve()
        if args.runtime_summary_output
        else runtime_root / "codex_runtime_summary.json"
    )

    command = [
        str(runtime_executable),
        "run",
        "--source", str(source),
        "--target", str(target),
        "--target-subdir", config.target_subdir,
        "--task-prompt", config.task_prompt_path,
        "--target-repo", target_repo,
        "--api-base", config.api_base,
        "--model", config.model,
        "--model-env-json", json.dumps(dict(config.model_env), ensure_ascii=False, sort_keys=True),
        "--runtime-root", str(runtime_root),
        "--output-root", str(report_allowed_root),
        "--codex-runtime", str(codex_runtime),
        "--dry-run", "true" if config.dry_run else "false",
        "--run-agent", "true" if config.run_agent else "false",
        "--confirm-real-run", "true" if config.confirm_real_run else "false",
        "--request-adapter", config.request_adapter,
        "--status-output", str(status_output),
        "--summary-output", str(runtime_summary_output),
        "--operation-log-output", str(operation_output),
        "--report-output-dir", str(report_output),
        "--visual-validation-enabled", config.visual_validation.enabled,
    ]
    if unit_id:
        command.extend(["--unit", unit_id])
    if not sys.stdin.isatty():
        command.append("--non-interactive")

    # Replace this Python control-plane process with the single authoritative
    # Swift/Intatis kernel. There is deliberately no return path or legacy
    # runtime fallback after execve succeeds.
    os.execve(str(runtime_executable), command, dict(os.environ))
    raise AssertionError("os.execve returned unexpectedly")


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

    for module_name in (
        "forgis_config",
        "guardrails",
        "migration_plan_store",
        "migration_scheduler",
    ):
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

agent_backend: codex-app-server
model: local-smoke-model
api_base: https://example.invalid/v1
api_format: responses
request_timeout_seconds: 5
model_env:
  FORGIS_MODEL_API_KEY: FORGIS_MODEL_API_KEY

execution_mode: codex
dry_run: true
run_agent: true
confirm_real_run: false

run_report_enabled: true
run_report_output_dir: reports
migration_plan_persistence_enabled: false
""",
    )

    previous_workspace = os.environ.get("GITHUB_WORKSPACE")
    os.environ["GITHUB_WORKSPACE"] = str(workdir)
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
            runtime_summary_output=str(workdir / "codex_runtime_summary.json"),
            report_output_dir="reports",
            print_result=False,
            unit="",
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

    init = subparsers.add_parser("init", help="Create a local Codex runtime config without calling an API")
    init.add_argument("--source", required=True, help="Path to the local source repository")
    init.add_argument("--target", required=True, help="Path to the local target repository")
    init.add_argument("--target-repo", required=True, help="Target repository label, for example local/my-migration")
    init.add_argument("--output", required=True, help="Explicit output path for FORGIS_CONFIG.local.yml")
    init.add_argument("--target-subdir", default="target-output", help="Writable target subdirectory")
    init.add_argument("--agent-backend", default="codex-app-server", help="Fixed production kernel: codex-app-server")
    init.add_argument("--model", default="forgis-migration-model", help="Native Responses model id")
    init.add_argument("--api-base", default="https://example.invalid/v1", help="Native Responses API base URL")
    init.add_argument("--api-key-env", default="FORGIS_MODEL_API_KEY", help="Environment variable name that will hold the API key")
    init.set_defaults(func=command_init)

    status = subparsers.add_parser("status", help="Show local migration config and migration unit status")
    status.add_argument("--config", required=True, help="Path to FORGIS_CONFIG.local.yml")
    status.set_defaults(func=command_status)

    run = subparsers.add_parser("run", help="Replace this process with the gated Intatis Codex runtime")
    run.add_argument("--source", default="", help="Path to the checked-out source repository; optional when config has local_source_path")
    run.add_argument("--target", default="", help="Path to the checked-out target repository; optional when config has local_target_path")
    run.add_argument("--target-repo", default="", help="Target repository label; optional when config has local_target_repo")
    run.add_argument("--config", default="", help="Optional config file path; defaults to target/FORGIS_CONFIG.yml")
    run.add_argument("--unit", default="", help="Explicit migration unit id to run")
    run.add_argument("--dry-run", action="store_true", help="Force a local dry-run without model calls or target writes")
    run.add_argument("--summary-output", default="", help="Optional controller summary markdown output path")
    run.add_argument("--status-output", default="", help="Optional env-style status output path")
    run.add_argument("--operation-log-output", default="", help="Optional JSON operation log output path")
    run.add_argument(
        "--runtime-summary-output",
        "--tool-loop-summary-output",
        dest="runtime_summary_output",
        default="",
        help="Optional Codex runtime JSON summary output path",
    )
    run.add_argument("--report-output-dir", default="", help="Optional Forgis runtime report output directory")
    run.set_defaults(func=command_run)

    resume = subparsers.add_parser("resume", help="Inspect resumable local migration state without running a model")
    resume.add_argument("--config", required=True, help="Path to FORGIS_CONFIG.local.yml")
    resume.add_argument("--skip-failed", action="store_true", help="Do not select blocked units as the next resumable unit")
    resume.set_defaults(func=command_resume)

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
