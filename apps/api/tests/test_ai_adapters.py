"""Provider calls through LiteLLM against mocked provider HTTP (no network, no keys).

Every call goes LiteLLM -> PARE's HTTP client -> httpx.MockTransport, so these tests see
the exact requests LiteLLM puts on the wire. Response bodies follow each provider's
documented formats. These tests are what the registry's ``verification="mocked"`` means.

They also pin the guarantees PARE relies on (PRD C5): one HTTP request per call (LiteLLM
never retries), redirects never followed, and PARE's client used on every provider route.
"""

import json
from collections.abc import Callable

import httpx
import pytest

from app.ai.adapters import AnthropicModelLister, GeminiModelLister, OpenAIModelLister
from app.ai.adapters.litellm_adapter import NO_KEY_PLACEHOLDER, load_litellm
from app.ai.errors import ErrorClass, ProviderError
from app.ai.registry import PROVIDER_SPECS, build_adapter_factory
from app.ai.types import ChatMessage, CompletionRequest, ProviderCallConfig
from app.models.enums import ProviderType

KEY = "sk-unit-test-key-0123456789abcdefXYZ"
REQ = CompletionRequest(
    messages=[ChatMessage("system", "Be brief."), ChatMessage("user", "Hi")],
    max_output_tokens=5,
)
Handler = Callable[[httpx.Request], httpx.Response]

OPENAI_OK = {
    "id": "chatcmpl-1",
    "object": "chat.completion",
    "model": "served-model",
    "choices": [
        {"index": 0, "message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
    ],
    "usage": {"prompt_tokens": 12, "completion_tokens": 1, "total_tokens": 13},
}
ANTHROPIC_OK = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-x",
    "content": [{"type": "text", "text": "OK"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 9, "output_tokens": 2},
}
GEMINI_OK = {
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"text": "O"}, {"text": "K"}]},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 1, "totalTokenCount": 5},
    "modelVersion": "gemini-x",
}

# Where each provider type sends a completion, and how it carries the key.
EXPECTED = {
    ProviderType.OPENAI: ("https://api.openai.com/v1/chat/completions", "authorization"),
    ProviderType.ANTHROPIC: ("https://api.anthropic.com/v1/messages", "x-api-key"),
    ProviderType.GEMINI: (
        "https://generativelanguage.googleapis.com/v1beta/models/m-1:generateContent",
        "x-goog-api-key",
    ),
    ProviderType.XAI: ("https://api.x.ai/v1/chat/completions", "authorization"),
    ProviderType.DEEPSEEK: ("https://api.deepseek.com/v1/chat/completions", "authorization"),
    ProviderType.MISTRAL: ("https://api.mistral.ai/v1/chat/completions", "authorization"),
    ProviderType.OPENAI_COMPATIBLE: ("http://localhost:1234/v1/chat/completions", "authorization"),
}
ALL_TYPES = list(ProviderType)


def ok_body(ptype: ProviderType) -> dict:
    if ptype is ProviderType.ANTHROPIC:
        return ANTHROPIC_OK
    if ptype is ProviderType.GEMINI:
        return GEMINI_OK
    return OPENAI_OK


def _cfg(ptype: ProviderType, model: str = "m-1", key: str | None = KEY) -> ProviderCallConfig:
    base = PROVIDER_SPECS[ptype].default_base_url or "http://localhost:1234/v1"
    return ProviderCallConfig(
        provider_type=ptype.value, base_url=base, model=model, timeout_seconds=5, api_key=key
    )


def _adapter(ptype: ProviderType, handler: Handler):  # type: ignore[no-untyped-def]
    return build_adapter_factory(httpx.MockTransport(handler))(PROVIDER_SPECS[ptype])


def _recorder(response: Handler) -> tuple[list[httpx.Request], Handler]:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return response(request)

    return calls, handler


def _raises(ptype: ProviderType, handler: Handler, cls: ErrorClass) -> ProviderError:
    with pytest.raises(ProviderError) as info:
        _adapter(ptype, handler).complete(_cfg(ptype), REQ)
    assert info.value.error_class is cls, (info.value.error_class, info.value.message)
    assert KEY not in info.value.message
    return info.value


