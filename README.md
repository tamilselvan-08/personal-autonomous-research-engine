# PARE — Personal Autonomous Research Engine

PARE turns a research question written in plain language into a reviewed plan, then collects, verifies and organises the answer from public sources, with a source for every value.

**This release covers Phases 1–2 of [the PRD](docs/PRD.md):** accounts, projects, research-task management, the dashboard, settings and health monitoring, and **AI provider management** — encrypted API keys, connection tests, models, primary/fallback routing, health and usage ([details](docs/AI_PROVIDERS.md)). Research planning, web research and browser automation are **not implemented yet**; their screens are labelled *Coming soon* and have no controls.

| | |
|---|---|
| Dashboard | http://localhost:3000 |
| API | http://localhost:8000 |
| API docs (OpenAPI) | http://localhost:8000/docs |

---

## Quick start on Windows (Docker Desktop + WSL2)

### 1. Prerequisites

- **Windows 11** (23H2 or later). Windows 10 22H2 is best-effort only.
- Hardware virtualisation enabled in BIOS/UEFI (Task Manager → Performance → CPU → "Virtualization: Enabled").
- **WSL2** — in an administrator PowerShell: `wsl --install`, then reboot.
- **Docker Desktop** — install from docker.com, and in *Settings → General* keep **"Use the WSL 2 based engine"** ticked.
- **Git for Windows**.
- 8 GB RAM minimum (16 GB recommended), 20 GB free disk.

Check your machine at any time:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
```

### 2. Get the code

For best performance clone **inside WSL** (file access from containers is much faster there):

```powershell
wsl
# now inside Ubuntu:
git clone <your-repo-url> ~/pare && cd ~/pare
```

Cloning to a normal Windows folder (e.g. `C:\dev\pare`) also works; hot reload in dev mode is just slower.

### 3. Create your environment file

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-env.ps1
```

(or `sh scripts/setup-env.sh` inside WSL). This copies `.env.example` to `.env` and fills in random `POSTGRES_PASSWORD`, `JWT_SECRET` and `SECRETS_MASTER_KEY` values. Never commit `.env`.

**Upgrading from the base release?** Run the same script again: it leaves your existing values alone and only adds `SECRETS_MASTER_KEY`, which encrypts AI provider API keys (`scripts\start.ps1` does this automatically).

### 4. Start

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

The script checks Docker is running, builds the images, starts PostgreSQL, the API and the web app, waits until the API reports ready, and opens the dashboard. The first build downloads images and can take several minutes.

Equivalent manual commands (PowerShell or WSL):

```bash
docker compose up -d --build
docker compose ps            # all three services should be "healthy"
```

Open http://localhost:3000, **create your account** (it is stored only in your local database), and create a research task.

### 5. Stop

```powershell
powershell -ExecutionPolicy Bypass -File scripts\stop.ps1      # or: docker compose stop
```

Your data lives in the `pare_pgdata` Docker volume and survives restarts and `docker compose down`. **`docker compose down -v` deletes all data.**

---

## Development

### Hot-reload stack

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
# or: scripts\start.ps1 -Dev
```

This mounts `apps/api` and `apps/web` into the containers, reloads on save, and publishes PostgreSQL on `127.0.0.1:5432`.

### Database migrations

Migrations run automatically when the API container starts. To run them yourself:

```bash
docker compose exec api alembic upgrade head          # apply
docker compose exec api alembic current               # show revision
docker compose exec api alembic downgrade -1          # roll back one
# after changing models (dev stack, so the file lands in your checkout):
docker compose exec api alembic revision --autogenerate -m "describe change"
docker compose exec api alembic check                 # models and migrations agree?
```

### Running without Docker

Requires Python 3.12+, Node 22+, and a PostgreSQL 16 you can reach.

```bash
# API
cd apps/api
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                               # then set DATABASE_URL and JWT_SECRET
alembic upgrade head
uvicorn app.main:app --reload --port 8000

# Web (new terminal)
cd apps/web
npm install
npm run dev                                         # http://localhost:3000
```

### Tests and checks

```bash
# Backend — needs a PostgreSQL; tests create and migrate their own `pare_test` database
cd apps/api
export TEST_DATABASE_URL=postgresql+psycopg://pare:pare@localhost:5432/pare_test
pytest --cov=app
ruff check . && ruff format --check .

# Inside the dev stack instead:
docker compose exec -e TEST_DATABASE_URL=postgresql+psycopg://pare:$POSTGRES_PASSWORD@postgres:5432/pare_test api pytest

