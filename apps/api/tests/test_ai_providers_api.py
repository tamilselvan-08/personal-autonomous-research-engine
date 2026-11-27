"""AI provider API: CRUD, credential handling, isolation, tests, routing, health, usage."""

import json
import logging
import uuid
from collections.abc import Callable

import httpx
import pytest
from sqlalchemy import text

from app.ai.registry import build_adapter_factory
from app.api.v1.routes.ai_providers import get_adapter_factory
from app.core.db import get_engine
from tests.ai_helpers import API, add_provider, set_chain

KEY = "sk-live-looking-secret-ZXCVBNMASDFGHJKL1234567890"


@pytest.fixture
def http_mock(app):  # type: ignore[no-untyped-def]
    """Route every provider HTTP call made by the API to a test handler."""
    state: dict = {"handler": lambda r: httpx.Response(500), "requests": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["handler"](request)

    transport = httpx.MockTransport(handler)
    app.dependency_overrides[get_adapter_factory] = lambda: build_adapter_factory(transport)
    yield state
    app.dependency_overrides.clear()


def openai_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 8, "completion_tokens": 1},
        },
    )


def anthropic_ok_body() -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "model-b",
        "content": [{"type": "text", "text": "OK"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 8, "output_tokens": 1},
    }


def _create(client, **overrides) -> dict:  # type: ignore[no-untyped-def]
    body = {
        "provider_type": "openai",
        "display_name": "My OpenAI",
        "api_key": KEY,
        "models": [{"model_identifier": "gpt-4o-mini"}],
        **overrides,
    }
    r = client.post(f"{API}/providers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


# --- types & CRUD -----------------------------------------------------------------------


def test_provider_types(auth_client) -> None:
    body = auth_client.get(f"{API}/providers/types").json()
    assert body["encryption_configured"] is True
    types = {t["type"]: t for t in body["types"]}
    assert set(types) == {
        "openai",
        "gemini",
        "anthropic",
        "xai",
        "deepseek",
        "mistral",
        "openai_compatible",
    }
    assert types["openai_compatible"]["requires_base_url"] is True
    assert all(t["verification"] == "mocked" for t in types.values())


def test_requires_auth(client) -> None:
    assert client.get(f"{API}/providers").status_code == 401
    assert client.post(f"{API}/providers", json={}).status_code == 401


def test_provider_crud_and_masking(auth_client) -> None:
    p = _create(auth_client)
    assert p["has_key"] is True
    assert p["key_masked"] == "••••7890"
    assert p["provider_label"] == "OpenAI"
    assert p["effective_base_url"] == "https://api.openai.com/v1"
    assert p["base_url"] is None
    assert p["health_state"] == "unknown"
    assert [m["model_identifier"] for m in p["models"]] == ["gpt-4o-mini"]

    listed = auth_client.get(f"{API}/providers").json()
    assert [x["id"] for x in listed] == [p["id"]]

    r = auth_client.patch(
        f"{API}/providers/{p['id']}", json={"display_name": "  Work OpenAI ", "enabled": False}
    )
    assert r.status_code == 200
    assert r.json()["display_name"] == "Work OpenAI"
    assert r.json()["enabled"] is False

    assert auth_client.delete(f"{API}/providers/{p['id']}").status_code == 204
    assert auth_client.get(f"{API}/providers/{p['id']}").status_code == 404
    with get_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM secrets")) == 0  # key deleted too
        assert conn.scalar(text("SELECT count(*) FROM ai_models")) == 0


def test_supports_more_than_three_providers(auth_client) -> None:
    for i, ptype in enumerate(["openai", "anthropic", "gemini", "xai", "deepseek", "mistral"]):
        _create(auth_client, provider_type=ptype, display_name=f"P{i}")
    _create(
        auth_client,
        provider_type="openai_compatible",
        display_name="Local",
        api_key=None,
        base_url="http://localhost:1234/v1/",
    )
    providers = auth_client.get(f"{API}/providers").json()
    assert len(providers) == 7
    local = providers[-1]
    assert local["has_key"] is False and local["key_masked"] is None
    assert local["base_url"] == "http://localhost:1234/v1"


def test_name_unique_per_user_case_insensitive(auth_client, other_client) -> None:
    _create(auth_client, display_name="Main")
    r = auth_client.post(
        f"{API}/providers",
        json={"provider_type": "openai", "display_name": "MAIN", "api_key": KEY},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROVIDER_NAME_TAKEN"
    _create(other_client, display_name="Main")  # other users are independent


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"provider_type": "openai", "display_name": "x"}, "api_key"),
        ({"provider_type": "openai_compatible", "display_name": "x"}, "base_url"),
        ({"provider_type": "openai", "display_name": "x", "api_key": "sk key"}, "api_key"),
        ({"provider_type": "openai", "display_name": " ", "api_key": KEY}, "display_name"),
        ({"provider_type": "nope", "display_name": "x", "api_key": KEY}, "provider_type"),
        (
            {
                "provider_type": "openai",
                "display_name": "x",
                "api_key": KEY,
                "base_url": "http://api.example.com/v1",
            },
            "base_url",
        ),
        (
            {
                "provider_type": "openai_compatible",
                "display_name": "x",
                "base_url": "http://u:p@h/v1",
            },
            "base_url",
        ),
        (
            {"provider_type": "openai_compatible", "display_name": "x", "base_url": "ftp://h/v1"},
            "base_url",
        ),
        (
            {
                "provider_type": "openai",
                "display_name": "x",
                "api_key": KEY,
                "models": [{"model_identifier": "bad model id"}],
            },
            "model_identifier",
        ),
    ],
)
def test_create_validation(auth_client, body, field) -> None:  # type: ignore[no-untyped-def]
    r = auth_client.post(f"{API}/providers", json=body)
    assert r.status_code == 422, r.text
    locs = [e["loc"] for e in r.json()["error"]["details"]["fields"]]
    assert any(field in loc for loc in locs), locs
    assert KEY not in r.text


