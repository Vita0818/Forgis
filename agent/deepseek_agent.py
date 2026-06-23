from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forgis_config import ResolvedConfig
from model_env import require_model_env_values
from openai_compatible_client import DEFAULT_TIMEOUT_SECONDS, OpenAICompatibleClient
from skill_loader import SkillSelection, render_selected_skills, select_skills


LEGACY_SYSTEM_MESSAGE = """You are running inside Forgis.
You do not have direct filesystem access.
You can only use the file tools provided by Forgis.
First read the task file with read_file("task").
Follow the task file.
You can read the source repo through source/... paths.
You can only write inside target_subdir.
You must not write the source repo.
You must not write the target repo root.
You must not write the config file or task file.
When finished, return final_summary.
"""

SYSTEM_MESSAGE = LEGACY_SYSTEM_MESSAGE
SYSTEM_AGENT_V3_PATH = Path(__file__).resolve().parents[1] / "prompts" / "system_agent_v3.md"


def system_message() -> str:
    try:
        text = SYSTEM_AGENT_V3_PATH.read_text(encoding="utf-8")
    except OSError:
        return LEGACY_SYSTEM_MESSAGE
    return text.strip() or LEGACY_SYSTEM_MESSAGE


def _read_task_text_for_skills(target_root: Path | None, config: ResolvedConfig) -> str:
    if target_root is None:
        return ""
    try:
        path = (target_root / config.task_prompt_path).resolve()
        root = target_root.resolve()
    except OSError:
        return ""
    if not path.is_relative_to(root) or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def build_skill_selection(
    config: ResolvedConfig,
    *,
    target_root: Path | None = None,
    task_text: str | None = None,
    stack_hint: str | None = None,
) -> SkillSelection:
    effective_task_text = task_text if task_text is not None else _read_task_text_for_skills(target_root, config)
    return select_skills(config, effective_task_text, stack_hint=stack_hint)


def initial_messages(
    config: ResolvedConfig,
    skills_section: str = "",
    active_migration_unit_context: str = "",
) -> list[dict[str, str]]:
    user_lines = [
        "Forgis virtual paths:",
        "- task: configured task file",
        "- config: FORGIS_CONFIG.yml",
        "- source/: source repository root",
        "- target/: target repository root",
        "- target_subdir/: writable target_subdir",
        "",
        f"target_subdir: {config.target_subdir}",
        f"run_log_path: {config.run_log_path}",
        "Use tools to inspect source and target paths as needed.",
        "After modifying target files, use git_diff to inspect your changes before final_summary.",
        "Use run_build and run_tests when configured and useful; read their short failure summaries before repair edits.",
        "If the repair loop blocks a build/test or edit, stop blind repairs and report the blocker.",
    ]
    if skills_section.strip():
        user_lines.extend(["", skills_section.strip()])
    if active_migration_unit_context.strip():
        user_lines.extend(["", active_migration_unit_context.strip()])
    return [
        {"role": "system", "content": system_message()},
        {"role": "user", "content": "\n".join(user_lines)},
    ]


