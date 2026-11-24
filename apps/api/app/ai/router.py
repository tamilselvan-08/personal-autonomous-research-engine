"""Primary/fallback routing — the single owner of retries and fallback decisions.

For a role, the router walks the user's ordered chain (position 0 = primary):

1. Skip models that are disabled, have no usable key, or whose circuit is open.
2. Call the model once through its adapter.
3. On failure, classify it and consult ``errors.decide``: retry the same model (bounded,
   exponential backoff with jitter, honouring Retry-After), fall back to the next model,
   or stop and surface the error.
4. Return the first success, or raise a ``AIRoutingError`` explaining every attempt.

Every attempt is recorded (provider, model, latency, outcome, classification). API keys are
decrypted just before each call and never stored on the router.
"""

import json
import random
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.errors import (
    ERROR_HINTS,
    ErrorClass,
    ProviderError,
    RoutingPolicyValues,
    decide,
)
from app.ai.recorder import AttemptTarget, UsageRecorder, circuit_is_open
from app.ai.registry import AdapterFactory, default_adapter_factory, get_spec
from app.ai.types import ChatMessage, CompletionRequest, CompletionResponse, ProviderCallConfig
from app.core.config import Settings
from app.core.crypto import DecryptionError, EncryptionNotConfiguredError, get_keyring
from app.models import AIModel, ModelRoute, RoutingPolicy
from app.models.enums import ModelRole, UsageOutcome, UsagePurpose
from app.services import secret_service


@dataclass
class AttemptInfo:
    """What happened to one entry of the chain. Safe to return to the user."""

    provider_name: str
    model_identifier: str
    model_id: uuid.UUID | None
    outcome: str  # success | retry | fallback | error | skipped
    attempt: int | None = None
    error_class: str | None = None
    message: str | None = None
    http_status: int | None = None
    latency_ms: int | None = None


@dataclass
class RoutedResult:
    text: str
    data: Any
    call_id: uuid.UUID
    provider_id: uuid.UUID | None
    provider_name: str
    provider_type: str
    model_id: uuid.UUID | None
    model_identifier: str
    input_tokens: int | None
    output_tokens: int | None
    est_cost_usd: Decimal | None
    latency_ms: int
    attempts: list[AttemptInfo] = field(default_factory=list)

    @property
    def used_fallback(self) -> bool:
        return any(a.outcome == "fallback" for a in self.attempts)


