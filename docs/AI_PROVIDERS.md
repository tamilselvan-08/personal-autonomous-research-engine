# AI Provider Management (Phase 2)

How PARE stores provider credentials, routes completions between providers, and records
usage and health. The requirements are in [PRD.md](PRD.md) §6.3, §14.2, §15.4 and §17;
this document describes what is built.

---

## 1. Architecture

```
 Web: /ai-providers ──► FastAPI routes (app/api/v1/routes/ai_providers.py)   thin handlers
                              │
                              ▼
                 provider_service ── CRUD, validation, routes, health/usage queries
                 secret_service   ── the only code that sees plaintext keys
                              │
    future services ──► ai_service.AIService.complete / complete_structured
    (Research Planner)        │
                              ▼
                 ai.router.ModelRouter ── single owner of retries, fallback, circuit breaker
                     │            │
                     │            └─► ai.recorder.UsageRecorder ── usage_records + health
                     ▼
                 ai.registry ── ProviderSpec per provider type (LiteLLM route, lister)
                     │
                     ▼
                 LiteLLMAdapter ── litellm.completion(): ONE HTTP request per call
                     │              (num_retries=0, max_retries=0, PARE's HTTP client)
                     ▼
                 PARE HTTP client ── no redirects, per-call timeout, pooled transport
                     │
                     ▼
                 provider HTTPS APIs
```

| Layer | File | Responsibility |
|---|---|---|
| Types | `app/ai/types.py` | Provider-neutral `ChatMessage`, `CompletionRequest`, `CompletionResponse` |
| Errors | `app/ai/errors.py` | `ErrorClass` taxonomy, HTTP classification, **the** retry/fallback decision table, message sanitising |
| LiteLLM adapter | `app/ai/adapters/litellm_adapter.py` | Every completion call via the LiteLLM SDK; maps LiteLLM exceptions onto `ErrorClass`; model-map prefill |
| Model listers | `app/ai/adapters/{openai_compatible,anthropic,gemini}.py` | Read-only "which models can this key use" calls (LiteLLM has no reliable per-key listing) |
| Registry | `app/ai/registry.py` | `ProviderSpec` per provider type: label, LiteLLM route, listing protocol, default URL, key rules, verification status |
| Router | `app/ai/router.py` | Walks the primary → fallback chain, retries with backoff, skips open circuits, raises typed errors |
| Recorder | `app/ai/recorder.py` | Writes one `usage_records` row per attempt and updates provider/model health in its own transaction |
| Façade | `app/services/ai_service.py` | What other features call. Hides providers entirely. |
| Config service | `app/services/provider_service.py` | Providers, models, routes, policy, connection tests, health and usage summaries |
| Credentials | `app/core/crypto.py`, `app/services/secret_service.py` | Envelope encryption, rotation |

### LiteLLM, and how PARE stays the single routing authority

Provider calls use the **LiteLLM Python SDK** (library, not the proxy), as the PRD requires
(C5, §12). LiteLLM makes individual calls only. Everything about *whether* and *where* to
call again belongs to `ModelRouter`. These guarantees are enforced in code and pinned by
tests (`tests/test_ai_adapters.py`):

| Guarantee | How | Why it matters (measured during the switch) |
|---|---|---|
| No retries inside LiteLLM | `num_retries=0` and `max_retries=0` on every call; `litellm.num_retries = 0` globally | With defaults, one LiteLLM call made **3** HTTP requests (its OpenAI client retries twice). Test: every provider × 503/429/500/timeout → exactly 1 request. |
| No LiteLLM fallbacks | `litellm.Router` is never used; one model per call | Fallback order is the user's chain, decided by `ModelRouter`. |
| PARE's HTTP client on every route | `client=` per call: an `OpenAI` SDK client for the `openai/` route, LiteLLM's `HTTPHandler` for `anthropic/`, `gemini/`, `deepseek/`, `xai/`, `mistral/` | LiteLLM **silently ignores** a client of the wrong type and uses its own. Test: every provider type must hit the mock transport. |
| Keys never follow a redirect | PARE's client has `follow_redirects=False` | LiteLLM's own client follows redirects and re-sends `Authorization` / `x-api-key`. Test: every provider × 307 → one request, error. |
| Timeouts honoured | The per-call client carries the call's timeout | On LiteLLM's Gemini route the `timeout` argument alone was ignored (waited 8 s for a 2 s timeout). |
| No network on import, no content logging | `LITELLM_LOCAL_MODEL_COST_MAP=True`, `turn_off_message_logging`, `suppress_debug_info`, LiteLLM loggers silenced | PARE logs sanitised, classified errors itself. |
| Tests can't reach real providers | A session fixture blocks DNS for provider domains | During development one mis-wired call reached a real API (with a fake key); this now fails the test instead. |