# Frontend
cd apps/web
npm run typecheck && npm run lint && npm test && npm run build
```

Tests run against real PostgreSQL, never SQLite, because enum, JSONB and locking behaviour differ.

---

## Project structure

```
pare/
├── apps/
│   ├── api/                       FastAPI backend (Python 3.12)
│   │   ├── app/
│   │   │   ├── ai/                provider adapters, registry, router (retries/fallback), usage recorder
│   │   │   ├── api/               routers (v1) and request dependencies (auth, pagination)
│   │   │   ├── core/              config, DB session, security, errors, logging, middleware
│   │   │   ├── domain/            pure business rules (task state machine)
│   │   │   ├── models/            SQLAlchemy models
│   │   │   ├── repositories/      query building where it is non-trivial (task listing)
│   │   │   ├── schemas/           Pydantic request/response models
│   │   │   ├── services/          business logic; route handlers stay thin (ai_service = AI façade)
│   │   │   ├── cli.py             maintenance commands (master-key generation/rotation/check)
│   │   │   └── main.py            application factory
│   │   ├── alembic/               migrations
│   │   └── tests/                 pytest suite (real PostgreSQL)
│   └── web/                       Next.js 16 frontend (TypeScript, Tailwind v4, shadcn-style UI)
│       ├── app/                   routes: (auth)/login, (auth)/register, (app)/…
│       ├── components/            ui/ primitives and layout/ (shell, page header, placeholders)
│       ├── features/              tasks/, projects/, auth/, ai-providers/ — feature components and hooks
│       ├── hooks/                 shared hooks (auth, debounce)
│       ├── lib/                   API client, endpoint functions, status metadata, utils
│       └── types/                 API types mirroring backend schemas
├── infrastructure/docker/         Dockerfiles for api and web
├── docs/PRD.md                    product requirements (source of truth)
├── docs/AI_PROVIDERS.md           provider architecture, routing, security, key rotation
├── tools/stub-llm/                OpenAI-compatible stub server for manual testing without keys
├── scripts/                       setup-env, start, stop, doctor (PowerShell) + setup-env.sh
├── docker-compose.yml             production-like local stack
├── docker-compose.dev.yml         hot-reload override
└── .env.example
```

**Deviations from the suggested structure**, and why:

- `app/domain/` was added for the task state machine: it has no I/O and is the single place that decides legal status transitions, so later phases (planning, execution) extend it instead of scattering rules across services.
- `apps/web/components/ui/` holds shadcn/ui-style components written into the repo (Button, Card, Dialog, DropdownMenu, …) on Radix primitives, as shadcn intends. They were hand-added rather than generated by the shadcn CLI.
- `docker-compose.dev.yml` is a separate override so the default stack runs built images (reliable on Windows) and hot reload is opt-in.

---

## What's implemented

**API** (`/api/v1`, documented at `/docs`)

| Area | Endpoints |
|---|---|
| Health | `GET /health` (liveness), `GET /health/ready` (checks DB; 503 when down) — also at the root for container health checks |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` |
| Projects | `GET/POST /projects`, `GET/PATCH/DELETE /projects/{id}` (`?detach_tasks=true` to delete a project that has tasks) |
| Research tasks | `GET/POST /tasks` (search `q`, filter `status` (repeatable) and `project_id`, `sort`, pagination), `GET/PATCH/DELETE /tasks/{id}`, `GET /tasks/{id}/status`, `GET /tasks/stats`, `GET /tasks/recent-activity` |
| Settings | `GET /settings` — version, environment, database version and migration revision, feature availability |
| AI providers | `GET /providers/types`, `GET/POST /providers`, `GET/PATCH/DELETE /providers/{id}`, `PUT/DELETE /providers/{id}/key`, `POST /providers/{id}/test`, `GET /providers/{id}/available-models`, `GET/POST /providers/{id}/models`, `PATCH/DELETE /models/{id}`, `GET /model-routes`, `PUT /model-routes/{role}`, `POST /model-routes/{role}/test`, `GET/PUT /routing-policy`, `GET /providers/health`, `GET /usage`, `GET /usage/records` — see [docs/AI_PROVIDERS.md](docs/AI_PROVIDERS.md) |

All errors use one envelope: `{"error": {"code", "message", "details", "request_id"}}`.

**Database tables:** `users`, `projects`, `research_tasks`, `audit_events`, and for AI providers `secrets`, `ai_providers`, `ai_models`, `model_routes`, `ai_routing_policies`, `usage_records` (plus `alembic_version`). UUID keys, timezone-aware timestamps, foreign keys with explicit delete rules, case-insensitive unique email and per-user unique project names, and indexes for the list queries.

**Web screens:** sign in / create account, dashboard (real counts, recent tasks, recent activity, empty state), research list (search, status/project filters, sort, pagination), new task, task detail, edit draft, delete with confirmation, projects list/create/edit/delete, project detail, history (completed/failed/cancelled tasks), settings (theme, backend and database status, system information), AI Providers (add/edit/enable/disable/delete providers, write-only masked keys, models with provider model discovery, connection tests, primary + ordered fallback chain per role, retry/fallback policy, routing test with per-attempt detail, health and usage), and Browser Manager (*Coming soon*). Light and dark themes; responsive with a mobile menu.

### Security in this release

