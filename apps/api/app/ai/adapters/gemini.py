"""Model listing for the Gemini API, and Gemini error-detail parsing.

Completions go through LiteLLM; ``gemini_error_details`` is shared with it so Gemini's
structured error reasons and ``RetryInfo`` delays are honoured on both paths.
"""

import re

import httpx

from app.ai.adapters.base import HTTPModelLister, as_int
from app.ai.errors import ErrorClass, ProviderError, classify_http
from app.ai.types import DiscoveredModel, ProviderCallConfig

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s$")
INVALID_KEY_REASONS = frozenset({"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED"})


def gemini_error_details(body: object) -> tuple[set[str], float | None]:
    """(error reasons, RetryInfo delay in seconds) from a Gemini error body."""
    details = (body.get("error") or {}).get("details") if isinstance(body, dict) else None
    reasons: set[str] = set()
    retry_after: float | None = None
    for d in details if isinstance(details, list) else []:
        if not isinstance(d, dict):
            continue
        if isinstance(d.get("reason"), str):
            reasons.add(d["reason"])
        delay = d.get("retryDelay")
        if isinstance(delay, str) and (m := _DURATION.match(delay)):
            retry_after = float(m.group(1))
    return reasons, retry_after


class GeminiModelLister(HTTPModelLister):
    protocol = "gemini"

    def _headers(self, cfg: ProviderCallConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": cfg.api_key or "",
        }

    def list_models(self, cfg: ProviderCallConfig) -> list[DiscoveredModel]:
        data = self._request(
            cfg,
            "GET",
            f"{cfg.base_url}/models",
            headers=self._headers(cfg),
            params={"pageSize": 200},
        )
        items = data.get("models")
        if not isinstance(items, list):
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no model list.")
        out = []
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                continue
            methods = item.get("supportedGenerationMethods") or []
            if "generateContent" not in methods:
                continue
            out.append(
                DiscoveredModel(
                    id=item["name"].removeprefix("models/"),
                    display_name=item.get("displayName")
                    if isinstance(item.get("displayName"), str)
                    else None,
                    context_window=as_int(item.get("inputTokenLimit")),
                )
            )
        return sorted(out, key=lambda m: m.id)

    def _error_from_response(
        self, response: httpx.Response, cfg: ProviderCallConfig
    ) -> ProviderError:
        error = super()._error_from_response(response, cfg)
        try:
            body = response.json()
        except ValueError:
            return error
        reasons, delay = gemini_error_details(body)
        retry_after = delay if delay is not None else error.retry_after
        error_class = error.error_class
        if reasons & INVALID_KEY_REASONS:
            error_class = ErrorClass.AUTH
        elif response.status_code == 429:
            # Gemini reports both per-minute limits and exhausted free-tier quotas as
            # RESOURCE_EXHAUSTED; treat as rate limiting and let Retry-After guide us.
            error_class = ErrorClass.RATE_LIMITED
        elif error_class is ErrorClass.UNKNOWN:
            error_class = classify_http(response.status_code, None, error.message)
        return ProviderError(
            error_class,
            error.message,
            http_status=error.http_status,
            retry_after=retry_after,
            provider_code=error.provider_code,
        )