# --- LiteLLM configuration and the single-routing-authority guarantees -------------------


def test_litellm_is_configured_for_single_authority() -> None:
    import os

    litellm = load_litellm()
    assert litellm.num_retries == 0
    assert litellm.suppress_debug_info is True
    assert litellm.turn_off_message_logging is True
    assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True"  # no fetch on import


@pytest.mark.parametrize("ptype", ALL_TYPES, ids=lambda t: t.value)
def test_every_provider_uses_pare_http_client(ptype: ProviderType) -> None:
    """A call reaches the mock transport, at the right URL, with the key in a header.

    LiteLLM silently ignores a client of the wrong type for a route and then uses its own
    (redirect-following, retrying) client; this test fails if that ever happens.
    """
    calls, handler = _recorder(lambda r: httpx.Response(200, json=ok_body(ptype)))
    out = _adapter(ptype, handler).complete(_cfg(ptype), REQ)
    assert out.text == "OK"
    assert len(calls) == 1
    url, key_header = EXPECTED[ptype]
    assert str(calls[0].url) == url
    assert KEY not in str(calls[0].url)  # never in the URL
    assert KEY in calls[0].headers[key_header]


@pytest.mark.parametrize("ptype", ALL_TYPES, ids=lambda t: t.value)
@pytest.mark.parametrize(
    "failure",
    [
        lambda r: httpx.Response(503, json={"error": {"message": "unavailable"}}),
        lambda r: httpx.Response(429, json={"error": {"message": "slow down"}}),
        lambda r: httpx.Response(500, json={"error": {"message": "boom"}}),
    ],
    ids=["503", "429", "500"],
)
def test_litellm_never_retries(ptype: ProviderType, failure: Handler) -> None:
    calls, handler = _recorder(failure)
    with pytest.raises(ProviderError):
        _adapter(ptype, handler).complete(_cfg(ptype), REQ)
    assert len(calls) == 1, f"{ptype.value}: LiteLLM retried ({len(calls)} requests)"


@pytest.mark.parametrize("ptype", ALL_TYPES, ids=lambda t: t.value)
def test_timeouts_are_single_attempt(ptype: ProviderType) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    calls, handler = _recorder(slow)
    _raises(ptype, handler, ErrorClass.TIMEOUT)
    assert len(calls) == 1


@pytest.mark.parametrize("ptype", ALL_TYPES, ids=lambda t: t.value)
def test_redirects_are_not_followed(ptype: ProviderType) -> None:
    calls, handler = _recorder(
        lambda r: httpx.Response(307, headers={"location": "https://evil.example/steal"})
    )
    with pytest.raises(ProviderError) as info:
        _adapter(ptype, handler).complete(_cfg(ptype), REQ)
    assert info.value.error_class in (ErrorClass.INVALID_REQUEST, ErrorClass.NETWORK)
    assert [str(c.url.host) for c in calls] == [httpx.URL(EXPECTED[ptype][0]).host]


@pytest.mark.parametrize("ptype", ALL_TYPES, ids=lambda t: t.value)
def test_connection_errors_are_network(ptype: ProviderType) -> None:
    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    _raises(ptype, refused, ErrorClass.NETWORK)


# --- request and response shapes ---------------------------------------------------------


def test_openai_request_shape_and_usage() -> None:
    calls, handler = _recorder(lambda r: httpx.Response(200, json=OPENAI_OK))
    out = _adapter(ProviderType.OPENAI, handler).complete(_cfg(ProviderType.OPENAI), REQ)
    assert (out.text, out.input_tokens, out.output_tokens) == ("OK", 12, 1)
    assert out.response_model == "served-model"
    body = json.loads(calls[0].content)
    assert body["model"] == "m-1"
    # OpenAI's newer models reject max_tokens.
    assert body["max_completion_tokens"] == 5 and "max_tokens" not in body
    assert body["messages"][0] == {"role": "system", "content": "Be brief."}
    assert "temperature" not in body  # only sent when the caller sets it


