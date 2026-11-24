"""The interface other services use to get AI completions.

Callers say *what* they need (a role, messages, optionally a Pydantic schema); they never
know which provider or model answers. Routing, retries, fallback, usage recording and
key handling all happen behind this interface.

Example (the future Research Planner)::

    ai = get_ai_service()
    result = ai.complete_structured(
        owner_id=user.id,
        role=ModelRole.PLANNER,
        system="You turn research objectives into plans.",
        prompt=objective,
        schema=ResearchPlanDraft,
    )
    plan: ResearchPlanDraft = result.data
    # result.model_identifier, result.provider_name, result.attempts, result.est_cost_usd …

Errors are subclasses of ``app.ai.router.AIRoutingError``:
``AINotConfiguredError``, ``AIProviderConfigError``, ``AIRequestRejectedError``,
``AllProvidersFailedError``. Each carries ``error_class`` and the list of ``attempts``.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from app.ai.registry import AdapterFactory, default_adapter_factory
from app.ai.router import ModelRouter, RoutedResult, parse_json_reply
from app.ai.types import ChatMessage, CompletionRequest
from app.core.config import Settings, get_settings
from app.core.db import get_session_factory
from app.models.enums import ModelRole, UsagePurpose


@dataclass
class StructuredResult[T: BaseModel]:
    data: T
    routed: RoutedResult

    def __getattr__(self, name: str) -> Any:  # result.model_identifier etc.
        if name in ("data", "routed") or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.routed, name)


class AIService:
    def __init__(self, router: ModelRouter) -> None:
        self.router = router

    def complete(
        self,
        *,
        owner_id: uuid.UUID,
        messages: Sequence[ChatMessage] | None = None,
        prompt: str | None = None,
        system: str | None = None,
        role: ModelRole = ModelRole.DEFAULT,
        max_output_tokens: int = 1024,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> RoutedResult:
        request = CompletionRequest(
            messages=_messages(messages, prompt, system),
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        )
        return self.router.complete(owner_id, request, role=role, purpose=UsagePurpose.COMPLETION)

    def complete_structured[T: BaseModel](
        self,
        *,
        owner_id: uuid.UUID,
        schema: type[T],
        messages: Sequence[ChatMessage] | None = None,
        prompt: str | None = None,
        system: str | None = None,
        role: ModelRole = ModelRole.DEFAULT,
        max_output_tokens: int = 4096,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
        max_repairs: int = 1,
    ) -> StructuredResult[T]:
        """Ask for JSON matching ``schema``. Invalid replies get ``max_repairs`` repair
        attempts on the same model (with the validation errors), then fall back."""
        instruction = (
            "Respond with a single JSON object only, no prose and no code fences. "
            "It must validate against this JSON Schema:\n"
            + json.dumps(schema.model_json_schema(), separators=(",", ":"))
        )
        base = _messages(messages, prompt, system)
        if base and base[0].role == "system":
            base = [ChatMessage("system", base[0].content + "\n\n" + instruction), *base[1:]]
        else:
            base = [ChatMessage("system", instruction), *base]
        request = CompletionRequest(
            messages=base,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            json_mode=True,
            timeout_seconds=timeout_seconds,
        )
        routed = self.router.complete(
            owner_id,
            request,
            role=role,
            purpose=UsagePurpose.COMPLETION,
            parse=lambda text: schema.model_validate(parse_json_reply(text)),
            max_repairs=max_repairs,
        )
        return StructuredResult(data=routed.data, routed=routed)


def _messages(
    messages: Sequence[ChatMessage] | None, prompt: str | None, system: str | None
) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    if system:
        out.append(ChatMessage("system", system))
    out.extend(messages or [])
    if prompt:
        out.append(ChatMessage("user", prompt))
    if not any(m.role == "user" for m in out):
        raise ValueError("A completion needs at least one user message.")
    return out


def build_router(
    settings: Settings | None = None, adapter_factory: AdapterFactory | None = None
) -> ModelRouter:
    return ModelRouter(
        get_session_factory(),
        settings or get_settings(),
        adapter_factory or default_adapter_factory(),
    )


def get_ai_service(
    settings: Settings | None = None, adapter_factory: AdapterFactory | None = None
) -> AIService:
    return AIService(build_router(settings, adapter_factory))
