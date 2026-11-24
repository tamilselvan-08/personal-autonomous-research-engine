"""Google Gemini API (generativelanguage.googleapis.com, generateContent) protocol."""

import re
from typing import Any

import httpx

from app.ai.adapters.base import ProviderAdapter, as_int
from app.ai.errors import ErrorClass, ProviderError, classify_http, sanitize_message
from app.ai.types import CompletionRequest, CompletionResponse, DiscoveredModel, ProviderCallConfig

_DURATION = re.compile(r"^(\d+(?:\.\d+)?)s$")


def model_path(model: str) -> str:
    """'gemini-x' → 'models/gemini-x'; already-qualified names are kept."""
    if model.startswith(("models/", "tunedModels/")):
        return model
    return f"models/{model}"


class GeminiAdapter(ProviderAdapter):
    protocol = "gemini"

    def _headers(self, cfg: ProviderCallConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-goog-api-key": cfg.api_key or "",
        }

    def complete(self, cfg: ProviderCallConfig, request: CompletionRequest) -> CompletionResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        contents = [
            {"role": "model" if m.role == "assistant" else "user", "parts": [{"text": m.content}]}
            for m in request.messages
            if m.role != "system"
        ]
        generation: dict[str, Any] = {"maxOutputTokens": request.max_output_tokens}
        if request.temperature is not None:
            generation["temperature"] = request.temperature
        if request.json_mode:
            generation["responseMimeType"] = "application/json"
        body: dict[str, Any] = {"contents": contents, "generationConfig": generation}
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        data = self._request(
            cfg,
            "POST",
            f"{cfg.base_url}/{model_path(cfg.model)}:generateContent",
            headers=self._headers(cfg),
            json=body,
        )
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = data.get("promptFeedback")
            if isinstance(feedback, dict) and feedback.get("blockReason"):
                raise ProviderError(
                    ErrorClass.CONTENT_POLICY,
                    f"The prompt was blocked ({sanitize_message(feedback['blockReason'])}).",
                )
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no candidates.")
        first = candidates[0] if isinstance(candidates[0], dict) else {}
        parts = (first.get("content") or {}).get("parts") or []
        text = "".join(
            p.get("text", "")
            for p in parts
            if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")
        )
        finish = first.get("finishReason")
        if finish in ("SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST") and not text:
            raise ProviderError(ErrorClass.CONTENT_POLICY, "The response was blocked for safety.")
        usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
        return CompletionResponse(
            text=text,
            input_tokens=as_int(usage.get("promptTokenCount")),
            output_tokens=as_int(usage.get("candidatesTokenCount")),
            finish_reason=finish if isinstance(finish, str) else None,
            response_model=data.get("modelVersion")
            if isinstance(data.get("modelVersion"), str)
            else None,
        )

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
        details = (body.get("error") or {}).get("details") if isinstance(body, dict) else None
        reasons: set[str] = set()
        retry_after = error.retry_after
        for d in details if isinstance(details, list) else []:
            if not isinstance(d, dict):
                continue
            if isinstance(d.get("reason"), str):
                reasons.add(d["reason"])
            delay = d.get("retryDelay")
            if isinstance(delay, str) and (m := _DURATION.match(delay)):
                retry_after = float(m.group(1))
        error_class = error.error_class
        if reasons & {"API_KEY_INVALID", "API_KEY_EXPIRED", "API_KEY_SERVICE_BLOCKED"}:
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