def test_openai_compatible_without_key_sends_only_a_placeholder() -> None:
    calls, handler = _recorder(lambda r: httpx.Response(200, json=OPENAI_OK))
    cfg = _cfg(ProviderType.OPENAI_COMPATIBLE, model="local", key=None)
    assert _adapter(ProviderType.OPENAI_COMPATIBLE, handler).complete(cfg, REQ).text == "OK"
    assert calls[0].headers["authorization"] == f"Bearer {NO_KEY_PLACEHOLDER}"
    assert json.loads(calls[0].content)["max_tokens"] == 5


@pytest.mark.parametrize(
    "ptype", [ProviderType.OPENAI, ProviderType.XAI, ProviderType.OPENAI_COMPATIBLE]
)
def test_json_mode_sets_response_format(ptype: ProviderType) -> None:
    calls, handler = _recorder(lambda r: httpx.Response(200, json=OPENAI_OK))
    req = CompletionRequest(
        messages=[ChatMessage("user", "x")], max_output_tokens=5, json_mode=True
    )
    _adapter(ptype, handler).complete(_cfg(ptype), req)
    assert json.loads(calls[0].content)["response_format"] == {"type": "json_object"}


def test_temperature_is_passed_when_set() -> None:
    calls, handler = _recorder(lambda r: httpx.Response(200, json=OPENAI_OK))
    req = CompletionRequest(
        messages=[ChatMessage("user", "x")], max_output_tokens=5, temperature=0.2
    )
    _adapter(ProviderType.DEEPSEEK, handler).complete(_cfg(ProviderType.DEEPSEEK), req)
    assert json.loads(calls[0].content)["temperature"] == 0.2


def test_anthropic_request_shape() -> None:
    calls, handler = _recorder(lambda r: httpx.Response(200, json=ANTHROPIC_OK))
    out = _adapter(ProviderType.ANTHROPIC, handler).complete(
        _cfg(ProviderType.ANTHROPIC, "claude-x"), REQ
    )
    assert (out.text, out.input_tokens, out.output_tokens) == ("OK", 9, 2)
    headers = calls[0].headers
    assert headers["x-api-key"] == KEY
    assert headers["anthropic-version"]
    assert "authorization" not in headers
    body = json.loads(calls[0].content)
    system = body["system"]
    system_text = system if isinstance(system, str) else "".join(b["text"] for b in system)
    assert system_text == "Be brief."
    assert [m["role"] for m in body["messages"]] == ["user"]
    assert body["max_tokens"] == 5


def test_gemini_request_shape() -> None:
    calls, handler = _recorder(lambda r: httpx.Response(200, json=GEMINI_OK))
    out = _adapter(ProviderType.GEMINI, handler).complete(
        _cfg(ProviderType.GEMINI, "models/gemini-2.5-flash"), REQ
    )
    assert (out.text, out.input_tokens, out.output_tokens) == ("OK", 4, 1)
    assert calls[0].url.path.endswith("/models/gemini-2.5-flash:generateContent")
    assert "key=" not in str(calls[0].url)  # key goes in a header, never the URL
    body = json.loads(calls[0].content)
    system = body.get("system_instruction") or body.get("systemInstruction")
    assert system["parts"][0]["text"] == "Be brief."
    gen = body["generationConfig"]
    assert (gen.get("max_output_tokens") or gen.get("maxOutputTokens")) == 5


def test_empty_choices_is_invalid_response() -> None:
    body = {**OPENAI_OK, "choices": []}
    _raises(
        ProviderType.OPENAI, lambda r: httpx.Response(200, json=body), ErrorClass.INVALID_RESPONSE
    )


def test_content_filter_without_text_is_content_policy() -> None:
    body = {
        **OPENAI_OK,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": None},
                "finish_reason": "content_filter",
            }
        ],
    }
    _raises(
        ProviderType.OPENAI, lambda r: httpx.Response(200, json=body), ErrorClass.CONTENT_POLICY
    )


# --- error classification on both LiteLLM client routes ----------------------------------

ERROR_CASES = [
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
    (400, {"error": {"message": "messages: field required"}}, {}, ErrorClass.INVALID_REQUEST),
    (
        400,
        {"error": {"message": "This model's maximum context length is 8192 tokens"}},
        {},
        ErrorClass.CONTEXT_LENGTH,
    ),
]