def test_key_replace_and_remove(auth_client) -> None:
    p = _create(auth_client)
    new_key = "sk-replacement-key-QWERTYUIOP0987654321-abcd"
    r = auth_client.put(f"{API}/providers/{p['id']}/key", json={"api_key": new_key})
    assert r.status_code == 200
    assert r.json()["key_masked"] == "••••abcd"
    assert new_key not in r.text
    with get_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM secrets")) == 1  # old one deleted

    r = auth_client.delete(f"{API}/providers/{p['id']}/key")
    assert r.status_code == 200
    assert r.json()["has_key"] is False and r.json()["key_masked"] is None
    with get_engine().connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM secrets")) == 0
    assert (
        auth_client.put(f"{API}/providers/{p['id']}/key", json={"api_key": ""}).status_code == 422
    )


def test_model_crud(auth_client) -> None:
    p = _create(auth_client)
    r = auth_client.post(
        f"{API}/providers/{p['id']}/models",
        json={"model_identifier": "gpt-4.1", "input_price_per_mtok": "2", "supports_json": True},
    )
    assert r.status_code == 201, r.text
    model = r.json()
    assert model["supports_json"] is True and model["input_price_per_mtok"] == "2.000000"
    dup = auth_client.post(
        f"{API}/providers/{p['id']}/models", json={"model_identifier": "gpt-4.1"}
    )
    assert dup.status_code == 409

    r = auth_client.patch(
        f"{API}/models/{model['id']}", json={"enabled": False, "display_name": "Big"}
    )
    assert r.json()["enabled"] is False and r.json()["display_name"] == "Big"
    assert len(auth_client.get(f"{API}/providers/{p['id']}/models").json()) == 2
    assert auth_client.delete(f"{API}/models/{model['id']}").status_code == 204
    assert len(auth_client.get(f"{API}/providers/{p['id']}/models").json()) == 1


# --- isolation --------------------------------------------------------------------------


def test_user_isolation(auth_client, other_client) -> None:
    p = _create(auth_client)
    pid, mid = p["id"], p["models"][0]["id"]
    assert other_client.get(f"{API}/providers").json() == []
    assert other_client.get(f"{API}/providers/{pid}").status_code == 404
    assert other_client.patch(f"{API}/providers/{pid}", json={"enabled": False}).status_code == 404
    assert other_client.put(f"{API}/providers/{pid}/key", json={"api_key": KEY}).status_code == 404
    assert other_client.delete(f"{API}/providers/{pid}/key").status_code == 404
    assert other_client.post(f"{API}/providers/{pid}/test").status_code == 404
    assert other_client.get(f"{API}/providers/{pid}/available-models").status_code == 404
    assert other_client.get(f"{API}/providers/{pid}/models").status_code == 404
    assert other_client.patch(f"{API}/models/{mid}", json={"enabled": False}).status_code == 404
    assert other_client.delete(f"{API}/models/{mid}").status_code == 404
    assert other_client.delete(f"{API}/providers/{pid}").status_code == 404
    # Another user's model can't be placed in your chain.
    r = other_client.put(f"{API}/model-routes/default", json={"model_ids": [mid]})
    assert r.status_code == 422
    assert other_client.get(f"{API}/providers/health").json()["providers"] == []
    assert auth_client.get(f"{API}/providers/{pid}").status_code == 200


