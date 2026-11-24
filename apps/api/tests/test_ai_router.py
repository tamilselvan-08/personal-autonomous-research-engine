"""Primary/fallback routing against a real database with a scripted adapter."""

import uuid

import pytest
from pydantic import BaseModel
from sqlalchemy import select

from app.ai.errors import ErrorClass as E
from app.ai.recorder import CIRCUIT_OPEN_AFTER
from app.ai.router import (
    AINotConfiguredError,
    AIProviderConfigError,
    AIRequestRejectedError,
    AllProvidersFailedError,
    ModelRouter,
)
from app.ai.types import ChatMessage, CompletionRequest
from app.core.config import get_settings
from app.core.db import get_session_factory
from app.models import AIModel, AIProvider, UsageRecord
from app.services.ai_service import AIService
from tests.ai_helpers import ScriptedAdapter, add_provider, perr, set_chain, user_id

REQ = CompletionRequest(messages=[ChatMessage("user", "hello")], max_output_tokens=16)


@pytest.fixture
def adapter() -> ScriptedAdapter:
    return ScriptedAdapter()


@pytest.fixture
def sleeps() -> list[float]:
    return []


@pytest.fixture
def router(adapter, sleeps) -> ModelRouter:  # type: ignore[no-untyped-def]
    get_settings.cache_clear()
    return ModelRouter(
        get_session_factory(),
        get_settings(),
        lambda spec: adapter,
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    )


@pytest.fixture
def chain(auth_client):  # type: ignore[no-untyped-def]
    """Three providers; chain primary → fallback-1 → fallback-2."""
    a = add_provider(auth_client, "Primary", "model-a")
    b = add_provider(auth_client, "Second", "model-b", ptype="anthropic")
    c = add_provider(auth_client, "Third", "model-c", ptype="gemini")
    ids = [p["models"][0]["id"] for p in (a, b, c)]
    set_chain(auth_client, ids)
    return {"owner": uuid.UUID(user_id(auth_client)), "providers": [a, b, c], "model_ids": ids}


def _usage(owner: uuid.UUID) -> list[UsageRecord]:
    with get_session_factory()() as db:
        return list(
            db.scalars(
                select(UsageRecord)
                .where(UsageRecord.owner_id == owner)
                .order_by(UsageRecord.created_at, UsageRecord.attempt)
            )
        )


def _provider(pid: str) -> AIProvider:
    with get_session_factory()() as db:
        return db.get(AIProvider, uuid.UUID(pid))


def _model(mid: str) -> AIModel:
    with get_session_factory()() as db:
        return db.get(AIModel, uuid.UUID(mid))


def test_primary_success(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    result = router.complete(chain["owner"], REQ)
    assert result.text == "OK"
    assert result.provider_name == "Primary"
    assert result.model_identifier == "model-a"
    assert result.used_fallback is False
    assert adapter.models_called() == ["model-a"]
    assert adapter.calls[0][2] == "sk-test-key-for-unit-tests-0001"  # decrypted just in time
    rows = _usage(chain["owner"])
    assert [(r.model_identifier, r.outcome, r.attempt) for r in rows] == [("model-a", "success", 1)]
    assert rows[0].input_tokens == 10 and rows[0].latency_ms >= 0
    assert rows[0].call_id == result.call_id
    assert _provider(chain["providers"][0]["id"]).health_state == "healthy"


def test_primary_transient_failure_retries_then_falls_back(router, adapter, chain, sleeps) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.SERVER_ERROR, 503)] * 3)
    result = router.complete(chain["owner"], REQ)
    assert result.model_identifier == "model-b"
    assert result.used_fallback is True
    assert adapter.models_called() == ["model-a"] * 3 + ["model-b"]
    assert len(sleeps) == 2 and sleeps[0] < sleeps[1]  # bounded exponential backoff
    outcomes = [(r.model_identifier, r.outcome, r.error_class) for r in _usage(chain["owner"])]
    assert outcomes == [
        ("model-a", "retry", "server_error"),
        ("model-a", "retry", "server_error"),
        ("model-a", "fallback", "server_error"),
        ("model-b", "success", None),
    ]
    assert [a.outcome for a in result.attempts] == ["retry", "retry", "fallback", "success"]
    assert _provider(chain["providers"][0]["id"]).health_state == "down"


