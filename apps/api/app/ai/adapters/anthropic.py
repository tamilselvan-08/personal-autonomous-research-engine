"""Model listing for the Anthropic API. Completions go through LiteLLM."""

from app.ai.adapters.base import HTTPModelLister
from app.ai.errors import ErrorClass, ProviderError
from app.ai.types import DiscoveredModel, ProviderCallConfig

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicModelLister(HTTPModelLister):
    protocol = "anthropic"

    def _headers(self, cfg: ProviderCallConfig) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "anthropic-version": ANTHROPIC_VERSION,
            "x-api-key": cfg.api_key or "",
        }

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