- Passwords hashed with bcrypt (cost 12); login is rate-limited (10/min per IP and email) and returns the same message for unknown email and wrong password.
- Sessions are signed JWTs in an **HttpOnly, SameSite=Lax** cookie; the token never reaches JavaScript. Scripts can use `Authorization: Bearer` with the token from `/auth/login`.
- **CSRF:** state-changing requests that use the cookie must send `X-PARE-CSRF: 1` (cross-origin pages cannot set it without passing CORS), and requests from a non-allowed `Origin` are rejected.
- Host header allow-list (protects against DNS rebinding), strict CORS to the web origin, security headers and a Content-Security-Policy on the web app.
- Every query is scoped to the signed-in user; another user's IDs return 404.
- Ports are bound to `127.0.0.1` so the app is not reachable from your network.
- Logs are JSON with request IDs; values that look like secrets are redacted.
- **AI provider keys** are encrypted with AES-256-GCM envelope encryption under `SECRETS_MASTER_KEY` (kept in `.env`, never in the database), bound to their row and owner, decrypted only for the duration of a call, and never returned by the API — only `••••` plus the last 4 characters. Provider error messages are scrubbed of keys before they are stored or shown.

### Credential encryption

`SECRETS_MASTER_KEY` encrypts every stored API key. Treat it like a password:

- **Back it up separately from the database.** A database backup alone cannot decrypt the keys; the master key alone is useless without the database.
- **If you lose it**, stored keys can't be recovered: re-enter each provider's key (*AI Providers → ⋯ → Replace API key*). Nothing else is affected.
- **To rotate it** without re-entering keys, follow [docs/AI_PROVIDERS.md §4](docs/AI_PROVIDERS.md#rotating-the-master-key) (`python -m app.cli rotate-master-key`).
- Without the key the app still runs; the AI Providers page shows a warning and only keyless local endpoints can be added.

---

## Troubleshooting (Windows)

| Symptom | Fix |
|---|---|
| `docker: command not found` / "Docker is not running" | Start Docker Desktop and wait for *Engine running*. Re-open your terminal after installing. |
| "WSL 2 installation is incomplete" | Admin PowerShell: `wsl --install`, then `wsl --update`, reboot. |
| `Set POSTGRES_PASSWORD in .env` error | Run `scripts\setup-env.ps1`. |
| Port 3000 or 8000 already in use | Stop the other program, or set `WEB_PORT`/`API_PORT` in `.env`. If you change `API_PORT`, also set `PUBLIC_API_URL=http://localhost:<port>` and rebuild: `docker compose up -d --build`. |
| Dashboard shows "Cannot reach the PARE backend" | `docker compose ps` — is `api` healthy? Check `docker compose logs api`. |
| API logs `password authentication failed` | The DB volume was created with an older password. Put the old `POSTGRES_PASSWORD` back in `.env`, or delete all data with `docker compose down -v` and start again. |
| Browser shows CORS errors | Open the app via the same host listed in `CORS_ORIGINS` (`localhost` vs `127.0.0.1` matters). |
| Signed in but immediately signed out | `JWT_SECRET` changed (invalidates sessions) — sign in again. |
| Hot reload doesn't pick up changes (dev stack) | Clone inside WSL, or keep `WATCHPACK_POLLING=true` (already set in the dev override). |
| `exec ... no such file or directory` for scripts in containers | Line endings were converted to CRLF. Run `git config core.autocrlf false` and re-clone; `.gitattributes` keeps LF for container files. |
| Docker uses too much memory | Create `%UserProfile%\.wslconfig` with `[wsl2]` / `memory=6GB` / `processors=4`, then `wsl --shutdown`. |
| AI Providers says "API keys can't be saved yet" | `SECRETS_MASTER_KEY` is missing. Run `scripts\setup-env.ps1`, then `docker compose up -d api`. |
| A provider shows "credential could not be decrypted" | `SECRETS_MASTER_KEY` changed. Restore the old key (or add it to `SECRETS_PREVIOUS_KEYS`), or replace that provider's key. |
| An OpenAI-compatible server on your PC is unreachable from Docker | Use `http://host.docker.internal:<port>/v1` as the base URL, not `localhost`. |
| PowerShell refuses to run scripts | Use `powershell -ExecutionPolicy Bypass -File scripts\start.ps1` as shown, or `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |

---

## Known limitations

- No AI planning, web search, crawling, browser automation, scheduling or exports yet (see the roadmap in `docs/PRD.md` §26).
- AI provider adapters are tested against mocked provider responses; **none has yet been verified against a live provider API** (run `tests/test_live_providers.py` with your keys — see `docs/AI_PROVIDERS.md` §7).
- Budgets and spending caps (PRD §17.3) are not enforced yet; usage cost is an estimate and only for models with prices entered.
- Connection-test rate limiting is in-memory (per API process), like the login limiter.
- Task statuses beyond `draft` can't be reached through the UI yet; the full state machine exists in `app/domain/task_state.py` for the next phases.
- The login rate limiter is in-memory, which is correct for the single API process used locally; multi-process deployments need a shared store.
- No password change or "sign out everywhere" UI yet (the `token_version` column already supports revocation).
- `NEXT_PUBLIC_API_URL` is compiled into the web bundle, so changing the API URL requires rebuilding the web image.
