# PARE — Development Status

_Last updated: 2026-11-26_

| Phase (PRD §26) | Status |
|---|---|
| 1. Foundation (base application) | **Done** — committed as the recovery point `39e8cb3` |
| 2. AI provider management | **Done** (Development Prompt 02 applied 2026-11-26), with open verification items below |
| 3. Research planning | Not started — do not begin until instructed |
| 4–7 | Not started |

---

## Phase 2 — AI Provider Management

### Development Prompt 02 changes (2026-11-26)

- **LiteLLM** now makes every provider completion call (PRD C5). LiteLLM's retries are
  disabled on every call and its Router is not used; PARE's `ModelRouter` remains the only
  component that retries or falls back. PARE's own HTTP client is passed on every LiteLLM
  route (no redirects, per-call timeout). Model discovery stays as direct read-only calls.
- Findings while switching, each now covered by a test: LiteLLM's default OpenAI client
  retried twice on its own (3 HTTP requests per call); LiteLLM followed redirects and re-sent
  the key; it silently ignores an HTTP client of the wrong type for a route (and one test
  call reached a real provider with a fake key before this was found — tests now block real
  provider hosts); its Gemini route ignored the timeout; it truncates long error bodies.
- New **`researcher`** role (migration `0003`), model **`capabilities`**, provider
  **`connection_status`**, and **prefill** of context window / prices / capabilities from
  LiteLLM's model map for known hosted models.
- New endpoints alongside the existing ones: `PUT /providers/{id}`,
  `POST /providers/{id}/enable|disable`, `GET/POST /models`, `PUT /models/{id}`,
  `GET/PUT /model-routing` (atomic multi-role update).
- Tests no longer read `apps/api/.env` (it can hold a real database URL).
- Alembic reads `DATABASE_URL` from `apps/api/.env` when it isn't in the environment.
- `docs/ARCHITECTURE.md` added; `docs/AI_PROVIDERS.md` updated.

**Cost:** LiteLLM adds ~200 MB per API process (measured 75 → 273 MB) and a slow import
(~15–19 s on the development machine), so the API imports it in a background thread at
startup. It fits the 512 MB API container with one worker.

### What was built (Phase 2, 2026-11-25)

- **Provider layer** (`apps/api/app/ai/`): error taxonomy and single retry/fallback decision
  table, three protocol adapters (OpenAI-compatible, Anthropic Messages, Gemini), provider
  registry for 7 provider types, `ModelRouter` (primary → ordered fallbacks, bounded
  exponential backoff with jitter, `Retry-After`, circuit breaker, structured-output repair),
  usage/health recorder.
- **Credential security**: AES-256-GCM envelope encryption (`app/core/crypto.py`), AAD bound
  to secret id + owner, KEK from `SECRETS_MASTER_KEY`, rotation via `python -m app.cli
  rotate-master-key`, write-only keys with `••••last4` masking, error-message scrubbing.
- **Database** (migration `0002`): `secrets`, `ai_providers`, `ai_models`, `model_routes`,
  `ai_routing_policies`, `usage_records`.
- **API**: providers, keys, models, connection tests, model discovery, routes per role,
  routing test, policy, health, usage (see `docs/AI_PROVIDERS.md` §6).
- **Interface for later phases**: `app.services.ai_service.AIService.complete()` /
  `complete_structured(schema=…)` — callers never see which provider answered.
- **UI**: `/ai-providers` — add-provider dialog, provider cards (masked key, health, models,
  test, enable/disable, edit, replace/delete key, delete), model discovery, routing editor
  (primary + fallbacks per role, routing test with per-attempt results), retry/fallback
  policy, health table, usage summary and recent calls. Nav no longer marks it "Coming soon".
- **Ops**: `setup-env` scripts generate `SECRETS_MASTER_KEY` and add it to an existing `.env`;
  `start.ps1` runs them on every start; Compose passes the key and maps
  `host.docker.internal` for local OpenAI-compatible servers.
- **Tooling**: `tools/stub-llm/stub_llm.py` — OpenAI-compatible stub with healthy and failing
  routes for manual testing without keys.

### Verification performed — Prompt 02 (2026-11-26)

| Check | Result |
|---|---|
| Backend tests (`pytest --cov=app`) | **302 passed**, 18 skipped (opt-in live checks), coverage 93 % |
| LiteLLM guarantees (every provider type) | one HTTP request per call on 503/429/500/timeout; PARE's client used; redirects not followed; keys only in headers |
| Migration `0003` up/down (incl. rollback with researcher data) | pass |
| `ruff check` / `ruff format --check` | clean |
| Frontend `typecheck`, `lint`, `vitest` (28 tests), `next build` | all pass |
| Browser, against the stub server through LiteLLM | routing test: retry, retry, fallback, success; connection tests made exactly 1 HTTP request each; Researcher role in the picker; `gpt-4o-mini` prefilled as "128k context · JSON · Tools · Vision" without any call to OpenAI |

### Verification performed — Phase 2 (2026-11-25, Windows 11, Python 3.13, Node 22, PostgreSQL 15)

| Check | Result |
|---|---|
| Backend tests (`pytest --cov=app`) | **223 passed**, 18 skipped (opt-in live checks), coverage 94 % |
| Existing Phase 1 regression tests | all pass (included above) |
| Migration up → down → up, model/migration drift | pass |
| `ruff check` / `ruff format --check` | clean |
| Frontend `typecheck`, `lint`, `vitest` (27 tests), `next build` | all pass |
| End-to-end in the browser against the stub server | add provider → auto connection test (failure classified, health "Degraded"), second provider, primary + fallback saved, routing test showed retry, retry, fallback, success; circuit breaker opened after repeated failures; usage and health tables populated |

Tests ran against a throwaway local PostgreSQL 15 cluster (CI uses PostgreSQL 16).

### Not yet verified — do these before treating Phase 2 as fully validated

- [ ] **Live provider calls.** No provider has been called through LiteLLM with a real key. Run
      `tests/test_live_providers.py` with real keys (at least OpenAI, Anthropic, Gemini per
      FR-LLM-024), then set `verification="live"` for passing types in `app/ai/registry.py`
      and record model + date here.
- [ ] **Docker**: Docker is not installed on the development machine, so `docker compose up
      --build` (API image with the new `cryptography`/`httpx` dependencies, migration `0002` on
      startup, key passed through Compose) has not been run. CI's `compose` job covers it.
- [ ] **Windows `start.ps1` on a real install**: the setup scripts were tested in isolation
      (fresh `.env`, upgrade of an existing `.env`, idempotent re-run); the full start script
      was not run.
- [ ] Phase 1 milestone checks from the plan: base app on Windows via Docker, registration and
      login, task CRUD, data survives restart.

### Known limitations / deferred

- Budget enforcement and spending caps (PRD §17.3) — not implemented; cost is an estimate and
  only for models with prices set.
- Circuit breaker uses consecutive transient failures only (not the ">50 % of last 20" rule).
- Rate limiting of connection tests is in-memory per API process.
- Price prefill from a model cost map (FR-LLM-002) is not implemented; prices are entered by
  the user.
- Auth failures never fall back (PRD FR-LLM-022). A rejected primary key blocks calls for that
  role until the key is fixed or the chain changed — intentional, so a broken key is not
  silently hidden.
- Provider/model names shown in examples are placeholders; use **Browse models** to see what
  your key can access.

### Recommended next feature

**Phase 3 — AI Research Planner** (PRD §6.4, §8.3): plan schema, generation through
`AIService.complete_structured(role=PLANNER, schema=…)`, validation and repair, version
history, editor, diff and approval with content hash. Do not start until instructed.
