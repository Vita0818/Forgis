from __future__ import annotations

import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = REPO_ROOT / "agent"
sys.path.insert(0, str(AGENT_DIR))

from openai_compatible_client import (
    OpenAICompatibleClient,
    OpenAICompatibleClientError,
    chat_completions_url,
)

try:
    from deepseek_agent import DeepSeekClient
except ModuleNotFoundError as exc:
    if exc.name != "yaml":
        raise
    DeepSeekClient = None


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object] | str) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read(self) -> bytes:
        if isinstance(self.payload, str):
            return self.payload.encode("utf-8")
        return json.dumps(self.payload).encode("utf-8")


class OpenAICompatibleClientTests(unittest.TestCase):
    def test_chat_completions_url_avoids_duplicate_suffixes(self) -> None:
        self.assertEqual(
            chat_completions_url("https://api.openai.com/v1"),
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://api.openai.com/v1/chat/completions"),
            "https://api.openai.com/v1/chat/completions",
        )
        self.assertEqual(
            chat_completions_url("https://api.deepseek.com"),
            "https://api.deepseek.com/chat/completions",
        )

    def test_request_schema_model_tools_and_tool_choice(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: int) -> FakeHTTPResponse:
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["authorization"] = request.get_header("Authorization")
            captured["content_type"] = request.get_header("Content-type")
            captured["body"] = json.loads(request.data.decode("utf-8"))
            return FakeHTTPResponse({"choices": [{"message": {"content": "done"}}]})

        client = OpenAICompatibleClient(
            api_base="https://example.test/v1",
            api_key="REDACT_ME_TEST_VALUE",
            model="provider/model",
            timeout_seconds=17,
        )
        with mock.patch("openai_compatible_client.urllib.request.urlopen", side_effect=fake_urlopen):
            response = client.chat(
                messages=[{"role": "user", "content": "hello"}],
                tools=[{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
                tool_choice="auto",
            )

        self.assertEqual(response["choices"][0]["message"]["content"], "done")
        self.assertEqual(captured["url"], "https://example.test/v1/chat/completions")
        self.assertEqual(captured["timeout"], 17)
        self.assertEqual(captured["authorization"], "Bearer REDACT_ME_TEST_VALUE")
        self.assertEqual(captured["content_type"], "application/json")
        body = captured["body"]
        self.assertEqual(body["model"], "provider/model")
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello"}])
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["tools"][0]["function"]["name"], "read_file")

    def test_http_error_is_redacted_and_bounded(self) -> None:
        secret = "REDACT_ME_TEST_VALUE"
        long_message = "bad " + secret + " " + ("x" * 1000)
        error = urllib.error.HTTPError(
            "https://example.test/v1/chat/completions",
            401,
            "Unauthorized",
            {},
            io.BytesIO(json.dumps({"error": {"message": long_message}}).encode("utf-8")),
        )
        client = OpenAICompatibleClient(api_base="https://example.test/v1", api_key=secret, model="m")
        with mock.patch("openai_compatible_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenAICompatibleClientError) as caught:
                client.chat(messages=[{"role": "user", "content": "hello"}])
        rendered = str(caught.exception)
        self.assertIn("HTTP 401", rendered)
        self.assertIn("[REDACTED]", rendered)
        self.assertIn("[truncated]", rendered)
        self.assertNotIn(secret, rendered)

    def test_invalid_json_and_invalid_shapes_are_safe(self) -> None:
        client = OpenAICompatibleClient(api_base="https://example.test/v1", api_key="REDACT_ME_TEST_VALUE", model="m")
        with mock.patch(
            "openai_compatible_client.urllib.request.urlopen",
            return_value=FakeHTTPResponse("not json REDACT_ME_TEST_VALUE"),
        ):
            with self.assertRaisesRegex(OpenAICompatibleClientError, "invalid JSON"):
                client.chat(messages=[{"role": "user", "content": "hello"}])

        for payload, pattern in (
            ({}, "no choices"),
            ({"choices": [{}]}, "message"),
            ({"choices": [{"message": {"tool_calls": {}}}]}, "tool_calls"),
            (
                {"choices": [{"message": {"tool_calls": [{"function": {"name": "read_file", "arguments": {}}}]}}]},
                "arguments",
            ),
        ):
            with self.subTest(pattern=pattern):
                with mock.patch(
                    "openai_compatible_client.urllib.request.urlopen",
                    return_value=FakeHTTPResponse(payload),
                ):
                    with self.assertRaisesRegex(OpenAICompatibleClientError, pattern):
                        client.chat(messages=[{"role": "user", "content": "hello"}])

    def test_api_key_not_in_client_repr_or_url_error(self) -> None:
        secret = "REDACT_ME_TEST_VALUE"
        client = OpenAICompatibleClient(api_base="https://example.test/v1", api_key=secret, model="m")
        self.assertNotIn(secret, repr(client))
        error = urllib.error.URLError(f"Bearer {secret}")
        with mock.patch("openai_compatible_client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(OpenAICompatibleClientError) as caught:
                client.chat(messages=[{"role": "user", "content": "hello"}])
        self.assertNotIn(secret, str(caught.exception))
        self.assertIn("Bearer [REDACTED]", str(caught.exception))

    @unittest.skipIf(DeepSeekClient is None, "PyYAML is required for DeepSeekClient import")
    def test_deepseek_client_shim_keeps_legacy_chat_shape(self) -> None:
        captured: dict[str, object] = {}

        def fake_urlopen(request: object, timeout: int) -> FakeHTTPResponse:
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return FakeHTTPResponse({"choices": [{"message": {"content": "ok"}}]})

        client = DeepSeekClient(
            api_base="https://api.deepseek.com",
            api_key="REDACT_ME_TEST_VALUE",
            model="deepseek-v4-pro",
            timeout_seconds=22,
        )
        self.assertNotIn("REDACT_ME_TEST_VALUE", repr(client))
        with mock.patch("openai_compatible_client.urllib.request.urlopen", side_effect=fake_urlopen):
            response = client.chat(
                [{"role": "user", "content": "hello"}],
                [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
            )
        self.assertEqual(response["choices"][0]["message"]["content"], "ok")
        self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
        self.assertEqual(captured["timeout"], 22)
        body = captured["body"]
        self.assertEqual(body["model"], "deepseek-v4-pro")
        self.assertEqual(body["tool_choice"], "auto")
        self.assertEqual(body["tools"][0]["function"]["name"], "read_file")


if __name__ == "__main__":
    unittest.main()