class AIRoutingError(Exception):
    code = "AI_ROUTING_FAILED"

    def __init__(
        self,
        message: str,
        *,
        error_class: ErrorClass | None = None,
        attempts: list[AttemptInfo] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_class = error_class
        self.attempts = attempts or []


class AINotConfiguredError(AIRoutingError):
    code = "AI_NOT_CONFIGURED"


class AIProviderConfigError(AIRoutingError):
    """Auth failure, unknown model, or exhausted quota without fallback: the user must act."""

    code = "AI_PROVIDER_CONFIG_ERROR"


class AIRequestRejectedError(AIRoutingError):
    """The request itself was rejected (invalid, too long, content policy)."""

    code = "AI_REQUEST_REJECTED"


class AllProvidersFailedError(AIRoutingError):
    code = "AI_ALL_PROVIDERS_FAILED"


@dataclass(frozen=True)
class ChainEntry:
    target: AttemptTarget
    base_url: str
    supports_json: bool
    secret_id: uuid.UUID | None
    skip_reason: str | None


def load_policy(db: Session, owner_id: uuid.UUID) -> RoutingPolicyValues:
    row = db.get(RoutingPolicy, owner_id)
    if row is None:
        return RoutingPolicyValues()
    return RoutingPolicyValues(
        max_retries=row.max_retries,
        max_retry_after_seconds=row.max_retry_after_seconds,
        fallback_on_rate_limit=row.fallback_on_rate_limit,
        fallback_on_quota_exhausted=row.fallback_on_quota_exhausted,
    )


def resolve_base_url(provider_type: str, base_url: str | None) -> str:
    spec = get_spec(provider_type)
    return (base_url or spec.default_base_url or "").rstrip("/")


def _entry_for(model: AIModel, now: datetime) -> ChainEntry:
    provider = model.provider
    spec = get_spec(provider.provider_type)
    skip: str | None = None
    if not provider.enabled:
        skip = "Provider is disabled."
    elif not model.enabled:
        skip = "Model is disabled."
    elif provider.secret_id is None and spec.api_key_required:
        skip = "Provider has no API key."
    elif circuit_is_open(model.circuit_opened_at, now):
        skip = "Circuit open after repeated failures; retrying after a short cool-down."
    return ChainEntry(
        target=AttemptTarget(
            owner_id=model.owner_id,
            provider_id=provider.id,
            provider_type=provider.provider_type,
            provider_name=provider.display_name,
            model_id=model.id,
            model_identifier=model.model_identifier,
            input_price_per_mtok=model.input_price_per_mtok,
            output_price_per_mtok=model.output_price_per_mtok,
        ),
        base_url=resolve_base_url(provider.provider_type, provider.base_url),
        supports_json=model.supports_json,
        secret_id=provider.secret_id,
        skip_reason=skip,
    )


def load_chain(
    db: Session, owner_id: uuid.UUID, role: ModelRole
) -> tuple[ModelRole, list[ChainEntry]]:
    """The ordered chain for ``role``, falling back to the 'default' role's chain."""
    now = datetime.now(UTC)
    for candidate in (role, ModelRole.DEFAULT) if role is not ModelRole.DEFAULT else (role,):
        routes = list(
            db.scalars(
                select(ModelRoute)
                .where(ModelRoute.owner_id == owner_id, ModelRoute.role == candidate.value)
                .order_by(ModelRoute.position)
            )
        )
        if routes:
            return candidate, [
                _entry_for(r.model, now) for r in routes if r.model.owner_id == owner_id
            ]
    return role, []


def _ms(start: float, end: float) -> int:
    return max(0, round((end - start) * 1000))


def _repair_messages(request: CompletionRequest, reply: str, problem: str) -> CompletionRequest:
    excerpt = reply if len(reply) <= 4000 else reply[:4000] + "…"
    return replace(
        request,
        messages=[
            *request.messages,
            ChatMessage("assistant", excerpt),
            ChatMessage(
                "user",
                "Your previous reply could not be used: "
                f"{problem[:1000]}\nReply again with only the corrected JSON, no prose.",
            ),
        ],
    )


def parse_json_reply(text: str) -> Any:
    """Parse a JSON reply, tolerating a surrounding ```json fence."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        start, end = stripped.find("{"), stripped.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"Reply is not valid JSON ({exc.msg}).") from exc


class ModelRouter:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        settings: Settings,
        adapter_factory: AdapterFactory | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._adapters = adapter_factory or default_adapter_factory()
        self._sleep = sleep
        self._jitter = jitter
        self._clock = clock
        self.recorder = UsageRecorder(session_factory)

    # --- public API ---------------------------------------------------------------------

    def complete(
        self,
        owner_id: uuid.UUID,
        request: CompletionRequest,
        *,
        role: ModelRole = ModelRole.DEFAULT,
        purpose: UsagePurpose = UsagePurpose.COMPLETION,
        parse: Callable[[str], Any] | None = None,
        max_repairs: int = 1,
    ) -> RoutedResult:
        """Route one completion. ``parse`` (optional) converts the reply text; a ValueError
        from it triggers a repair attempt on the same model, then fallback."""
        with self._session_factory() as db:
            used_role, chain = load_chain(db, owner_id, role)
            policy = load_policy(db, owner_id)
        if not chain:
            raise AINotConfiguredError(
                "No AI model is configured. Add a provider and choose a primary model in "
                "AI Providers."
            )

        call_id = uuid.uuid4()
        attempts: list[AttemptInfo] = []
        attempt_no = 0
        started = self._clock()
        last_error: ProviderError | None = None

        for index, entry in enumerate(chain):
            has_next = index < len(chain) - 1
            target = entry.target
            if entry.skip_reason:
                attempts.append(self._skipped(target, entry.skip_reason))
                continue
            try:
                api_key = self._reveal_key(owner_id, entry)
            except (DecryptionError, EncryptionNotConfiguredError) as exc:
                attempts.append(self._skipped(target, str(exc)))
                continue

            cfg = ProviderCallConfig(
                provider_type=target.provider_type,
                base_url=entry.base_url,
                model=target.model_identifier,
                timeout_seconds=request.timeout_seconds
                or self._settings.ai_request_timeout_seconds,
                api_key=api_key,
            )
            adapter = self._adapters(get_spec(target.provider_type))
            current = replace(request, json_mode=request.json_mode and entry.supports_json)
            retries = 0
            repairs = 0

            while True:
                attempt_no += 1
                t0 = self._clock()
                response: CompletionResponse | None = None
                parsed: Any = None
                try:
                    response = adapter.complete(cfg, current)
                    if parse is not None:
                        parsed = parse(response.text)
                except ProviderError as exc:
                    error = exc
                except ValueError as exc:  # parse/validation failure of an otherwise OK reply
                    error = ProviderError(ErrorClass.INVALID_RESPONSE, str(exc)[:300])
                else:
                    latency = _ms(t0, self._clock())
                    cost = self.recorder.record(
                        target,
                        role=used_role,
                        purpose=purpose,
                        call_id=call_id,
                        attempt=attempt_no,
                        outcome=UsageOutcome.SUCCESS,
                        latency_ms=latency,
                        response=response,
                    )
                    attempts.append(
                        AttemptInfo(
                            provider_name=target.provider_name,
                            model_identifier=target.model_identifier,
                            model_id=target.model_id,
                            outcome="success",
                            attempt=attempt_no,
                            latency_ms=latency,
                        )
                    )
                    return RoutedResult(
                        text=response.text,
                        data=parsed,
                        call_id=call_id,
                        provider_id=target.provider_id,
                        provider_name=target.provider_name,
                        provider_type=target.provider_type,
                        model_id=target.model_id,
                        model_identifier=target.model_identifier,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        est_cost_usd=cost,
                        latency_ms=_ms(started, self._clock()),
                        attempts=attempts,
                    )

                latency = _ms(t0, self._clock())
                last_error = error
                is_repairable = (
                    parse is not None
                    and response is not None
                    and error.error_class is ErrorClass.INVALID_RESPONSE
                )
                can_repair = is_repairable and repairs < max_repairs
                fallback_ok = False
                delay = 0.0
                if can_repair:
                    outcome = UsageOutcome.RETRY
                else:
                    # Once repairs are exhausted an invalid reply is not retried, only
                    # passed to the next model.
                    retries_done = policy.max_retries if is_repairable else retries
                    decision = decide(error, retries_done, policy, self._jitter())
                    fallback_ok = decision.fallback
                    delay = decision.delay
                    if decision.retry:
                        outcome = UsageOutcome.RETRY
                    elif decision.fallback and has_next:
                        outcome = UsageOutcome.FALLBACK
                    else:
                        outcome = UsageOutcome.ERROR

                self.recorder.record(
                    target,
                    role=used_role,
                    purpose=purpose,
                    call_id=call_id,
                    attempt=attempt_no,
                    outcome=outcome,
                    latency_ms=latency,
                    response=response,
                    error=error,
                )
                attempts.append(
                    AttemptInfo(
                        provider_name=target.provider_name,
                        model_identifier=target.model_identifier,
                        model_id=target.model_id,
                        outcome=outcome.value,
                        attempt=attempt_no,
                        error_class=error.error_class.value,
                        message=error.message,
                        http_status=error.http_status,
                        latency_ms=latency,
                    )
                )

                if outcome is UsageOutcome.RETRY:
                    if can_repair and response is not None:
                        repairs += 1
                        current = _repair_messages(current, response.text, error.message)
                    else:
                        retries += 1
                        if delay > 0:
                            self._sleep(delay)
                    continue
                if outcome is UsageOutcome.FALLBACK:
                    break  # next entry in the chain
                raise self._final_error(error, attempts, chain_exhausted=fallback_ok)

        raise AllProvidersFailedError(
            "All configured AI models failed."
            if last_error
            else "No AI model in the chain is currently available.",
            error_class=last_error.error_class if last_error else None,
            attempts=attempts,
        )

    def call_single(
        self,
        owner_id: uuid.UUID,
        target: AttemptTarget,
        base_url: str,
        api_key: str | None,
        request: CompletionRequest,
        *,
        purpose: UsagePurpose = UsagePurpose.CONNECTION_TEST,
    ) -> tuple[CompletionResponse | None, ProviderError | None, int]:
        """One call, no retries or fallback (connection tests). Records usage and health."""
        cfg = ProviderCallConfig(
            provider_type=target.provider_type,
            base_url=base_url,
            model=target.model_identifier,
            timeout_seconds=request.timeout_seconds
            or self._settings.ai_connection_test_timeout_seconds,
            api_key=api_key,
        )
        adapter = self._adapters(get_spec(target.provider_type))
        t0 = self._clock()
        try:
            response = adapter.complete(cfg, request)
        except ProviderError as error:
            latency = _ms(t0, self._clock())
            self.recorder.record(
                target,
                role=ModelRole.DEFAULT,
                purpose=purpose,
                call_id=uuid.uuid4(),
                attempt=1,
                outcome=UsageOutcome.ERROR,
                latency_ms=latency,
                error=error,
                mark_tested=True,
            )
            return None, error, latency
        latency = _ms(t0, self._clock())
        self.recorder.record(
            target,
            role=ModelRole.DEFAULT,
            purpose=purpose,
            call_id=uuid.uuid4(),
            attempt=1,
            outcome=UsageOutcome.SUCCESS,
            latency_ms=latency,
            response=response,
            mark_tested=True,
        )
        return response, None, latency

    # --- helpers ------------------------------------------------------------------------

    def _reveal_key(self, owner_id: uuid.UUID, entry: ChainEntry) -> str | None:
        if entry.secret_id is None:
            return None
        keyring = get_keyring(self._settings)
        with self._session_factory() as db:
            secret = secret_service.get_owned(db, owner_id, entry.secret_id)
            if secret is None:
                raise DecryptionError("The stored API key is missing. Enter the key again.")
            return secret_service.reveal(keyring, secret, owner_id)

    @staticmethod
    def _skipped(target: AttemptTarget, reason: str) -> AttemptInfo:
        return AttemptInfo(
            provider_name=target.provider_name,
            model_identifier=target.model_identifier,
            model_id=target.model_id,
            outcome="skipped",
            message=reason,
        )

    @staticmethod
    def _final_error(
        error: ProviderError, attempts: list[AttemptInfo], *, chain_exhausted: bool
    ) -> AIRoutingError:
        cls = error.error_class
        hint = ERROR_HINTS.get(cls, "")
        where = f"{attempts[-1].provider_name} / {attempts[-1].model_identifier}"
        message = f"{where}: {hint} ({error.message})" if hint else f"{where}: {error.message}"
        if chain_exhausted:
            return AllProvidersFailedError(
                f"All configured AI models failed. Last: {message}",
                error_class=cls,
                attempts=attempts,
            )
        if cls in (ErrorClass.AUTH, ErrorClass.MODEL_NOT_FOUND, ErrorClass.QUOTA_EXHAUSTED):
            return AIProviderConfigError(message, error_class=cls, attempts=attempts)
        if cls in (
            ErrorClass.INVALID_REQUEST,
            ErrorClass.CONTEXT_LENGTH,
            ErrorClass.CONTENT_POLICY,
        ):
            return AIRequestRejectedError(message, error_class=cls, attempts=attempts)
        return AllProvidersFailedError(message, error_class=cls, attempts=attempts)
