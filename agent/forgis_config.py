from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "FORGIS_CONFIG.yml"
DEFAULT_SOURCE_REF = "main"
DEFAULT_TARGET_BASE_BRANCH = "main"
DEFAULT_MIGRATION_PROFILE = "default"
DEFAULT_TASK_PROMPT_PATH = "FORGIS_TASK.md"
DEFAULT_TARGET_SUBDIR = "forgis-output"
DEFAULT_MODEL = "deepseek/deepseek-v4-pro"
DEFAULT_RUN_LOG_FILENAME = "FORGIS_LOG.md"
DEFAULT_FORBIDDEN_PROMPT_MARKERS = (
    "make the greeting more casual",
    "Which file (or which phrase) should be changed?",
    "casual greeting",
)

CONFIG_FIELDS = {
    "source_repo",
    "source_ref",
    "target_platform",
    "target_stack",
    "migration_profile",
    "target_subdir",
    "task_prompt_path",
    "model",
    "target_branch",
    "target_base_branch",
    "run_log_path",
    "dry_run",
    "run_aider",
    "confirm_real_run",
    "required_prompt_markers",
    "forbidden_prompt_markers",
}

REQUIRED_FIELDS = {
    "source_repo",
    "target_repo",
    "target_platform",
    "target_stack",
    "target_branch",
}


