from __future__ import annotations

import dataclasses
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = "FORGIS_CONFIG.yml"
DEFAULT_SOURCE_REF = "main"
DEFAULT_TASK_PROMPT_PATH = "FORGIS_TASK.md"
DEFAULT_TARGET_SUBDIR = "target-output"
DEFAULT_AGENT_BACKEND = "deepseek"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_API_FORMAT = "openai-compatible"
DEFAULT_TARGET_BASE_BRANCH = "main"
DEFAULT_RUN_LOG_FILENAME = "FORGIS_LOG.md"
DEFAULT_MAX_ITERATIONS = 80
MAX_ITERATIONS_LIMIT = 5_000
DEFAULT_MAX_TOOL_RESULT_CHARS = 20_000
MAX_TOOL_RESULT_CHARS_LIMIT = 5_000_000
DEFAULT_BUILD_TIMEOUT_SECONDS = 60
DEFAULT_TEST_TIMEOUT_SECONDS = 60
DEFAULT_MAX_COMMAND_OUTPUT_CHARS = 8_000
MAX_COMMAND_OUTPUT_CHARS_LIMIT = 2_000_000
DEFAULT_REPAIR_LOOP_ENABLED = False
DEFAULT_MAX_REPAIR_ATTEMPTS = 2
MAX_REPAIR_ATTEMPTS_LIMIT = 5
DEFAULT_REPAIR_REQUIRES_DIFF_CHECK = True
DEFAULT_REPAIR_REQUIRES_BUILD_OR_TEST = True
DEFAULT_REPAIR_STOP_ON_SUCCESS = True
DEFAULT_RUN_REPORT_ENABLED = True
DEFAULT_RUN_REPORT_OUTPUT_DIR = ".forgis/reports"
DEFAULT_RUN_REPORT_INCLUDE_EVENTS = True
DEFAULT_RUN_REPORT_MAX_EVENTS = 100
MAX_RUN_REPORT_EVENTS_LIMIT = 10_000
DEFAULT_RUN_REPORT_MAX_CHARS = 200_000
MAX_RUN_REPORT_MAX_CHARS_LIMIT = 20_000_000
DEFAULT_RUN_REPORT_REQUIRED = False
DEFAULT_SKILLS_ENABLED = True
DEFAULT_SELECTED_SKILLS: tuple[str, ...] = ()
DEFAULT_AUTO_SELECT_SKILLS = True
DEFAULT_MAX_SKILL_CHARS = 12_000
DEFAULT_MAX_TOTAL_SKILL_CHARS = 30_000
MAX_SKILL_CHARS_LIMIT = 50_000
MAX_TOTAL_SKILL_CHARS_LIMIT = 100_000
DEFAULT_MIGRATION_SCHEDULER_ENABLED = False
DEFAULT_MAX_MIGRATION_UNITS = 50
MAX_MIGRATION_UNITS_LIMIT = 200
DEFAULT_MIGRATION_UNIT_STRATEGY = "inventory"
DEFAULT_MIGRATION_UNIT_PRIORITIZE_UI = True
DEFAULT_MIGRATION_UNIT_INCLUDE_TESTS = True
DEFAULT_MIGRATION_UNIT_INCLUDE_ASSETS = True
DEFAULT_MIGRATION_PLAN_PERSISTENCE_ENABLED = True
DEFAULT_MIGRATION_PLAN_OUTPUT_DIR = DEFAULT_RUN_REPORT_OUTPUT_DIR
DEFAULT_MIGRATION_PLAN_FILENAME = "FORGIS_MIGRATION_PLAN.json"
DEFAULT_MIGRATION_PLAN_RESUME_ENABLED = False
DEFAULT_MIGRATION_PLAN_REQUIRED = False
DEFAULT_MIGRATION_PLAN_AUTO_UPDATE_ENABLED = True
DEFAULT_MIGRATION_PLAN_RESUME_SUMMARY_ENABLED = True
DEFAULT_MIGRATION_PLAN_EVENT_LOG_MAX_EVENTS = 100
MAX_MIGRATION_PLAN_EVENT_LOG_MAX_EVENTS = 500
DEFAULT_MIGRATION_PLAN_AUDIT_SUMMARY_ENABLED = True
DEFAULT_MIGRATION_PLAN_AUDIT_MAX_EVENTS = 10
MAX_MIGRATION_PLAN_AUDIT_MAX_EVENTS = 50
DEFAULT_MIGRATION_PLAN_AUTO_COMPLETE_ON_SUCCESS = False
DEFAULT_MIGRATION_PLAN_REQUESTED_ACTIVE_UNIT_ID = ""
DEFAULT_MIGRATION_PLAN_ALLOW_SWITCH_FROM_BLOCKED = True
DEFAULT_MIGRATION_PLAN_ALLOW_SWITCH_FROM_COMPLETED = False
DEFAULT_MIGRATION_PLAN_ALLOW_SWITCH_FROM_DEFERRED = True
DEFAULT_MIGRATION_PLAN_SWITCH_REQUIRES_RESUME = True
DEFAULT_MIGRATION_PLAN_SWITCH_REASON = ""
DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS_UNIT_ID = ""
DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS = ""
DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS_REASON = ""
DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_COMPLETE = True
DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_BLOCK = True
DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_DEFER = True
DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_ACTIVATE = True
DEFAULT_MIGRATION_PLAN_STATUS_UPDATE_REQUIRES_RESUME = True
DEFAULT_EXECUTION_MODE = "tool_loop"
STAGED_TRANSLATION_MODE = "staged_translation"
DEFAULT_STAGED_MIN_TOTAL_ITERATIONS = 120
DEFAULT_STAGED_MIN_PROCESSED_UNITS = 3
DEFAULT_STAGED_MAX_UNITS_PER_RUN = 12
DEFAULT_STAGED_COMPARE_REPORT_DIR = "FORGIS_COMPARE_REPORTS"
DEFAULT_VISUAL_VALIDATION_ENABLED = "auto"
DEFAULT_VISUAL_VALIDATION_PROVIDER = "qwen"
DEFAULT_MAX_VISUAL_ITERATIONS = 2
MAX_VISUAL_ITERATIONS_LIMIT = 2
VISUAL_VALIDATION_ENABLED_VALUES = frozenset({"auto", "true", "false"})
VISUAL_VALIDATION_PROVIDERS = frozenset({"qwen"})
VISUAL_VALIDATION_FIELDS = frozenset(
    {
        "enabled",
        "provider",
        "max_visual_iterations",
        "require_reference_first",
        "upload_visual_artifact",
    }
)

ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$")
MIGRATION_UNIT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
SECRET_SKILL_NAME_WORDS = re.compile(
    r"(secret|token|credential|password|api[_-]?key|private|\.env|\.npmrc|\.pypirc|\.netrc)",
    re.IGNORECASE,
)

CONFIG_FIELDS = {
    "source_repo",
    "source_ref",
    "target_subdir",
    "task_prompt_path",
    "agent_backend",
    "model",
    "api_base",
    "api_format",
    "target_branch",
    "target_base_branch",
    "run_log_path",
    "dry_run",
    "run_agent",
    "confirm_real_run",
    "model_env",
    "max_iterations",
    "max_tool_result_chars",
    "validation_commands",
    "success_checks",
    "build_command",
    "test_command",
    "build_timeout_seconds",
    "test_timeout_seconds",
    "max_command_output_chars",
    "repair_loop_enabled",
    "max_repair_attempts",
    "repair_requires_diff_check",
    "repair_requires_build_or_test",
    "repair_stop_on_success",
    "run_report_enabled",
    "run_report_output_dir",
    "run_report_include_events",
    "run_report_max_events",
    "run_report_max_chars",
    "run_report_required",
    "skills_enabled",
    "selected_skills",
    "auto_select_skills",
    "max_skill_chars",
    "max_total_skill_chars",
    "migration_scheduler_enabled",
    "max_migration_units",
    "migration_unit_strategy",
    "migration_unit_prioritize_ui",
    "migration_unit_include_tests",
    "migration_unit_include_assets",
    "migration_plan_persistence_enabled",
    "migration_plan_output_dir",
    "migration_plan_filename",
    "migration_plan_resume_enabled",
    "migration_plan_required",
    "migration_plan_auto_update_enabled",
    "migration_plan_resume_summary_enabled",
    "migration_plan_event_log_max_events",
    "migration_plan_audit_summary_enabled",
    "migration_plan_audit_max_events",
    "migration_plan_auto_complete_on_success",
    "migration_plan_requested_active_unit_id",
    "migration_plan_allow_switch_from_blocked",
    "migration_plan_allow_switch_from_completed",
    "migration_plan_allow_switch_from_deferred",
    "migration_plan_switch_requires_resume",
    "migration_plan_switch_reason",
    "migration_plan_requested_unit_status_unit_id",
    "migration_plan_requested_unit_status",
    "migration_plan_requested_unit_status_reason",
    "migration_plan_allow_manual_complete",
    "migration_plan_allow_manual_block",
    "migration_plan_allow_manual_defer",
    "migration_plan_allow_manual_activate",
    "migration_plan_status_update_requires_resume",
    "strict_mode",
    "execution_mode",
    "run_mode",
    "visual_validation",
    "staged_translation",
}