def test_secret_row_cannot_be_decrypted_for_another_owner(auth_client, other_client) -> None:
    """Even if a bug pointed a provider at someone else's secret, AAD blocks decryption."""
    from app.core.config import get_settings
    from app.core.crypto import DecryptionError, get_keyring
    from app.core.db import get_session_factory
    from app.models import Secret
    from app.services import secret_service

    _create(auth_client)
    other_id = uuid.UUID(other_client.get(f"{API}/auth/me").json()["id"])
    with get_session_factory()() as db:
        secret = db.query(Secret).one()
        keyring = get_keyring(get_settings())
        assert secret_service.reveal(keyring, secret, secret.owner_id) == KEY
        with pytest.raises(DecryptionError):
            secret_service.reveal(keyring, secret, other_id)


# --- connection tests -------------------------------------------------------------------


def test_connection_test_success(auth_client, http_mock) -> None:
    http_mock["handler"] = openai_ok
    p = _create(auth_client)
    r = auth_client.post(f"{API}/providers/{p['id']}/test", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True and body["model_identifier"] == "gpt-4o-mini"
    assert body["health_state"] == "healthy"
    sent = http_mock["requests"][0]
    assert str(sent.url) == "https://api.openai.com/v1/chat/completions"
    assert sent.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(sent.content)["max_completion_tokens"] == 5
    after = auth_client.get(f"{API}/providers/{p['id']}").json()
    assert after["last_tested_at"] is not None and after["health_state"] == "healthy"
    records = auth_client.get(f"{API}/usage/records").json()["items"]
    assert [(x["purpose"], x["outcome"]) for x in records] == [("connection_test", "success")]


def test_connection_test_invalid_key(auth_client, http_mock) -> None:
    http_mock["handler"] = lambda r: httpx.Response(
        401, json={"error": {"message": f"Incorrect API key provided: {KEY[:12]}...{KEY[-4:]}"}}
    )
    p = _create(auth_client)
    body = auth_client.post(f"{API}/providers/{p['id']}/test").json()
    assert body["ok"] is False
    assert body["error_class"] == "auth"
    assert "Replace the key" in body["error_hint"]
    assert body["health_state"] == "invalid_credentials"
    assert len(http_mock["requests"]) == 1  # tests never retry


@pytest.mark.parametrize(
    ("response", "error_class"),
    [
        (
            httpx.Response(
                404, json={"error": {"message": "model not found", "code": "model_not_found"}}
            ),
            "model_not_found",
        ),
        (
            httpx.Response(
                429, json={"error": {"message": "slow down"}}, headers={"retry-after": "2"}
            ),
            "rate_limited",
        ),
        (httpx.Response(503, text="upstream unavailable"), "server_error"),
    ],
)
def test_connection_test_failures_are_classified(
    auth_client, http_mock, response, error_class
) -> None:  # type: ignore[no-untyped-def]
    http_mock["handler"] = lambda r: response
    p = _create(auth_client)
    body = auth_client.post(f"{API}/providers/{p['id']}/test").json()
    assert body["ok"] is False and body["error_class"] == error_class


def test_connection_test_timeout(auth_client, http_mock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    http_mock["handler"] = handler
    p = _create(auth_client)
    body = auth_client.post(f"{API}/providers/{p['id']}/test").json()
    assert body["ok"] is False and body["error_class"] == "timeout"
    assert body["health_state"] == "degraded"


def test_connection_test_with_unsaved_model_and_no_model(auth_client, http_mock) -> None:
    http_mock["handler"] = openai_ok
    p = _create(auth_client, models=[])
    assert auth_client.post(f"{API}/providers/{p['id']}/test").status_code == 422
    r = auth_client.post(f"{API}/providers/{p['id']}/test", json={"model_identifier": "gpt-x"})
    assert r.json()["ok"] is True and r.json()["model_identifier"] == "gpt-x"


def test_connection_test_rate_limited(auth_client, http_mock) -> None:
    http_mock["handler"] = openai_ok
    p = _create(auth_client)
    codes = [auth_client.post(f"{API}/providers/{p['id']}/test").status_code for _ in range(7)]
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_available_models(auth_client, http_mock) -> None:
    http_mock["handler"] = lambda r: httpx.Response(
        200, json={"data": [{"id": "gpt-4o-mini"}, {"id": "gpt-4.1"}]}
    )
    p = _create(auth_client)
    body = auth_client.get(f"{API}/providers/{p['id']}/available-models").json()
    assert body["ok"] is True
    assert {m["id"]: m["configured"] for m in body["models"]} == {
        "gpt-4.1": False,
        "gpt-4o-mini": True,
    }


# --- routing ----------------------------------------------------------------------------


def test_primary_and_fallback_configuration(auth_client) -> None:
    a = add_provider(auth_client, "A", "model-a")
    b = add_provider(auth_client, "B", "model-b", ptype="anthropic")
    c = add_provider(auth_client, "C", "model-c", ptype="gemini")
    ids = [x["models"][0]["id"] for x in (a, b, c)]
    routes = set_chain(auth_client, [ids[1], ids[0], ids[2]])
    default = next(r for r in routes["roles"] if r["role"] == "default")
    assert [e["model_identifier"] for e in default["entries"]] == ["model-b", "model-a", "model-c"]
    assert [e["position"] for e in default["entries"]] == [0, 1, 2]
    planner = next(r for r in routes["roles"] if r["role"] == "planner")
    assert planner["uses_default"] is True and planner["entries"] == []

    # Change the primary.
    routes = set_chain(auth_client, [ids[2], ids[1]])
    default = next(r for r in routes["roles"] if r["role"] == "default")
    assert [e["model_identifier"] for e in default["entries"]] == ["model-c", "model-b"]
    assert auth_client.get(f"{API}/providers/{c['id']}").json()["models"][0]["route_roles"] == [
        "default"
    ]


def test_route_validation(auth_client) -> None:
    a = add_provider(auth_client, "A", "model-a")
    mid = a["models"][0]["id"]
    assert (
        auth_client.put(f"{API}/model-routes/default", json={"model_ids": [mid, mid]}).status_code
        == 422
    )
    assert (
        auth_client.put(
            f"{API}/model-routes/default", json={"model_ids": [str(uuid.uuid4())]}
        ).status_code
        == 422
    )
    assert auth_client.put(f"{API}/model-routes/bogus", json={"model_ids": []}).status_code == 422
    auth_client.patch(f"{API}/models/{mid}", json={"enabled": False})
    r = auth_client.put(f"{API}/model-routes/default", json={"model_ids": [mid]})
    assert r.status_code == 422 and "disabled" in r.text


def test_delete_in_use_requires_force_and_compacts_chain(auth_client) -> None:
    a = add_provider(auth_client, "A", "model-a")
    b = add_provider(auth_client, "B", "model-b")
    set_chain(auth_client, [a["models"][0]["id"], b["models"][0]["id"]])
    r = auth_client.delete(f"{API}/providers/{a['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROVIDER_IN_USE"
    assert r.json()["error"]["details"]["roles"] == ["default"]
    assert (
        auth_client.delete(f"{API}/providers/{a['id']}", params={"force": True}).status_code == 204
    )
    default = auth_client.get(f"{API}/model-routes").json()["roles"][0]
    assert [(e["position"], e["model_identifier"]) for e in default["entries"]] == [(0, "model-b")]

    r = auth_client.delete(f"{API}/models/{b['models'][0]['id']}")
    assert r.status_code == 409 and r.json()["error"]["code"] == "MODEL_IN_USE"


def test_disabled_provider_shows_unavailable_in_chain(auth_client) -> None:
    a = add_provider(auth_client, "A", "model-a")
    set_chain(auth_client, [a["models"][0]["id"]])
    auth_client.patch(f"{API}/providers/{a['id']}", json={"enabled": False})
    entry = auth_client.get(f"{API}/model-routes").json()["roles"][0]["entries"][0]
    assert entry["available"] is False and entry["unavailable_reason"] == "Provider is disabled."


def test_routing_policy(auth_client) -> None:
    assert auth_client.get(f"{API}/routing-policy").json() == {
        "max_retries": 2,
        "max_retry_after_seconds": 20,
        "fallback_on_rate_limit": True,
        "fallback_on_quota_exhausted": False,
    }
    r = auth_client.put(
        f"{API}/routing-policy", json={"fallback_on_quota_exhausted": True, "max_retries": 1}
    )
    assert r.json()["fallback_on_quota_exhausted"] is True and r.json()["max_retries"] == 1
    assert auth_client.put(f"{API}/routing-policy", json={"max_retries": 9}).status_code == 422


def test_routing_test_endpoint_reports_fallback(auth_client, http_mock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openai.com":
            return httpx.Response(401, json={"error": {"message": "bad key"}})
        return httpx.Response(200, json=anthropic_ok_body())

    http_mock["handler"] = handler
    a = add_provider(auth_client, "OpenAI", "model-a")
    b = add_provider(auth_client, "Claude", "model-b", ptype="anthropic")
    set_chain(auth_client, [b["models"][0]["id"], a["models"][0]["id"]])
    body = auth_client.post(f"{API}/model-routes/default/test").json()
    assert body["ok"] is True and body["provider_name"] == "Claude"

    set_chain(auth_client, [a["models"][0]["id"], b["models"][0]["id"]])
    body = auth_client.post(f"{API}/model-routes/default/test").json()
    assert body["ok"] is False
    assert body["error_code"] == "AI_PROVIDER_CONFIG_ERROR" and body["error_class"] == "auth"
    assert [x["outcome"] for x in body["attempts"]] == ["error"]  # auth: no fallback


def test_routing_test_without_configuration(auth_client) -> None:
    body = auth_client.post(f"{API}/model-routes/default/test").json()
    assert body["ok"] is False and body["error_code"] == "AI_NOT_CONFIGURED"


# --- health & usage ---------------------------------------------------------------------


def test_health_and_usage(auth_client, http_mock) -> None:
    responses = iter([openai_ok, openai_ok, lambda r: httpx.Response(500)])
    http_mock["handler"] = lambda r: next(responses)(r)
    p = _create(auth_client)
    for _ in range(3):
        auth_client.post(f"{API}/providers/{p['id']}/test")

    health = auth_client.get(f"{API}/providers/health").json()["providers"][0]
    assert health["calls"] == 3 and health["successes"] == 2 and health["failures"] == 1
    assert health["success_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert health["p50_latency_ms"] is not None and health["health_state"] == "degraded"

    by_provider = auth_client.get(f"{API}/usage", params={"group_by": "provider"}).json()
    assert by_provider["totals"]["calls"] == 3
    assert by_provider["totals"]["input_tokens"] == 16
    assert by_provider["rows"][0]["label"] == "My OpenAI"
    for group in ("model", "day", "purpose", "outcome"):
        r = auth_client.get(f"{API}/usage", params={"group_by": group})
        assert r.status_code == 200 and r.json()["totals"]["calls"] == 3
    assert auth_client.get(f"{API}/usage", params={"group_by": "nope"}).status_code == 422

    records = auth_client.get(f"{API}/usage/records", params={"page_size": 2}).json()
    assert records["total"] == 3 and len(records["items"]) == 2


def test_usage_survives_provider_deletion(auth_client, http_mock) -> None:
    http_mock["handler"] = openai_ok
    p = _create(auth_client)
    auth_client.post(f"{API}/providers/{p['id']}/test")
    auth_client.delete(f"{API}/providers/{p['id']}")
    items = auth_client.get(f"{API}/usage/records").json()["items"]
    assert len(items) == 1 and items[0]["provider_id"] is None
    assert items[0]["provider_name"] == "My OpenAI"


# --- secret leakage ---------------------------------------------------------------------


def test_api_key_never_leaks(auth_client, http_mock, caplog) -> None:  # type: ignore[no-untyped-def]
    http_mock["handler"] = lambda r: httpx.Response(
        401, json={"error": {"message": f"Incorrect API key provided: {KEY}"}}
    )
    caplog.set_level(logging.DEBUG)
    bodies: list[str] = []

    p = auth_client.post(
        f"{API}/providers",
        json={
            "provider_type": "openai",
            "display_name": "Leak check",
            "api_key": KEY,
            "models": [{"model_identifier": "gpt-4o-mini"}],
        },
    )
    bodies.append(p.text)
    pid = p.json()["id"]
    mid = p.json()["models"][0]["id"]
    set_chain(auth_client, [mid])
    for method, path in [
        ("get", "/providers"),
        ("get", f"/providers/{pid}"),
        ("post", f"/providers/{pid}/test"),
        ("get", f"/providers/{pid}/available-models"),
        ("post", "/model-routes/default/test"),
        ("get", "/model-routes"),
        ("get", "/providers/health"),
        ("get", "/usage"),
        ("get", "/usage/records"),
        ("get", "/settings"),
        ("put", f"/providers/{pid}/key"),
    ]:
        kwargs = {"json": {"api_key": KEY}} if method == "put" else {}
        bodies.append(getattr(auth_client, method)(f"{API}{path}", **kwargs).text)

    for body in bodies:
        assert KEY not in body
        assert KEY[3:20] not in body  # nor a recognisable fragment
    assert KEY not in caplog.text

    with get_engine().connect() as conn:
        dump = " ".join(
            str(row)
            for table in ("secrets", "ai_providers", "ai_models", "usage_records", "audit_events")
            for row in conn.execute(text(f"SELECT * FROM {table}"))  # noqa: S608
        )
        raw = b"".join(
            bytes(r[0]) + bytes(r[1])
            for r in conn.execute(text("SELECT ciphertext, wrapped_dek FROM secrets"))
        )
    assert KEY not in dump
    assert KEY.encode() not in raw


def test_validation_errors_do_not_echo_keys(auth_client) -> None:
    r = auth_client.post(
        f"{API}/providers",
        json={"provider_type": "openai", "display_name": "", "api_key": KEY + " x"},
    )
    assert r.status_code == 422
    assert KEY not in r.text


def test_encryption_not_configured(make_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.core.config import get_settings
    from tests.conftest import register

    monkeypatch.delenv("SECRETS_MASTER_KEY")
    get_settings.cache_clear()
    try:
        c = make_client()
        register(c)
        assert c.get(f"{API}/providers/types").json()["encryption_configured"] is False
        r = c.post(
            f"{API}/providers",
            json={"provider_type": "openai", "display_name": "x", "api_key": KEY},
        )
        assert r.status_code == 503 and r.json()["error"]["code"] == "ENCRYPTION_NOT_CONFIGURED"
        # Keyless local endpoints still work without encryption.
        r = c.post(
            f"{API}/providers",
            json={
                "provider_type": "openai_compatible",
                "display_name": "Local",
                "base_url": "http://localhost:11434/v1",
            },
        )
        assert r.status_code == 201
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


# --- key rotation -----------------------------------------------------------------------


def test_master_key_rotation_rewraps_all_secrets(auth_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import os

    from app.core.config import get_settings
    from app.core.crypto import generate_master_key, get_keyring
    from app.core.db import get_session_factory
    from app.models import Secret
    from app.services import secret_service

    _create(auth_client)
    _create(auth_client, display_name="Second", api_key=KEY[::-1])
    old = os.environ["SECRETS_MASTER_KEY"]
    monkeypatch.setenv("SECRETS_MASTER_KEY", generate_master_key())
    monkeypatch.setenv("SECRETS_MASTER_KEY_ID", "test2")
    monkeypatch.setenv("SECRETS_PREVIOUS_KEYS", f"test1:{old}")
    get_settings.cache_clear()
    try:
        keyring = get_keyring(get_settings())
        with get_session_factory()() as db:
            assert secret_service.rewrap_all(db, keyring) == 2
            assert secret_service.rewrap_all(db, keyring) == 0  # idempotent
        monkeypatch.delenv("SECRETS_PREVIOUS_KEYS")
        get_settings.cache_clear()
        only_new = get_keyring(get_settings())
        with get_session_factory()() as db:
            secrets = db.query(Secret).all()
            assert {s.kek_id for s in secrets} == {"test2"}
            assert sorted(
                secret_service.reveal(only_new, s, s.owner_id) for s in secrets
            ) == sorted([KEY, KEY[::-1]])
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


Handler = Callable[[httpx.Request], httpx.Response]
