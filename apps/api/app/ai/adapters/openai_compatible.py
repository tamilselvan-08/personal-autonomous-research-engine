"""OpenAI Chat Completions protocol.

Serves OpenAI, xAI, DeepSeek, Mistral and any OpenAI-compatible endpoint (LM Studio,
Ollama, vLLM, LiteLLM proxy, …). Differences between them are parameters, not code.
"""

from typing import Any

import httpx

from app.ai.adapters.base import ProviderAdapter, as_int
from app.ai.errors import ErrorClass, ProviderError
from app.ai.types import CompletionRequest, CompletionResponse, DiscoveredModel, ProviderCallConfig


class OpenAICompatibleAdapter(ProviderAdapter):
    protocol = "openai"

    def __init__(
        self, client: httpx.Client | None = None, *, max_tokens_param: str = "max_tokens"
    ) -> None:
        super().__init__(client)
        # OpenAI's newer models reject `max_tokens` and require `max_completion_tokens`.
        self.max_tokens_param = max_tokens_param

    def _headers(self, cfg: ProviderCallConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        return headers

    def complete(self, cfg: ProviderCallConfig, request: CompletionRequest) -> CompletionResponse:
        body: dict[str, Any] = {
            "model": cfg.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            self.max_tokens_param: request.max_output_tokens,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.json_mode:
            body["response_format"] = {"type": "json_object"}

        data = self._request(
            cfg, "POST", f"{cfg.base_url}/chat/completions", headers=self._headers(cfg), json=body
        )
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no choices.")
        choice = choices[0]
        message = choice.get("message") or {}
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):  # some compatible servers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        finish = choice.get("finish_reason")
        if finish == "content_filter" and not content:
            raise ProviderError(
                ErrorClass.CONTENT_POLICY, "The provider filtered the response (content policy)."
            )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        return CompletionResponse(
            text=content if isinstance(content, str) else "",
            input_tokens=as_int(usage.get("prompt_tokens")),
            output_tokens=as_int(usage.get("completion_tokens")),
            finish_reason=finish if isinstance(finish, str) else None,
            response_model=data.get("model") if isinstance(data.get("model"), str) else None,
        )

    def list_models(self, cfg: ProviderCallConfig) -> list[DiscoveredModel]:
        data = self._request(cfg, "GET", f"{cfg.base_url}/models", headers=self._headers(cfg))
        items = data.get("data")
        if not isinstance(items, list):
            raise ProviderError(ErrorClass.INVALID_RESPONSE, "The provider returned no model list.")
        models = [
            DiscoveredModel(
                id=str(item["id"]),
                display_name=item.get("name") if isinstance(item.get("name"), str) else None,
                context_window=as_int(item.get("context_length") or item.get("context_window")),
            )
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return sorted(models, key=lambda m: m.id)
