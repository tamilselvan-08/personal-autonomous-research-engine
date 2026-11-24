"""Error taxonomy for provider calls and the single retry/fallback decision table.

Ownership: PARE's router is the only component that retries or falls back. Adapters make
exactly one HTTP request per call and raise ``ProviderError`` with a classification.
"""

import enum
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from app.core.logging import redact


class ErrorClass(enum.StrEnum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    AUTH = "auth"
    QUOTA_EXHAUSTED = "quota_exhausted"
    MODEL_NOT_FOUND = "model_not_found"
    INVALID_REQUEST = "invalid_request"
    CONTEXT_LENGTH = "context_length"
    CONTENT_POLICY = "content_policy"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


# Human-readable explanations shown in the UI next to a classified failure.
ERROR_HINTS: dict[ErrorClass, str] = {
    ErrorClass.TIMEOUT: "The provider did not answer in time.",
    ErrorClass.NETWORK: "Could not connect to the provider. Check the base URL and your network.",
    ErrorClass.RATE_LIMITED: "The provider is rate-limiting requests. Try again shortly.",
    ErrorClass.SERVER_ERROR: "The provider reported a temporary server error or overload.",
    ErrorClass.AUTH: "The API key was rejected. Replace the key for this provider.",
    ErrorClass.QUOTA_EXHAUSTED: "The account has no remaining credit or quota.",
    ErrorClass.MODEL_NOT_FOUND: "The model was not found. Check the model ID.",
    ErrorClass.INVALID_REQUEST: "The provider rejected the request as invalid.",
    ErrorClass.CONTEXT_LENGTH: "The request is larger than the model's context window.",
    ErrorClass.CONTENT_POLICY: "The provider refused the request on content-policy grounds.",
    ErrorClass.INVALID_RESPONSE: "The provider's reply could not be understood.",
    ErrorClass.UNKNOWN: "The provider returned an unexpected error.",
}

TRANSIENT = frozenset(
    {ErrorClass.TIMEOUT, ErrorClass.NETWORK, ErrorClass.SERVER_ERROR, ErrorClass.RATE_LIMITED}
)
# Errors caused by the provider configuration rather than the request.
CONFIGURATION = frozenset({ErrorClass.AUTH, ErrorClass.MODEL_NOT_FOUND})


class ProviderError(Exception):
    """One failed provider call. ``message`` is sanitised and safe to log and display."""

    def __init__(
        self,
        error_class: ErrorClass,
        message: str,
        *,
        http_status: int | None = None,
        retry_after: float | None = None,
        provider_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_class = error_class
        self.message = message
        self.http_status = http_status
        self.retry_after = retry_after
        self.provider_code = provider_code

    def __repr__(self) -> str:
        return f"ProviderError({self.error_class.value}, status={self.http_status})"


_WS = re.compile(r"\s+")
_KEYISH = re.compile(r"\b(?:sk|xai|gsk|key)-[A-Za-z0-9_\-]{8,}\b")


def sanitize_message(message: object, api_key: str | None = None, limit: int = 300) -> str:
    """Make a provider error message safe to store, log and show.

    Removes the exact key (and long fragments of it), anything that looks like a key, and
    truncates. Providers sometimes echo part of the submitted key in auth errors.
    """
    text = message if isinstance(message, str) else str(message or "")
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
        if len(api_key) >= 12:
            for size in (16, 12):
                for i in range(0, len(api_key) - size + 1):
                    frag = api_key[i : i + size]
                    if frag in text:
                        text = text.replace(frag, "[REDACTED]")
    text = _KEYISH.sub("[REDACTED]", redact(text))
    text = _WS.sub(" ", text).strip()
    return text[:limit] + ("…" if len(text) > limit else "")


_AUTH = re.compile(
    r"(invalid|incorrect|missing|expired|revoked)[ _-]*(x-)?api[ _-]?key|api[ _-]?key[ _-]*"
    r"(not valid|invalid|is invalid|expired)|api_key_invalid|authentication|unauthori[sz]ed|"
    r"invalid[ _-]authentication|permission[ _-]denied|permission_error",
    re.I,
)
_QUOTA = re.compile(
    r"insufficient[ _-]quota|insufficient[ _-]balance|credit balance is too low|"
    r"billing[ _-]hard[ _-]limit|payment required|out of credits|no credits|"
    r"exceeded your (?:monthly|current) (?:spending|budget)",
    re.I,
)
_MODEL_NOT_FOUND = re.compile(
    r"model[_ -]not[_ -]found|(model|deployment)\b[^.]{0,80}\b(not found|does not exist|"
    r"is not supported|not available|unknown|no such)|unknown model|invalid model|"
    r"no such model",
    re.I,
)
_CONTEXT = re.compile(
    r"context[_ -]length|maximum context|context window|too many tokens|prompt is too long|"
    r"input is too long|reduce the length",
    re.I,
)
_CONTENT_POLICY = re.compile(r"content[_ -](policy|filter|management)|safety|blocked", re.I)
_OVERLOADED = re.compile(r"overloaded|over capacity|temporarily unavailable", re.I)


def classify_http(status: int, code: str | None, message: str) -> ErrorClass:
    """Classify an HTTP error from a provider. ``code`` is the provider's error code/type."""
    hay = f"{code or ''} {message}"
    is_quota = bool(_QUOTA.search(hay))
    if (status == 401 or _AUTH.search(hay)) and not is_quota:
        return ErrorClass.AUTH
    if status == 402 or is_quota:
        return ErrorClass.QUOTA_EXHAUSTED
    if status == 403:
        return ErrorClass.AUTH
    if status == 408:
        return ErrorClass.TIMEOUT
    if status == 429:
        return ErrorClass.RATE_LIMITED
    if status >= 500 or _OVERLOADED.search(hay):
        return ErrorClass.SERVER_ERROR
    if status == 404 or _MODEL_NOT_FOUND.search(hay):
        return ErrorClass.MODEL_NOT_FOUND
    if _CONTEXT.search(hay):
        return ErrorClass.CONTEXT_LENGTH
    if _CONTENT_POLICY.search(hay):
        return ErrorClass.CONTENT_POLICY
    if status in (400, 405, 409, 413, 415, 422):
        return ErrorClass.INVALID_REQUEST
    return ErrorClass.UNKNOWN


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value.strip())
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        seconds = (when - datetime.now(UTC)).total_seconds()
    return max(0.0, seconds)


@dataclass(frozen=True)
class RoutingPolicyValues:
    max_retries: int = 2
    max_retry_after_seconds: int = 20
    fallback_on_rate_limit: bool = True
    fallback_on_quota_exhausted: bool = False


@dataclass(frozen=True)
class Decision:
    retry: bool
    fallback: bool
    delay: float = 0.0


def backoff_delay(retry_number: int, jitter: float, base: float = 1.0, cap: float = 8.0) -> float:
    """Exponential backoff with jitter. retry_number starts at 1; jitter in [0, 1)."""
    return min(cap, base * (2 ** (retry_number - 1))) * (0.5 + jitter / 2)


def decide(
    error: ProviderError, retries_done: int, policy: RoutingPolicyValues, jitter: float = 0.5
) -> Decision:
    """The single decision table for what happens after a failed attempt."""
    cls = error.error_class
    can_retry = retries_done < policy.max_retries
    delay = backoff_delay(retries_done + 1, jitter)

    if cls in (ErrorClass.TIMEOUT, ErrorClass.NETWORK, ErrorClass.SERVER_ERROR):
        return Decision(retry=can_retry, fallback=True, delay=delay)
    if cls is ErrorClass.RATE_LIMITED:
        hint = error.retry_after
        if hint is not None and hint > policy.max_retry_after_seconds:
            # The provider wants us to wait longer than we are willing to: don't retry here.
            return Decision(retry=False, fallback=policy.fallback_on_rate_limit)
        return Decision(
            retry=can_retry,
            fallback=policy.fallback_on_rate_limit,
            delay=max(delay, hint or 0.0),
        )
    if cls is ErrorClass.QUOTA_EXHAUSTED:
        return Decision(retry=False, fallback=policy.fallback_on_quota_exhausted)
    if cls is ErrorClass.INVALID_RESPONSE:
        return Decision(retry=retries_done < min(1, policy.max_retries), fallback=True, delay=delay)
    if cls is ErrorClass.UNKNOWN:
        # Unknown errors get one retry (they may be transient) but never a fallback.
        return Decision(
            retry=retries_done < min(1, policy.max_retries), fallback=False, delay=delay
        )
    # AUTH, MODEL_NOT_FOUND, INVALID_REQUEST, CONTEXT_LENGTH, CONTENT_POLICY:
    # retrying or sending the same request elsewhere would not help, or would hide a
    # configuration problem the user needs to fix.
    return Decision(retry=False, fallback=False)
