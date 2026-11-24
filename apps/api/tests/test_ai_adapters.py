"""Adapters against mocked provider HTTP APIs (httpx.MockTransport; no network, no keys).

The response bodies mirror each provider's documented formats. These tests are what the
registry's ``verification="mocked"`` refers to.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai.adapters import AnthropicAdapter, GeminiAdapter, OpenAICompatibleAdapter
from app.ai.errors import ErrorClass, ProviderError
from app.ai.registry import PROVIDER_SPECS, build_adapter_factory
from app.ai.types import ChatMessage, CompletionRequest, ProviderCallConfig
from app.models.enums import ProviderType

KEY = "sk-unit-test-key-0123456789abcdefXYZ"
REQ = CompletionRequest(
    messages=[ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")],
    max_output_tokens=5,
)


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def _cfg(base_url: str, model: str = "m-1", ptype: str = "openai") -> ProviderCallConfig:
    return ProviderCallConfig(
        provider_type=ptype, base_url=base_url, model=model, timeout_seconds=5, api_key=KEY
    )


def _raises(adapter, cfg, cls: ErrorClass) -> ProviderError:  # type: ignore[no-untyped-def]
    with pytest.raises(ProviderError) as info:
        adapter.complete(cfg, REQ)
    assert info.value.error_class is cls, info.value.message
    assert KEY not in info.value.message
    return info.value


# --- OpenAI-compatible ------------------------------------------------------------------


def test_openai_success_and_request_shape() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "gpt-4o-mini-2024",
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 1},
            },
        )

    adapter = OpenAICompatibleAdapter(_client(handler), max_tokens_param="max_completion_tokens")
    out = adapter.complete(_cfg("https://api.openai.com/v1", "gpt-4o-mini"), REQ)
    assert out.text == "OK"
    assert (out.input_tokens, out.output_tokens) == (12, 1)
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["auth"] == f"Bearer {KEY}"
    assert seen["body"]["max_completion_tokens"] == 5
    assert "max_tokens" not in seen["body"]
    assert seen["body"]["messages"][0] == {"role": "system", "content": "Be brief."}
    assert "temperature" not in seen["body"]  # only sent when the caller sets it


def test_openai_compatible_without_key_sends_no_auth_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    cfg = ProviderCallConfig("openai_compatible", "http://localhost:1234/v1", "local", 5, None)
    assert OpenAICompatibleAdapter(_client(handler)).complete(cfg, REQ).text == "hi"


def test_json_mode_sets_response_format() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        assert body["max_tokens"] == 5
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    req = CompletionRequest(
        messages=[ChatMessage("user", "x")], max_output_tokens=5, json_mode=True
    )
    OpenAICompatibleAdapter(_client(handler)).complete(_cfg("https://api.x.ai/v1"), req)


@pytest.mark.parametrize(
    ("status", "body", "headers", "expected"),
    [
        (
            401,
            {"error": {"message": f"Incorrect API key provided: {KEY}", "code": "invalid_api_key"}},
            {},
            ErrorClass.AUTH,
        ),
        (
            429,
            {"error": {"message": "Rate limit reached", "code": "rate_limit_exceeded"}},
            {"retry-after": "3"},
            ErrorClass.RATE_LIMITED,
        ),
        (
            429,
            {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}},
            {},
            ErrorClass.QUOTA_EXHAUSTED,
        ),
        (402, {"error": {"message": "Insufficient Balance"}}, {}, ErrorClass.QUOTA_EXHAUSTED),
        (
            404,
            {"error": {"message": "The model `nope` does not exist", "code": "model_not_found"}},
            {},
            ErrorClass.MODEL_NOT_FOUND,
        ),
        (503, {"error": {"message": "Service Unavailable"}}, {}, ErrorClass.SERVER_ERROR),
        (400, {"detail": "messages: field required"}, {}, ErrorClass.INVALID_REQUEST),
    ],
)
def test_openai_error_mapping(status, body, headers, expected) -> None:  # type: ignore[no-untyped-def]
    adapter = OpenAICompatibleAdapter(
        _client(lambda r: httpx.Response(status, json=body, headers=headers))
    )
    err = _raises(adapter, _cfg("https://api.openai.com/v1"), expected)
    assert err.http_status == status
    if "retry-after" in headers:
        assert err.retry_after == 3


def test_timeout_and_connection_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    cfg = _cfg("https://api.openai.com/v1")
    _raises(OpenAICompatibleAdapter(_client(timeout)), cfg, ErrorClass.TIMEOUT)
    _raises(OpenAICompatibleAdapter(_client(refused)), cfg, ErrorClass.NETWORK)


def test_redirects_are_not_followed() -> None:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://evil.example/steal"})

    _raises(
        OpenAICompatibleAdapter(_client(handler)),
        _cfg("https://api.openai.com/v1"),
        ErrorClass.INVALID_REQUEST,
    )
    assert calls == ["https://api.openai.com/v1/chat/completions"]


def test_non_json_success_is_invalid_response() -> None:
    adapter = OpenAICompatibleAdapter(_client(lambda r: httpx.Response(200, text="<html>")))
    _raises(adapter, _cfg("https://example.test/v1"), ErrorClass.INVALID_RESPONSE)


def test_openai_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}, {}]})

    models = OpenAICompatibleAdapter(_client(handler)).list_models(
        _cfg("https://api.openai.com/v1")
    )
    assert [m.id for m in models] == ["a-model", "b-model"]


# --- Anthropic --------------------------------------------------------------------------


def test_anthropic_success_and_request_shape() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "model": "claude-x",
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 9, "output_tokens": 2},
            },
        )

    out = AnthropicAdapter(_client(handler)).complete(
        _cfg("https://api.anthropic.com", "claude-x", "anthropic"), REQ
    )
    assert (out.text, out.input_tokens, out.output_tokens) == ("OK", 9, 2)
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == KEY
    assert seen["headers"]["anthropic-version"] == "2023-06-01"
    assert "authorization" not in seen["headers"]
    assert seen["body"]["system"] == "Be brief."
    assert seen["body"]["messages"] == [{"role": "user", "content": "Hi"}]
    assert seen["body"]["max_tokens"] == 5


@pytest.mark.parametrize(
    ("status", "etype", "message", "expected"),
    [
        (401, "authentication_error", "invalid x-api-key", ErrorClass.AUTH),
        (429, "rate_limit_error", "Number of requests exceeded", ErrorClass.RATE_LIMITED),
        (529, "overloaded_error", "Overloaded", ErrorClass.SERVER_ERROR),
        (404, "not_found_error", "model: claude-nope", ErrorClass.MODEL_NOT_FOUND),
        (
            400,
            "invalid_request_error",
            "Your credit balance is too low to access the Anthropic API.",
            ErrorClass.QUOTA_EXHAUSTED,
        ),
        (
            400,
            "invalid_request_error",
            "prompt is too long: 300000 tokens",
            ErrorClass.CONTEXT_LENGTH,
        ),
    ],
)
def test_anthropic_error_mapping(status, etype, message, expected) -> None:  # type: ignore[no-untyped-def]
    body = {"type": "error", "error": {"type": etype, "message": message}}
    adapter = AnthropicAdapter(_client(lambda r: httpx.Response(status, json=body)))
    _raises(adapter, _cfg("https://api.anthropic.com", ptype="anthropic"), expected)


# --- Gemini -----------------------------------------------------------------------------


def test_gemini_success_and_request_shape() -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": "O"}, {"text": "K"}]}, "finishReason": "STOP"}
                ],
                "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 1},
            },
        )

    base = "https://generativelanguage.googleapis.com/v1beta"
    out = GeminiAdapter(_client(handler)).complete(_cfg(base, "gemini-2.5-flash", "gemini"), REQ)
    assert (out.text, out.input_tokens, out.output_tokens) == ("OK", 4, 1)
    assert seen["url"] == f"{base}/models/gemini-2.5-flash:generateContent"
    assert "key=" not in seen["url"]  # key goes in a header, never the URL
    assert seen["key"] == KEY
    assert seen["body"]["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    assert seen["body"]["contents"] == [{"role": "user", "parts": [{"text": "Hi"}]}]
    assert seen["body"]["generationConfig"]["maxOutputTokens"] == 5


def test_gemini_invalid_key_is_auth_even_with_400() -> None:
    body = {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
            "details": [
                {"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}
            ],
        }
    }
    adapter = GeminiAdapter(_client(lambda r: httpx.Response(400, json=body)))
    _raises(adapter, _cfg("https://g.test/v1beta", ptype="gemini"), ErrorClass.AUTH)


def test_gemini_resource_exhausted_reads_retry_delay() -> None:
    body = {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota, please check your plan.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}],
        }
    }
    adapter = GeminiAdapter(_client(lambda r: httpx.Response(429, json=body)))
    err = _raises(adapter, _cfg("https://g.test/v1beta", ptype="gemini"), ErrorClass.RATE_LIMITED)
    assert err.retry_after == 17


def test_gemini_blocked_prompt_is_content_policy() -> None:
    adapter = GeminiAdapter(
        _client(lambda r: httpx.Response(200, json={"promptFeedback": {"blockReason": "SAFETY"}}))
    )
    _raises(adapter, _cfg("https://g.test/v1beta", ptype="gemini"), ErrorClass.CONTENT_POLICY)


def test_gemini_list_models_filters_to_generate_content() -> None:
    body = {
        "models": [
            {
                "name": "models/gemini-a",
                "supportedGenerationMethods": ["generateContent"],
                "inputTokenLimit": 1000,
            },
            {"name": "models/embed-b", "supportedGenerationMethods": ["embedContent"]},
        ]
    }
    adapter = GeminiAdapter(_client(lambda r: httpx.Response(200, json=body)))
    models = adapter.list_models(_cfg("https://g.test/v1beta", ptype="gemini"))
    assert [(m.id, m.context_window) for m in models] == [("gemini-a", 1000)]


# --- registry ---------------------------------------------------------------------------


def test_every_provider_type_has_a_spec_and_adapter() -> None:
    factory = build_adapter_factory(_client(lambda r: httpx.Response(500)))
    assert set(PROVIDER_SPECS) == set(ProviderType)
    for spec in PROVIDER_SPECS.values():
        adapter = factory(spec)
        assert adapter.protocol == spec.protocol
        assert spec.requires_base_url == (spec.default_base_url is None)
        assert spec.verification == "mocked"  # nothing claims live verification yet