REQUIRED_FIELDS = {
    "source_repo",
    "target_repo",
    "target_branch",
}


@dataclasses.dataclass(frozen=True)
class VisualValidationConfig:
    enabled: str
    provider: str
    max_visual_iterations: int
    require_reference_first: bool
    upload_visual_artifact: bool


@dataclasses.dataclass(frozen=True)
class StagedPhaseConfig:
    min_iterations: int
    max_iterations: int


@dataclasses.dataclass(frozen=True)
class StagedMicroPhasesConfig:
    enabled: bool
    require_feed: bool
    require_write: bool
    require_compare_report: bool
    require_revision: bool


@dataclasses.dataclass(frozen=True)
class FolderBatchReviewConfig:
    enabled: bool
    max_bundle_chars: int
    require_after_folder_complete: bool


@dataclasses.dataclass(frozen=True)
class LowImpactWarningConfig:
    enabled: bool
    min_code_changed_paths: int
    ignore_report_only_changes: bool


@dataclasses.dataclass(frozen=True)
class SourceInventoryConfig:
    include_globs: tuple[str, ...]
    exclude_globs: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class ProgressFilesConfig:
    plan: str
    source_target_map: str
    progress: str
    compare_report_dir: str


@dataclasses.dataclass(frozen=True)
class StagedTranslationConfig:
    min_total_iterations: int
    min_processed_units: int
    max_units_per_run: int
    enforce_micro_phases: bool
    require_source_read: bool
    require_compare_report: bool
    require_progress_update: bool
    require_target_effect_or_deferred_reason: bool
    overview: StagedPhaseConfig
    per_file: StagedPhaseConfig
    stabilization: StagedPhaseConfig
    per_file_micro_phases: StagedMicroPhasesConfig
    folder_batch_review: FolderBatchReviewConfig
    low_impact_warning: LowImpactWarningConfig
    source_inventory: SourceInventoryConfig
    progress_files: ProgressFilesConfig


