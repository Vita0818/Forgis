#!/usr/bin/env python3

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Callable

from deepseek_agent import DeepSeekClient, TOOL_DEFINITIONS, initial_messages
from file_tools import READ_TOOLS, WRITE_TOOLS, FileToolSandbox, ToolError
from forgis_config import ResolvedConfig, resolve_config


ClientFactory = Callable[[ResolvedConfig, dict[str, str]], Any]
SECRET_PATH_WORDS = re.compile(r"(secret|token|credential|password|api[_-]?key|private)", re.IGNORECASE)


@dataclasses.dataclass(frozen=True)
class ToolLoopResult:
    executed: bool
    status: str
    final_summary: str
    iterations: int
    tool_call_count: int
    read_tool_count: int
    write_tool_count: int
    operation_log: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        loaded = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise ToolError(f"Tool arguments are not valid JSON: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ToolError("Tool arguments must decode to a JSON object.")
    return loaded


def message_from_response(response: dict[str, Any]) -> dict[str, Any]:
    if "choices" not in response and "message" in response:
        message = response["message"]
    else:
        choices = response.get("choices") or []
        if not choices:
            raise RuntimeError("DeepSeek response did not contain choices.")
        message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise RuntimeError("DeepSeek response message is not an object.")
    return message


def assistant_tool_call_message(message: dict[str, Any], tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    history_message: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content"),
        "tool_calls": tool_calls,
    }
    if "reasoning_content" in message:
        history_message["reasoning_content"] = message["reasoning_content"]
    return history_message


def extract_final_summary(content: str) -> str:
    text = content.strip()
    if not text:
        return ""
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(loaded, dict):
        value = loaded.get("final_summary") or loaded.get("summary") or loaded.get("done")
        if value is not None:
            return str(value)
    return text


def format_tool_result(result: dict[str, Any], max_chars: int) -> str:
    text = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return text
    note = f'... [Forgis tool result truncated after {max_chars} characters]'
    keep = max(0, max_chars - len(note))
    return text[:keep] + note


def safe_log(message: str) -> None:
    print(f"[forgis] {message}", flush=True)


def sanitize_log_path(value: Any) -> str:
    text = str(value if value is not None else "").strip().replace("\\", "/")
    if not text:
        return "[none]"
    parts: list[str] = []
    for part in text.split("/"):
        if not part:
            continue
        parts.append("[redacted]" if SECRET_PATH_WORDS.search(part) else part)
    sanitized = "/".join(parts) or "[root]"
    if len(sanitized) <= 160:
        return sanitized
    return sanitized[:80] + ".../" + sanitized[-60:]


def tool_call_log_details(name: str, arguments: dict[str, Any] | None) -> str:
    if not arguments:
        return "path=[unavailable]"
    parts: list[str] = []
    if "path" in arguments:
        parts.append(f"path={sanitize_log_path(arguments.get('path'))}")
    for key in ("start_line", "max_lines", "max_depth"):
        if key in arguments and arguments[key] is not None:
            parts.append(f"{key}={arguments[key]}")
    if name in WRITE_TOOLS and "path" not in arguments:
        parts.append("path=[unavailable]")
    return " ".join(parts) if parts else "path=[none]"


def changed_paths_from_operations(operation_log: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(item.get("path", ""))
            for item in operation_log
            if item.get("path")
        }
    )


def log_tool_loop_finished(
    *,
    iterations: int,
    tool_call_count: int,
    sandbox: FileToolSandbox,
) -> None:
    changed_paths = changed_paths_from_operations(sandbox.operation_log())
    safe_log(
        "tool loop finished: "
        f"iterations={iterations} "
        f"tool_calls={tool_call_count} "
        f"reads={sandbox.read_count} "
        f"writes={sandbox.write_count} "
        f"changed_paths={len(changed_paths)}"
    )


