"""Model listing for the OpenAI ``GET /models`` protocol.

Serves OpenAI, xAI, DeepSeek, Mistral and any OpenAI-compatible endpoint (LM Studio,
Ollama, vLLM, …). Completions go through LiteLLM (see litellm_adapter.py).
"""

from app.ai.adapters.base import HTTPModelLister, as_int
from app.ai.errors import ErrorClass, ProviderError
from app.ai.types import DiscoveredModel, ProviderCallConfig


class OpenAIModelLister(HTTPModelLister):
    protocol = "openai"

    def _headers(self, cfg: ProviderCallConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if cfg.api_key:
            headers["Authorization"] = f"Bearer {cfg.api_key}"
        return headers

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
