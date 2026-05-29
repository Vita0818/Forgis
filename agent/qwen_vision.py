from __future__ import annotations

import base64
import dataclasses
import json
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from visual_evidence import (
    HOST_ENV_BLOCKED,
    QWEN_PERMISSION_GATED,
    QWEN_UNAVAILABLE_IN_SESSION,
    sanitize_visual_path_label,
    validate_visual_image_path,
)


PROVIDER = "qwen"
MODE_INSPECT = "inspect"
MODE_COMPARE = "compare"
DEFAULT_QWEN_MODEL = "qwen-vl"
DEFAULT_QWEN_API_BASE = "https://dashscope.aliyuncs.com"
DEFAULT_QWEN_TIMEOUT_SECONDS = 60
MAX_SUMMARY_CHARS = 1000
MAX_FINDING_CHARS = 300
MAX_FINDINGS = 20
MAX_LIMITATIONS = 12

SECRET_VALUE_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|CREDENTIAL|API[_-]?KEY|PRIVATE)[A-Z0-9_]*)\s*[:=]\s*([^\s,;]+)"
)
AUTH_RE = re.compile(r"(?i)\b(authorization\s*:\s*bearer)\s+([^\s,;]+)")
BASE64_RE = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")


class QwenVisionProviderError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class QwenVisionResult:
    ok: bool
    provider: str
    mode: str
    summary: str
    findings: tuple[str, ...]
    limitations: tuple[str, ...]
    blocker: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": bool(self.ok),
            "provider": self.provider,
            "mode": self.mode,
            "summary": self.summary,
            "findings": list(self.findings),
            "limitations": list(self.limitations),
            "blocker": self.blocker,
        }


