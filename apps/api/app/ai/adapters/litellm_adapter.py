"""Completion calls through the LiteLLM Python SDK (PRD C5).

LiteLLM performs exactly one provider HTTP request per call. Everything that decides
*whether* and *where* to call again lives in ``app.ai.router.ModelRouter``. This module
guarantees that LiteLLM cannot retry, fall back or leak a key on its own:

* ``num_retries=0`` and ``max_retries=0`` on every call. LiteLLM's default OpenAI client
  would otherwise retry twice by itself (verified: 3 HTTP requests for one call).
* Every call uses PARE's own HTTP client (``client=``): never follows redirects, so a
  key is never re-sent to a host other than the configured one, and carries the call's
  timeout. Which client type LiteLLM accepts depends on the provider route, so this is
  pinned per provider and covered by tests (a wrong type is silently ignored by LiteLLM).
* The bundled model-cost map is used (no network fetch on import), debug output and
  message logging are off, and LiteLLM's own loggers are silenced; PARE logs
  sanitised, classified errors itself.
* Errors are mapped onto PARE's ``ErrorClass`` taxonomy; messages are sanitised.
"""

import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx

from app.ai.adapters.base import (
    HTTPModelLister,
    ProviderAdapter,
    as_int,
    client_for,
    parse_error_body,
)
from app.ai.adapters.gemini import INVALID_KEY_REASONS, gemini_error_details
from app.ai.errors import (
    ErrorClass,
    ProviderError,
    classify_http,
    parse_retry_after,
    sanitize_message,
)
from app.ai.types import CompletionRequest, CompletionResponse, DiscoveredModel, ProviderCallConfig

# Keyless local OpenAI-compatible servers (LM Studio, Ollama): the OpenAI client needs a
# non-empty key, and these servers ignore it.
NO_KEY_PLACEHOLDER = "not-needed"

_LITELLM_LOGGERS = ("LiteLLM", "LiteLLM Router", "LiteLLM Proxy", "litellm")
_load_lock = threading.Lock()
_litellm: Any = None


def load_litellm() -> Any:
    """Import and configure LiteLLM once. Lazy: the import takes several seconds."""
    global _litellm
    if _litellm is None:
        with _load_lock:
            if _litellm is None:
                os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
                import litellm

                litellm.suppress_debug_info = True
                litellm.telemetry = False
                litellm.num_retries = 0
                litellm.turn_off_message_logging = True
                # Drop parameters a model doesn't accept (e.g. temperature on reasoning
                # models) instead of failing; JSON output is validated by PARE anyway.
                litellm.drop_params = True
                for name in _LITELLM_LOGGERS:
                    logging.getLogger(name).setLevel(logging.CRITICAL)
                _litellm = litellm
    return _litellm


# "litellm.RateLimitError: RateLimitError: DeepseekException - {...}" -> "{...}"
_PREFIX = re.compile(r"^\s*(?:litellm\.\w+:\s*)?(?:\w+Error:\s*)*(?:\w+Exception\s*-\s*)?")
_CONNECTION = re.compile(
    r"connection (?:error|refused|reset|aborted)|connecterror|failed to establish|"
    r"name or service not known|getaddrinfo|nodename nor servname|unreachable",
    re.I,
)


_JSON_MESSAGE = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"')
_JSON_REASON = re.compile(r'"reason"\s*:\s*"([A-Z_]+)"')
_JSON_RETRY_DELAY = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def _chain(exc: BaseException) -> list[BaseException]:
    """The exception and its causes. LiteLLM wraps transport errors in its own types."""
    seen: list[BaseException] = []
    current: BaseException | None = exc
    while current is not None and current not in seen and len(seen) < 10:
        seen.append(current)
        current = current.__cause__ or current.__context__
    return seen


