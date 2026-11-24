"""Opt-in live checks against real provider APIs. Skipped unless PARE_LIVE_TESTS=1.

These make real, tiny (5 output tokens) paid calls with your own keys. Nothing in the
default test run needs them. Example (PowerShell):

    $env:PARE_LIVE_TESTS = "1"
    $env:PARE_LIVE_OPENAI_KEY = "sk-..."; $env:PARE_LIVE_OPENAI_MODEL = "gpt-4o-mini"
    pytest tests/test_live_providers.py -v

For each provider, set PARE_LIVE_<TYPE>_KEY and PARE_LIVE_<TYPE>_MODEL, where TYPE is
OPENAI, ANTHROPIC, GEMINI, XAI, DEEPSEEK or MISTRAL. Providers without both are skipped.
When a provider passes, record it in app/ai/registry.py (verification="live") and in
DEVELOPMENT_STATUS.md with the date and model.
"""

import os

import pytest

from app.ai.errors import ErrorClass, ProviderError
from app.ai.registry import PROVIDER_SPECS, default_adapter_factory
from app.ai.types import ChatMessage, CompletionRequest, ProviderCallConfig
from app.models.enums import ProviderType

pytestmark = pytest.mark.skipif(
    os.environ.get("PARE_LIVE_TESTS") != "1", reason="set PARE_LIVE_TESTS=1 to run live checks"
)

LIVE_TYPES = [t for t in ProviderType if t is not ProviderType.OPENAI_COMPATIBLE]
REQ = CompletionRequest(
    messages=[ChatMessage("user", "Reply with the single word: OK")], max_output_tokens=5
)


def _cfg(ptype: ProviderType, key: str, model: str) -> ProviderCallConfig:
    spec = PROVIDER_SPECS[ptype]
    return ProviderCallConfig(
        provider_type=ptype.value,
        base_url=(spec.default_base_url or "").rstrip("/"),
        model=model,
        timeout_seconds=30,
        api_key=key,
    )


def _env(ptype: ProviderType) -> tuple[str, str]:
    key = os.environ.get(f"PARE_LIVE_{ptype.value.upper()}_KEY")
    model = os.environ.get(f"PARE_LIVE_{ptype.value.upper()}_MODEL")
    if not key or not model:
        pytest.skip(f"PARE_LIVE_{ptype.value.upper()}_KEY/_MODEL not set")
    return key, model


@pytest.mark.parametrize("ptype", LIVE_TYPES, ids=lambda t: t.value)
def test_live_completion(ptype: ProviderType) -> None:
    key, model = _env(ptype)
    adapter = default_adapter_factory()(PROVIDER_SPECS[ptype])
    response = adapter.complete(_cfg(ptype, key, model), REQ)
    assert response.input_tokens is None or response.input_tokens > 0


@pytest.mark.parametrize("ptype", LIVE_TYPES, ids=lambda t: t.value)
def test_live_invalid_key_is_classified_as_auth(ptype: ProviderType) -> None:
    _, model = _env(ptype)
    adapter = default_adapter_factory()(PROVIDER_SPECS[ptype])
    with pytest.raises(ProviderError) as info:
        adapter.complete(_cfg(ptype, "invalid-key-for-pare-live-test-000000", model), REQ)
    assert info.value.error_class is ErrorClass.AUTH


@pytest.mark.parametrize("ptype", LIVE_TYPES, ids=lambda t: t.value)
def test_live_unknown_model_is_classified(ptype: ProviderType) -> None:
    key, _ = _env(ptype)
    adapter = default_adapter_factory()(PROVIDER_SPECS[ptype])
    with pytest.raises(ProviderError) as info:
        adapter.complete(_cfg(ptype, key, "pare-no-such-model-xyz"), REQ)
    assert info.value.error_class in (ErrorClass.MODEL_NOT_FOUND, ErrorClass.INVALID_REQUEST)
