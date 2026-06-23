from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


DEFAULT_TIMEOUT_SECONDS = 120
MAX_ERROR_DETAIL_CHARS = 300


class OpenAICompatibleClientError(RuntimeError):
    pass


SECRET_MARKERS_RE = re.compile(
    r"(?i)(authorization|api[_-]?key|token|secret|cookie)\s*[:=]\s*[^,\s}\]]+"
)
BEARER_RE = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")


def sanitize_provider_text(text: str, *, secret_values: tuple[str, ...] = (), limit: int = MAX_ERROR_DETAIL_CHARS) -> str:
    safe = str(text or "")
    for value in secret_values:
        if value:
            safe = safe.replace(value, "[REDACTED]")
    safe = BEARER_RE.sub("Bearer [REDACTED]", safe)
    safe = SECRET_MARKERS_RE.sub(lambda m: m.group(1) + "=[REDACTED]", safe)
    safe = safe.replace("\x00", "")
    if len(safe) > limit:
        safe = safe[:limit] + "...[truncated]"
    return safe


def chat_completions_url(api_base: str) -> str:
    text = str(api_base or "").strip()
    if not text:
        raise OpenAICompatibleClientError("OpenAI-compatible API base URL is empty.")
    lowered = text.casefold().rstrip("/")
    if lowered.endswith("/chat/completions"):
        return text.rstrip("/")
    return text.rstrip("/") + "/chat/completions"


def _error_detail(body: str, *, secret_values: tuple[str, ...]) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return sanitize_provider_text(message.strip(), secret_values=secret_values)
        message = parsed.get("message")
        if isinstance(message, str) and message.strip():
            return sanitize_provider_text(message.strip(), secret_values=secret_values)
    return sanitize_provider_text(body, secret_values=secret_values)


def _validate_tool_calls(tool_calls: Any) -> None:
    if tool_calls is None:
        return
    if not isinstance(tool_calls, list):
        raise OpenAICompatibleClientError("OpenAI-compatible API returned malformed tool_calls.")
    for index, call in enumerate(tool_calls):
        if not isinstance(call, dict):
            raise OpenAICompatibleClientError(f"OpenAI-compatible API returned malformed tool_calls[{index}].")
        function = call.get("function")
        if not isinstance(function, dict):
            raise OpenAICompatibleClientError(f"OpenAI-compatible API returned malformed tool_calls[{index}].function.")
        name = function.get("name")
        arguments = function.get("arguments")
        if not isinstance(name, str) or not name.strip():
            raise OpenAICompatibleClientError(f"OpenAI-compatible API returned malformed tool_calls[{index}].function.name.")
        if not isinstance(arguments, str):
            raise OpenAICompatibleClientError(
                f"OpenAI-compatible API returned malformed tool_calls[{index}].function.arguments."
            )


def validate_chat_completion_response(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OpenAICompatibleClientError("OpenAI-compatible API returned an invalid response shape.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise OpenAICompatibleClientError("OpenAI-compatible API returned no choices.")
    first = choices[0]
    if not isinstance(first, dict):
        raise OpenAICompatibleClientError("OpenAI-compatible API returned malformed choices[0].")
    message = first.get("message")
    if not isinstance(message, dict):
        raise OpenAICompatibleClientError("OpenAI-compatible API returned malformed choices[0].message.")
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        raise OpenAICompatibleClientError("OpenAI-compatible API returned malformed assistant message content.")
    _validate_tool_calls(message.get("tool_calls"))
    return payload


@dataclass(frozen=True)
class OpenAICompatibleClient:
    api_base: str
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS

    def chat(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(messages, list) or not messages:
            raise OpenAICompatibleClientError("messages must be a non-empty list.")
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
        }
        if tools is not None:
            payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            chat_completions_url(self.api_base),
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            detail = _error_detail(body_text, secret_values=(self.api_key,))
            suffix = f": {detail}" if detail else ""
            raise OpenAICompatibleClientError(
                f"OpenAI-compatible API request failed with HTTP {exc.code}{suffix}"
            ) from exc
        except urllib.error.URLError as exc:
            reason = sanitize_provider_text(str(exc.reason), secret_values=(self.api_key,))
            raise OpenAICompatibleClientError(f"OpenAI-compatible API request failed: {reason}") from exc

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAICompatibleClientError("OpenAI-compatible API returned invalid JSON.") from exc
        return validate_chat_completion_response(parsed)
