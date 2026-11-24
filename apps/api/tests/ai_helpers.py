"""Shared helpers for AI provider tests: a scripted fake adapter and setup shortcuts."""

from collections import defaultdict, deque
from collections.abc import Iterable

from app.ai.adapters.base import ProviderAdapter
from app.ai.errors import ErrorClass, ProviderError
from app.ai.types import CompletionRequest, CompletionResponse, DiscoveredModel, ProviderCallConfig

API = "/api/v1"


class ScriptedAdapter(ProviderAdapter):
    """Returns scripted outcomes per model identifier, in order; records every call."""

    protocol = "openai"

    def __init__(self) -> None:
        self.scripts: dict[str, deque] = defaultdict(deque)
        self.calls: list[tuple[str, CompletionRequest, str | None]] = []
        self.default = CompletionResponse(text="OK", input_tokens=10, output_tokens=2)

    def script(self, model: str, outcomes: Iterable[object]) -> None:
        self.scripts[model].extend(outcomes)

    def complete(self, cfg: ProviderCallConfig, request: CompletionRequest) -> CompletionResponse:
        self.calls.append((cfg.model, request, cfg.api_key))
        queue = self.scripts[cfg.model]
        outcome = queue.popleft() if queue else self.default
        if isinstance(outcome, BaseException):
            raise outcome
        if isinstance(outcome, str):
            return CompletionResponse(text=outcome, input_tokens=10, output_tokens=2)
        return outcome  # type: ignore[return-value]

    def list_models(self, cfg: ProviderCallConfig) -> list[DiscoveredModel]:
        return [DiscoveredModel(id="m-a"), DiscoveredModel(id="m-b")]

    def models_called(self) -> list[str]:
        return [c[0] for c in self.calls]


def perr(
    cls: ErrorClass, status: int | None = None, retry_after: float | None = None
) -> ProviderError:
    return ProviderError(cls, f"simulated {cls.value}", http_status=status, retry_after=retry_after)


def add_provider(
    client,  # type: ignore[no-untyped-def]
    name: str,
    model: str,
    *,
    ptype: str = "openai",
    key: str | None = "sk-test-key-for-unit-tests-0001",
    base_url: str | None = None,
    supports_json: bool = False,
) -> dict:
    body: dict = {
        "provider_type": ptype,
        "display_name": name,
        "models": [{"model_identifier": model, "supports_json": supports_json}],
    }
    if key is not None:
        body["api_key"] = key
    if base_url is not None:
        body["base_url"] = base_url
    r = client.post(f"{API}/providers", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def set_chain(client, model_ids: list[str], role: str = "default") -> dict:  # type: ignore[no-untyped-def]
    r = client.put(f"{API}/model-routes/{role}", json={"model_ids": model_ids})
    assert r.status_code == 200, r.text
    return r.json()


def user_id(client) -> str:  # type: ignore[no-untyped-def]
    return client.get(f"{API}/auth/me").json()["id"]
