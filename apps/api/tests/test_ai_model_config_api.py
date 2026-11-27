"""Model configuration API: flat model endpoints, capabilities, LiteLLM prefill, provider
enable/disable and PUT, combined routing configuration, and the five task roles."""

from decimal import Decimal

import httpx
import pytest

from app.ai.registry import build_adapter_factory
from app.api.v1.routes.ai_providers import get_adapter_factory
from tests.ai_helpers import API, add_provider, set_chain

KEY = "sk-model-config-test-key-0123456789"
ROLES = ["default", "planner", "researcher", "extractor", "verifier", "summarizer"]


def _provider(client, name: str = "Main", model: str = "m-1", ptype: str = "openai") -> dict:  # type: ignore[no-untyped-def]
    return add_provider(client, name, model, ptype=ptype, key=KEY)


# --- roles ------------------------------------------------------------------------------


def test_all_task_roles_are_supported(auth_client) -> None:
    roles = [r["role"] for r in auth_client.get(f"{API}/model-routes").json()["roles"]]
    assert roles == ROLES
    p = _provider(auth_client)
    mid = p["models"][0]["id"]
    for role in ROLES[1:]:
        body = set_chain(auth_client, [mid], role=role)
        entry = next(r for r in body["roles"] if r["role"] == role)
        assert entry["uses_default"] is False and entry["entries"][0]["model_id"] == mid
    assert auth_client.put(f"{API}/model-routes/writer", json={"model_ids": []}).status_code == 422


def test_researcher_routing_test_is_recorded_with_role(auth_client, app) -> None:  # type: ignore[no-untyped-def]
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1},
            },
        )
    )
    app.dependency_overrides[get_adapter_factory] = lambda: build_adapter_factory(transport)
    try:
        p = _provider(auth_client)
        set_chain(auth_client, [p["models"][0]["id"]], role="researcher")
        body = auth_client.post(f"{API}/model-routes/researcher/test").json()
        assert body["ok"] is True and body["role"] == "researcher"
        records = auth_client.get(f"{API}/usage/records").json()["items"]
        assert records[0]["role"] == "researcher"
    finally:
        app.dependency_overrides.clear()


# --- providers: PUT, enable/disable, connection status ----------------------------------


def test_put_provider_enable_disable_and_status(auth_client) -> None:
    p = _provider(auth_client)
    assert p["connection_status"] == "not_tested"

    r = auth_client.put(f"{API}/providers/{p['id']}", json={"display_name": "Renamed"})
    assert r.status_code == 200 and r.json()["display_name"] == "Renamed"
    assert r.json()["enabled"] is True  # partial update: other fields unchanged

    r = auth_client.post(f"{API}/providers/{p['id']}/disable")
    assert r.status_code == 200
    assert r.json()["enabled"] is False and r.json()["connection_status"] == "disabled"
    r = auth_client.post(f"{API}/providers/{p['id']}/enable")
    assert r.json()["enabled"] is True and r.json()["connection_status"] == "not_tested"


# --- flat model endpoints ----------------------------------------------------------------


