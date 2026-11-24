"""Usage records and provider/model health, written in their own short transactions so
they persist even when the caller's transaction rolls back."""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, lazyload

from app.ai.errors import TRANSIENT, ErrorClass, ProviderError
from app.ai.types import CompletionResponse
from app.core.logging import request_id_var
from app.models import AIModel, AIProvider, UsageRecord
from app.models.enums import HealthState, ModelRole, UsageOutcome, UsagePurpose

logger = logging.getLogger("pare.ai")

PROVIDER_DOWN_AFTER = 3  # consecutive transient failures before a provider shows "down"
CIRCUIT_OPEN_AFTER = 5  # consecutive transient failures before a model's circuit opens
CIRCUIT_COOLDOWN = timedelta(seconds=60)


@dataclass(frozen=True)
class AttemptTarget:
    """Snapshot of what was called, so records survive provider/model deletion."""

    owner_id: uuid.UUID
    provider_id: uuid.UUID | None
    provider_type: str
    provider_name: str
    model_id: uuid.UUID | None
    model_identifier: str
    input_price_per_mtok: Decimal | None = None
    output_price_per_mtok: Decimal | None = None


def estimate_cost(
    target: AttemptTarget, input_tokens: int | None, output_tokens: int | None
) -> Decimal | None:
    if (
        target.input_price_per_mtok is None
        or target.output_price_per_mtok is None
        or input_tokens is None
        or output_tokens is None
    ):
        return None
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) * target.input_price_per_mtok
        + Decimal(output_tokens) * target.output_price_per_mtok
    ) / million


def circuit_is_open(opened_at: datetime | None, now: datetime | None = None) -> bool:
    if opened_at is None:
        return False
    return (now or datetime.now(UTC)) - opened_at < CIRCUIT_COOLDOWN


class UsageRecorder:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def record(
        self,
        target: AttemptTarget,
        *,
        role: ModelRole,
        purpose: UsagePurpose,
        call_id: uuid.UUID,
        attempt: int,
        outcome: UsageOutcome,
        latency_ms: int,
        response: CompletionResponse | None = None,
        error: ProviderError | None = None,
        mark_tested: bool = False,
    ) -> Decimal | None:
        """Write one usage row and update health. Never raises: recording must not turn a
        successful completion into a failure."""
        cost = (
            estimate_cost(target, response.input_tokens, response.output_tokens)
            if response
            else None
        )
        try:
            with self._session_factory() as db:
                db.add(
                    UsageRecord(
                        owner_id=target.owner_id,
                        provider_id=target.provider_id,
                        model_id=target.model_id,
                        provider_type=target.provider_type,
                        provider_name=target.provider_name,
                        model_identifier=target.model_identifier,
                        role=role.value,
                        purpose=purpose.value,
                        call_id=call_id,
                        attempt=attempt,
                        outcome=outcome.value,
                        error_class=error.error_class.value if error else None,
                        http_status=error.http_status if error else None,
                        latency_ms=latency_ms,
                        input_tokens=response.input_tokens if response else None,
                        output_tokens=response.output_tokens if response else None,
                        est_cost_usd=cost,
                        request_id=request_id_var.get(),
                    )
                )
                self._update_health(db, target, error, mark_tested)
                db.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to record AI usage: %s", exc.__class__.__name__)
        logger.info(
            "ai.call",
            extra={
                "provider_type": target.provider_type,
                "model": target.model_identifier,
                "role": role.value,
                "purpose": purpose.value,
                "attempt": attempt,
                "outcome": outcome.value,
                "error_class": error.error_class.value if error else None,
                "latency_ms": latency_ms,
            },
        )
        return cost

    @staticmethod
    def _update_health(
        db: Session, target: AttemptTarget, error: ProviderError | None, mark_tested: bool
    ) -> None:
        now = datetime.now(UTC)
        # Lock only the health rows (not eagerly joined relations) and scope to the owner.
        provider = (
            db.scalar(
                select(AIProvider)
                .options(lazyload("*"))
                .where(AIProvider.id == target.provider_id, AIProvider.owner_id == target.owner_id)
                .with_for_update(of=AIProvider)
            )
            if target.provider_id
            else None
        )
        model = (
            db.scalar(
                select(AIModel)
                .options(lazyload("*"))
                .where(AIModel.id == target.model_id, AIModel.owner_id == target.owner_id)
                .with_for_update(of=AIModel)
            )
            if target.model_id
            else None
        )
        if provider is not None and mark_tested:
            provider.last_tested_at = now

        if error is None:
            for row in (provider, model):
                if row is not None:
                    row.health_state = HealthState.HEALTHY.value
                    row.consecutive_failures = 0
                    row.last_success_at = now
            if model is not None:
                model.circuit_opened_at = None
            return

        cls = error.error_class
        if cls in (
            ErrorClass.INVALID_REQUEST,
            ErrorClass.CONTEXT_LENGTH,
            ErrorClass.CONTENT_POLICY,
        ):
            return  # the request's fault, not the provider's

        def _note(row: AIProvider | AIModel) -> None:
            row.last_error_class = cls.value
            row.last_error_message = error.message[:500]
            row.last_error_at = now

        if cls is ErrorClass.AUTH and provider is not None:
            provider.health_state = HealthState.INVALID_CREDENTIALS.value
            _note(provider)
        elif cls is ErrorClass.QUOTA_EXHAUSTED and provider is not None:
            provider.health_state = HealthState.QUOTA_EXHAUSTED.value
            _note(provider)
        elif cls is ErrorClass.MODEL_NOT_FOUND:
            if model is not None:
                model.health_state = HealthState.MISCONFIGURED.value
                _note(model)
            elif provider is not None:
                _note(provider)
        elif cls in TRANSIENT or cls in (ErrorClass.INVALID_RESPONSE, ErrorClass.UNKNOWN):
            if provider is not None:
                provider.consecutive_failures += 1
                provider.health_state = (
                    HealthState.DOWN.value
                    if provider.consecutive_failures >= PROVIDER_DOWN_AFTER
                    else HealthState.DEGRADED.value
                )
                _note(provider)
            if model is not None:
                model.consecutive_failures += 1
                model.health_state = HealthState.DEGRADED.value
                _note(model)
                if cls in TRANSIENT and model.consecutive_failures >= CIRCUIT_OPEN_AFTER:
                    model.circuit_opened_at = now
