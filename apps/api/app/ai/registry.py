"""Provider types PARE knows about, and which adapter serves each.

Adding a provider that speaks an existing protocol is one ``ProviderSpec`` entry (plus
the CHECK-constraint migration for ``ai_providers.provider_type``). A new protocol is one
new adapter class.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import httpx

from app.ai.adapters import (
    AnthropicAdapter,
    GeminiAdapter,
    OpenAICompatibleAdapter,
    ProviderAdapter,
)
from app.ai.adapters.base import shared_client
from app.models.enums import ProviderType

Protocol = Literal["openai", "anthropic", "gemini"]
# "mocked": the adapter is covered by automated tests against recorded/mock provider
# responses. "live": additionally verified against the real provider API. Nothing is
# marked live until someone runs tests/live with a real key and records the result here.
Verification = Literal["mocked", "live"]


@dataclass(frozen=True)
class ProviderSpec:
    type: ProviderType
    label: str
    protocol: Protocol
    default_base_url: str | None
    requires_base_url: bool = False
    api_key_required: bool = True
    allow_http: bool = False  # plain-http base URLs (local servers only)
    max_tokens_param: str = "max_tokens"
    key_hint: str = ""
    docs_url: str | None = None
    model_examples: tuple[str, ...] = ()
    verification: Verification = "mocked"


PROVIDER_SPECS: dict[ProviderType, ProviderSpec] = {
    s.type: s
    for s in (
        ProviderSpec(
            type=ProviderType.OPENAI,
            label="OpenAI",
            protocol="openai",
            default_base_url="https://api.openai.com/v1",
            max_tokens_param="max_completion_tokens",
            key_hint="Starts with sk-",
            docs_url="https://platform.openai.com/api-keys",
            model_examples=("gpt-4o-mini",),
        ),
        ProviderSpec(
            type=ProviderType.ANTHROPIC,
            label="Anthropic Claude",
            protocol="anthropic",
            default_base_url="https://api.anthropic.com",
            key_hint="Starts with sk-ant-",
            docs_url="https://console.anthropic.com/settings/keys",
            model_examples=("claude-sonnet-4-5",),
        ),
        ProviderSpec(
            type=ProviderType.GEMINI,
            label="Google Gemini",
            protocol="gemini",
            default_base_url="https://generativelanguage.googleapis.com/v1beta",
            key_hint="Google AI Studio key (starts with AIza)",
            docs_url="https://aistudio.google.com/apikey",
            model_examples=("gemini-2.5-flash",),
        ),
        ProviderSpec(
            type=ProviderType.XAI,
            label="xAI Grok",
            protocol="openai",
            default_base_url="https://api.x.ai/v1",
            key_hint="Starts with xai-",
            docs_url="https://console.x.ai",
            model_examples=("grok-4",),
        ),
        ProviderSpec(
            type=ProviderType.DEEPSEEK,
            label="DeepSeek",
            protocol="openai",
            default_base_url="https://api.deepseek.com/v1",
            key_hint="Starts with sk-",
            docs_url="https://platform.deepseek.com/api_keys",
            model_examples=("deepseek-chat",),
        ),
        ProviderSpec(
            type=ProviderType.MISTRAL,
            label="Mistral",
            protocol="openai",
            default_base_url="https://api.mistral.ai/v1",
            docs_url="https://console.mistral.ai/api-keys",
            model_examples=("mistral-small-latest",),
        ),
        ProviderSpec(
            type=ProviderType.OPENAI_COMPATIBLE,
            label="OpenAI-compatible endpoint",
            protocol="openai",
            default_base_url=None,
            requires_base_url=True,
            api_key_required=False,
            allow_http=True,
            key_hint="Optional for local servers",
            model_examples=("llama3.1:8b",),
        ),
    )
}


def get_spec(provider_type: str) -> ProviderSpec:
    return PROVIDER_SPECS[ProviderType(provider_type)]


AdapterFactory = Callable[[ProviderSpec], ProviderAdapter]


def build_adapter_factory(client: httpx.Client) -> AdapterFactory:
    """Factory over a specific HTTP client (tests pass one with httpx.MockTransport)."""

    def factory(spec: ProviderSpec) -> ProviderAdapter:
        if spec.protocol == "anthropic":
            return AnthropicAdapter(client)
        if spec.protocol == "gemini":
            return GeminiAdapter(client)
        return OpenAICompatibleAdapter(client, max_tokens_param=spec.max_tokens_param)

    return factory


@lru_cache(maxsize=1)
def default_adapter_factory() -> AdapterFactory:
    """Process-wide factory sharing one pooled HTTP client."""
    return build_adapter_factory(shared_client())
