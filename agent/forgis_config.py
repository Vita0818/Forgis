from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "FORGIS_CONFIG.yml"
DEFAULT_SOURCE_REF = "main"
DEFAULT_TASK_PROMPT_PATH = "FORGIS_TASK.md"
DEFAULT_TARGET_SUBDIR = "target-output"
DEFAULT_AGENT_BACKEND = "aider"
DEFAULT_MODEL = "provider/model-name"
DEFAULT_TARGET_BASE_BRANCH = "main"
DEFAULT_RUN_LOG_FILENAME = "FORGIS_LOG.md"
DEFAULT_SOURCE_CONTEXT_MODE = "none"
DEFAULT_SOURCE_CONTEXT_MAX_CHARS = 100_000
DEFAULT_SOURCE_CONTEXT_EXCLUDE = (".git/**",)
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

CONFIG_FIELDS = {
    "source_repo",
    "source_ref",
    "target_subdir",
    "task_prompt_path",
    "agent_backend",
    "model",
    "target_branch",
    "target_base_branch",
    "run_log_path",
    "dry_run",
    "run_agent",
    "run_aider",
    "confirm_real_run",
    "model_env",
    "validation_commands",
    "success_checks",
    "source_context",
    "target_stack",
    "migration_profile",
}

REQUIRED_FIELDS = {
    "source_repo",
    "target_repo",
    "target_branch",
}


@dataclasses.dataclass(frozen=True)
class SourceContextConfig:
    mode: str = DEFAULT_SOURCE_CONTEXT_MODE
    max_chars: int = DEFAULT_SOURCE_CONTEXT_MAX_CHARS
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = DEFAULT_SOURCE_CONTEXT_EXCLUDE

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "max_chars": self.max_chars,
            "include": list(self.include),
            "exclude": list(self.exclude),
        }