def _sanitize_text(value: Any, *, limit: int, secret_values: tuple[str, ...] = ()) -> str:
    text = str(value if value is not None else "")
    text = text.replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    for secret in secret_values:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = SECRET_VALUE_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = AUTH_RE.sub(lambda match: f"{match.group(1)} [redacted]", text)
    text = BASE64_RE.sub("[redacted-binary]", text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _safe_tuple(value: Any, *, limit: int, max_items: int, secret_values: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        values = [] if value is None or value == "" else [value]
    else:
        values = list(value)
    output: list[str] = []
    for item in values[:max_items]:
        text = _sanitize_text(item, limit=limit, secret_values=secret_values)
        if text:
            output.append(text)
    return tuple(output)


def _safe_api_url(api_base: str) -> str:
    text = _sanitize_text(api_base, limit=300)
    if not text:
        raise QwenVisionProviderError("Qwen vision API base is empty.")
    if not (text.startswith("https://") or text.startswith("http://")):
        raise QwenVisionProviderError("Qwen vision API base must use http or https.")
    if text.startswith("http://") and not re.match(r"^http://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:/|$)", text):
        raise QwenVisionProviderError("Qwen vision API base must use https unless it targets localhost.")
    if text.endswith("/chat/completions"):
        return text
    return text.rstrip("/") + "/chat/completions"


def _image_mime_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _image_data_url(path: Path) -> str:
    # Kept private to transport construction; callers and result objects never receive base64 data.
    data = path.read_bytes()
    encoded = base64.b64encode(data).decode("ascii")
    return f"data:{_image_mime_type(path)};base64,{encoded}"


def _vision_prompt(*, mode: str, goal: str, image_count: int) -> str:
    if mode == MODE_COMPARE:
        task = "Compare the first screenshot as reference against the second screenshot as actual."
    else:
        task = "Inspect the screenshot and summarize only visible UI structure and visual issues."
    return "\n".join(
        [
            "You are Qwen Visual Evidence provider for Forgis.",
            "You are not a coding agent. Do not request source code, secrets, commands, or file edits.",
            task,
            f"image_count: {image_count}",
            f"goal: {goal or 'visual inspection'}",
            "Return compact JSON with keys: summary, findings, limitations.",
        ]
    )


def _response_content_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        chunks: list[str] = []
        for item in value:
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                elif item.get("type") == "text" and isinstance(item.get("content"), str):
                    chunks.append(item["content"])
        return "\n".join(chunks)
    return ""


def _post_qwen_vision_payload(
    *,
    api_base: str,
    api_key: str,
    model: str,
    mode: str,
    image_paths: tuple[Path, ...],
    goal: str,
    timeout_seconds: int = DEFAULT_QWEN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    url = _safe_api_url(api_base)
    prompt = _vision_prompt(mode=mode, goal=goal, image_count=len(image_paths))
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for image_path in image_paths:
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(image_path)}})
    request_payload = {
        "model": _sanitize_text(model or DEFAULT_QWEN_MODEL, limit=120) or DEFAULT_QWEN_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
    }
    data = json.dumps(request_payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(1, int(timeout_seconds))) as response:
            response_body = response.read(2_000_000)
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(2048).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        safe_body = _sanitize_text(body, limit=240, secret_values=(api_key,))
        detail = f": {safe_body}" if safe_body else ""
        raise QwenVisionProviderError(f"Qwen vision provider returned HTTP {exc.code}{detail}") from exc
    except urllib.error.URLError as exc:
        raise QwenVisionProviderError("Qwen vision provider network request failed.") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise QwenVisionProviderError("Qwen vision provider request timed out.") from exc
    except OSError as exc:
        raise QwenVisionProviderError("Qwen vision provider request failed before response.") from exc
    try:
        decoded = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QwenVisionProviderError("Qwen vision provider returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise QwenVisionProviderError("Qwen vision provider returned an invalid response shape.")
    return decoded


def _result_from_payload(
    payload: dict[str, Any],
    *,
    mode: str,
    secret_values: tuple[str, ...],
) -> QwenVisionResult:
    data: Any = payload
    if isinstance(payload.get("choices"), list) and payload["choices"]:
        message = payload["choices"][0].get("message") if isinstance(payload["choices"][0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        content_text = _response_content_text(content)
        if content_text:
            try:
                parsed = json.loads(content_text)
            except json.JSONDecodeError:
                data = {"summary": content_text}
            else:
                data = parsed if isinstance(parsed, dict) else {"summary": content_text}
    if not isinstance(data, dict):
        data = {"summary": data}
    summary = _sanitize_text(data.get("summary") or "", limit=MAX_SUMMARY_CHARS, secret_values=secret_values)
    findings = _safe_tuple(
        data.get("findings") or data.get("differences") or (),
        limit=MAX_FINDING_CHARS,
        max_items=MAX_FINDINGS,
        secret_values=secret_values,
    )
    limitations = _safe_tuple(
        data.get("limitations") or (),
        limit=MAX_FINDING_CHARS,
        max_items=MAX_LIMITATIONS,
        secret_values=secret_values,
    )
    if not summary and not findings and not limitations:
        raise QwenVisionProviderError("Qwen vision provider returned no usable visual summary.")
    return QwenVisionResult(
        ok=True,
        provider=PROVIDER,
        mode=mode,
        summary=summary,
        findings=findings,
        limitations=limitations,
    )


def _permission_gated(mode: str) -> QwenVisionResult:
    return QwenVisionResult(
        ok=False,
        provider=PROVIDER,
        mode=mode,
        summary="Qwen vision provider is unavailable because no API key was provided.",
        findings=(),
        limitations=("No screenshot was sent to Qwen.",),
        blocker=QWEN_PERMISSION_GATED,
    )


def _provider_failure(mode: str, exc: Exception, *, secret_values: tuple[str, ...]) -> QwenVisionResult:
    message = _sanitize_text(exc, limit=300, secret_values=secret_values)
    return QwenVisionResult(
        ok=False,
        provider=PROVIDER,
        mode=mode,
        summary="Qwen vision provider is unavailable.",
        findings=(),
        limitations=(message,),
        blocker=QWEN_UNAVAILABLE_IN_SESSION,
    )


def _path_failure(mode: str, exc: Exception) -> QwenVisionResult:
    message = _sanitize_text(exc, limit=300)
    return QwenVisionResult(
        ok=False,
        provider=PROVIDER,
        mode=mode,
        summary="Visual screenshot path was rejected before provider use.",
        findings=(),
        limitations=(message,),
        blocker=HOST_ENV_BLOCKED,
    )


def _call_qwen(
    *,
    mode: str,
    image_paths: tuple[Path, ...],
    goal: str,
    api_key: str | None,
    api_base: str | None,
    model: str | None,
) -> QwenVisionResult:
    if not api_key:
        return _permission_gated(mode)
    secret_values = (api_key,)
    safe_goal = _sanitize_text(goal, limit=500, secret_values=secret_values)
    try:
        payload = _post_qwen_vision_payload(
            api_base=api_base or DEFAULT_QWEN_API_BASE,
            api_key=api_key,
            model=model or DEFAULT_QWEN_MODEL,
            mode=mode,
            image_paths=image_paths,
            goal=safe_goal,
        )
        return _result_from_payload(payload, mode=mode, secret_values=secret_values)
    except Exception as exc:
        return _provider_failure(mode, exc, secret_values=secret_values)


def inspect_screenshot(
    image_path: Path,
    goal: str,
    *,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
) -> QwenVisionResult:
    try:
        validated = validate_visual_image_path(image_path, must_exist=True)
    except ValueError as exc:
        return _path_failure(MODE_INSPECT, exc)
    return _call_qwen(
        mode=MODE_INSPECT,
        image_paths=(validated,),
        goal=goal,
        api_key=api_key,
        api_base=api_base,
        model=model,
    )


def compare_screenshots(
    reference_path: Path,
    actual_path: Path,
    goal: str,
    *,
    api_key: str | None = None,
    api_base: str | None = None,
    model: str | None = None,
) -> QwenVisionResult:
    try:
        reference = validate_visual_image_path(reference_path, must_exist=True)
        actual = validate_visual_image_path(actual_path, must_exist=True)
    except ValueError as exc:
        return _path_failure(MODE_COMPARE, exc)
    return _call_qwen(
        mode=MODE_COMPARE,
        image_paths=(reference, actual),
        goal=goal,
        api_key=api_key,
        api_base=api_base,
        model=model,
    )


@dataclasses.dataclass(frozen=True)
class QwenVisionClient:
    api_key: str | None = None
    api_base: str | None = None
    model: str | None = None

    def inspect_screenshot(self, image_path: Path, goal: str) -> QwenVisionResult:
        return inspect_screenshot(
            image_path,
            goal,
            api_key=self.api_key,
            api_base=self.api_base,
            model=self.model,
        )

    def compare_screenshots(self, reference_path: Path, actual_path: Path, goal: str) -> QwenVisionResult:
        return compare_screenshots(
            reference_path,
            actual_path,
            goal,
            api_key=self.api_key,
            api_base=self.api_base,
            model=self.model,
        )


def safe_qwen_image_label(path: Path) -> str:
    return sanitize_visual_path_label(path)
