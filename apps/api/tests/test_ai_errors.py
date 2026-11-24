"""Error classification, the retry/fallback decision table, and message sanitising."""

import pytest

from app.ai.errors import (
    Decision,
    ErrorClass,
    ProviderError,
    RoutingPolicyValues,
    backoff_delay,
    classify_http,
    decide,
    parse_retry_after,
    sanitize_message,
)

E = ErrorClass


@pytest.mark.parametrize(
    ("status", "code", "message", "expected"),
    [
        (401, "invalid_api_key", "Incorrect API key provided", E.AUTH),
        (403, "permission_error", "Your key lacks access", E.AUTH),
        (400, None, "Incorrect API key provided: xai-****", E.AUTH),  # xAI style
        (400, "INVALID_ARGUMENT", "API key not valid. Please pass a valid API key.", E.AUTH),
        (429, "insufficient_quota", "You exceeded your current quota", E.QUOTA_EXHAUSTED),
        (402, None, "Insufficient Balance", E.QUOTA_EXHAUSTED),  # DeepSeek
        (400, "invalid_request_error", "Your credit balance is too low", E.QUOTA_EXHAUSTED),
        (429, "rate_limit_exceeded", "Rate limit reached for requests", E.RATE_LIMITED),
        (404, "model_not_found", "The model `gpt-x` does not exist", E.MODEL_NOT_FOUND),
        (400, None, "model 'llama9' not found, try pulling it first", E.MODEL_NOT_FOUND),
        (400, "context_length_exceeded", "maximum context length is 8192", E.CONTEXT_LENGTH),
        (400, "content_filter", "flagged by content management policy", E.CONTENT_POLICY),
        (400, "invalid_request_error", "messages: field required", E.INVALID_REQUEST),
        (422, None, "Unprocessable", E.INVALID_REQUEST),
        (500, None, "Internal error", E.SERVER_ERROR),
        (502, None, "Bad gateway", E.SERVER_ERROR),
        (503, None, "Service unavailable", E.SERVER_ERROR),
        (529, "overloaded_error", "Overloaded", E.SERVER_ERROR),
        (408, None, "Request timeout", E.TIMEOUT),
        (418, None, "I'm a teapot", E.UNKNOWN),
    ],
)
def test_classify_http(status: int, code: str | None, message: str, expected: ErrorClass) -> None:
    assert classify_http(status, code, message) is expected


POLICY = RoutingPolicyValues()


def _err(cls: ErrorClass, retry_after: float | None = None) -> ProviderError:
    return ProviderError(cls, "x", retry_after=retry_after)


@pytest.mark.parametrize("cls", [E.TIMEOUT, E.NETWORK, E.SERVER_ERROR])
def test_transient_errors_retry_then_fall_back(cls: ErrorClass) -> None:
    assert decide(_err(cls), 0, POLICY).retry is True
    assert decide(_err(cls), 1, POLICY).retry is True
    last = decide(_err(cls), 2, POLICY)  # max_retries = 2
    assert last.retry is False and last.fallback is True


@pytest.mark.parametrize(
    "cls", [E.AUTH, E.MODEL_NOT_FOUND, E.INVALID_REQUEST, E.CONTEXT_LENGTH, E.CONTENT_POLICY]
)
def test_non_transient_errors_never_retry_or_fall_back(cls: ErrorClass) -> None:
    assert decide(_err(cls), 0, POLICY) == Decision(retry=False, fallback=False)


def test_rate_limit_honours_retry_after() -> None:
    d = decide(_err(E.RATE_LIMITED, retry_after=7), 0, POLICY, jitter=0.0)
    assert d.retry is True and d.delay == 7
    assert d.fallback is True


def test_rate_limit_with_long_retry_after_skips_waiting() -> None:
    d = decide(_err(E.RATE_LIMITED, retry_after=600), 0, POLICY)
    assert d.retry is False and d.fallback is True


def test_rate_limit_fallback_can_be_disabled() -> None:
    policy = RoutingPolicyValues(fallback_on_rate_limit=False)
    assert decide(_err(E.RATE_LIMITED), 2, policy).fallback is False


def test_quota_exhausted_follows_explicit_policy() -> None:
    assert decide(_err(E.QUOTA_EXHAUSTED), 0, POLICY) == Decision(retry=False, fallback=False)
    opted_in = RoutingPolicyValues(fallback_on_quota_exhausted=True)
    assert decide(_err(E.QUOTA_EXHAUSTED), 0, opted_in) == Decision(retry=False, fallback=True)


def test_unknown_gets_one_retry_and_no_fallback() -> None:
    assert decide(_err(E.UNKNOWN), 0, POLICY).retry is True
    second = decide(_err(E.UNKNOWN), 1, POLICY)
    assert second.retry is False and second.fallback is False


def test_zero_retries_policy() -> None:
    d = decide(_err(E.TIMEOUT), 0, RoutingPolicyValues(max_retries=0))
    assert d.retry is False and d.fallback is True


def test_backoff_is_exponential_bounded_and_jittered() -> None:
    assert backoff_delay(1, 1.0) == pytest.approx(1.0)
    assert backoff_delay(2, 1.0) == pytest.approx(2.0)
    assert backoff_delay(10, 1.0) == pytest.approx(8.0)  # capped
    assert backoff_delay(1, 0.0) == pytest.approx(0.5)  # jitter lower bound


def test_parse_retry_after() -> None:
    assert parse_retry_after("12") == 12
    assert parse_retry_after("0.5") == 0.5
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0  # in the past


def test_sanitize_removes_keys_and_fragments() -> None:
    key = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    msg = f"Incorrect API key provided: {key}. Also {key[5:25]}… and sk-other1234567890abcd"
    clean = sanitize_message(msg, key)
    assert key not in clean
    assert key[5:25] not in clean
    assert "sk-other1234567890abcd" not in clean
    assert "[REDACTED]" in clean


def test_sanitize_truncates_and_collapses_whitespace() -> None:
    clean = sanitize_message("a\n\n  b " + "x" * 1000)
    assert clean.startswith("a b ")
    assert len(clean) <= 301