Error mapping reads LiteLLM's typed exceptions, the HTTP status, the provider body (from
`exc.response`, `exc.body` or the message — LiteLLM sometimes truncates the middle of long
bodies, so reason codes and `retryDelay` are also extracted from text), and
`litellm_response_headers` for `Retry-After`.

**Costs of LiteLLM:** about **+200 MB memory per API process** (75 → 273 MB measured) and
a **slow import** (~15–19 s on the development machine). The API therefore imports it in a
background thread at startup; until then the API serves everything else normally, and the
first AI call waits for the import if it hasn't finished. The API container (one uvicorn
worker, 512 MB limit) has room for this; raise `mem_limit` if you add workers.

**Model metadata:** when you add a model of a hosted provider and leave context window,
prices or capabilities empty, PARE fills them from LiteLLM's bundled model map
(FR-LLM-002). Values stay editable; OpenAI-compatible endpoints are never prefilled.

### Interface for the Research Planner (and every later feature)

```python
from app.services.ai_service import get_ai_service
from app.models.enums import ModelRole

ai = get_ai_service()
result = ai.complete_structured(
    owner_id=user.id,
    role=ModelRole.PLANNER,
    system="You turn research objectives into plans.",
    prompt=objective,
    schema=ResearchPlanDraft,            # any Pydantic model
)
result.data              # validated ResearchPlanDraft
result.model_identifier, result.provider_name, result.attempts, result.est_cost_usd
```

The caller never knows which provider answered. Errors are `AIRoutingError` subclasses:
`AINotConfiguredError`, `AIProviderConfigError` (bad key / unknown model / out of quota),
`AIRequestRejectedError` (invalid, too long, content policy), `AllProvidersFailedError`.
Each carries `error_class` and the full `attempts` list.

---

## 2. Supported providers

| Type | LiteLLM route | Default base URL | Key (sent as) |
|---|---|---|---|
| `openai` | `openai/<model>` (sends `max_completion_tokens`) | `https://api.openai.com/v1` | required (`Authorization: Bearer`) |
| `anthropic` | `anthropic/<model>` | `https://api.anthropic.com` | required (`x-api-key`) |
| `gemini` | `gemini/<model>` | `https://generativelanguage.googleapis.com/v1beta` | required (`x-goog-api-key`, never in the URL) |
| `xai` | `xai/<model>` | `https://api.x.ai/v1` | required (`Authorization: Bearer`) |
| `deepseek` | `deepseek/<model>` | `https://api.deepseek.com/v1` | required (`Authorization: Bearer`) |
| `mistral` | `mistral/<model>` | `https://api.mistral.ai/v1` | required (`Authorization: Bearer`) |
| `openai_compatible` | `openai/<model>` with your base URL (LM Studio, Ollama, vLLM, proxies) | user-supplied, http allowed | optional (a placeholder `Bearer not-needed` is sent when empty) |

**Verification status — be precise about what "supported" means:**

- Every provider type is tested **through LiteLLM** against mocked provider responses
  that follow each provider's documented request, response and error formats
  (`tests/test_ai_adapters.py`: the requests checked are the exact ones LiteLLM puts on the
  wire). The registry marks all types `verification="mocked"`, and the UI says so.
- **No provider has been verified against its live API yet** (no keys were available during
  development). Run the opt-in live checks (§7) with your keys; when one passes, set its
  `verification="live"` in `registry.py` and record it in `DEVELOPMENT_STATUS.md`.
- The OpenAI-compatible path was additionally exercised end-to-end through the real UI against
  the local stub server (`tools/stub-llm`).

