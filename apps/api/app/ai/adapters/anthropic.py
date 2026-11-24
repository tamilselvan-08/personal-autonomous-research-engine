"""Anthropic Messages API protocol."""

from typing import Any

from app.ai.adapters.base import ProviderAdapter, as_int
from app.ai.errors import ErrorClass, ProviderError
from app.ai.types import CompletionRequest, CompletionResponse, DiscoveredModel, ProviderCallConfig

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicAdapter(ProviderAdapter):
    protocol = "anthropic"

    def _headers(self, cfg: ProviderCallConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "x-api-key": cfg.api_key or "",
        }

    def complete(self, cfg: ProviderCallConfig, request: CompletionRequest) -> CompletionResponse:
        system = "\n\n".join(m.content for m in request.messages if m.role == "system")
        messages: list[dict[str, str]] = []
        for m in request.messages:
            if m.role == "system":
                continue
            # The Messages API requires alternating roles; merge consecutive same-role turns.
            if messages and messages[-1]["role"] == m.role:
                messages[-1]["content"] += "\n\n" + m.content
            else:
                messages.append({"role": m.role, "content": m.content})
        body: dict[str, Any] = {
            "model": cfg.model,
            "max_tokens": request.max_output_tokens,
            "messages": messages,
        }
        if system:
            body["system"] = system
        if request.temperature is not None:
            body["temperature"] = request.temperature

        data = self._request(
            cfg, "POST", f"{cfg.base_url}/v1/messages", headers=self._headers(cfg), json=body
        )
        content = data.get("content")
        if not isinstance(content, list):
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no content.")
        text = "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
        stop = data.get("stop_reason")
        if stop == "refusal" and not text:
            raise ProviderError(ErrorClass.CONTENT_POLICY, "The model declined the request.")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return CompletionResponse(
            text=text,
            input_tokens=as_int(usage.get("input_tokens")),
            output_tokens=as_int(usage.get("output_tokens")),
            finish_reason=stop if isinstance(stop, str) else None,
            response_model=data.get("model") if isinstance(data.get("model"), str) else None,
        )

    def list_models(self, cfg: ProviderCallConfig) -> list[DiscoveredModel]:
        data = self._request(
            cfg,
            "GET",
            f"{cfg.base_url}/v1/models",
            headers=self._headers(cfg),
            params={"limit": 100},
        )
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no model list.")
        return sorted(
            (
                DiscoveredModel(
                    id=item["id"],
                    display_name=item.get("display_name")
                    if isinstance(item.get("display_name"), str)
                    else None,
                )
                for item in items
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ),
            key=lambda m: m.id,
        )
