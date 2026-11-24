"""AI provider layer.

Layout:
    types.py      provider-neutral request/response types
    errors.py     error taxonomy, classification and the retry/fallback decision table
    adapters/     one adapter per wire protocol (OpenAI-compatible, Anthropic, Gemini)
    registry.py   provider types PARE supports and which adapter serves each
    router.py     primary/fallback routing with retries and circuit breaking
    recorder.py   usage records and provider/model health

Services elsewhere call ``app.services.ai_service`` and never talk to adapters directly.
"""