# openai: OpenAI SDK client route. deepseek: LiteLLM HTTPHandler route.
@pytest.mark.parametrize(
    "ptype", [ProviderType.OPENAI, ProviderType.DEEPSEEK], ids=lambda t: t.value
)
@pytest.mark.parametrize(("status", "body", "headers", "expected"), ERROR_CASES)
def test_error_mapping(ptype, status, body, headers, expected) -> None:  # type: ignore[no-untyped-def]
    err = _raises(ptype, lambda r: httpx.Response(status, json=body, headers=headers), expected)
    if expected is not ErrorClass.CONTEXT_LENGTH:
        assert err.http_status == status
    if "retry-after" in headers:
        assert err.retry_after == 3


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
            "prompt is too long: 300000 tokens > 200000 maximum",
            ErrorClass.CONTEXT_LENGTH,
        ),
    ],
)
def test_anthropic_error_mapping(status, etype, message, expected) -> None:  # type: ignore[no-untyped-def]
    body = {"type": "error", "error": {"type": etype, "message": message}}
    _raises(ProviderType.ANTHROPIC, lambda r: httpx.Response(status, json=body), expected)


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
    _raises(ProviderType.GEMINI, lambda r: httpx.Response(400, json=body), ErrorClass.AUTH)


def test_gemini_resource_exhausted_reads_retry_delay() -> None:
    body = {
        "error": {
            "code": 429,
            "message": "You exceeded your current quota, please check your plan.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "17s"}],
        }
    }
    err = _raises(
        ProviderType.GEMINI, lambda r: httpx.Response(429, json=body), ErrorClass.RATE_LIMITED
    )
    assert err.retry_after == 17


def test_key_fragments_are_scrubbed_from_errors() -> None:
    body = {"error": {"message": f"Key {KEY[:20]}… was rejected", "code": "invalid_api_key"}}
    err = _raises(ProviderType.OPENAI, lambda r: httpx.Response(401, json=body), ErrorClass.AUTH)
    assert KEY[:16] not in err.message


# --- model listing (direct, read-only) ---------------------------------------------------


def _lister_cfg(base: str, ptype: str) -> ProviderCallConfig:
    return ProviderCallConfig(ptype, base, "m", 5, KEY)


def test_openai_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}, {}]})

    models = OpenAIModelLister(httpx.MockTransport(handler)).list_models(
        _lister_cfg("https://api.openai.com/v1", "openai")
    )
    assert [m.id for m in models] == ["a-model", "b-model"]


def test_anthropic_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models" and request.headers["x-api-key"] == KEY
        return httpx.Response(200, json={"data": [{"id": "claude-b", "display_name": "B"}]})

    models = AnthropicModelLister(httpx.MockTransport(handler)).list_models(
        _lister_cfg("https://api.anthropic.com", "anthropic")
    )
    assert [(m.id, m.display_name) for m in models] == [("claude-b", "B")]


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
    lister = GeminiModelLister(httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    models = lister.list_models(_lister_cfg("https://g.test/v1beta", "gemini"))
    assert [(m.id, m.context_window) for m in models] == [("gemini-a", 1000)]


def test_listing_does_not_follow_redirects() -> None:
    calls, handler = _recorder(
        lambda r: httpx.Response(302, headers={"location": "https://evil.example"})
    )
    with pytest.raises(ProviderError) as info:
        OpenAIModelLister(httpx.MockTransport(handler)).list_models(
            _lister_cfg("https://api.openai.com/v1", "openai")
        )
    assert info.value.error_class is ErrorClass.INVALID_REQUEST
    assert len(calls) == 1


# --- registry ---------------------------------------------------------------------------


def test_every_provider_type_has_a_spec_and_litellm_route() -> None:
    factory = build_adapter_factory(httpx.MockTransport(lambda r: httpx.Response(500)))
    assert set(PROVIDER_SPECS) == set(ProviderType)
    for spec in PROVIDER_SPECS.values():
        adapter = factory(spec)
        assert adapter.litellm_provider == spec.litellm_provider
        assert spec.requires_base_url == (spec.default_base_url is None)
        assert spec.verification == "mocked"  # nothing claims live verification yet
