"""Adapter contract and shared HTTP handling.

An adapter translates one provider-neutral request into one HTTP request for a wire
protocol, and translates the response or failure back. It never retries, never falls
back, never logs request content, and never follows redirects (so a key is never sent to
a host other than the configured one).
"""

from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.ai.errors import (
    ErrorClass,
    ProviderError,
    classify_http,
    parse_retry_after,
    sanitize_message,
)
from app.ai.types import CompletionRequest, CompletionResponse, DiscoveredModel, ProviderCallConfig

USER_AGENT = "PARE/0.2 (personal research engine)"


def shared_client() -> httpx.Client:
    return httpx.Client(
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


class ProviderAdapter(ABC):
    """One wire protocol. Instances are stateless apart from the HTTP client."""

    protocol: str

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or shared_client()

    @abstractmethod
    def complete(self, cfg: ProviderCallConfig, request: CompletionRequest) -> CompletionResponse:
        """Make one completion call. Raises ProviderError on any failure."""

    @abstractmethod
    def list_models(self, cfg: ProviderCallConfig) -> list[DiscoveredModel]:
        """List models the account can use. Raises ProviderError on any failure."""

    # --- shared HTTP plumbing -----------------------------------------------------------

    def _request(
        self,
        cfg: ProviderCallConfig,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                timeout=httpx.Timeout(cfg.timeout_seconds, connect=min(10.0, cfg.timeout_seconds)),
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                ErrorClass.TIMEOUT, "The request to the provider timed out."
            ) from exc
        except httpx.InvalidURL as exc:
            raise ProviderError(ErrorClass.NETWORK, "The provider base URL is not valid.") from exc
        except httpx.TransportError as exc:
            raise ProviderError(
                ErrorClass.NETWORK,
                f"Could not connect to the provider ({exc.__class__.__name__}).",
            ) from exc

        if 300 <= response.status_code < 400:
            raise ProviderError(
                ErrorClass.INVALID_REQUEST,
                f"The provider answered with a redirect ({response.status_code}). "
                "Check the base URL; PARE does not follow redirects with your API key.",
                http_status=response.status_code,
            )
        if response.status_code >= 400:
            raise self._error_from_response(response, cfg)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError(
                ErrorClass.INVALID_RESPONSE,
                "The provider returned a response that is not JSON. Check the base URL.",
                http_status=response.status_code,
            ) from exc
        if not isinstance(data, dict):
            raise ProviderError(
                ErrorClass.INVALID_RESPONSE,
                "The provider returned an unexpected response shape.",
                http_status=response.status_code,
            )
        return data

    def _parse_error_body(self, response: httpx.Response) -> tuple[str | None, str]:
        """Return (provider_code, message) from a provider error body."""
        try:
            body = response.json()
        except ValueError:
            return None, response.text[:300] or response.reason_phrase
        if isinstance(body, dict):
            err = body.get("error", body)
            if isinstance(err, dict):
                code = err.get("code") or err.get("type") or err.get("status")
                message = err.get("message") or body.get("message") or body.get("detail") or ""
                return (str(code) if code is not None else None), str(message)
            if isinstance(err, str):
                return None, err
            detail = body.get("detail") or body.get("message")
            if detail:
                return None, str(detail)
        return None, str(body)[:300]

    def _retry_after(self, response: httpx.Response) -> float | None:
        ms = response.headers.get("retry-after-ms")
        if ms:
            try:
                return max(0.0, float(ms) / 1000)
            except ValueError:
                pass
        return parse_retry_after(response.headers.get("retry-after"))

    def _error_from_response(
        self, response: httpx.Response, cfg: ProviderCallConfig
    ) -> ProviderError:
        code, message = self._parse_error_body(response)
        error_class = classify_http(response.status_code, code, message)
        return ProviderError(
            error_class,
            sanitize_message(message or response.reason_phrase, cfg.api_key)
            or f"HTTP {response.status_code}",
            http_status=response.status_code,
            retry_after=self._retry_after(response),
            provider_code=sanitize_message(code, cfg.api_key, limit=60) if code else None,
        )


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