def test_timeout_falls_back(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.TIMEOUT)] * 3)
    assert router.complete(chain["owner"], REQ).model_identifier == "model-b"


def test_multiple_fallback_failures_then_last_succeeds(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.NETWORK)] * 3)
    adapter.script("model-b", [perr(E.SERVER_ERROR, 500)] * 3)
    result = router.complete(chain["owner"], REQ)
    assert result.model_identifier == "model-c"
    assert adapter.models_called() == ["model-a"] * 3 + ["model-b"] * 3 + ["model-c"]


def test_all_providers_fail(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    for m in ("model-a", "model-b", "model-c"):
        adapter.script(m, [perr(E.SERVER_ERROR, 503)] * 3)
    with pytest.raises(AllProvidersFailedError) as info:
        router.complete(chain["owner"], REQ)
    err = info.value
    assert err.code == "AI_ALL_PROVIDERS_FAILED"
    assert err.error_class is E.SERVER_ERROR
    assert len(err.attempts) == 9
    assert err.attempts[-1].outcome == "error"
    assert "Third" in err.message


def test_invalid_key_does_not_fall_back_and_marks_provider(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.AUTH, 401)])
    with pytest.raises(AIProviderConfigError) as info:
        router.complete(chain["owner"], REQ)
    assert info.value.error_class is E.AUTH
    assert "Replace the key" in info.value.message
    assert adapter.models_called() == ["model-a"]  # no retry, no fallback
    provider = _provider(chain["providers"][0]["id"])
    assert provider.health_state == "invalid_credentials"
    assert provider.last_error_class == "auth"


def test_invalid_model_surfaces_configuration_error(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.MODEL_NOT_FOUND, 404)])
    with pytest.raises(AIProviderConfigError) as info:
        router.complete(chain["owner"], REQ)
    assert info.value.error_class is E.MODEL_NOT_FOUND
    assert adapter.models_called() == ["model-a"]
    assert _model(chain["model_ids"][0]).health_state == "misconfigured"


@pytest.mark.parametrize("cls", [E.INVALID_REQUEST, E.CONTEXT_LENGTH, E.CONTENT_POLICY])
def test_request_errors_are_not_sent_to_every_provider(router, adapter, chain, cls) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(cls, 400)])
    with pytest.raises(AIRequestRejectedError):
        router.complete(chain["owner"], REQ)
    assert adapter.models_called() == ["model-a"]
    assert _provider(chain["providers"][0]["id"]).health_state == "unknown"  # not its fault


def test_rate_limit_honours_retry_after_then_succeeds(router, adapter, chain, sleeps) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.RATE_LIMITED, 429, retry_after=4)])
    result = router.complete(chain["owner"], REQ)
    assert result.model_identifier == "model-a"
    assert sleeps == [4]


def test_rate_limit_with_long_retry_after_falls_back_immediately(
    router, adapter, chain, sleeps
) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.RATE_LIMITED, 429, retry_after=3600)])
    result = router.complete(chain["owner"], REQ)
    assert result.model_identifier == "model-b"
    assert sleeps == []


def test_rate_limit_fallback_can_be_turned_off(router, adapter, chain, auth_client) -> None:  # type: ignore[no-untyped-def]
    auth_client.put(
        "/api/v1/routing-policy", json={"fallback_on_rate_limit": False, "max_retries": 0}
    )
    adapter.script("model-a", [perr(E.RATE_LIMITED, 429)])
    with pytest.raises(AllProvidersFailedError):
        router.complete(chain["owner"], REQ)
    assert adapter.models_called() == ["model-a"]


def test_quota_exhausted_needs_explicit_policy(router, adapter, chain, auth_client) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", [perr(E.QUOTA_EXHAUSTED, 402)])
    with pytest.raises(AIProviderConfigError) as info:
        router.complete(chain["owner"], REQ)
    assert info.value.error_class is E.QUOTA_EXHAUSTED
    assert _provider(chain["providers"][0]["id"]).health_state == "quota_exhausted"

    auth_client.put("/api/v1/routing-policy", json={"fallback_on_quota_exhausted": True})
    adapter.script("model-a", [perr(E.QUOTA_EXHAUSTED, 402)])
    assert router.complete(chain["owner"], REQ).model_identifier == "model-b"


