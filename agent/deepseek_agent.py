from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from forgis_config import ResolvedConfig
from model_env import require_model_env_values


SYSTEM_MESSAGE = """You are running inside Forgis.
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


def initial_messages(config: ResolvedConfig) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {
            "role": "user",
            "content": "\n".join(
                [
                    "Forgis virtual paths:",
                    "- task: configured task file",
                    "- config: FORGIS_CONFIG.yml",
                    "- source/: source repository root",
                    "- target/: target repository root",
                    "- target_subdir/: writable target_subdir",
                    "",
                    f"target_subdir: {config.target_subdir}",
                    f"run_log_path: {config.run_log_path}",
                    "Use file tools to inspect source and target paths as needed.",
                ]
            ),
        },
    ]


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
]


@dataclass(frozen=True)
class DeepSeekClient:
    api_base: str
    api_key: str
    model: str
    timeout_seconds: int = 120

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
        return cls(api_base=config.api_base, api_key=api_key, model=config.model)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.api_base.rstrip("/") + "/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DeepSeek API request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"DeepSeek API request failed: {exc.reason}") from exc