def build_initial_messages(
    config: ResolvedConfig,
    *,
    target_root: Path | None = None,
    task_text: str | None = None,
    stack_hint: str | None = None,
    active_migration_unit_context: str = "",
) -> tuple[list[dict[str, str]], SkillSelection]:
    selection = build_skill_selection(
        config,
        target_root=target_root,
        task_text=task_text,
        stack_hint=stack_hint,
    )
    return initial_messages(config, render_selected_skills(selection), active_migration_unit_context), selection


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List one directory inside an allowed Forgis virtual path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tree",
            "description": "Return a bounded file tree for an allowed Forgis virtual path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_depth": {"type": "integer", "minimum": 0},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a text file from an allowed Forgis virtual path with optional line pagination.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "minimum": 1},
                    "max_lines": {"type": "integer", "minimum": 1},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "file_exists",
            "description": "Check whether a path exists inside an allowed Forgis virtual path.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_text",
            "description": "Search text in source, target, or target_subdir without leaving allowed Forgis roots.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "root": {"type": "string", "default": "target"},
                    "regex": {"type": "boolean", "default": False},
                    "case_sensitive": {"type": "boolean", "default": False},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_status",
            "description": "Return a bounded git status summary for the target workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_entries": {"type": "integer", "minimum": 1, "maximum": 500, "default": 200},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Return the current target workspace git diff, bounded by max_chars.",
            "parameters": {
                "type": "object",
                "properties": {
                    "max_chars": {"type": "integer", "minimum": 100, "maximum": 200000, "default": 20000},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mkdir",
            "description": "Create a directory inside target_subdir.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write a UTF-8 text file inside target_subdir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_file",
            "description": "Append UTF-8 text to a file inside target_subdir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Make a small exact text replacement in an existing UTF-8 file inside target_subdir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"},
                    "expected_replacements": {"type": "integer", "minimum": 1, "default": 1},
                },
                "required": ["path", "old_text", "new_text"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": "Apply a unified diff hunk to one existing UTF-8 file inside target_subdir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "patch": {"type": "string"},
                },
                "required": ["path", "patch"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_file",
            "description": "Delete a file inside target_subdir.",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_visual_references",
            "description": (
                "List configured reference screenshot images for reference-guided visual migration. "
                "This is visual-only: it returns Forgis virtual image paths and never returns source code, "
                "text files, secrets, raw image bytes, or base64."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum reference screenshot paths to return.",
                        "minimum": 1,
                        "maximum": 200,
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_visual_reference",
            "description": (
                "Inspect one reference screenshot image through the configured visual provider for visual guidance. "
                "Use only Forgis virtual image paths; do not send source code, text files, secrets, or config."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Forgis virtual image path under source/, target/, or target_subdir/.",
                        "pattern": "^(?!/)(?!~)(?![A-Za-z]:[\\\\/])(?!.*(?:^|/)\\.\\.(?:/|$)).+\\.(png|jpg|jpeg|webp)$",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Short visual inspection goal. Do not include code, secrets, or full file contents.",
                        "maxLength": 500,
                    },
                },
                "required": ["path", "goal"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inspect_visual_actual",
            "description": (
                "Inspect one actual rendered target screenshot image through the configured visual provider. "
                "Use only Forgis virtual image paths; do not send source code, text files, secrets, or config."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Forgis virtual image path under target/ or target_subdir/.",
                        "pattern": "^(?!/)(?!~)(?![A-Za-z]:[\\\\/])(?!.*(?:^|/)\\.\\.(?:/|$)).+\\.(png|jpg|jpeg|webp)$",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Short visual inspection goal. Do not include code, secrets, or full file contents.",
                        "maxLength": 500,
                    },
                },
                "required": ["path", "goal"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_visual_screenshots",
            "description": (
                "Compare a reference screenshot image and an actual rendered target screenshot image. "
                "This is visual-only and must not be used for source code, text files, secrets, or config."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference_path": {
                        "type": "string",
                        "description": "Forgis virtual reference image path under source/, target/, or target_subdir/.",
                        "pattern": "^(?!/)(?!~)(?![A-Za-z]:[\\\\/])(?!.*(?:^|/)\\.\\.(?:/|$)).+\\.(png|jpg|jpeg|webp)$",
                    },
                    "actual_path": {
                        "type": "string",
                        "description": "Forgis virtual actual screenshot path under target/ or target_subdir/.",
                        "pattern": "^(?!/)(?!~)(?![A-Za-z]:[\\\\/])(?!.*(?:^|/)\\.\\.(?:/|$)).+\\.(png|jpg|jpeg|webp)$",
                    },
                    "goal": {
                        "type": "string",
                        "description": "Short visual comparison goal. Do not include code, secrets, or full file contents.",
                        "maxLength": 500,
                    },
                },
                "required": ["reference_path", "actual_path", "goal"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a conservative allowlisted command inside target_subdir without shell=True.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "cwd": {"type": "string", "default": "target_subdir"},
                    "timeout_seconds": {"type": "integer", "minimum": 1, "maximum": 60, "default": 10},
                    "max_output_chars": {"type": "integer", "minimum": 100, "maximum": 50000, "default": 8000},
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_build",
            "description": "Run the configured build_command inside target_subdir and return a structured short result.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the configured test_command inside target_subdir and return a structured short result.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class DeepSeekClient:
    api_base: str
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    @classmethod
    def from_config(
        cls,
        config: ResolvedConfig,
        environ: Mapping[str, str] | None = None,
    ) -> "DeepSeekClient":
        env = os.environ if environ is None else environ
        values = require_model_env_values(config.model_env, env)
        api_key = (
            values.get("DEEPSEEK_API_KEY")
            or values.get("FORGIS_MODEL_API_KEY")
            or next(iter(values.values()))
        )
        return cls(
            api_base=config.api_base,
            api_key=api_key,
            model=config.model,
            timeout_seconds=getattr(config, "request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        )

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        client = OpenAICompatibleClient(
            api_base=self.api_base,
            api_key=self.api_key,
            model=self.model,
            timeout_seconds=self.timeout_seconds,
        )
        return client.chat(messages=messages, tools=tools, tool_choice="auto")