def test_disabled_provider_and_model_are_skipped(router, adapter, chain, auth_client) -> None:  # type: ignore[no-untyped-def]
    auth_client.patch(f"/api/v1/providers/{chain['providers'][0]['id']}", json={"enabled": False})
    auth_client.patch(f"/api/v1/models/{chain['model_ids'][1]}", json={"enabled": False})
    result = router.complete(chain["owner"], REQ)
    assert result.model_identifier == "model-c"
    assert [a.outcome for a in result.attempts] == ["skipped", "skipped", "success"]
    assert adapter.models_called() == ["model-c"]


def test_circuit_opens_after_repeated_transient_failures(
    router, adapter, chain, auth_client
) -> None:  # type: ignore[no-untyped-def]
    auth_client.put("/api/v1/routing-policy", json={"max_retries": 0})
    adapter.script("model-a", [perr(E.TIMEOUT)] * CIRCUIT_OPEN_AFTER)
    for _ in range(CIRCUIT_OPEN_AFTER):
        assert router.complete(chain["owner"], REQ).model_identifier == "model-b"
    assert _model(chain["model_ids"][0]).circuit_opened_at is not None
    adapter.calls.clear()
    result = router.complete(chain["owner"], REQ)
    assert adapter.models_called() == ["model-b"]  # model-a skipped while open
    assert result.attempts[0].outcome == "skipped"


def test_role_without_chain_uses_default(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    from app.models.enums import ModelRole

    result = router.complete(chain["owner"], REQ, role=ModelRole.PLANNER)
    assert result.model_identifier == "model-a"
    assert _usage(chain["owner"])[0].role == "default"


def test_role_specific_chain(router, adapter, chain, auth_client) -> None:  # type: ignore[no-untyped-def]
    from app.models.enums import ModelRole

    set_chain(auth_client, [chain["model_ids"][2]], role="planner")
    result = router.complete(chain["owner"], REQ, role=ModelRole.PLANNER)
    assert result.model_identifier == "model-c"
    assert _usage(chain["owner"])[0].role == "planner"


def test_no_configuration(router, auth_client) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AINotConfiguredError):
        router.complete(uuid.UUID(user_id(auth_client)), REQ)


def test_users_never_route_through_each_other(router, adapter, chain, other_client) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(AINotConfiguredError):
        router.complete(uuid.UUID(user_id(other_client)), REQ)
    assert adapter.calls == []


def test_cost_is_estimated_from_configured_prices(router, adapter, chain, auth_client) -> None:  # type: ignore[no-untyped-def]
    auth_client.patch(
        f"/api/v1/models/{chain['model_ids'][0]}",
        json={"input_price_per_mtok": "2.5", "output_price_per_mtok": "10"},
    )
    result = router.complete(chain["owner"], REQ)
    # 10 input tokens × $2.5/M + 2 output × $10/M
    assert float(result.est_cost_usd) == pytest.approx(0.000045)


# --- structured output (the interface the Research Planner will use) --------------------


class Plan(BaseModel):
    title: str
    steps: list[str]


def test_structured_completion_parses_and_validates(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", ['```json\n{"title": "T", "steps": ["a", "b"]}\n```'])
    result = AIService(router).complete_structured(
        owner_id=chain["owner"], schema=Plan, prompt="Plan it", system="You plan."
    )
    assert result.data == Plan(title="T", steps=["a", "b"])
    assert result.model_identifier == "model-a"
    system = adapter.calls[0][1].messages[0]
    assert system.role == "system" and "JSON Schema" in system.content


def test_structured_completion_repairs_then_falls_back(router, adapter, chain) -> None:  # type: ignore[no-untyped-def]
    adapter.script("model-a", ["not json", '{"title": 1}'])  # invalid, repair also invalid
    adapter.script("model-b", ['{"title": "ok", "steps": []}'])
    result = AIService(router).complete_structured(owner_id=chain["owner"], schema=Plan, prompt="x")
    assert result.model_identifier == "model-b"
    assert adapter.models_called() == ["model-a", "model-a", "model-b"]
    repair = adapter.calls[1][1].messages
    assert repair[-2].role == "assistant" and repair[-2].content == "not json"
    assert "could not be used" in repair[-1].content
    outcomes = [r.outcome for r in _usage(chain["owner"])]
    assert outcomes == ["retry", "fallback", "success"]
