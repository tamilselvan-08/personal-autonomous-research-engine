# PARE — Architecture

What is built today (Phases 1–2) and how the pieces fit. Requirements live in
[PRD.md](PRD.md); the AI provider layer is detailed in [AI_PROVIDERS.md](AI_PROVIDERS.md).
Where this document and the code disagree, the code is right — please fix this file.

---

## 1. System overview

```
 Browser ──► web (Next.js 16, React 19)        http://localhost:3000   apps/web
                │  fetch + cookie session, X-PARE-CSRF header
                ▼
             api (FastAPI, Python 3.12+)       http://localhost:8000   apps/api
                │  SQLAlchemy 2 / psycopg 3                │ LiteLLM SDK (one call at a time)
                ▼                                          ▼
             PostgreSQL 16 (pgdata volume)            AI providers (user's own keys)
```

Three containers in `docker-compose.yml` (`postgres`, `api`, `web`), each with a 512 MB
memory limit; only ports 3000 and 8000 are published, on 127.0.0.1. Migrations run when
the API container starts. Everything also runs without Docker (README → *Running without
Docker*), including against a hosted PostgreSQL such as Supabase.

## 2. Backend (`apps/api/app`)

| Package | Role | Rule |
|---|---|---|
| `api/v1/routes/` | HTTP endpoints: `auth`, `projects`, `tasks`, `system`, `ai_providers` | Thin: validate with schemas, call a service, return a schema |
| `schemas/` | Pydantic request/response models | Responses never carry secrets (keys are `SecretStr` in, `key_masked` out) |
| `services/` | Business logic, one module per area | Every function takes `owner_id`; ownership is checked here |
| `repositories/` | Non-trivial query construction (task lists) | Always owner-scoped |
| `domain/` | Pure rules (research-task state machine) | No I/O |
| `models/` | SQLAlchemy models | UUID keys, timezone-aware timestamps, `VARCHAR`+`CHECK` enums |
| `ai/` | Provider calls and routing | See §4 |
| `core/` | Config, DB sessions, security (JWT, bcrypt), crypto, errors, logging, middleware, rate limits | No feature logic |
| `cli.py` | Maintenance: master-key generation, rotation, checks | |
| `alembic/versions/` | Schema migrations `0001`–`0003` | Up/down tested; model/migration drift tested |

**Request path:** `RequestContextMiddleware` (request id, timing log) → CORS → trusted
hosts → CSRF origin check → security headers → route. Errors are converted to one JSON
shape (`{error: {code, message, details, request_id}}`) in `core/errors.py`.

**Auth:** registration/login issue a JWT in an HttpOnly cookie (`pare_session`); browsers
must send `X-PARE-CSRF: 1` on state-changing requests. Scripts may use
`Authorization: Bearer`. Passwords are bcrypt-hashed; login is rate-limited.

**Configuration:** environment variables (or `apps/api/.env` outside Docker), validated by
`core/config.py` at startup. Secrets: `JWT_SECRET`, `SECRETS_MASTER_KEY`, database URL.

## 3. Data model

| Area | Tables |
|---|---|
| Accounts & work | `users`, `projects`, `research_tasks`, `audit_events` |
| AI providers | `secrets`, `ai_providers`, `ai_models`, `model_routes`, `ai_routing_policies`, `usage_records` |

Every user-owned row has `owner_id` with an index; deleting a user cascades. Usage history
keeps provider/model name snapshots so it survives deletion of the provider. Details:
[AI_PROVIDERS.md §5](AI_PROVIDERS.md#5-data-model-migrations-0002-0003).

## 4. AI layer (`apps/api/app/ai`)

```
 feature code ─► AIService (complete / complete_structured, by role)
                    └─► ModelRouter ── chain for the role: primary → fallbacks
                           ├─ skips disabled / keyless / open-circuit models
                           ├─ classifies errors (ErrorClass) and decides: retry? fall back? stop?
                           ├─ bounded exponential backoff + Retry-After
                           └─► LiteLLMAdapter ── litellm.completion(), exactly one HTTP request
                                  └─► PARE HTTP client (no redirects, per-call timeout)
                    UsageRecorder ── one usage_records row per attempt; provider/model health
```

- **Single routing authority:** only `ModelRouter` retries or falls back. LiteLLM's own
  retries are disabled on every call and its Router is never used — enforced by tests that
  count HTTP requests per call for every provider type.
- **Roles:** `planner`, `researcher`, `extractor`, `verifier`, `summarizer`, plus `default`
  (used by any role without its own chain).
- **Stop conditions:** rejected keys, unknown models, invalid requests, context-length and
  content-policy errors are never retried or sent to another provider; they are reported.
- **Credentials:** AES-256-GCM envelope encryption; the master key lives only in the
  environment; keys are decrypted just before a call and never returned by the API.

## 5. Frontend (`apps/web`)

Next.js App Router. `app/(app)/…` holds signed-in pages, `app/(auth)/…` login and
registration. Feature code lives in `features/<area>/` (components + React Query hooks);
`lib/api.ts` is the typed API client, `types/api.ts` mirrors the API schemas, and
`components/ui/` holds shared primitives. The API base URL (`NEXT_PUBLIC_API_URL`) is
compiled into the bundle.

## 6. Testing

| Suite | Where | Notes |
|---|---|---|
| Backend | `apps/api/tests` (pytest) | Real PostgreSQL (`TEST_DATABASE_URL`), truncated between tests; provider HTTP mocked; real provider hosts blocked; `.env` ignored |
| Live provider checks | `tests/test_live_providers.py` | Opt-in (`PARE_LIVE_TESTS=1`), uses your keys |
| Frontend | `apps/web` (Vitest + Testing Library), `typecheck`, `lint`, `next build` | |
| Manual | `tools/stub-llm` | OpenAI-compatible stub with healthy and failing routes |

CI (`.github/workflows`) runs the backend suite, frontend checks and a Docker Compose build.

## 7. Known inconsistencies between documents and code

| Document says | Code does | Why |
|---|---|---|
| PRD §14.3: master key in a separate secrets volume | `SECRETS_MASTER_KEY` environment variable (from `.env`) | Simpler on Windows; documented in the PRD change log |
| PRD: health "> 50 % of last 20 calls" rule | Circuit breaker on 5 consecutive transient failures | Recorded in the PRD change log |
| Development Prompt 02: `PUT /providers/{id}`, flat `/models`, `/model-routing` | Implemented **alongside** the earlier `PATCH`, nested `/providers/{id}/models` and `/model-routes/{role}` | Existing UI and clients keep working |