def _response_text(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        text = response.text
    except Exception:  # noqa: BLE001 - unread/streamed/synthetic responses
        return None
    return text if isinstance(text, str) and text else None


def _header(headers: object, name: str) -> str | None:
    if headers is None:
        return None
    try:
        items = headers.items()  # type: ignore[attr-defined]
    except AttributeError:
        return None
    for key, value in items:
        if str(key).lower() == name:
            return str(value)
    return None


class LiteLLMAdapter(ProviderAdapter):
    """One provider type. Completions via LiteLLM; model listing via a direct lister."""

    def __init__(
        self,
        *,
        litellm_provider: str,
        max_tokens_param: str,
        transport: httpx.BaseTransport,
        lister: HTTPModelLister,
    ) -> None:
        self.litellm_provider = litellm_provider
        self.max_tokens_param = max_tokens_param
        self._transport = transport
        self._lister = lister

    def model_name(self, model: str) -> str:
        if self.litellm_provider == "gemini":
            model = model.removeprefix("models/")
        return f"{self.litellm_provider}/{model}"

    def _client_arg(self, cfg: ProviderCallConfig, api_key: str) -> Any:
        http = client_for(self._transport, cfg.timeout_seconds)
        if self.litellm_provider == "openai":
            # LiteLLM's openai route only accepts an OpenAI SDK client here.
            from openai import OpenAI

            return OpenAI(
                api_key=api_key,
                base_url=cfg.base_url,
                http_client=http,
                max_retries=0,
                timeout=cfg.timeout_seconds,
            )
        # anthropic, gemini, deepseek, xai, mistral routes take LiteLLM's HTTPHandler.
        from litellm.llms.custom_httpx.http_handler import HTTPHandler

        return HTTPHandler(client=http)

    def complete(self, cfg: ProviderCallConfig, request: CompletionRequest) -> CompletionResponse:
        litellm = load_litellm()
        api_key = cfg.api_key or NO_KEY_PLACEHOLDER
        kwargs: dict[str, Any] = {
            "model": self.model_name(cfg.model),
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "api_base": cfg.base_url,
            "api_key": api_key,
            "timeout": cfg.timeout_seconds,
            "num_retries": 0,
            "max_retries": 0,
            self.max_tokens_param: request.max_output_tokens,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        try:
            kwargs["client"] = self._client_arg(cfg, api_key)
            response = litellm.completion(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure becomes a classified error
            # `from None`: the original exception chain can carry request details.
            raise self.map_error(exc, cfg) from None
        return self.map_response(response)

    def list_models(self, cfg: ProviderCallConfig) -> list[DiscoveredModel]:
        return self._lister.list_models(cfg)

    # --- translation --------------------------------------------------------------------

    @staticmethod
    def map_response(response: Any) -> CompletionResponse:
        choices = getattr(response, "choices", None)
        if not choices:
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no choices.")
        choice = choices[0]
        message = getattr(choice, "message", None)
        content = getattr(message, "content", None)
        if isinstance(content, list):  # content parts
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict) and p.get("text")
            )
        text = content if isinstance(content, str) else ""
        finish = getattr(choice, "finish_reason", None)
        if finish == "content_filter" and not text:
            raise ProviderError(
                ErrorClass.CONTENT_POLICY, "The provider filtered the response (content policy)."
            )
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", None)
        return CompletionResponse(
            text=text,
            input_tokens=as_int(getattr(usage, "prompt_tokens", None)),
            output_tokens=as_int(getattr(usage, "completion_tokens", None)),
            finish_reason=finish if isinstance(finish, str) else None,
            response_model=model if isinstance(model, str) else None,
        )

    def map_error(self, exc: Exception, cfg: ProviderCallConfig) -> ProviderError:
        litellm = load_litellm()
        status = getattr(exc, "status_code", None)
        status = status if isinstance(status, int) and not isinstance(status, bool) else None
        raw = str(getattr(exc, "message", None) or exc)
        text = _PREFIX.sub("", raw).strip()
        # The provider's error body: on LiteLLM's openai route it is on the response (and
        # parsed in `body`); on the other routes it is embedded in the message.
        body_text = text if text.startswith("{") else None
        resp_text = _response_text(exc)
        if resp_text and resp_text.lstrip().startswith("{"):
            body_text = resp_text
        if body_text:
            code, message = parse_error_body(body_text)
        elif isinstance(getattr(exc, "body", None), dict):
            body = exc.body  # type: ignore[attr-defined]
            raw_code = body.get("code") or body.get("type")
            code = str(raw_code) if raw_code is not None else None
            message = str(body.get("message") or text)
        else:
            code, message = None, text
        headers = getattr(exc, "litellm_response_headers", None)
        retry_after = None
        ms = _header(headers, "retry-after-ms")
        if ms:
            try:
                retry_after = max(0.0, float(ms) / 1000)
            except ValueError:
                retry_after = None
        if retry_after is None:
            retry_after = parse_retry_after(_header(headers, "retry-after"))

        # LiteLLM sometimes truncates the middle of long bodies, so the JSON may not parse.
        if message.startswith("{") and (m := _JSON_MESSAGE.search(message)):
            message = m.group(1)
        chain = _chain(exc)

        error_class: ErrorClass
        if isinstance(exc, litellm.Timeout) or any(
            isinstance(e, httpx.TimeoutException) for e in chain
        ):
            error_class, message = ErrorClass.TIMEOUT, "The request to the provider timed out."
        elif isinstance(exc, litellm.ContextWindowExceededError):
            error_class = ErrorClass.CONTEXT_LENGTH
        elif isinstance(exc, litellm.ContentPolicyViolationError):
            error_class = ErrorClass.CONTENT_POLICY
        elif status is not None and 300 <= status < 400:
            error_class = ErrorClass.INVALID_REQUEST
            message = (
                f"The provider answered with a redirect ({status}). Check the base URL; "
                "PARE does not follow redirects with your API key."
            )
        elif (
            isinstance(exc, litellm.APIConnectionError)
            or any(isinstance(e, httpx.TransportError) for e in chain)
            or _CONNECTION.search(text)
        ):
            error_class = ErrorClass.NETWORK
            message = (
                "Could not connect to the provider, or it redirected the request. "
                "Check the base URL and your network."
            )
        elif status is not None:
            error_class = classify_http(status, code, message)
        elif isinstance(exc, litellm.AuthenticationError):
            error_class = ErrorClass.AUTH
        elif isinstance(exc, litellm.NotFoundError):
            error_class = ErrorClass.MODEL_NOT_FOUND
        elif isinstance(exc, litellm.RateLimitError):
            error_class = classify_http(429, code, message)
        elif isinstance(exc, litellm.BadRequestError):
            error_class = classify_http(400, code, message)
        elif isinstance(exc, (litellm.ServiceUnavailableError, litellm.InternalServerError)):
            error_class = ErrorClass.SERVER_ERROR
        else:
            error_class = ErrorClass.UNKNOWN
            message = message or f"Unexpected error in the provider client ({type(exc).__name__})."

        if self.litellm_provider == "gemini":
            reasons: set[str] = set()
            delay: float | None = None
            try:
                reasons, delay = gemini_error_details(json.loads(body_text or ""))
            except ValueError:
                reasons = set(_JSON_REASON.findall(text))
                if m := _JSON_RETRY_DELAY.search(text):
                    delay = float(m.group(1))
            if reasons & INVALID_KEY_REASONS:
                error_class = ErrorClass.AUTH
            elif status == 429:
                # Gemini reports per-minute limits and exhausted free-tier quotas alike as
                # RESOURCE_EXHAUSTED; treat as rate limiting and let RetryInfo guide us.
                error_class = ErrorClass.RATE_LIMITED
            if delay is not None:
                retry_after = delay

        return ProviderError(
            error_class,
            sanitize_message(message or type(exc).__name__, cfg.api_key)
            or f"HTTP {status or 'error'}",
            http_status=status,
            retry_after=retry_after,
            provider_code=sanitize_message(code, cfg.api_key, limit=60) if code else None,
        )


# --- model metadata from LiteLLM's bundled model map (FR-LLM-002 prefill) ----------------


@dataclass(frozen=True)
class KnownModelInfo:
    context_window: int | None
    input_price_per_mtok: Decimal | None
    output_price_per_mtok: Decimal | None
    capabilities: frozenset[str]  # ModelCapability values


def _per_mtok(per_token: object) -> Decimal | None:
    if not isinstance(per_token, (int, float)) or isinstance(per_token, bool) or per_token < 0:
        return None
    return (Decimal(str(per_token)) * 1_000_000).quantize(Decimal("0.000001"))


def known_model_info(litellm_provider: str, model: str) -> KnownModelInfo | None:
    """Context window, list prices and capabilities LiteLLM knows for a hosted model.

    Used only to prefill fields the user left empty; values stay user-editable. Returns
    None for unknown models.
    """
    litellm = load_litellm()
    name = model.removeprefix("models/") if litellm_provider == "gemini" else model
    try:
        info = litellm.get_model_info(model=f"{litellm_provider}/{name}")
    except Exception:  # noqa: BLE001 - unknown model (ModelNotMappedError and friends)
        return None
    caps = {
        cap
        for cap, key in (
            ("json", "supports_response_schema"),
            ("vision", "supports_vision"),
            ("tools", "supports_function_calling"),
            ("reasoning", "supports_reasoning"),
        )
        if info.get(key) is True
    }
    window = info.get("max_input_tokens")
    return KnownModelInfo(
        context_window=window if isinstance(window, int) and window > 0 else None,
        input_price_per_mtok=_per_mtok(info.get("input_cost_per_token")),
        output_price_per_mtok=_per_mtok(info.get("output_cost_per_token")),
        capabilities=frozenset(caps),
    )