Adding a provider LiteLLM supports: add a `ProviderType` value, a `ProviderSpec` with its
LiteLLM route, a migration that recreates the `provider_type` CHECK constraint, and — if
its route takes an OpenAI SDK client rather than `HTTPHandler` — a line in
`LiteLLMAdapter._client_arg`. The "every provider uses PARE's HTTP client" test will tell
you if that line is needed.

---

## 3. Routing, retries and fallback

Each user has an ordered chain per **role**: `planner`, `researcher`, `extractor`,
`verifier`, `summarizer`, plus `default`. Position 0 is the primary. A role without its own
chain uses `default`, so one chain is enough to start with.

For each entry in the chain the router:

1. **Skips** it (without calling) if the provider or model is disabled, the provider has no
   key, the key can't be decrypted, or the model's circuit is open.
2. Calls it once. On failure it classifies the error and applies the decision table below.
3. Retries with exponential backoff and jitter (1 s, 2 s, 4 s … capped at 8 s, ×0.5–1.0),
   using the provider's `Retry-After` when longer.
4. Falls back to the next entry, or stops and raises a typed error.

| Error class | Examples | Retry same model | Fall back | Health effect |
|---|---|---|---|---|
| `timeout`, `network` | read timeout, connection refused, DNS | yes (≤ max_retries) | yes | degraded → down after 3 |
| `server_error` | 500, 502, 503, 504, 529, "overloaded" | yes | yes | degraded → down after 3 |
| `rate_limited` | 429 | yes, honouring `Retry-After` up to the policy cap; skipped if longer | if `fallback_on_rate_limit` (default on) | degraded |
| `quota_exhausted` | OpenAI `insufficient_quota`, DeepSeek 402, Anthropic "credit balance is too low" | no | **only if** `fallback_on_quota_exhausted` (default off) | `quota_exhausted` |
| `auth` | 401/403, Gemini `API_KEY_INVALID`, xAI "Incorrect API key" | no | **no** — surfaced | `invalid_credentials` |
| `model_not_found` | 404, "model … does not exist" | no | **no** — surfaced | model `misconfigured` |
| `invalid_request`, `context_length`, `content_policy` | 400/422 | no | **no** (sending it elsewhere wouldn't help) | none |
| `invalid_response` | non-JSON body; structured reply failing schema validation | repair once with the validation error, then | yes | degraded |
| `unknown` | anything else | once | no | degraded |

**Circuit breaker:** 5 consecutive transient failures open a model's circuit; it is skipped
for 60 s, then half-open (one attempt; success closes it, failure re-opens it). State lives in
`ai_models.circuit_opened_at`, so every API process shares it.

**Policy** (`GET/PUT /api/v1/routing-policy`, per user): `max_retries` (0–5, default 2),
`max_retry_after_seconds` (0–120, default 20), `fallback_on_rate_limit` (default true),
`fallback_on_quota_exhausted` (default false).

**Connection tests** (`POST /providers/{id}/test`) are a single 5-token call: no retries, no
fallback, rate-limited to 6/min per user. They update health and are recorded as usage with
purpose `connection_test`.

---

## 4. Credential security

| Control | Implementation |
|---|---|
| Encryption at rest | AES-256-GCM **envelope** encryption: a random 256-bit data key (DEK) per secret encrypts the key; the DEK is encrypted with the key-encryption key (KEK). Both layers are authenticated. |
| Binding | AAD = `secret.id ‖ owner_id`. A ciphertext copied to another row or another user's account fails to decrypt (tested). |
| KEK location | `SECRETS_MASTER_KEY` environment variable only — never in the database. `scripts/setup-env` generates it. Only its short id (`kek_id`) is stored. |
| Write-only keys | Keys are accepted as `SecretStr`, never returned. Responses carry only `key_masked` (`••••` + last 4; nothing for keys shorter than 8 characters). |
| Just-in-time decryption | Keys are decrypted immediately before each provider call and never cached or stored on the router. |
| No leakage in errors/logs | Provider error messages are sanitised (exact key, 12–16-char fragments, key-like tokens removed) before storage, logging or display. JSON logs redact secret-named fields and key patterns. Usage records contain no prompt or reply content. |
| Transport | Keys go only in headers (`Authorization`, `x-api-key`, `x-goog-api-key`), never URLs. Redirects are not followed, so a key is never sent to a host other than the configured one. Hosted providers require `https://`; `http://` is allowed only for OpenAI-compatible (local) endpoints. URLs with embedded credentials are rejected. |
| Isolation | Every query filters by `owner_id`; another user's ids return 404 (tested for every endpoint). |
| Audit | `ai_provider.created/updated/deleted/key_replaced/key_removed`, `ai_model.*`, `model_route.updated`, `routing_policy.updated` — never with key material. |
| Tests | `test_api_key_never_leaks` scans every endpoint response, the log output and all AI tables for the key and fragments of it; a mutation check confirms the test fails if sanitising is removed. |

### Backups

- A database backup contains only ciphertext. **Without `SECRETS_MASTER_KEY` it cannot be
  decrypted** — so store the `.env` (or at least the key) separately from database backups,
  and protect it at least as well.
- If you restore a database but lose the master key, the stored keys are unrecoverable:
  providers show "Key rejected"/"credential could not be decrypted" and you re-enter each
  key with **Replace API key**. Nothing else is lost.
- `python -m app.cli check-secrets` reports how many stored keys decrypt with the current
  configuration.

### Rotating the master key

Rotation only re-wraps the per-secret data keys; ciphertexts are untouched, so it is fast
and safe to re-run.

1. Generate a new key: `docker compose exec api python -m app.cli generate-master-key`
2. In `.env`: move the current key to `SECRETS_PREVIOUS_KEYS=k1:<old key>`, set
   `SECRETS_MASTER_KEY=<new key>` and `SECRETS_MASTER_KEY_ID=k2`.
3. Restart: `docker compose up -d api` (old secrets still decrypt via the previous key).
4. Re-wrap: `docker compose exec api python -m app.cli rotate-master-key`
5. Verify: `docker compose exec api python -m app.cli check-secrets` → "Still on previous keys: 0".
6. Remove `SECRETS_PREVIOUS_KEYS` and restart. Destroy the old key.

Changing `SECRETS_MASTER_KEY` **without** keeping the old one in `SECRETS_PREVIOUS_KEYS`
makes all stored keys unreadable (users must re-enter them).

---

## 5. Data model (migrations `0002`, `0003`)

| Table | Purpose | Notes |
|---|---|---|
| `secrets` | Encrypted credentials | `ciphertext`, `nonce`, `wrapped_dek`, `dek_nonce`, `kek_id`, `last4`; CASCADE on user delete |
| `ai_providers` | Provider configuration | `provider_type` (CHECK), `display_name` unique per user (case-insensitive), `base_url` (NULL = default), `secret_id` → secrets, `enabled`, health columns, `last_tested_at` |
| `ai_models` | Models per provider | unique `(provider_id, model_identifier)`; `display_name`, prices per 1M tokens, `context_window`, `supports_json` + `capabilities` (JSONB array: `vision`, `tools`, `reasoning`; the API returns `json` too when `supports_json` is set), `enabled`, health + `circuit_opened_at`; `owner_id` denormalised for scoped queries |
| `model_routes` | Ordered chains | unique `(owner_id, role, position)` and `(owner_id, role, model_id)`; CASCADE when a model is deleted (positions are re-compacted) |
| `ai_routing_policies` | Retry/fallback preferences | one row per user; absent = defaults |
| `usage_records` | One row per attempt | provider/model snapshots (history survives deletion; FKs SET NULL), role, purpose, `call_id` grouping a routed call, attempt, outcome, error class, HTTP status, latency, tokens, estimated cost, request id |

Enumerations use `VARCHAR` + `CHECK` rather than PostgreSQL enum types so adding a value is a
constraint swap, not an `ALTER TYPE` (migration `0003` does this to add the `researcher`
role; its downgrade removes researcher chains and relabels researcher usage history as
`default` rather than deleting it).

**Mapping to the requested fields** (Development Prompt 02 §5): `encrypted_api_key` lives in
`secrets` (envelope-encrypted, referenced by `ai_providers.secret_id`); `connection_status`
is derived from the stored health and returned by the API as `connected` / `failing` /
`not_tested` / `disabled`; `user_id` is `owner_id`; `model_capabilities` is
`capabilities` (+ `supports_json`). Migration tests cover upgrade → downgrade → upgrade and
model/migration drift (`alembic check` equivalent).

---

## 6. API (all under `/api/v1`, authenticated, owner-scoped)

| Method & path | Purpose |
|---|---|
| `GET /providers/types` | Supported types and whether encryption is configured |
| `GET /providers`, `POST /providers` | List / create (`{provider_type, display_name, api_key?, base_url?, models?: [...]}`) |
| `GET/PUT/PATCH/DELETE /providers/{id}` | Read; partial update (rename / base URL / enable) — PUT and PATCH take the same body; delete (`?force=true` when used in routing) |
| `POST /providers/{id}/enable`, `POST /providers/{id}/disable` | Enable / disable (disabled providers are skipped by routing) |
| `PUT /providers/{id}/key`, `DELETE /providers/{id}/key` | Replace / delete the stored key |
| `POST /providers/{id}/test` | Connection test (`{model_id?}` or `{model_identifier?}`) → `{ok, latency_ms, error_class, error_hint, message, health_state}` |
| `GET /providers/{id}/available-models` | Ask the provider which models the key can use |
| `GET /models?provider_id=`, `POST /models` | All configured models across providers; add a model with `provider_id` in the body |
| `GET/POST /providers/{id}/models` | One provider's models; add a model to it |
| `PUT/PATCH/DELETE /models/{id}` | Update (incl. `capabilities`, `enabled`, prices) / delete a model |
| `GET /model-routes`, `PUT /model-routes/{role}` | Chains; PUT `{model_ids: [primary, fallback1, …]}` (enabled models only, max 10) |
| `POST /model-routes/{role}/test` | Send a tiny prompt through the chain and report every attempt |
| `GET/PUT /model-routing` | Everything at once: chains for every role + the policy. PUT `{routes: {planner: [ids], researcher: [], …}, policy: {…}}` is **atomic**; roles not listed keep their chain, `[]` returns a role to the default chain |
| `GET/PUT /routing-policy` | Retry/fallback policy |
| `GET /providers/health?window_hours=24` | Per-provider state, success rate, p50/p95 latency, last error |
| `GET /usage?group_by=provider\|model\|day\|purpose\|outcome&from&to` | Aggregated usage and estimated cost |
| `GET /usage/records` | Paginated attempt records |

Error codes added: `PROVIDER_NAME_TAKEN`, `PROVIDER_IN_USE`, `MODEL_ALREADY_CONFIGURED`,
`MODEL_IN_USE`, `ENCRYPTION_NOT_CONFIGURED` (503), `NO_API_KEY`, `CREDENTIAL_UNREADABLE`.

---

## 7. Testing

```bash
cd apps/api
pytest tests/test_ai_crypto.py tests/test_ai_errors.py tests/test_ai_adapters.py   # no DB needed
pytest tests/test_ai_router.py tests/test_ai_providers_api.py tests/test_ai_model_config_api.py
pytest tests/test_migrations.py
```

No automated test makes a network call or needs a key: provider HTTP goes through
`httpx.MockTransport`, and a session fixture blocks DNS for real provider domains so a
mis-wired call fails loudly. Tests also never read `apps/api/.env`. Optional live checks (real, tiny,
paid calls with your keys):

```powershell
$env:PARE_LIVE_TESTS = "1"
$env:PARE_LIVE_OPENAI_KEY = "sk-..."; $env:PARE_LIVE_OPENAI_MODEL = "gpt-4o-mini"
pytest tests/test_live_providers.py -v
```

### Manual testing without paid keys

```bash
python tools/stub-llm/stub_llm.py             # outside Docker; add --host 0.0.0.0 for Docker
```

In **AI Providers → Add provider**, choose *OpenAI-compatible endpoint* and use base URL
`http://127.0.0.1:9911/ok/v1` (or `http://host.docker.internal:9911/ok/v1` from the Docker
stack), model `stub-small`. Add a second one with `/down/v1`. Make `/down` primary and `/ok`
the fallback, then **Test routing**: you'll see two retries, a fallback and a success
(and the stub's log shows exactly one HTTP request per attempt — LiteLLM adds none). Other
routes: `/badkey/v1` (no fallback, "Key rejected"), `/nomodel/v1`, `/ratelimit/v1`,
`/noquota/v1`, `/slow/v1` (timeout).
