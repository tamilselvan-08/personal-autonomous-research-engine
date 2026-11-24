"""Provider-neutral request and response types."""

from dataclasses import dataclass, field
from typing import Literal

MessageRole = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: MessageRole
    content: str


@dataclass(frozen=True)
class CompletionRequest:
    messages: list[ChatMessage]
    max_output_tokens: int = 1024
    temperature: float | None = None
    # Ask the provider for a JSON object. Only honoured for models marked supports_json;
    # structured callers also instruct JSON in the prompt and validate the result.
    json_mode: bool = False
    timeout_seconds: float | None = None


@dataclass(frozen=True)
class ProviderCallConfig:
    """Everything an adapter needs for one call. The key is excluded from repr()."""

    provider_type: str
    base_url: str
    model: str
    timeout_seconds: float
    api_key: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class CompletionResponse:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    response_model: str | None = None


@dataclass(frozen=True)
class DiscoveredModel:
    id: str
    display_name: str | None = None
    context_window: int | None = None