@dataclasses.dataclass(frozen=True)
class ResolvedConfig:
    source_repo: str
    source_ref: str
    target_repo: str
    target_subdir: str
    task_prompt_path: str
    agent_backend: str
    model: str
    api_base: str
    api_format: str
    target_branch: str
    target_base_branch: str
    run_log_path: str
    config_path: str
    config_keys: tuple[str, ...]
    dry_run: bool
    run_agent_config: bool
    confirm_real_run: bool
    real_run_allowed: bool
    run_agent: bool
    model_env: tuple[tuple[str, str], ...]
    max_iterations: int
    max_tool_result_chars: int
    max_command_output_chars: int
    build_command: tuple[str, ...]
    test_command: tuple[str, ...]
    build_timeout_seconds: int
    test_timeout_seconds: int
    repair_loop_enabled: bool
    max_repair_attempts: int
    repair_requires_diff_check: bool
    repair_requires_build_or_test: bool
    repair_stop_on_success: bool
    run_report_enabled: bool
    run_report_output_dir: str
    run_report_include_events: bool
    run_report_max_events: int
    run_report_max_chars: int
    run_report_required: bool
    skills_enabled: bool
    selected_skills: tuple[str, ...]
    auto_select_skills: bool
    max_skill_chars: int
    max_total_skill_chars: int
    migration_scheduler_enabled: bool
    max_migration_units: int
    migration_unit_strategy: str
    migration_unit_prioritize_ui: bool
    migration_unit_include_tests: bool
    migration_unit_include_assets: bool
    migration_plan_persistence_enabled: bool
    migration_plan_output_dir: str
    migration_plan_filename: str
    migration_plan_resume_enabled: bool
    migration_plan_required: bool
    migration_plan_auto_update_enabled: bool
    migration_plan_resume_summary_enabled: bool
    migration_plan_event_log_max_events: int
    migration_plan_audit_summary_enabled: bool
    migration_plan_audit_max_events: int
    migration_plan_auto_complete_on_success: bool
    migration_plan_requested_active_unit_id: str
    migration_plan_allow_switch_from_blocked: bool
    migration_plan_allow_switch_from_completed: bool
    migration_plan_allow_switch_from_deferred: bool
    migration_plan_switch_requires_resume: bool
    migration_plan_switch_reason: str
    migration_plan_requested_unit_status_unit_id: str
    migration_plan_requested_unit_status: str
    migration_plan_requested_unit_status_reason: str
    migration_plan_allow_manual_complete: bool
    migration_plan_allow_manual_block: bool
    migration_plan_allow_manual_defer: bool
    migration_plan_allow_manual_activate: bool
    migration_plan_status_update_requires_resume: bool
    validation_commands: tuple[str, ...]
    success_checks: tuple[dict[str, str], ...]
    strict_mode: bool
    execution_mode: str
    visual_validation: VisualValidationConfig
    staged_translation: StagedTranslationConfig

    def env(self) -> dict[str, str]:
        model_env = {runtime: source for runtime, source in self.model_env}
        return {
            "SOURCE_REPO": self.source_repo,
            "SOURCE_REF": self.source_ref,
            "TARGET_REPO": self.target_repo,
            "TARGET_SUBDIR": self.target_subdir,
            "TASK_PROMPT_PATH": self.task_prompt_path,
            "AGENT_BACKEND": self.agent_backend,
            "MODEL": self.model,
            "API_BASE": self.api_base,
            "API_FORMAT": self.api_format,
            "TARGET_BRANCH": self.target_branch,
            "TARGET_BASE_BRANCH": self.target_base_branch,
            "RUN_LOG_PATH": self.run_log_path,
            "CONFIG_PATH": self.config_path,
            "CONFIG_KEYS": ",".join(self.config_keys),
            "DRY_RUN": "true" if self.dry_run else "false",
            "RUN_AGENT_CONFIG": "true" if self.run_agent_config else "false",
            "RUN_AGENT_REQUESTED": "true" if self.run_agent_config else "false",
            "CONFIRM_REAL_RUN": "true" if self.confirm_real_run else "false",
            "REAL_RUN_ALLOWED": "true" if self.real_run_allowed else "false",
            "RUN_AGENT": "true" if self.run_agent else "false",
            "MAX_ITERATIONS": str(self.max_iterations),
            "MAX_TOOL_RESULT_CHARS": str(self.max_tool_result_chars),
            "MAX_COMMAND_OUTPUT_CHARS": str(self.max_command_output_chars),
            "BUILD_COMMAND_JSON": json.dumps(
                list(self.build_command),
                ensure_ascii=False,
            ),
            "TEST_COMMAND_JSON": json.dumps(
                list(self.test_command),
                ensure_ascii=False,
            ),
            "BUILD_TIMEOUT_SECONDS": str(self.build_timeout_seconds),
            "TEST_TIMEOUT_SECONDS": str(self.test_timeout_seconds),
            "REPAIR_LOOP_ENABLED": "true" if self.repair_loop_enabled else "false",
            "MAX_REPAIR_ATTEMPTS": str(self.max_repair_attempts),
            "REPAIR_REQUIRES_DIFF_CHECK": "true" if self.repair_requires_diff_check else "false",
            "REPAIR_REQUIRES_BUILD_OR_TEST": "true" if self.repair_requires_build_or_test else "false",
            "REPAIR_STOP_ON_SUCCESS": "true" if self.repair_stop_on_success else "false",
            "RUN_REPORT_ENABLED": "true" if self.run_report_enabled else "false",
            "RUN_REPORT_OUTPUT_DIR": self.run_report_output_dir,
            "RUN_REPORT_INCLUDE_EVENTS": "true" if self.run_report_include_events else "false",
            "RUN_REPORT_MAX_EVENTS": str(self.run_report_max_events),
            "RUN_REPORT_MAX_CHARS": str(self.run_report_max_chars),
            "RUN_REPORT_REQUIRED": "true" if self.run_report_required else "false",
            "SKILLS_ENABLED": "true" if self.skills_enabled else "false",
            "SELECTED_SKILLS_JSON": json.dumps(list(self.selected_skills), ensure_ascii=False),
            "AUTO_SELECT_SKILLS": "true" if self.auto_select_skills else "false",
            "MAX_SKILL_CHARS": str(self.max_skill_chars),
            "MAX_TOTAL_SKILL_CHARS": str(self.max_total_skill_chars),
            "MIGRATION_SCHEDULER_ENABLED": "true" if self.migration_scheduler_enabled else "false",
            "MAX_MIGRATION_UNITS": str(self.max_migration_units),
            "MIGRATION_UNIT_STRATEGY": self.migration_unit_strategy,
            "MIGRATION_UNIT_PRIORITIZE_UI": "true" if self.migration_unit_prioritize_ui else "false",
            "MIGRATION_UNIT_INCLUDE_TESTS": "true" if self.migration_unit_include_tests else "false",
            "MIGRATION_UNIT_INCLUDE_ASSETS": "true" if self.migration_unit_include_assets else "false",
            "MIGRATION_PLAN_PERSISTENCE_ENABLED": "true" if self.migration_plan_persistence_enabled else "false",
            "MIGRATION_PLAN_OUTPUT_DIR": self.migration_plan_output_dir,
            "MIGRATION_PLAN_FILENAME": self.migration_plan_filename,
            "MIGRATION_PLAN_RESUME_ENABLED": "true" if self.migration_plan_resume_enabled else "false",
            "MIGRATION_PLAN_REQUIRED": "true" if self.migration_plan_required else "false",
            "MIGRATION_PLAN_AUTO_UPDATE_ENABLED": "true" if self.migration_plan_auto_update_enabled else "false",
            "MIGRATION_PLAN_RESUME_SUMMARY_ENABLED": "true" if self.migration_plan_resume_summary_enabled else "false",
            "MIGRATION_PLAN_EVENT_LOG_MAX_EVENTS": str(self.migration_plan_event_log_max_events),
            "MIGRATION_PLAN_AUDIT_SUMMARY_ENABLED": "true" if self.migration_plan_audit_summary_enabled else "false",
            "MIGRATION_PLAN_AUDIT_MAX_EVENTS": str(self.migration_plan_audit_max_events),
            "MIGRATION_PLAN_AUTO_COMPLETE_ON_SUCCESS": "true" if self.migration_plan_auto_complete_on_success else "false",
            "MIGRATION_PLAN_REQUESTED_ACTIVE_UNIT_ID": self.migration_plan_requested_active_unit_id,
            "MIGRATION_PLAN_ALLOW_SWITCH_FROM_BLOCKED": "true" if self.migration_plan_allow_switch_from_blocked else "false",
            "MIGRATION_PLAN_ALLOW_SWITCH_FROM_COMPLETED": "true" if self.migration_plan_allow_switch_from_completed else "false",
            "MIGRATION_PLAN_ALLOW_SWITCH_FROM_DEFERRED": "true" if self.migration_plan_allow_switch_from_deferred else "false",
            "MIGRATION_PLAN_SWITCH_REQUIRES_RESUME": "true" if self.migration_plan_switch_requires_resume else "false",
            "MIGRATION_PLAN_SWITCH_REASON": self.migration_plan_switch_reason,
            "MIGRATION_PLAN_REQUESTED_UNIT_STATUS_UNIT_ID": self.migration_plan_requested_unit_status_unit_id,
            "MIGRATION_PLAN_REQUESTED_UNIT_STATUS": self.migration_plan_requested_unit_status,
            "MIGRATION_PLAN_REQUESTED_UNIT_STATUS_REASON": self.migration_plan_requested_unit_status_reason,
            "MIGRATION_PLAN_ALLOW_MANUAL_COMPLETE": "true" if self.migration_plan_allow_manual_complete else "false",
            "MIGRATION_PLAN_ALLOW_MANUAL_BLOCK": "true" if self.migration_plan_allow_manual_block else "false",
            "MIGRATION_PLAN_ALLOW_MANUAL_DEFER": "true" if self.migration_plan_allow_manual_defer else "false",
            "MIGRATION_PLAN_ALLOW_MANUAL_ACTIVATE": "true" if self.migration_plan_allow_manual_activate else "false",
            "MIGRATION_PLAN_STATUS_UPDATE_REQUIRES_RESUME": "true" if self.migration_plan_status_update_requires_resume else "false",
            "MODEL_ENV_JSON": json.dumps(model_env, ensure_ascii=False, sort_keys=True),
            "VALIDATION_COMMANDS_JSON": json.dumps(
                list(self.validation_commands),
                ensure_ascii=False,
            ),
            "SUCCESS_CHECKS_JSON": json.dumps(
                list(self.success_checks),
                ensure_ascii=False,
            ),
            "STRICT_MODE": "true" if self.strict_mode else "false",
            "EXECUTION_MODE": self.execution_mode,
            "FORGIS_VISUAL_VALIDATION_ENABLED": self.visual_validation.enabled,
            "FORGIS_VISUAL_VALIDATION_PROVIDER": self.visual_validation.provider,
            "FORGIS_VISUAL_MAX_ITERATIONS": str(self.visual_validation.max_visual_iterations),
            "FORGIS_VISUAL_REQUIRE_REFERENCE_FIRST": (
                "true" if self.visual_validation.require_reference_first else "false"
            ),
            "FORGIS_VISUAL_UPLOAD_ARTIFACT": (
                "true" if self.visual_validation.upload_visual_artifact else "false"
            ),
            "STAGED_TRANSLATION_JSON": json.dumps(
                dataclasses.asdict(self.staged_translation),
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


def validate_skill_name(value: str, label: str) -> str:
    name = clean_single_line(value.strip(), label)
    if not name:
        raise ValueError(f"{label} must be a non-empty skill name.")
    if "\x00" in name or "/" in name or "\\" in name:
        raise ValueError(f"{label} must be a safe skill slug, not a path.")
    if name.startswith(".") or name.startswith("~") or not SKILL_NAME_PATTERN.fullmatch(name):
        raise ValueError(f"{label} must be a safe skill slug.")
    if SECRET_SKILL_NAME_WORDS.search(name):
        raise ValueError(f"{label} must not contain secret-like words.")
    return name


def select_skill_names(config: dict[str, Any]) -> tuple[str, ...]:
    names = select_string_list(config, "selected_skills")
    return tuple(validate_skill_name(name, f"selected_skills[{index}]") for index, name in enumerate(names))


def select_command_array(config: dict[str, Any], field: str) -> tuple[str, ...]:
    if field not in config or config[field] is None:
        return ()
    value = config[field]
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a YAML list of command argument strings.")
    if not value:
        raise ValueError(f"{field} must not be an empty list when configured.")

    args: list[str] = []
    for index, item in enumerate(value):
        text = non_empty(item)
        if text is None:
            raise ValueError(f"{field}[{index}] must be a non-empty string.")
        cleaned = clean_single_line(text, f"{field}[{index}]")
        if "\x00" in cleaned:
            raise ValueError(f"{field}[{index}] contains an unsafe character.")
        args.append(cleaned)
    return tuple(args)


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
        unknown = [key for key in item if key not in allowed_keys]
        if unknown:
            raise ValueError(f"success_checks[{index}] contains unsupported keys: {', '.join(unknown)}")
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


def select_int(
    config: dict[str, Any],
    field: str,
    default: int,
    *,
    minimum: int,
) -> int:
    if field not in config or config[field] is None:
        return default
    try:
        value = int(config[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"{field} must be at least {minimum}.")
    return value


def select_bounded_int(
    config: dict[str, Any],
    field: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = select_int(config, field, default, minimum=minimum)
    if value > maximum:
        raise ValueError(f"{field} must be at most {maximum}.")
    return value


def select_nested_int(
    config: dict[str, Any],
    field: str,
    default: int,
    *,
    minimum: int,
) -> int:
    if field not in config or config[field] is None:
        return default
    try:
        value = int(config[field])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"staged_translation.{field} must be an integer.") from exc
    if value < minimum:
        raise ValueError(f"staged_translation.{field} must be at least {minimum}.")
    return value


def select_mapping(config: dict[str, Any], field: str) -> dict[str, Any]:
    if field not in config or config[field] is None:
        return {}
    value = config[field]
    if not isinstance(value, dict):
        raise ValueError(f"staged_translation.{field} must be a YAML mapping.")
    return dict(value)


def select_nested_bool(config: dict[str, Any], field: str, default: bool, *, prefix: str) -> bool:
    if field not in config or config[field] is None:
        return default
    return parse_bool(config[field], f"{prefix}.{field}")


def select_strict_nested_bool(config: dict[str, Any], field: str, default: bool, *, prefix: str) -> bool:
    if field not in config or config[field] is None:
        return default
    value = config[field]
    if not isinstance(value, bool):
        raise ValueError(f"{prefix}.{field} must be a boolean value.")
    return value


def select_visual_validation_enabled(config: dict[str, Any]) -> str:
    if "enabled" not in config or config["enabled"] is None:
        return DEFAULT_VISUAL_VALIDATION_ENABLED
    value = config["enabled"]
    if isinstance(value, bool):
        return "true" if value else "false"
    text = non_empty(value)
    if text is None:
        raise ValueError("visual_validation.enabled must be one of: auto, true, false.")
    cleaned = clean_single_line(text, "visual_validation.enabled").casefold()
    if cleaned not in VISUAL_VALIDATION_ENABLED_VALUES:
        raise ValueError("visual_validation.enabled must be one of: auto, true, false.")
    return cleaned


def select_visual_validation_provider(config: dict[str, Any]) -> str:
    if "provider" not in config or config["provider"] is None:
        return DEFAULT_VISUAL_VALIDATION_PROVIDER
    text = non_empty(config["provider"])
    if text is None:
        raise ValueError("visual_validation.provider must be qwen.")
    provider = clean_single_line(text, "visual_validation.provider").casefold()
    if provider not in VISUAL_VALIDATION_PROVIDERS:
        raise ValueError("visual_validation.provider must be qwen.")
    return provider


def select_visual_validation_iterations(config: dict[str, Any]) -> int:
    if "max_visual_iterations" not in config or config["max_visual_iterations"] is None:
        return DEFAULT_MAX_VISUAL_ITERATIONS
    value = config["max_visual_iterations"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("visual_validation.max_visual_iterations must be an integer.")
    if value < 0 or value > MAX_VISUAL_ITERATIONS_LIMIT:
        raise ValueError(
            "visual_validation.max_visual_iterations must be between 0 and "
            f"{MAX_VISUAL_ITERATIONS_LIMIT}."
        )
    return value


def select_visual_validation_config(config: dict[str, Any]) -> VisualValidationConfig:
    visual = config.get("visual_validation")
    if visual is None:
        visual = {}
    if not isinstance(visual, dict):
        raise ValueError("visual_validation must be a YAML mapping.")

    unsupported = sorted(str(key) for key in visual if key not in VISUAL_VALIDATION_FIELDS)
    if unsupported:
        raise ValueError(
            "visual_validation contains unsupported field(s): "
            + ", ".join(unsupported)
            + ". Phase 2 only accepts non-secret control fields."
        )

    return VisualValidationConfig(
        enabled=select_visual_validation_enabled(visual),
        provider=select_visual_validation_provider(visual),
        max_visual_iterations=select_visual_validation_iterations(visual),
        require_reference_first=select_strict_nested_bool(
            visual,
            "require_reference_first",
            True,
            prefix="visual_validation",
        ),
        upload_visual_artifact=select_strict_nested_bool(
            visual,
            "upload_visual_artifact",
            False,
            prefix="visual_validation",
        ),
    )


def select_globs(config: dict[str, Any], field: str, default: tuple[str, ...], *, prefix: str) -> tuple[str, ...]:
    if field not in config or config[field] is None:
        return default
    value = config[field]
    if not isinstance(value, list):
        raise ValueError(f"{prefix}.{field} must be a YAML list of single-line strings.")
    globs: list[str] = []
    for index, item in enumerate(value):
        text = non_empty(item)
        if text is None:
            raise ValueError(f"{prefix}.{field}[{index}] must be a non-empty string.")
        globs.append(clean_single_line(text, f"{prefix}.{field}[{index}]"))
    return dedupe_strings(globs)


def select_phase_config(
    phases: dict[str, Any],
    name: str,
    *,
    default_min: int,
    default_max: int,
) -> StagedPhaseConfig:
    raw = phases.get(name)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"staged_translation.phases.{name} must be a YAML mapping.")
    minimum = select_nested_int(raw, "min_iterations", default_min, minimum=0)
    maximum = select_nested_int(raw, "max_iterations", default_max, minimum=0)
    if maximum < minimum:
        raise ValueError(
            f"staged_translation.phases.{name}.max_iterations must be greater than or equal to "
            f"min_iterations."
        )
    return StagedPhaseConfig(min_iterations=minimum, max_iterations=maximum)


def validate_target_subdir_relative_path(value: Any, label: str) -> str:
    text = non_empty(value)
    if text is None:
        raise ValueError(f"{label} must be a non-empty relative path.")
    cleaned = clean_single_line(text, label).replace("\\", "/")
    if cleaned.startswith("/") or cleaned.startswith("~"):
        raise ValueError(f"{label} must be relative to target_subdir.")
    raw = PurePosixPath(cleaned.strip("/"))
    if raw.is_absolute() or not raw.parts:
        raise ValueError(f"{label} must be relative to target_subdir.")
    if any(part in {"", ".", "..", ".git"} for part in raw.parts):
        raise ValueError(f"{label} contains an unsafe path segment: {value}")
    return raw.as_posix()


def validate_run_report_output_dir(value: Any, target_subdir: str) -> str:
    text = non_empty(value)
    if text is None:
        raise ValueError("run_report_output_dir must be a non-empty relative path.")
    cleaned = clean_single_line(text, "run_report_output_dir").replace("\\", "/")
    if cleaned.startswith("/") or cleaned.startswith("~"):
        raise ValueError("run_report_output_dir must be relative to the Forgis runtime workspace.")
    raw = PurePosixPath(cleaned.strip("/"))
    if raw.is_absolute() or not raw.parts:
        raise ValueError("run_report_output_dir must be relative to the Forgis runtime workspace.")
    if any(part in {"", ".", "..", ".git"} for part in raw.parts):
        raise ValueError(f"run_report_output_dir contains an unsafe path segment: {value}")
    lowered_parts = {part.casefold() for part in raw.parts}
    if lowered_parts & {"source", "source-repo", "target", "target-repo"}:
        raise ValueError("run_report_output_dir must not point at a source or target checkout directory.")
    target_parts = {part.casefold() for part in PurePosixPath(target_subdir).parts}
    if lowered_parts & target_parts:
        raise ValueError("run_report_output_dir must not point inside target_subdir.")
    if any(
        part.casefold() in {".env", ".netrc", ".npmrc", ".pypirc"}
        or part.casefold().endswith((".pem", ".key", ".p12", ".pfx"))
        or any(word in part.casefold() for word in ("secret", "credential", "private-key", "private_key", "token"))
        for part in raw.parts
    ):
        raise ValueError("run_report_output_dir must not contain secret-like path segments.")
    return raw.as_posix()


def validate_migration_plan_output_dir(value: Any, target_subdir: str) -> str:
    try:
        return validate_run_report_output_dir(value, target_subdir)
    except ValueError as exc:
        raise ValueError(str(exc).replace("run_report_output_dir", "migration_plan_output_dir")) from exc


def validate_migration_plan_filename(value: Any) -> str:
    text = non_empty(value)
    if text is None:
        raise ValueError("migration_plan_filename must be a non-empty JSON file name.")
    cleaned = clean_single_line(text, "migration_plan_filename")
    if "/" in cleaned or "\\" in cleaned:
        raise ValueError("migration_plan_filename must be a safe file name, not a path.")
    if cleaned in {".", "..", ".git"} or cleaned.startswith("."):
        raise ValueError("migration_plan_filename must be a safe JSON file name.")
    if not cleaned.lower().endswith(".json"):
        raise ValueError("migration_plan_filename must end with .json.")
    lowered = cleaned.casefold()
    if (
        lowered in {".env", ".netrc", ".npmrc", ".pypirc"}
        or lowered.endswith((".pem", ".key", ".p12", ".pfx"))
        or any(word in lowered for word in ("secret", "credential", "private-key", "private_key", "token", "api_key", "apikey"))
    ):
        raise ValueError("migration_plan_filename must not contain secret-like words.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,120}", cleaned):
        raise ValueError("migration_plan_filename must be a safe JSON file name.")
    return cleaned


def validate_migration_plan_requested_active_unit_id(value: Any) -> str:
    text = non_empty(value)
    if text is None:
        return DEFAULT_MIGRATION_PLAN_REQUESTED_ACTIVE_UNIT_ID
    cleaned = clean_single_line(text, "migration_plan_requested_active_unit_id")
    if "\x00" in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError("migration_plan_requested_active_unit_id must be a safe migration unit id, not a path.")
    if cleaned.startswith(".") or cleaned.startswith("~") or not MIGRATION_UNIT_ID_PATTERN.fullmatch(cleaned):
        raise ValueError("migration_plan_requested_active_unit_id must be a safe migration unit id.")
    if SECRET_SKILL_NAME_WORDS.search(cleaned):
        raise ValueError("migration_plan_requested_active_unit_id must not contain secret-like words.")
    return cleaned


def validate_migration_plan_requested_unit_status_unit_id(value: Any) -> str:
    text = non_empty(value)
    if text is None:
        return DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS_UNIT_ID
    cleaned = clean_single_line(text, "migration_plan_requested_unit_status_unit_id")
    if "\x00" in cleaned or "/" in cleaned or "\\" in cleaned:
        raise ValueError("migration_plan_requested_unit_status_unit_id must be a safe migration unit id, not a path.")
    if cleaned.startswith(".") or cleaned.startswith("~") or not MIGRATION_UNIT_ID_PATTERN.fullmatch(cleaned):
        raise ValueError("migration_plan_requested_unit_status_unit_id must be a safe migration unit id.")
    if SECRET_SKILL_NAME_WORDS.search(cleaned):
        raise ValueError("migration_plan_requested_unit_status_unit_id must not contain secret-like words.")
    return cleaned


def validate_migration_plan_requested_unit_status(value: Any) -> str:
    text = non_empty(value)
    if text is None:
        return DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS
    cleaned = clean_single_line(text, "migration_plan_requested_unit_status")
    if "\x00" in cleaned:
        raise ValueError("migration_plan_requested_unit_status contains an unsafe character.")
    return cleaned.strip().casefold()


def validate_migration_plan_requested_unit_status_reason(value: Any) -> str:
    text = non_empty(value)
    if text is None:
        return DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS_REASON
    cleaned = clean_single_line(text, "migration_plan_requested_unit_status_reason")
    if "\x00" in cleaned:
        raise ValueError("migration_plan_requested_unit_status_reason contains an unsafe character.")
    return cleaned


def validate_migration_plan_switch_reason(value: Any) -> str:
    text = non_empty(value)
    if text is None:
        return DEFAULT_MIGRATION_PLAN_SWITCH_REASON
    cleaned = clean_single_line(text, "migration_plan_switch_reason")
    if "\x00" in cleaned:
        raise ValueError("migration_plan_switch_reason contains an unsafe character.")
    return cleaned


def select_progress_files(config: dict[str, Any]) -> ProgressFilesConfig:
    progress = select_mapping(config, "progress_files")
    return ProgressFilesConfig(
        plan=validate_target_subdir_relative_path(
            progress.get("plan", "FORGIS_TRANSLATION_PLAN.md"),
            "staged_translation.progress_files.plan",
        ),
        source_target_map=validate_target_subdir_relative_path(
            progress.get("source_target_map", "FORGIS_SOURCE_TARGET_MAP.md"),
            "staged_translation.progress_files.source_target_map",
        ),
        progress=validate_target_subdir_relative_path(
            progress.get("progress", "FORGIS_TRANSLATION_PROGRESS.md"),
            "staged_translation.progress_files.progress",
        ),
        compare_report_dir=validate_target_subdir_relative_path(
            progress.get("compare_report_dir", DEFAULT_STAGED_COMPARE_REPORT_DIR),
            "staged_translation.progress_files.compare_report_dir",
        ),
    )


def select_execution_mode(config: dict[str, Any]) -> str:
    execution_mode = non_empty(config.get("execution_mode"))
    run_mode = non_empty(config.get("run_mode"))
    if execution_mode and run_mode and execution_mode.casefold() != run_mode.casefold():
        raise ValueError("execution_mode and run_mode must match when both are configured.")

    mode = execution_mode or run_mode or DEFAULT_EXECUTION_MODE
    mode = clean_single_line(mode, "execution_mode").casefold()
    aliases = {
        "default": DEFAULT_EXECUTION_MODE,
        "tool_loop": DEFAULT_EXECUTION_MODE,
        "legacy": DEFAULT_EXECUTION_MODE,
        STAGED_TRANSLATION_MODE: STAGED_TRANSLATION_MODE,
    }
    if mode not in aliases:
        raise ValueError("execution_mode must be either tool_loop or staged_translation.")
    return aliases[mode]


def select_migration_unit_strategy(config: dict[str, Any]) -> str:
    strategy = non_empty(config.get("migration_unit_strategy")) or DEFAULT_MIGRATION_UNIT_STRATEGY
    strategy = clean_single_line(strategy, "migration_unit_strategy").casefold()
    aliases = {
        "inventory": "inventory",
        "source_inventory": "inventory",
        "task_text": "task_text",
        "explicit_paths": "task_text",
    }
    if strategy not in aliases:
        raise ValueError("migration_unit_strategy must be either inventory or task_text.")
    return aliases[strategy]


def select_staged_translation_config(config: dict[str, Any]) -> StagedTranslationConfig:
    staged = config.get("staged_translation")
    if staged is None:
        staged = {}
    if not isinstance(staged, dict):
        raise ValueError("staged_translation must be a YAML mapping.")

    phases = select_mapping(staged, "phases")
    overview = select_phase_config(
        phases,
        "overview",
        default_min=20,
        default_max=80,
    )
    per_file = select_phase_config(
        phases,
        "per_file",
        default_min=80,
        default_max=240,
    )
    stabilization = select_phase_config(
        phases,
        "stabilization",
        default_min=20,
        default_max=80,
    )

    micro = select_mapping(staged, "per_file_micro_phases")
    folder = select_mapping(staged, "folder_batch_review")
    low_impact = select_mapping(staged, "low_impact_warning")
    inventory = select_mapping(staged, "source_inventory")

    return StagedTranslationConfig(
        min_total_iterations=select_nested_int(
            staged,
            "min_total_iterations",
            DEFAULT_STAGED_MIN_TOTAL_ITERATIONS,
            minimum=0,
        ),
        min_processed_units=select_nested_int(
            staged,
            "min_processed_units",
            DEFAULT_STAGED_MIN_PROCESSED_UNITS,
            minimum=0,
        ),
        max_units_per_run=select_nested_int(
            staged,
            "max_units_per_run",
            DEFAULT_STAGED_MAX_UNITS_PER_RUN,
            minimum=1,
        ),
        enforce_micro_phases=select_nested_bool(
            staged,
            "enforce_micro_phases",
            True,
            prefix="staged_translation",
        ),
        require_source_read=select_nested_bool(
            staged,
            "require_source_read",
            True,
            prefix="staged_translation",
        ),
        require_compare_report=select_nested_bool(
            staged,
            "require_compare_report",
            True,
            prefix="staged_translation",
        ),
        require_progress_update=select_nested_bool(
            staged,
            "require_progress_update",
            True,
            prefix="staged_translation",
        ),
        require_target_effect_or_deferred_reason=select_nested_bool(
            staged,
            "require_target_effect_or_deferred_reason",
            True,
            prefix="staged_translation",
        ),
        overview=overview,
        per_file=per_file,
        stabilization=stabilization,
        per_file_micro_phases=StagedMicroPhasesConfig(
            enabled=select_nested_bool(micro, "enabled", True, prefix="staged_translation.per_file_micro_phases"),
            require_feed=select_nested_bool(
                micro,
                "require_feed",
                True,
                prefix="staged_translation.per_file_micro_phases",
            ),
            require_write=select_nested_bool(
                micro,
                "require_write",
                True,
                prefix="staged_translation.per_file_micro_phases",
            ),
            require_compare_report=select_nested_bool(
                micro,
                "require_compare_report",
                True,
                prefix="staged_translation.per_file_micro_phases",
            ),
            require_revision=select_nested_bool(
                micro,
                "require_revision",
                True,
                prefix="staged_translation.per_file_micro_phases",
            ),
        ),
        folder_batch_review=FolderBatchReviewConfig(
            enabled=select_nested_bool(folder, "enabled", True, prefix="staged_translation.folder_batch_review"),
            max_bundle_chars=select_nested_int(folder, "max_bundle_chars", 80_000, minimum=1),
            require_after_folder_complete=select_nested_bool(
                folder,
                "require_after_folder_complete",
                True,
                prefix="staged_translation.folder_batch_review",
            ),
        ),
        low_impact_warning=LowImpactWarningConfig(
            enabled=select_nested_bool(low_impact, "enabled", True, prefix="staged_translation.low_impact_warning"),
            min_code_changed_paths=select_nested_int(low_impact, "min_code_changed_paths", 1, minimum=0),
            ignore_report_only_changes=select_nested_bool(
                low_impact,
                "ignore_report_only_changes",
                True,
                prefix="staged_translation.low_impact_warning",
            ),
        ),
        source_inventory=SourceInventoryConfig(
            include_globs=select_globs(
                inventory,
                "include_globs",
                ("**/*",),
                prefix="staged_translation.source_inventory",
            ),
            exclude_globs=select_globs(
                inventory,
                "exclude_globs",
                (
                    ".git/**",
                    "**/.DS_Store",
                    "**/build/**",
                    "**/.gradle/**",
                    "**/DerivedData/**",
                    "**/node_modules/**",
                    "**/.cache/**",
                    "**/cache/**",
                    "**/generated/**",
                    "**/*.lock",
                    "**/*lock.json",
                    "**/*.png",
                    "**/*.jpg",
                    "**/*.jpeg",
                    "**/*.gif",
                    "**/*.webp",
                    "**/*.ico",
                    "**/*.pdf",
                    "**/*.zip",
                    "**/*.gz",
                    "**/*.tar",
                ),
                prefix="staged_translation.source_inventory",
            ),
        ),
        progress_files=select_progress_files(staged),
    )


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


def load_config_file(target_root: Path) -> tuple[dict[str, Any], str]:
    config_abs, config_relative = resolve_inside_root(target_root, DEFAULT_CONFIG_PATH, "config_path")
    if not config_abs.exists():
        raise FileNotFoundError(f"Config file not found: {config_relative}")

    if not config_abs.is_file():
        raise ValueError(f"Config path is not a file: {config_relative}")

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

    unsupported = sorted(set(config) - CONFIG_FIELDS)
    if unsupported:
        raise ValueError(
            "Unsupported FORGIS_CONFIG.yml field(s): "
            + ", ".join(unsupported)
            + ". Forgis only accepts generic DeepSeek/file-tool settings."
        )

    return config, config_relative


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


def ensure_task_file(target_root: Path, task_prompt_path: str) -> str:
    task_abs, task_relative = resolve_inside_root(target_root, task_prompt_path, "task_prompt_path")
    if not task_abs.exists():
        raise FileNotFoundError(f"Task file not found: {task_relative}")
    if not task_abs.is_file():
        raise ValueError(f"Task path is not a file: {task_relative}")
    text = task_abs.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise ValueError(f"Task file is empty: {task_relative}")
    return task_relative


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
    if config_path_input != DEFAULT_CONFIG_PATH:
        raise ValueError("Forgis config path is fixed to FORGIS_CONFIG.yml at the target repository root.")

    config, resolved_config_path = load_config_file(target_root)

    target_repo_value = non_empty(target_repo)
    if target_repo_value is not None:
        target_repo_value = clean_single_line(target_repo_value, "target_repo")

    values: dict[str, str | None] = {
        "source_repo": select_value("source_repo", config),
        "source_ref": select_value("source_ref", config, DEFAULT_SOURCE_REF),
        "target_repo": target_repo_value,
        "target_subdir": select_value("target_subdir", config, DEFAULT_TARGET_SUBDIR),
        "task_prompt_path": select_value("task_prompt_path", config, DEFAULT_TASK_PROMPT_PATH),
        "agent_backend": select_value("agent_backend", config, DEFAULT_AGENT_BACKEND),
        "model": select_value("model", config, DEFAULT_MODEL),
        "api_base": select_value("api_base", config, DEFAULT_API_BASE),
        "api_format": select_value("api_format", config, DEFAULT_API_FORMAT),
        "target_branch": select_value("target_branch", config),
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
    if agent_backend != "deepseek":
        raise ValueError("Only agent_backend: deepseek is currently supported.")

    api_format = (values["api_format"] or DEFAULT_API_FORMAT).casefold()
    if api_format != DEFAULT_API_FORMAT:
        raise ValueError("Only api_format: openai-compatible is currently supported.")

    target_subdir = values["target_subdir"] or DEFAULT_TARGET_SUBDIR
    _, target_subdir_relative = resolve_target_subdir(target_root, target_subdir)

    task_prompt_path = values["task_prompt_path"] or DEFAULT_TASK_PROMPT_PATH
    task_prompt_relative = ensure_task_file(target_root, task_prompt_path)

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
    run_agent_config = select_config_bool(config, "run_agent", False)
    confirm_real_run = select_config_bool(config, "confirm_real_run", False)
    model_env = select_model_env(config)
    validation_commands = select_string_list(config, "validation_commands")
    success_checks = select_success_checks(config)
    build_command = select_command_array(config, "build_command")
    test_command = select_command_array(config, "test_command")
    repair_loop_enabled = select_config_bool(
        config,
        "repair_loop_enabled",
        DEFAULT_REPAIR_LOOP_ENABLED,
    )
    max_repair_attempts = select_bounded_int(
        config,
        "max_repair_attempts",
        DEFAULT_MAX_REPAIR_ATTEMPTS,
        minimum=0,
        maximum=MAX_REPAIR_ATTEMPTS_LIMIT,
    )
    repair_requires_diff_check = select_config_bool(
        config,
        "repair_requires_diff_check",
        DEFAULT_REPAIR_REQUIRES_DIFF_CHECK,
    )
    repair_requires_build_or_test = select_config_bool(
        config,
        "repair_requires_build_or_test",
        DEFAULT_REPAIR_REQUIRES_BUILD_OR_TEST,
    )
    repair_stop_on_success = select_config_bool(
        config,
        "repair_stop_on_success",
        DEFAULT_REPAIR_STOP_ON_SUCCESS,
    )
    run_report_enabled = select_config_bool(
        config,
        "run_report_enabled",
        DEFAULT_RUN_REPORT_ENABLED,
    )
    run_report_output_dir = validate_run_report_output_dir(
        config.get("run_report_output_dir", DEFAULT_RUN_REPORT_OUTPUT_DIR),
        target_subdir_relative,
    )
    run_report_include_events = select_config_bool(
        config,
        "run_report_include_events",
        DEFAULT_RUN_REPORT_INCLUDE_EVENTS,
    )
    run_report_max_events = select_bounded_int(
        config,
        "run_report_max_events",
        DEFAULT_RUN_REPORT_MAX_EVENTS,
        minimum=1,
        maximum=MAX_RUN_REPORT_EVENTS_LIMIT,
    )
    run_report_max_chars = select_bounded_int(
        config,
        "run_report_max_chars",
        DEFAULT_RUN_REPORT_MAX_CHARS,
        minimum=1_000,
        maximum=MAX_RUN_REPORT_MAX_CHARS_LIMIT,
    )
    run_report_required = select_config_bool(
        config,
        "run_report_required",
        DEFAULT_RUN_REPORT_REQUIRED,
    )
    skills_enabled = select_config_bool(
        config,
        "skills_enabled",
        DEFAULT_SKILLS_ENABLED,
    )
    selected_skills = select_skill_names(config)
    auto_select_skills = select_config_bool(
        config,
        "auto_select_skills",
        DEFAULT_AUTO_SELECT_SKILLS,
    )
    max_skill_chars = select_bounded_int(
        config,
        "max_skill_chars",
        DEFAULT_MAX_SKILL_CHARS,
        minimum=100,
        maximum=MAX_SKILL_CHARS_LIMIT,
    )
    max_total_skill_chars = select_bounded_int(
        config,
        "max_total_skill_chars",
        DEFAULT_MAX_TOTAL_SKILL_CHARS,
        minimum=100,
        maximum=MAX_TOTAL_SKILL_CHARS_LIMIT,
    )
    migration_scheduler_enabled = select_config_bool(
        config,
        "migration_scheduler_enabled",
        DEFAULT_MIGRATION_SCHEDULER_ENABLED,
    )
    max_migration_units = select_bounded_int(
        config,
        "max_migration_units",
        DEFAULT_MAX_MIGRATION_UNITS,
        minimum=1,
        maximum=MAX_MIGRATION_UNITS_LIMIT,
    )
    migration_unit_strategy = select_migration_unit_strategy(config)
    migration_unit_prioritize_ui = select_config_bool(
        config,
        "migration_unit_prioritize_ui",
        DEFAULT_MIGRATION_UNIT_PRIORITIZE_UI,
    )
    migration_unit_include_tests = select_config_bool(
        config,
        "migration_unit_include_tests",
        DEFAULT_MIGRATION_UNIT_INCLUDE_TESTS,
    )
    migration_unit_include_assets = select_config_bool(
        config,
        "migration_unit_include_assets",
        DEFAULT_MIGRATION_UNIT_INCLUDE_ASSETS,
    )
    migration_plan_persistence_enabled = select_config_bool(
        config,
        "migration_plan_persistence_enabled",
        DEFAULT_MIGRATION_PLAN_PERSISTENCE_ENABLED,
    )
    migration_plan_output_dir = validate_migration_plan_output_dir(
        config.get("migration_plan_output_dir", DEFAULT_MIGRATION_PLAN_OUTPUT_DIR),
        target_subdir_relative,
    )
    migration_plan_filename = validate_migration_plan_filename(
        config.get("migration_plan_filename", DEFAULT_MIGRATION_PLAN_FILENAME),
    )
    migration_plan_resume_enabled = select_config_bool(
        config,
        "migration_plan_resume_enabled",
        DEFAULT_MIGRATION_PLAN_RESUME_ENABLED,
    )
    migration_plan_required = select_config_bool(
        config,
        "migration_plan_required",
        DEFAULT_MIGRATION_PLAN_REQUIRED,
    )
    migration_plan_auto_update_enabled = select_config_bool(
        config,
        "migration_plan_auto_update_enabled",
        DEFAULT_MIGRATION_PLAN_AUTO_UPDATE_ENABLED,
    )
    migration_plan_resume_summary_enabled = select_config_bool(
        config,
        "migration_plan_resume_summary_enabled",
        DEFAULT_MIGRATION_PLAN_RESUME_SUMMARY_ENABLED,
    )
    migration_plan_event_log_max_events = select_bounded_int(
        config,
        "migration_plan_event_log_max_events",
        DEFAULT_MIGRATION_PLAN_EVENT_LOG_MAX_EVENTS,
        minimum=0,
        maximum=MAX_MIGRATION_PLAN_EVENT_LOG_MAX_EVENTS,
    )
    migration_plan_audit_summary_enabled = select_config_bool(
        config,
        "migration_plan_audit_summary_enabled",
        DEFAULT_MIGRATION_PLAN_AUDIT_SUMMARY_ENABLED,
    )
    migration_plan_audit_max_events = select_bounded_int(
        config,
        "migration_plan_audit_max_events",
        DEFAULT_MIGRATION_PLAN_AUDIT_MAX_EVENTS,
        minimum=0,
        maximum=MAX_MIGRATION_PLAN_AUDIT_MAX_EVENTS,
    )
    migration_plan_auto_complete_on_success = select_config_bool(
        config,
        "migration_plan_auto_complete_on_success",
        DEFAULT_MIGRATION_PLAN_AUTO_COMPLETE_ON_SUCCESS,
    )
    migration_plan_requested_active_unit_id = validate_migration_plan_requested_active_unit_id(
        config.get("migration_plan_requested_active_unit_id", DEFAULT_MIGRATION_PLAN_REQUESTED_ACTIVE_UNIT_ID),
    )
    migration_plan_allow_switch_from_blocked = select_config_bool(
        config,
        "migration_plan_allow_switch_from_blocked",
        DEFAULT_MIGRATION_PLAN_ALLOW_SWITCH_FROM_BLOCKED,
    )
    migration_plan_allow_switch_from_completed = select_config_bool(
        config,
        "migration_plan_allow_switch_from_completed",
        DEFAULT_MIGRATION_PLAN_ALLOW_SWITCH_FROM_COMPLETED,
    )
    migration_plan_allow_switch_from_deferred = select_config_bool(
        config,
        "migration_plan_allow_switch_from_deferred",
        DEFAULT_MIGRATION_PLAN_ALLOW_SWITCH_FROM_DEFERRED,
    )
    migration_plan_switch_requires_resume = select_config_bool(
        config,
        "migration_plan_switch_requires_resume",
        DEFAULT_MIGRATION_PLAN_SWITCH_REQUIRES_RESUME,
    )
    migration_plan_switch_reason = validate_migration_plan_switch_reason(
        config.get("migration_plan_switch_reason", DEFAULT_MIGRATION_PLAN_SWITCH_REASON),
    )
    migration_plan_requested_unit_status_unit_id = validate_migration_plan_requested_unit_status_unit_id(
        config.get(
            "migration_plan_requested_unit_status_unit_id",
            DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS_UNIT_ID,
        ),
    )
    migration_plan_requested_unit_status = validate_migration_plan_requested_unit_status(
        config.get("migration_plan_requested_unit_status", DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS),
    )
    migration_plan_requested_unit_status_reason = validate_migration_plan_requested_unit_status_reason(
        config.get(
            "migration_plan_requested_unit_status_reason",
            DEFAULT_MIGRATION_PLAN_REQUESTED_UNIT_STATUS_REASON,
        ),
    )
    migration_plan_allow_manual_complete = select_config_bool(
        config,
        "migration_plan_allow_manual_complete",
        DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_COMPLETE,
    )
    migration_plan_allow_manual_block = select_config_bool(
        config,
        "migration_plan_allow_manual_block",
        DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_BLOCK,
    )
    migration_plan_allow_manual_defer = select_config_bool(
        config,
        "migration_plan_allow_manual_defer",
        DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_DEFER,
    )
    migration_plan_allow_manual_activate = select_config_bool(
        config,
        "migration_plan_allow_manual_activate",
        DEFAULT_MIGRATION_PLAN_ALLOW_MANUAL_ACTIVATE,
    )
    migration_plan_status_update_requires_resume = select_config_bool(
        config,
        "migration_plan_status_update_requires_resume",
        DEFAULT_MIGRATION_PLAN_STATUS_UPDATE_REQUIRES_RESUME,
    )
    visual_validation = select_visual_validation_config(config)
    strict_mode = select_config_bool(config, "strict_mode", False)
    execution_mode = select_execution_mode(config)
    staged_translation = select_staged_translation_config(config)
    default_max_iterations = DEFAULT_MAX_ITERATIONS
    if execution_mode == STAGED_TRANSLATION_MODE and "max_iterations" not in config:
        default_max_iterations = max(
            DEFAULT_MAX_ITERATIONS,
            staged_translation.min_total_iterations,
        )
    max_iterations = select_bounded_int(
        config,
        "max_iterations",
        default_max_iterations,
        minimum=1,
        maximum=MAX_ITERATIONS_LIMIT,
    )
    max_tool_result_chars = select_bounded_int(
        config,
        "max_tool_result_chars",
        DEFAULT_MAX_TOOL_RESULT_CHARS,
        minimum=100,
        maximum=MAX_TOOL_RESULT_CHARS_LIMIT,
    )
    max_command_output_chars = select_bounded_int(
        config,
        "max_command_output_chars",
        DEFAULT_MAX_COMMAND_OUTPUT_CHARS,
        minimum=100,
        maximum=MAX_COMMAND_OUTPUT_CHARS_LIMIT,
    )
    build_timeout_seconds = select_int(
        config,
        "build_timeout_seconds",
        DEFAULT_BUILD_TIMEOUT_SECONDS,
        minimum=1,
    )
    test_timeout_seconds = select_int(
        config,
        "test_timeout_seconds",
        DEFAULT_TEST_TIMEOUT_SECONDS,
        minimum=1,
    )

    if not dry_run_value and not confirm_real_run:
        raise ValueError("Real Forgis runs require confirm_real_run: true in FORGIS_CONFIG.yml.")

    if execution_mode == STAGED_TRANSLATION_MODE and max_iterations < staged_translation.min_total_iterations:
        raise ValueError(
            "max_iterations must be greater than or equal to "
            "staged_translation.min_total_iterations when execution_mode=staged_translation."
        )

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
        api_base=values["api_base"] or DEFAULT_API_BASE,
        api_format=api_format,
        target_branch=values["target_branch"] or "",
        target_base_branch=values["target_base_branch"] or DEFAULT_TARGET_BASE_BRANCH,
        run_log_path=run_log_relative,
        config_path=resolved_config_path,
        config_keys=tuple(sorted(str(key) for key in config.keys())),
        dry_run=dry_run_value,
        run_agent_config=run_agent_config,
        confirm_real_run=confirm_real_run,
        real_run_allowed=real_run_allowed,
        run_agent=run_agent_effective,
        model_env=model_env,
        max_iterations=max_iterations,
        max_tool_result_chars=max_tool_result_chars,
        max_command_output_chars=max_command_output_chars,
        build_command=build_command,
        test_command=test_command,
        build_timeout_seconds=build_timeout_seconds,
        test_timeout_seconds=test_timeout_seconds,
        repair_loop_enabled=repair_loop_enabled,
        max_repair_attempts=max_repair_attempts,
        repair_requires_diff_check=repair_requires_diff_check,
        repair_requires_build_or_test=repair_requires_build_or_test,
        repair_stop_on_success=repair_stop_on_success,
        run_report_enabled=run_report_enabled,
        run_report_output_dir=run_report_output_dir,
        run_report_include_events=run_report_include_events,
        run_report_max_events=run_report_max_events,
        run_report_max_chars=run_report_max_chars,
        run_report_required=run_report_required,
        skills_enabled=skills_enabled,
        selected_skills=selected_skills,
        auto_select_skills=auto_select_skills,
        max_skill_chars=max_skill_chars,
        max_total_skill_chars=max_total_skill_chars,
        migration_scheduler_enabled=migration_scheduler_enabled,
        max_migration_units=max_migration_units,
        migration_unit_strategy=migration_unit_strategy,
        migration_unit_prioritize_ui=migration_unit_prioritize_ui,
        migration_unit_include_tests=migration_unit_include_tests,
        migration_unit_include_assets=migration_unit_include_assets,
        migration_plan_persistence_enabled=migration_plan_persistence_enabled,
        migration_plan_output_dir=migration_plan_output_dir,
        migration_plan_filename=migration_plan_filename,
        migration_plan_resume_enabled=migration_plan_resume_enabled,
        migration_plan_required=migration_plan_required,
        migration_plan_auto_update_enabled=migration_plan_auto_update_enabled,
        migration_plan_resume_summary_enabled=migration_plan_resume_summary_enabled,
        migration_plan_event_log_max_events=migration_plan_event_log_max_events,
        migration_plan_audit_summary_enabled=migration_plan_audit_summary_enabled,
        migration_plan_audit_max_events=migration_plan_audit_max_events,
        migration_plan_auto_complete_on_success=migration_plan_auto_complete_on_success,
        migration_plan_requested_active_unit_id=migration_plan_requested_active_unit_id,
        migration_plan_allow_switch_from_blocked=migration_plan_allow_switch_from_blocked,
        migration_plan_allow_switch_from_completed=migration_plan_allow_switch_from_completed,
        migration_plan_allow_switch_from_deferred=migration_plan_allow_switch_from_deferred,
        migration_plan_switch_requires_resume=migration_plan_switch_requires_resume,
        migration_plan_switch_reason=migration_plan_switch_reason,
        migration_plan_requested_unit_status_unit_id=migration_plan_requested_unit_status_unit_id,
        migration_plan_requested_unit_status=migration_plan_requested_unit_status,
        migration_plan_requested_unit_status_reason=migration_plan_requested_unit_status_reason,
        migration_plan_allow_manual_complete=migration_plan_allow_manual_complete,
        migration_plan_allow_manual_block=migration_plan_allow_manual_block,
        migration_plan_allow_manual_defer=migration_plan_allow_manual_defer,
        migration_plan_allow_manual_activate=migration_plan_allow_manual_activate,
        migration_plan_status_update_requires_resume=migration_plan_status_update_requires_resume,
        validation_commands=validation_commands,
        success_checks=success_checks,
        strict_mode=strict_mode,
        execution_mode=execution_mode,
        visual_validation=visual_validation,
        staged_translation=staged_translation,
    )


def markdown_summary(resolved: ResolvedConfig) -> str:
    config_keys = ", ".join(resolved.config_keys) if resolved.config_keys else "[none]"
    run_agent_note = ""
    if resolved.dry_run and resolved.run_agent_config:
        run_agent_note = " (dry_run=true, DeepSeek execution is disabled.)"
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
    build_command = "configured" if resolved.build_command else "[none]"
    test_command = "configured" if resolved.test_command else "[none]"
    success_checks = (
        f"{len(resolved.success_checks)} configured"
        if resolved.success_checks
        else "[none]"
    )
    selected_skills = ", ".join(resolved.selected_skills) if resolved.selected_skills else "[auto/default]"

    return "\n".join(
        [
            "# Forgis Resolved Configuration",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Config path | `{resolved.config_path}` |",
            f"| Config keys | `{config_keys}` |",
            f"| Source repo | `{resolved.source_repo}` |",
            f"| Source ref | `{resolved.source_ref}` |",
            f"| Target repo | `{resolved.target_repo}` |",
            f"| Target base branch | `{resolved.target_base_branch}` |",
            f"| Target branch | `{resolved.target_branch}` |",
            f"| Agent backend | `{resolved.agent_backend}` |",
            f"| Execution mode | `{resolved.execution_mode}` |",
            f"| visual_validation.enabled | `{resolved.visual_validation.enabled}` |",
            f"| visual_validation.provider | `{resolved.visual_validation.provider}` |",
            f"| visual_validation.max_visual_iterations | `{resolved.visual_validation.max_visual_iterations}` |",
            f"| visual_validation.require_reference_first | `{str(resolved.visual_validation.require_reference_first).lower()}` |",
            f"| visual_validation.upload_visual_artifact | `{str(resolved.visual_validation.upload_visual_artifact).lower()}` |",
            f"| Task prompt path | `{resolved.task_prompt_path}` |",
            f"| Target subdir | `{resolved.target_subdir}` |",
            f"| Run log path | `{resolved.run_log_path}` |",
            f"| Model | `{resolved.model}` |",
            f"| API base | `{resolved.api_base}` |",
            f"| API format | `{resolved.api_format}` |",
            f"| Model env mapping | `{model_env}` |",
            f"| Max iterations | `{resolved.max_iterations}` |",
            f"| Max tool result chars | `{resolved.max_tool_result_chars}` |",
            f"| Max command output chars | `{resolved.max_command_output_chars}` |",
            f"| build_command | `{build_command}` |",
            f"| test_command | `{test_command}` |",
            f"| build_timeout_seconds | `{resolved.build_timeout_seconds}` |",
            f"| test_timeout_seconds | `{resolved.test_timeout_seconds}` |",
            f"| repair_loop_enabled | `{str(resolved.repair_loop_enabled).lower()}` |",
            f"| max_repair_attempts | `{resolved.max_repair_attempts}` |",
            f"| repair_requires_diff_check | `{str(resolved.repair_requires_diff_check).lower()}` |",
            f"| repair_requires_build_or_test | `{str(resolved.repair_requires_build_or_test).lower()}` |",
            f"| repair_stop_on_success | `{str(resolved.repair_stop_on_success).lower()}` |",
            f"| run_report_enabled | `{str(resolved.run_report_enabled).lower()}` |",
            f"| run_report_output_dir | `{resolved.run_report_output_dir}` |",
            f"| run_report_include_events | `{str(resolved.run_report_include_events).lower()}` |",
            f"| run_report_max_events | `{resolved.run_report_max_events}` |",
            f"| run_report_max_chars | `{resolved.run_report_max_chars}` |",
            f"| run_report_required | `{str(resolved.run_report_required).lower()}` |",
            f"| skills_enabled | `{str(resolved.skills_enabled).lower()}` |",
            f"| selected_skills | `{selected_skills}` |",
            f"| auto_select_skills | `{str(resolved.auto_select_skills).lower()}` |",
            f"| max_skill_chars | `{resolved.max_skill_chars}` |",
            f"| max_total_skill_chars | `{resolved.max_total_skill_chars}` |",
            f"| migration_scheduler_enabled | `{str(resolved.migration_scheduler_enabled).lower()}` |",
            f"| max_migration_units | `{resolved.max_migration_units}` |",
            f"| migration_unit_strategy | `{resolved.migration_unit_strategy}` |",
            f"| migration_unit_prioritize_ui | `{str(resolved.migration_unit_prioritize_ui).lower()}` |",
            f"| migration_unit_include_tests | `{str(resolved.migration_unit_include_tests).lower()}` |",
            f"| migration_unit_include_assets | `{str(resolved.migration_unit_include_assets).lower()}` |",
            f"| migration_plan_persistence_enabled | `{str(resolved.migration_plan_persistence_enabled).lower()}` |",
            f"| migration_plan_output_dir | `{resolved.migration_plan_output_dir}` |",
            f"| migration_plan_filename | `{resolved.migration_plan_filename}` |",
            f"| migration_plan_resume_enabled | `{str(resolved.migration_plan_resume_enabled).lower()}` |",
            f"| migration_plan_required | `{str(resolved.migration_plan_required).lower()}` |",
            f"| migration_plan_auto_update_enabled | `{str(resolved.migration_plan_auto_update_enabled).lower()}` |",
            f"| migration_plan_resume_summary_enabled | `{str(resolved.migration_plan_resume_summary_enabled).lower()}` |",
            f"| migration_plan_event_log_max_events | `{resolved.migration_plan_event_log_max_events}` |",
            f"| migration_plan_audit_summary_enabled | `{str(resolved.migration_plan_audit_summary_enabled).lower()}` |",
            f"| migration_plan_audit_max_events | `{resolved.migration_plan_audit_max_events}` |",
            f"| migration_plan_auto_complete_on_success | `{str(resolved.migration_plan_auto_complete_on_success).lower()}` |",
            f"| migration_plan_requested_active_unit_id | `{resolved.migration_plan_requested_active_unit_id or '[none]'}` |",
            f"| migration_plan_allow_switch_from_blocked | `{str(resolved.migration_plan_allow_switch_from_blocked).lower()}` |",
            f"| migration_plan_allow_switch_from_completed | `{str(resolved.migration_plan_allow_switch_from_completed).lower()}` |",
            f"| migration_plan_allow_switch_from_deferred | `{str(resolved.migration_plan_allow_switch_from_deferred).lower()}` |",
            f"| migration_plan_switch_requires_resume | `{str(resolved.migration_plan_switch_requires_resume).lower()}` |",
            f"| migration_plan_switch_reason | `{resolved.migration_plan_switch_reason or '[none]'}` |",
            f"| migration_plan_requested_unit_status_unit_id | `{resolved.migration_plan_requested_unit_status_unit_id or '[none]'}` |",
            f"| migration_plan_requested_unit_status | `{resolved.migration_plan_requested_unit_status or '[none]'}` |",
            f"| migration_plan_requested_unit_status_reason | `{resolved.migration_plan_requested_unit_status_reason or '[none]'}` |",
            f"| migration_plan_allow_manual_complete | `{str(resolved.migration_plan_allow_manual_complete).lower()}` |",
            f"| migration_plan_allow_manual_block | `{str(resolved.migration_plan_allow_manual_block).lower()}` |",
            f"| migration_plan_allow_manual_defer | `{str(resolved.migration_plan_allow_manual_defer).lower()}` |",
            f"| migration_plan_allow_manual_activate | `{str(resolved.migration_plan_allow_manual_activate).lower()}` |",
            f"| migration_plan_status_update_requires_resume | `{str(resolved.migration_plan_status_update_requires_resume).lower()}` |",
            f"| validation_commands | `{validation_commands}` |",
            f"| success_checks | `{success_checks}` |",
            f"| strict_mode | `{str(resolved.strict_mode).lower()}` |",
            f"| staged_translation min_total_iterations | `{resolved.staged_translation.min_total_iterations}` |",
            f"| staged_translation min_processed_units | `{resolved.staged_translation.min_processed_units}` |",
            f"| staged_translation max_units_per_run | `{resolved.staged_translation.max_units_per_run}` |",
            f"| dry_run config value | `{str(resolved.dry_run).lower()}` |",
            f"| run_agent config value | `{str(resolved.run_agent_config).lower()}` |",
            f"| confirm_real_run config value | `{str(resolved.confirm_real_run).lower()}` |",
            f"| Effective dry_run | `{str(resolved.dry_run).lower()}` |",
            f"| Effective run_agent | `{str(resolved.run_agent).lower()}`{run_agent_note} |",
            f"| Writable scope | `{resolved.target_subdir}/` |",
            f"| Read-only target inputs | `{resolved.config_path}`, `{resolved.task_prompt_path}` |",
            f"| Real run allowed | `{str(resolved.real_run_allowed and resolved.run_agent).lower()}` |",
            "",
            "Config path is fixed to FORGIS_CONFIG.yml in the main workflow.",
            "DeepSeek execution is allowed only when dry_run=false, run_agent=true, and confirm_real_run=true.",
        ]
    )