def run_tool_loop(
    *,
    config: ResolvedConfig,
    source_root: Path,
    target_root: Path,
    environ: dict[str, str] | None = None,
    client_factory: ClientFactory | None = None,
) -> ToolLoopResult:
    env = dict(os.environ if environ is None else environ)
    if config.dry_run:
        safe_log("dry_run=true; skipping DeepSeek tool loop")
        return ToolLoopResult(
            executed=False,
            status="skipped-dry-run",
            final_summary="dry_run=true; DeepSeek was not called.",
            iterations=0,
            tool_call_count=0,
            read_tool_count=0,
            write_tool_count=0,
            operation_log=[],
        )
    if not config.run_agent:
        safe_log("run_agent=false; skipping DeepSeek tool loop")
        return ToolLoopResult(
            executed=False,
            status="skipped-run-agent-false",
            final_summary="run_agent=false; DeepSeek was not called.",
            iterations=0,
            tool_call_count=0,
            read_tool_count=0,
            write_tool_count=0,
            operation_log=[],
        )

    sandbox = FileToolSandbox(
        source_root=source_root,
        target_root=target_root,
        target_subdir=config.target_subdir,
        config_path=config.config_path,
        task_path=config.task_prompt_path,
        max_result_chars=config.max_tool_result_chars,
    )
    factory = client_factory or (lambda cfg, local_env: DeepSeekClient.from_config(cfg, local_env))
    client = factory(config, env)
    messages: list[dict[str, Any]] = initial_messages(config)
    tool_call_count = 0
    safe_log(f"tool loop started: max_iterations={config.max_iterations}")

    for iteration in range(1, config.max_iterations + 1):
        safe_log(f"iteration {iteration}/{config.max_iterations}: requesting model")
        response = client.chat(messages, TOOL_DEFINITIONS)
        message = message_from_response(response)
        tool_calls = message.get("tool_calls") or []
        content = message.get("content") or ""
        has_assistant_message = "yes" if message else "no"

        if not tool_calls:
            summary = extract_final_summary(str(content))
            safe_log(
                f"iteration {iteration}/{config.max_iterations}: "
                f"assistant_message={has_assistant_message} tool_calls=0 "
                f"final_summary={'yes' if summary else 'no'}"
            )
            if summary:
                safe_log("final_summary received")
            log_tool_loop_finished(
                iterations=iteration,
                tool_call_count=tool_call_count,
                sandbox=sandbox,
            )
            return ToolLoopResult(
                executed=True,
                status="completed",
                final_summary=summary or "DeepSeek returned no final summary.",
                iterations=iteration,
                tool_call_count=tool_call_count,
                read_tool_count=sandbox.read_count,
                write_tool_count=sandbox.write_count,
                operation_log=sandbox.operation_log(),
            )

        messages.append(assistant_tool_call_message(message, tool_calls))
        safe_log(
            f"iteration {iteration}/{config.max_iterations}: "
            f"assistant_message={has_assistant_message} "
            f"model returned {len(tool_calls)} tool calls "
            "final_summary=no"
        )

        for call in tool_calls:
            function = call.get("function") or {}
            name = function.get("name", "")
            raw_arguments = function.get("arguments", "{}")
            tool_call_count += 1
            arguments: dict[str, Any] | None = None
            status = "error"
            try:
                arguments = parse_tool_arguments(raw_arguments)
                safe_log(
                    f"tool call {tool_call_count}: iteration={iteration} "
                    f"{name or '[unknown]'} {tool_call_log_details(name, arguments)}"
                )
                result = sandbox.invoke(name, arguments)
                status = "ok" if result.get("ok") else "error"
            except ToolError as exc:
                if arguments is None:
                    safe_log(
                        f"tool call {tool_call_count}: iteration={iteration} "
                        f"{name or '[unknown]'} path=[unavailable]"
                    )
                result = {"ok": False, "error": str(exc)}
                status = "blocked"
            except Exception as exc:
                if arguments is None:
                    safe_log(
                        f"tool call {tool_call_count}: iteration={iteration} "
                        f"{name or '[unknown]'} path=[unavailable]"
                    )
                result = {"ok": False, "error": str(exc)}
                status = "error"
            full_result_text = json.dumps(result, ensure_ascii=False, sort_keys=True)
            formatted_result = format_tool_result(result, config.max_tool_result_chars)
            result_truncated = bool(result.get("truncated")) or len(full_result_text) > config.max_tool_result_chars
            changed_paths = changed_paths_from_operations(sandbox.operation_log())
            safe_log(
                f"tool call {tool_call_count} result: {status} "
                f"chars={len(formatted_result)} "
                f"truncated={str(result_truncated).lower()} "
                f"total_tool_calls={tool_call_count} "
                f"reads={sandbox.read_count} "
                f"writes={sandbox.write_count} "
                f"changed_paths={len(changed_paths)}"
            )
            if name in WRITE_TOOLS and result.get("ok") and result.get("path"):
                safe_log(f"tool call {tool_call_count} changed_path={sanitize_log_path(result.get('path'))}")
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.get("id", f"tool-{tool_call_count}"),
                    "name": name,
                    "content": formatted_result,
                }
            )

    safe_log(f"max_iterations reached: {config.max_iterations}")
    log_tool_loop_finished(
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        sandbox=sandbox,
    )
    return ToolLoopResult(
        executed=True,
        status="max-iterations",
        final_summary=f"DeepSeek tool loop stopped after max_iterations={config.max_iterations}.",
        iterations=config.max_iterations,
        tool_call_count=tool_call_count,
        read_tool_count=sandbox.read_count,
        write_tool_count=sandbox.write_count,
        operation_log=sandbox.operation_log(),
    )


def write_status(path: str, result: ToolLoopResult) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    safe_summary = result.final_summary.replace("\n", "\\n")
    values = {
        "deepseek_executed": "true" if result.executed else "false",
        "deepseek_status": result.status,
        "tool_call_count": str(result.tool_call_count),
        "read_tool_count": str(result.read_tool_count),
        "write_tool_count": str(result.write_tool_count),
        "final_summary": safe_summary,
    }
    output.write_text(
        "\n".join(f"{key}={shlex.quote(value)}" for key, value in values.items()) + "\n",
        encoding="utf-8",
    )


def write_json(path: str, payload: Any) -> None:
    if not path:
        return
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Forgis DeepSeek tool loop")
    parser.add_argument("--source", required=True, help="Path to the checked-out source repository")
    parser.add_argument("--target", required=True, help="Path to the checked-out target repository")
    parser.add_argument("--target-repo", required=True, help="Target repository, for example owner/target-repo")
    parser.add_argument("--status-output", default="")
    parser.add_argument("--operation-log-output", default="")
    parser.add_argument("--summary-output", default="")
    args = parser.parse_args()

    config = resolve_config(target_root=Path(args.target), target_repo=args.target_repo)
    result = run_tool_loop(
        config=config,
        source_root=Path(args.source),
        target_root=Path(args.target),
        environ=dict(os.environ),
    )
    write_status(args.status_output, result)
    write_json(args.operation_log_output, result.operation_log)
    write_json(args.summary_output, result.as_dict())
    print(json.dumps(result.as_dict(), indent=2, ensure_ascii=False, sort_keys=True))

    if result.status == "max-iterations":
        raise RuntimeError(result.final_summary)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