@dataclasses.dataclass(frozen=True)
class ResolvedConfig:
    source_repo: str
    source_ref: str
    target_repo: str
    target_platform: str
    target_stack: str
    migration_profile: str
    target_subdir: str
    task_prompt_path: str
    model: str
    target_branch: str
    target_base_branch: str
    run_log_path: str
    config_path: str
    config_found: bool
    config_keys: tuple[str, ...]
    dry_run: bool
    run_aider_config: bool
    confirm_real_run: bool
    real_run_allowed: bool
    run_aider: bool
    required_prompt_markers: tuple[str, ...]
    forbidden_prompt_markers: tuple[str, ...]

    def env(self) -> dict[str, str]:
        return {
            "SOURCE_REPO": self.source_repo,
            "SOURCE_REF": self.source_ref,
            "TARGET_REPO": self.target_repo,
            "TARGET_PLATFORM": self.target_platform,
            "TARGET_STACK": self.target_stack,
            "MIGRATION_PROFILE": self.migration_profile,
            "TARGET_SUBDIR": self.target_subdir,
            "TASK_PROMPT_PATH": self.task_prompt_path,
            "AIDER_MODEL": self.model,
            "TARGET_BRANCH": self.target_branch,
            "TARGET_BASE_BRANCH": self.target_base_branch,
            "RUN_LOG_PATH": self.run_log_path,
            "CONFIG_PATH": self.config_path,
            "CONFIG_FOUND": "true" if self.config_found else "false",
            "CONFIG_KEYS": ",".join(self.config_keys),
            "DRY_RUN": "true" if self.dry_run else "false",
            "DRY_RUN_CONFIG": "true" if self.dry_run else "false",
            "RUN_AIDER_CONFIG": "true" if self.run_aider_config else "false",
            "RUN_AIDER_REQUESTED": "true" if self.run_aider_config else "false",
            "CONFIRM_REAL_RUN": "true" if self.confirm_real_run else "false",
            "REAL_RUN_ALLOWED": "true" if self.real_run_allowed else "false",
            "RUN_AIDER": "true" if self.run_aider else "false",
            "RUN_AI": "true" if self.run_aider else "false",
            "REQUIRED_PROMPT_MARKERS_JSON": json.dumps(
                list(self.required_prompt_markers),
                ensure_ascii=False,
            ),
            "FORBIDDEN_PROMPT_MARKERS_JSON": json.dumps(
                list(self.forbidden_prompt_markers),
                ensure_ascii=False,
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

    markers: list[str] = []
    for index, item in enumerate(value):
        text = non_empty(item)
        if text is None:
            raise ValueError(f"{field}[{index}] must be a non-empty string.")
        markers.append(clean_single_line(text, f"{field}[{index}]"))

    return dedupe_strings(markers)


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
    explicit_inputs: dict[str, Any],
    config: dict[str, Any],
    default: str | None = None,
) -> str | None:
    explicit = non_empty(explicit_inputs.get(field))
    if explicit is not None:
        return clean_single_line(explicit, field)

    configured = non_empty(config.get(field))
    if configured is not None:
        return clean_single_line(configured, field)

    return default


def select_config_bool(config: dict[str, Any], field: str, default: bool) -> bool:
    if field not in config or config[field] is None:
        return default

    return parse_bool(config[field], field)


def resolve_config(
    *,
    target_root: Path,
    target_repo: str | None,
    config_path: str | None = DEFAULT_CONFIG_PATH,
    explicit_inputs: dict[str, Any],
) -> ResolvedConfig:
    target_root = target_root.resolve()
    if not target_root.exists() or not target_root.is_dir():
        raise FileNotFoundError(f"Target repository directory not found: {target_root}")

    config_path_input = non_empty(config_path) or DEFAULT_CONFIG_PATH
    config_found, config, resolved_config_path = load_config_file(target_root, config_path_input)

    merged_inputs = dict(explicit_inputs)
    merged_inputs["target_repo"] = non_empty(target_repo) or merged_inputs.get("target_repo")

    source_repo_override = non_empty(merged_inputs.get("source_repo"))
    source_repo_value = (
        clean_single_line(source_repo_override, "source_repo")
        if source_repo_override is not None
        else select_value("source_repo", {}, config)
    )

    values: dict[str, str | None] = {
        "source_repo": source_repo_value,
        "source_ref": select_value("source_ref", {}, config, DEFAULT_SOURCE_REF),
        "target_repo": select_value("target_repo", merged_inputs, config),
        "target_platform": select_value("target_platform", {}, config),
        "target_stack": select_value("target_stack", {}, config),
        "migration_profile": select_value(
            "migration_profile",
            {},
            config,
            DEFAULT_MIGRATION_PROFILE,
        ),
        "target_subdir": select_value("target_subdir", {}, config, DEFAULT_TARGET_SUBDIR),
        "task_prompt_path": select_value(
            "task_prompt_path",
            {},
            config,
            DEFAULT_TASK_PROMPT_PATH,
        ),
        "model": select_value("model", {}, config, DEFAULT_MODEL),
        "target_branch": select_value("target_branch", {}, config),
        "target_base_branch": select_value(
            "target_base_branch",
            {},
            config,
            DEFAULT_TARGET_BASE_BRANCH,
        ),
        "run_log_path": select_value("run_log_path", {}, config),
    }

    missing = sorted(field for field in REQUIRED_FIELDS if not values.get(field))
    if missing:
        source = f"{resolved_config_path} was not found" if not config_found else f"{resolved_config_path} is incomplete"
        raise ValueError(
            "Missing required Forgis migration parameters: "
            + ", ".join(missing)
            + f". Provide them in FORGIS_CONFIG.yml; only source_repo can be overridden by workflow input. {source}."
        )

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
    run_aider_config = select_config_bool(config, "run_aider", False)
    confirm_real_run = select_config_bool(config, "confirm_real_run", False)
    required_prompt_markers = select_string_list(config, "required_prompt_markers")
    configured_forbidden_prompt_markers = select_string_list(config, "forbidden_prompt_markers")
    forbidden_prompt_markers = dedupe_strings(
        list(DEFAULT_FORBIDDEN_PROMPT_MARKERS) + list(configured_forbidden_prompt_markers)
    )

    if not dry_run_value and not confirm_real_run:
        raise ValueError("Real AI migration requires confirm_real_run: true in FORGIS_CONFIG.yml.")

    real_run_allowed = not dry_run_value and confirm_real_run
    run_aider_effective = run_aider_config and real_run_allowed

    return ResolvedConfig(
        source_repo=values["source_repo"] or "",
        source_ref=values["source_ref"] or DEFAULT_SOURCE_REF,
        target_repo=values["target_repo"] or "",
        target_platform=values["target_platform"] or "",
        target_stack=values["target_stack"] or "",
        migration_profile=values["migration_profile"] or DEFAULT_MIGRATION_PROFILE,
        target_subdir=target_subdir_relative,
        task_prompt_path=task_prompt_relative,
        model=values["model"] or DEFAULT_MODEL,
        target_branch=values["target_branch"] or "",
        target_base_branch=values["target_base_branch"] or DEFAULT_TARGET_BASE_BRANCH,
        run_log_path=run_log_relative,
        config_path=resolved_config_path,
        config_found=config_found,
        config_keys=tuple(sorted(str(key) for key in config.keys())),
        dry_run=dry_run_value,
        run_aider_config=run_aider_config,
        confirm_real_run=confirm_real_run,
        real_run_allowed=real_run_allowed,
        run_aider=run_aider_effective,
        required_prompt_markers=required_prompt_markers,
        forbidden_prompt_markers=forbidden_prompt_markers,
    )


def markdown_summary(resolved: ResolvedConfig) -> str:
    config_keys = ", ".join(resolved.config_keys) if resolved.config_keys else "[none]"
    run_aider_note = ""
    if resolved.dry_run and resolved.run_aider_config:
        run_aider_note = " (dry_run=true, Aider execution is disabled.)"
    required_markers = (
        ", ".join(resolved.required_prompt_markers)
        if resolved.required_prompt_markers
        else "[none]"
    )
    forbidden_markers = ", ".join(resolved.forbidden_prompt_markers)

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
            f"| Target platform | `{resolved.target_platform}` |",
            f"| Target stack | `{resolved.target_stack}` |",
            f"| Migration profile | `{resolved.migration_profile}` |",
            f"| Task prompt path | `{resolved.task_prompt_path}` |",
            f"| Target subdir | `{resolved.target_subdir}` |",
            f"| Run log path | `{resolved.run_log_path}` |",
            f"| Model | `{resolved.model}` |",
            f"| dry_run config value | `{str(resolved.dry_run).lower()}` |",
            f"| run_aider config value | `{str(resolved.run_aider_config).lower()}` |",
            f"| confirm_real_run config value | `{str(resolved.confirm_real_run).lower()}` |",
            f"| Effective dry_run | `{str(resolved.dry_run).lower()}` |",
            f"| Effective run_aider | `{str(resolved.run_aider).lower()}`{run_aider_note} |",
            f"| Required prompt markers | `{required_markers}` |",
            f"| Forbidden prompt markers | `{forbidden_markers}` |",
            f"| Writable scope | `{resolved.target_subdir}/` |",
            f"| Read-only files | `{resolved.config_path}`, `{resolved.task_prompt_path}`, source repository, target paths outside `{resolved.target_subdir}/` |",
            f"| Real migration allowed | `{str(resolved.real_run_allowed and resolved.run_aider).lower()}` |",
            "",
            "Config path is fixed to FORGIS_CONFIG.yml in the main workflow.",
            "Real AI migration is allowed only when dry_run=false, run_aider=true, and confirm_real_run=true.",
        ]
    )
