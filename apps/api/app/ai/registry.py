"""Provider types PARE knows about, and how each is called.

Completions for every type go through ``LiteLLMAdapter`` with the type's LiteLLM route
(``litellm_provider``). ``protocol`` selects the direct model lister. Adding a provider
LiteLLM supports is one ``ProviderSpec`` entry (plus the CHECK-constraint migration for
``ai_providers.provider_type``) and, if its route takes a different client type, one line
in ``LiteLLMAdapter._client_arg``.
"""

from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

import httpx

from app.ai.adapters import (
    AnthropicModelLister,
    GeminiModelLister,
    HTTPModelLister,
    LiteLLMAdapter,
    OpenAIModelLister,
    ProviderAdapter,
)
from app.ai.adapters.base import shared_transport
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
    protocol: Protocol  # model-listing protocol
    litellm_provider: str  # LiteLLM route prefix, e.g. "anthropic" -> "anthropic/<model>"
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
            litellm_provider="openai",
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
            litellm_provider="anthropic",
            default_base_url="https://api.anthropic.com",
            key_hint="Starts with sk-ant-",
            docs_url="https://console.anthropic.com/settings/keys",
            model_examples=("claude-sonnet-4-5",),
        ),
        ProviderSpec(
            type=ProviderType.GEMINI,
            label="Google Gemini",
            protocol="gemini",
            litellm_provider="gemini",
            default_base_url="https://generativelanguage.googleapis.com/v1beta",
            key_hint="Google AI Studio key (starts with AIza)",
            docs_url="https://aistudio.google.com/apikey",
            model_examples=("gemini-2.5-flash",),
        ),
        ProviderSpec(
            type=ProviderType.XAI,
            label="xAI Grok",
            protocol="openai",
            litellm_provider="xai",
            default_base_url="https://api.x.ai/v1",
            key_hint="Starts with xai-",
            docs_url="https://console.x.ai",
            model_examples=("grok-4",),
        ),
        ProviderSpec(
            type=ProviderType.DEEPSEEK,
            label="DeepSeek",
            protocol="openai",
            litellm_provider="deepseek",
            default_base_url="https://api.deepseek.com/v1",
            key_hint="Starts with sk-",
            docs_url="https://platform.deepseek.com/api_keys",
            model_examples=("deepseek-chat",),
        ),
        ProviderSpec(
            type=ProviderType.MISTRAL,
            label="Mistral",
            protocol="openai",
            litellm_provider="mistral",
            default_base_url="https://api.mistral.ai/v1",
            docs_url="https://console.mistral.ai/api-keys",
            model_examples=("mistral-small-latest",),
        ),
        ProviderSpec(
            type=ProviderType.OPENAI_COMPATIBLE,
            label="OpenAI-compatible endpoint",
            protocol="openai",
            litellm_provider="openai",
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


def build_adapter_factory(transport: httpx.BaseTransport) -> AdapterFactory:
    """Factory over a specific HTTP transport (tests pass an httpx.MockTransport)."""
    listers: dict[str, HTTPModelLister] = {
        "openai": OpenAIModelLister(transport),
        "anthropic": AnthropicModelLister(transport),
        "gemini": GeminiModelLister(transport),
    }

    def factory(spec: ProviderSpec) -> ProviderAdapter:
        return LiteLLMAdapter(
            litellm_provider=spec.litellm_provider,
            max_tokens_param=spec.max_tokens_param,
            transport=transport,
            lister=listers[spec.protocol],
        )

    return factory


@lru_cache(maxsize=1)
def default_adapter_factory() -> AdapterFactory:
    """Process-wide factory sharing one pooled HTTP transport."""
    return build_adapter_factory(shared_transport())