def test_flat_model_endpoints(auth_client) -> None:
    a = _provider(auth_client, "Alpha", "a-model")
    b = _provider(auth_client, "Beta", "b-model")
    listed = auth_client.get(f"{API}/models").json()
    assert [m["model_identifier"] for m in listed] == ["a-model", "b-model"]
    only_b = auth_client.get(f"{API}/models", params={"provider_id": b["id"]}).json()
    assert [m["model_identifier"] for m in only_b] == ["b-model"]

    r = auth_client.post(
        f"{API}/models",
        json={"provider_id": a["id"], "model_identifier": "a-two", "display_name": "Two"},
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["provider_id"] == a["id"] and created["display_name"] == "Two"

    r = auth_client.put(f"{API}/models/{created['id']}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert r.json()["display_name"] == "Two"  # partial update

    dup = auth_client.post(
        f"{API}/models", json={"provider_id": a["id"], "model_identifier": "a-two"}
    )
    assert dup.status_code == 409


def test_flat_model_endpoints_are_owner_scoped(auth_client, other_client) -> None:
    p = _provider(auth_client)
    mid = p["models"][0]["id"]
    assert other_client.get(f"{API}/models").json() == []
    assert other_client.get(f"{API}/models", params={"provider_id": p["id"]}).status_code == 404
    r = other_client.post(f"{API}/models", json={"provider_id": p["id"], "model_identifier": "x"})
    assert r.status_code == 404
    assert other_client.put(f"{API}/models/{mid}", json={"enabled": False}).status_code == 404
    assert (
        other_client.put(f"{API}/providers/{p['id']}", json={"enabled": False}).status_code == 404
    )
    assert other_client.post(f"{API}/providers/{p['id']}/enable").status_code == 404
    assert other_client.post(f"{API}/providers/{p['id']}/disable").status_code == 404
    r = other_client.put(f"{API}/model-routing", json={"routes": {"planner": [mid]}})
    assert r.status_code == 422
    assert auth_client.get(f"{API}/providers/{p['id']}").json()["enabled"] is True


# --- capabilities -------------------------------------------------------------------------


def test_capabilities_round_trip(auth_client) -> None:
    p = add_provider(
        auth_client,
        "Local",
        "local",
        ptype="openai_compatible",
        key=None,
        base_url="http://localhost:1234/v1",
    )
    mid = p["models"][0]["id"]
    assert p["models"][0]["capabilities"] == []

    r = auth_client.patch(f"{API}/models/{mid}", json={"capabilities": ["vision", "json", "tools"]})
    assert r.status_code == 200, r.text
    assert r.json()["capabilities"] == ["json", "tools", "vision"]
    assert r.json()["supports_json"] is True  # 'json' and supports_json are one flag

    r = auth_client.patch(f"{API}/models/{mid}", json={"supports_json": False})
    assert r.json()["capabilities"] == ["tools", "vision"]

    bad = auth_client.patch(f"{API}/models/{mid}", json={"capabilities": ["telepathy"]})
    assert bad.status_code == 422
    conflict = auth_client.patch(
        f"{API}/models/{mid}", json={"capabilities": ["json"], "supports_json": False}
    )
    assert conflict.status_code == 422


# --- LiteLLM model-map prefill (FR-LLM-002) ----------------------------------------------


def test_known_models_are_prefilled_from_litellm(auth_client) -> None:
    r = auth_client.post(
        f"{API}/providers",
        json={
            "provider_type": "openai",
            "display_name": "OpenAI",
            "api_key": KEY,
            "models": [{"model_identifier": "gpt-4o-mini"}],
        },
    )
    model = r.json()["models"][0]
    assert model["context_window"] and model["context_window"] > 0
    assert Decimal(model["input_price_per_mtok"]) > 0
    assert Decimal(model["output_price_per_mtok"]) > 0
    assert "json" in model["capabilities"] and model["supports_json"] is True


def test_user_values_win_over_prefill(auth_client) -> None:
    r = auth_client.post(
        f"{API}/providers",
        json={
            "provider_type": "anthropic",
            "display_name": "Claude",
            "api_key": KEY,
            "models": [
                {
                    "model_identifier": "claude-sonnet-4-5",
                    "context_window": 1000,
                    "input_price_per_mtok": "1.5",
                    "capabilities": ["tools"],
                }
            ],
        },
    )
    model = r.json()["models"][0]
    assert model["context_window"] == 1000
    assert Decimal(model["input_price_per_mtok"]) == Decimal("1.5")
    assert model["output_price_per_mtok"] is not None  # left empty, so prefilled
    assert model["capabilities"] == ["tools"]


@pytest.mark.parametrize(
    ("ptype", "model"), [("openai_compatible", "gpt-4o-mini"), ("openai", "no-such-model-xyz")]
)
def test_no_prefill_for_local_or_unknown_models(auth_client, ptype, model) -> None:  # type: ignore[no-untyped-def]
    body = {
        "provider_type": ptype,
        "display_name": "X",
        "api_key": KEY,
        "models": [{"model_identifier": model}],
    }
    if ptype == "openai_compatible":
        body["base_url"] = "http://localhost:1234/v1"
    m = auth_client.post(f"{API}/providers", json=body).json()["models"][0]
    assert (m["context_window"], m["input_price_per_mtok"], m["capabilities"]) == (None, None, [])


# --- combined routing configuration -------------------------------------------------------


def test_model_routing_get_and_put(auth_client) -> None:
    a = _provider(auth_client, "Alpha", "a-model")["models"][0]["id"]
    b = _provider(auth_client, "Beta", "b-model")["models"][0]["id"]
    body = auth_client.get(f"{API}/model-routing").json()
    assert [r["role"] for r in body["roles"]] == ROLES
    assert body["policy"]["max_retries"] == 2

    r = auth_client.put(
        f"{API}/model-routing",
        json={
            "routes": {"planner": [a, b], "researcher": [b], "default": [a]},
            "policy": {"max_retries": 1, "fallback_on_quota_exhausted": True},
        },
    )
    assert r.status_code == 200, r.text
    out = {x["role"]: [e["model_id"] for e in x["entries"]] for x in r.json()["roles"]}
    assert out["planner"] == [a, b] and out["researcher"] == [b] and out["default"] == [a]
    assert r.json()["policy"]["max_retries"] == 1
    assert r.json()["policy"]["fallback_on_quota_exhausted"] is True

    # Roles not mentioned keep their chain; an empty list returns a role to the default.
    r = auth_client.put(f"{API}/model-routing", json={"routes": {"researcher": []}})
    roles = {x["role"]: x for x in r.json()["roles"]}
    assert roles["researcher"]["uses_default"] is True
    assert [e["model_id"] for e in roles["planner"]["entries"]] == [a, b]


def test_model_routing_put_is_atomic(auth_client) -> None:
    a = _provider(auth_client, "Alpha", "a-model")["models"][0]["id"]
    set_chain(auth_client, [a], role="planner")
    before = auth_client.get(f"{API}/model-routing").json()

    r = auth_client.put(
        f"{API}/model-routing",
        json={
            "routes": {"planner": [], "verifier": ["00000000-0000-0000-0000-000000000000"]},
            "policy": {"max_retries": 5},
        },
    )
    assert r.status_code == 422
    assert auth_client.get(f"{API}/model-routing").json() == before  # nothing applied


@pytest.mark.parametrize(
    "routes",
    [
        {"writer": []},
        {"planner": ["00000000-0000-0000-0000-000000000001"] * 2},
        {"planner": [f"00000000-0000-0000-0000-{i:012d}" for i in range(11)]},
    ],
    ids=["unknown-role", "duplicate", "too-long"],
)
def test_model_routing_validation(auth_client, routes) -> None:  # type: ignore[no-untyped-def]
    assert auth_client.put(f"{API}/model-routing", json={"routes": routes}).status_code == 422