@dataclasses.dataclass(frozen=True)
class ResolvedConfig:
    source_repo: str
    source_ref: str
    target_repo: str
    target_subdir: str
    task_prompt_path: str
    agent_backend: str
    model: str
    target_branch: str
    target_base_branch: str
    run_log_path: str
    config_path: str
    config_found: bool
    config_keys: tuple[str, ...]
    dry_run: bool
    run_agent_config: bool
    confirm_real_run: bool
    real_run_allowed: bool
    run_agent: bool
    model_env: tuple[tuple[str, str], ...]
    validation_commands: tuple[str, ...]
    success_checks: tuple[dict[str, str], ...]
    source_context: SourceContextConfig
    passthrough_config: tuple[tuple[str, str], ...]

    def env(self) -> dict[str, str]:
        model_env = {runtime: source for runtime, source in self.model_env}
        return {
            "SOURCE_REPO": self.source_repo,
            "SOURCE_REF": self.source_ref,
            "TARGET_REPO": self.target_repo,
            "TARGET_SUBDIR": self.target_subdir,
            "TASK_PROMPT_PATH": self.task_prompt_path,
            "AGENT_BACKEND": self.agent_backend,
            "AIDER_MODEL": self.model,
            "TARGET_BRANCH": self.target_branch,
            "TARGET_BASE_BRANCH": self.target_base_branch,
            "RUN_LOG_PATH": self.run_log_path,
            "CONFIG_PATH": self.config_path,
            "CONFIG_FOUND": "true" if self.config_found else "false",
            "CONFIG_KEYS": ",".join(self.config_keys),
            "DRY_RUN": "true" if self.dry_run else "false",
            "DRY_RUN_CONFIG": "true" if self.dry_run else "false",
            "RUN_AGENT_CONFIG": "true" if self.run_agent_config else "false",
            "RUN_AGENT_REQUESTED": "true" if self.run_agent_config else "false",
            "RUN_AIDER_CONFIG": "true" if self.run_agent_config else "false",
            "RUN_AIDER_REQUESTED": "true" if self.run_agent_config else "false",
            "CONFIRM_REAL_RUN": "true" if self.confirm_real_run else "false",
            "REAL_RUN_ALLOWED": "true" if self.real_run_allowed else "false",
            "RUN_AGENT": "true" if self.run_agent else "false",
            "RUN_AIDER": "true" if self.run_agent else "false",
            "RUN_AI": "true" if self.run_agent else "false",
            "MODEL_ENV_JSON": json.dumps(model_env, ensure_ascii=False, sort_keys=True),
            "VALIDATION_COMMANDS_JSON": json.dumps(
                list(self.validation_commands),
                ensure_ascii=False,
            ),
            "SUCCESS_CHECKS_JSON": json.dumps(
                list(self.success_checks),
                ensure_ascii=False,
            ),
            "SOURCE_CONTEXT_JSON": json.dumps(
                self.source_context.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            "SOURCE_CONTEXT_MODE": self.source_context.mode,
            "SOURCE_CONTEXT_MAX_CHARS": str(self.source_context.max_chars),
            "SOURCE_CONTEXT_INCLUDE_JSON": json.dumps(
                list(self.source_context.include),
                ensure_ascii=False,
            ),
            "SOURCE_CONTEXT_EXCLUDE_JSON": json.dumps(
                list(self.source_context.exclude),
                ensure_ascii=False,
            ),
            "FORGIS_PASSTHROUGH_CONFIG_JSON": json.dumps(
                dict(self.passthrough_config),
                ensure_ascii=False,
                sort_keys=True,
            ),
        }

    def outputs(self) -> dict[str, str]:
        return {key.lower(): value for key, value in self.env().items()}


def parse_bool(value: str | bool, label: str) -> bool:
    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise ValueError(f"{label} must be a boolean value, got: {value}")


def non_empty(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def clean_single_line(value: str, label: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{label} must be a single-line value.")
    return value


def dedupe_strings(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def select_string_list(config: dict[str, Any], field: str) -> tuple[str, ...]:
    if field not in config or config[field] is None:
        return ()

    value = config[field]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a YAML list of single-line strings.")

    strings: list[str] = []
    for index, item in enumerate(value):
        text = non_empty(item)
        if text is None:
            raise ValueError(f"{field}[{index}] must be a non-empty string.")
        strings.append(clean_single_line(text, f"{field}[{index}]"))

    return dedupe_strings(strings)


def validate_env_name(value: str, label: str) -> str:
    name = clean_single_line(value.strip(), label)
    if not ENV_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"{label} must be a valid environment variable name: {value}")
    return name


def select_model_env(config: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    if "model_env" not in config or config["model_env"] is None:
        return ()

    value = config["model_env"]
    if not isinstance(value, dict):
        raise ValueError("model_env must be a YAML mapping of runtime env names to secret env names.")

    pairs: list[tuple[str, str]] = []
    for runtime_name_raw, secret_name_raw in value.items():
        if not isinstance(runtime_name_raw, str):
            raise ValueError("model_env contains a non-string runtime env name.")

        runtime_name = validate_env_name(runtime_name_raw, "model_env runtime env name")
        secret_name_text = non_empty(secret_name_raw)
        if secret_name_text is None:
            raise ValueError(f"model_env.{runtime_name} must name a non-empty secret env.")
        secret_name = validate_env_name(secret_name_text, f"model_env.{runtime_name}")
        pairs.append((runtime_name, secret_name))

    return tuple(sorted(pairs))


def select_success_checks(config: dict[str, Any]) -> tuple[dict[str, str], ...]:
    if "success_checks" not in config or config["success_checks"] is None:
        return ()

    value = config["success_checks"]
    if not isinstance(value, list):
        raise ValueError("success_checks must be a YAML list.")

    checks: list[dict[str, str]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"success_checks[{index}] must be a mapping.")

        allowed_keys = {"path_exists", "command"}
        keys = [key for key in item if key in allowed_keys]
        if len(keys) != 1:
            raise ValueError(
                f"success_checks[{index}] must contain exactly one of: path_exists, command."
            )
        key = keys[0]
        text = non_empty(item.get(key))
        if text is None:
            raise ValueError(f"success_checks[{index}].{key} must be a non-empty string.")
        checks.append({key: clean_single_line(text, f"success_checks[{index}].{key}")})

    return tuple(checks)


def select_source_context(config: dict[str, Any]) -> SourceContextConfig:
    if "source_context" not in config or config["source_context"] is None:
        return SourceContextConfig()

    value = config["source_context"]
    if not isinstance(value, dict):
        raise ValueError("source_context must be a YAML mapping.")

    mode = non_empty(value.get("mode")) or DEFAULT_SOURCE_CONTEXT_MODE
    mode = clean_single_line(mode, "source_context.mode").lower()
    if mode not in {"none", "tree", "selected_files"}:
        raise ValueError("source_context.mode must be one of: none, tree, selected_files.")

    max_chars_raw = value.get("max_chars", DEFAULT_SOURCE_CONTEXT_MAX_CHARS)
    try:
        max_chars = int(max_chars_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("source_context.max_chars must be an integer.") from exc
    if max_chars < 0:
        raise ValueError("source_context.max_chars must not be negative.")

    include = select_nested_string_list(value, "include", "source_context.include")
    exclude = select_nested_string_list(value, "exclude", "source_context.exclude")
    if not exclude:
        exclude = DEFAULT_SOURCE_CONTEXT_EXCLUDE

    if mode == "selected_files" and not include:
        raise ValueError("source_context.include is required when mode is selected_files.")

    return SourceContextConfig(
        mode=mode,
        max_chars=max_chars,
        include=include,
        exclude=exclude,
    )


def select_nested_string_list(
    config: dict[str, Any],
    field: str,
    label: str,
) -> tuple[str, ...]:
    if field not in config or config[field] is None:
        return ()
    value = config[field]
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a YAML list of single-line strings.")

    strings: list[str] = []
    for index, item in enumerate(value):
        text = non_empty(item)
        if text is None:
            raise ValueError(f"{label}[{index}] must be a non-empty string.")
        strings.append(clean_single_line(text, f"{label}[{index}]"))
    return dedupe_strings(strings)


def resolve_inside_root(root: Path, relative_path: str, label: str) -> tuple[Path, str]:
    value = clean_single_line(relative_path.strip(), label)
    if not value:
        raise ValueError(f"{label} is required.")

    raw = Path(value)
    if raw.is_absolute():
        raise ValueError(f"{label} must be relative to the target repository root: {relative_path}")

    if any(part in {"", ".", "..", ".git"} for part in raw.parts):
        raise ValueError(f"{label} contains an unsafe path segment: {relative_path}")

    root_resolved = root.resolve()
    resolved = (root_resolved / raw).resolve()

    if not resolved.is_relative_to(root_resolved):
        raise ValueError(f"{label} escapes the target repository root: {relative_path}")

    if resolved == root_resolved:
        raise ValueError(f"{label} must not resolve to the target repository root.")

    return resolved, resolved.relative_to(root_resolved).as_posix()


def resolve_target_subdir(root: Path, target_subdir: str) -> tuple[Path, str]:
    resolved, relative = resolve_inside_root(root, target_subdir, "target_subdir")
    return resolved, relative.rstrip("/")


def require_path_inside_subdir(
    root: Path,
    target_subdir: str,
    relative_path: str,
    label: str,
) -> tuple[Path, str]:
    target_subdir_path, target_subdir_relative = resolve_target_subdir(root, target_subdir)
    resolved, relative = resolve_inside_root(root, relative_path, label)

    if resolved == target_subdir_path or not resolved.is_relative_to(target_subdir_path):
        raise ValueError(
            f"{label} must be located inside target_subdir "
            f"'{target_subdir_relative}/': {relative_path}"
        )

    return resolved, relative


def load_config_file(target_root: Path, config_path: str) -> tuple[bool, dict[str, Any], str]:
    config_abs, config_relative = resolve_inside_root(target_root, config_path, "config_path")
    if not config_abs.exists():
        return False, {}, config_relative

    if not config_abs.is_file():
        raise ValueError(f"config_path is not a file: {config_relative}")

    text = config_abs.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"Config file exists but is empty: {config_relative}")

    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Config file has invalid YAML: {config_relative}: {exc}") from exc

    if not loaded:
        raise ValueError(f"Config file does not contain any configuration: {config_relative}")

    if not isinstance(loaded, dict):
        raise ValueError(f"Config file must contain a YAML mapping: {config_relative}")

    config: dict[str, Any] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise ValueError(f"Config file contains a non-string key: {config_relative}")
        config[key] = value

    return True, config, config_relative


def select_value(
    field: str,
    config: dict[str, Any],
    default: str | None = None,
) -> str | None:
    configured = non_empty(config.get(field))
    if configured is not None:
        return clean_single_line(configured, field)
    return default


def select_config_bool(config: dict[str, Any], field: str, default: bool) -> bool:
    if field not in config or config[field] is None:
        return default
    return parse_bool(config[field], field)


def select_run_agent(config: dict[str, Any]) -> bool:
    if "run_agent" in config and config["run_agent"] is not None:
        return parse_bool(config["run_agent"], "run_agent")
    if "run_aider" in config and config["run_aider"] is not None:
        return parse_bool(config["run_aider"], "run_aider")
    return False


def select_passthrough_config(config: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    passthrough: list[tuple[str, str]] = []
    for key in ("target_stack", "migration_profile"):
        text = non_empty(config.get(key))
        if text is not None:
            passthrough.append((key, clean_single_line(text, key)))
    return tuple(passthrough)


def resolve_config(
    *,
    target_root: Path,
    target_repo: str | None,
    config_path: str | None = DEFAULT_CONFIG_PATH,
) -> ResolvedConfig:
    target_root = target_root.resolve()
    if not target_root.exists() or not target_root.is_dir():
        raise FileNotFoundError(f"Target repository directory not found: {target_root}")

    config_path_input = non_empty(config_path) or DEFAULT_CONFIG_PATH
    config_found, config, resolved_config_path = load_config_file(target_root, config_path_input)
    if not config_found:
        raise FileNotFoundError(f"Config file not found: {resolved_config_path}")

    target_repo_value = non_empty(target_repo)
    if target_repo_value is not None:
        target_repo_value = clean_single_line(target_repo_value, "target_repo")

    source_repo = select_value("source_repo", config)
    target_branch = select_value("target_branch", config)
    values: dict[str, str | None] = {
        "source_repo": source_repo,
        "source_ref": select_value("source_ref", config, DEFAULT_SOURCE_REF),
        "target_repo": target_repo_value,
        "target_subdir": select_value("target_subdir", config, DEFAULT_TARGET_SUBDIR),
        "task_prompt_path": select_value("task_prompt_path", config, DEFAULT_TASK_PROMPT_PATH),
        "agent_backend": select_value("agent_backend", config, DEFAULT_AGENT_BACKEND),
        "model": select_value("model", config, DEFAULT_MODEL),
        "target_branch": target_branch,
        "target_base_branch": select_value(
            "target_base_branch",
            config,
            DEFAULT_TARGET_BASE_BRANCH,
        ),
        "run_log_path": select_value("run_log_path", config),
    }

    missing = sorted(field for field in REQUIRED_FIELDS if not values.get(field))
    if missing:
        raise ValueError(
            "Missing required Forgis parameters: "
            + ", ".join(missing)
            + ". Provide them in FORGIS_CONFIG.yml; target_repo is supplied by the workflow input."
        )

    agent_backend = (values["agent_backend"] or DEFAULT_AGENT_BACKEND).casefold()
    if agent_backend != "aider":
        raise ValueError("Only agent_backend: aider is currently supported.")

    target_subdir = values["target_subdir"] or DEFAULT_TARGET_SUBDIR
    _, target_subdir_relative = resolve_target_subdir(target_root, target_subdir)

    task_prompt_path = values["task_prompt_path"] or DEFAULT_TASK_PROMPT_PATH
    _, task_prompt_relative = resolve_inside_root(target_root, task_prompt_path, "task_prompt_path")

    run_log_path = values["run_log_path"]
    if not run_log_path:
        run_log_path = f"{target_subdir_relative}/{DEFAULT_RUN_LOG_FILENAME}"

    _, run_log_relative = require_path_inside_subdir(
        target_root,
        target_subdir_relative,
        run_log_path,
        "run_log_path",
    )

    dry_run_value = select_config_bool(config, "dry_run", True)
    run_agent_config = select_run_agent(config)
    confirm_real_run = select_config_bool(config, "confirm_real_run", False)
    model_env = select_model_env(config)
    validation_commands = select_string_list(config, "validation_commands")
    success_checks = select_success_checks(config)
    source_context = select_source_context(config)
    passthrough_config = select_passthrough_config(config)

    if not dry_run_value and not confirm_real_run:
        raise ValueError("Real Forgis runs require confirm_real_run: true in FORGIS_CONFIG.yml.")

    real_run_allowed = not dry_run_value and confirm_real_run
    run_agent_effective = run_agent_config and real_run_allowed

    return ResolvedConfig(
        source_repo=values["source_repo"] or "",
        source_ref=values["source_ref"] or DEFAULT_SOURCE_REF,
        target_repo=values["target_repo"] or "",
        target_subdir=target_subdir_relative,
        task_prompt_path=task_prompt_relative,
        agent_backend=agent_backend,
        model=values["model"] or DEFAULT_MODEL,
        target_branch=values["target_branch"] or "",
        target_base_branch=values["target_base_branch"] or DEFAULT_TARGET_BASE_BRANCH,
        run_log_path=run_log_relative,
        config_path=resolved_config_path,
        config_found=config_found,
        config_keys=tuple(sorted(str(key) for key in config.keys())),
        dry_run=dry_run_value,
        run_agent_config=run_agent_config,
        confirm_real_run=confirm_real_run,
        real_run_allowed=real_run_allowed,
        run_agent=run_agent_effective,
        model_env=model_env,
        validation_commands=validation_commands,
        success_checks=success_checks,
        source_context=source_context,
        passthrough_config=passthrough_config,
    )


def markdown_summary(resolved: ResolvedConfig) -> str:
    config_keys = ", ".join(resolved.config_keys) if resolved.config_keys else "[none]"
    run_agent_note = ""
    if resolved.dry_run and resolved.run_agent_config:
        run_agent_note = " (dry_run=true, agent execution is disabled.)"
    model_env = (
        ", ".join(f"{runtime} <- {source}" for runtime, source in resolved.model_env)
        if resolved.model_env
        else "[none]"
    )
    validation_commands = (
        f"{len(resolved.validation_commands)} configured"
        if resolved.validation_commands
        else "[none]"
    )
    success_checks = (
        f"{len(resolved.success_checks)} configured"
        if resolved.success_checks
        else "[none]"
    )
    passthrough = (
        ", ".join(f"{key}={value}" for key, value in resolved.passthrough_config)
        if resolved.passthrough_config
        else "[none]"
    )

    return "\n".join(
        [
            "# Forgis Resolved Configuration",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Config path | `{resolved.config_path}` |",
            f"| Config found | `{'yes' if resolved.config_found else 'no'}` |",
            f"| Config keys | `{config_keys}` |",
            f"| Source repo | `{resolved.source_repo}` |",
            f"| Source ref | `{resolved.source_ref}` |",
            f"| Target repo | `{resolved.target_repo}` |",
            f"| Target base branch | `{resolved.target_base_branch}` |",
            f"| Target branch | `{resolved.target_branch}` |",
            f"| Agent backend | `{resolved.agent_backend}` |",
            f"| Task prompt path | `{resolved.task_prompt_path}` |",
            f"| Target subdir | `{resolved.target_subdir}` |",
            f"| Run log path | `{resolved.run_log_path}` |",
            f"| Model | `{resolved.model}` |",
            f"| Model env mapping | `{model_env}` |",
            f"| validation_commands | `{validation_commands}` |",
            f"| success_checks | `{success_checks}` |",
            f"| source_context mode | `{resolved.source_context.mode}` |",
            f"| passthrough user config | `{passthrough}` |",
            f"| dry_run config value | `{str(resolved.dry_run).lower()}` |",
            f"| run_agent config value | `{str(resolved.run_agent_config).lower()}` |",
            f"| confirm_real_run config value | `{str(resolved.confirm_real_run).lower()}` |",
            f"| Effective dry_run | `{str(resolved.dry_run).lower()}` |",
            f"| Effective run_agent | `{str(resolved.run_agent).lower()}`{run_agent_note} |",
            f"| Writable scope | `{resolved.target_subdir}/` |",
            f"| Read-only files | `{resolved.config_path}`, `{resolved.task_prompt_path}`, source repository, target paths outside `{resolved.target_subdir}/` |",
            f"| Real run allowed | `{str(resolved.real_run_allowed and resolved.run_agent).lower()}` |",
            "",
            "Config path is fixed to FORGIS_CONFIG.yml in the main workflow.",
            "Agent execution is allowed only when dry_run=false, run_agent=true, and confirm_real_run=true.",
        ]
    )
