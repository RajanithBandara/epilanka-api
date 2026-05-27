# EpiLanka API

<p align="center">
  <strong>Backend service for community-driven disease surveillance, district risk scoring, and public-health analytics in Sri Lanka.</strong>
</p>

<p align="center">
  FastAPI · MongoDB · PostgreSQL · Redis · Socket.IO · Appwrite · Alembic · Docker
</p>

---

## Overview

EpiLanka API powers the EpiWatch Lanka platform. It accepts disease reports from citizens and officers, runs them through a multi-layer content filter, fuses them with official historical records and rainfall data, then produces a per-district **Community Epidemic Risk Index (CERI)** score that is consumed by the web and mobile clients. The service also handles user management, real-time chat and notifications, article publishing, and admin/officer dashboards.

## Features

- **Citizen, officer, and admin roles** backed by Appwrite authentication with JWT verification and an `x-api-key` gate for server-to-server calls.
- **Health reporting** with a 4-layer content filter — regex link blocking, spam/profanity keywords, Detoxify toxicity scoring, and an optional Groq health-relevance classifier.
- **Community validation** via vote / unvote endpoints that feed credibility weights into the risk engine.
- **CERI risk engine** that scores every disease × district × week using report density, vote credibility, and temporal urgency, then classifies the result as `low` / `moderate` / `high` / `critical`.
- **Outbreak thresholds** computed from historical weekly records, editable per disease and district, with one-click recompute.
- **Rainfall ingestion** — sync external rainfall data, list it, and edit per-district values.
- **District analytics** — recent reports, metadata, historical chart series, weekly aggregates, and officer-uploaded records.
- **Articles** — officer-authored articles with public listing, summaries, and AI-driven analysis endpoints.
- **Real-time** chat history and notification delivery over Socket.IO.
- **Cached read paths** — admin and officer analytics are refreshed in the background and served from Redis.
- **Offline-safe tests** — set `TESTING=1` and the app and its tests run without MongoDB, Postgres, Redis, Appwrite, or Groq.

## Architecture

```
main.py                FastAPI app + Socket.IO ASGI wrapper, CORS, x-api-key middleware, lifespan
config/
  db.py                MongoDB sync + async clients
  postgredb.py         PostgreSQL async/sync engines and session factories
controllers/           Business logic (reports, users, maps, notifications, articles, rainfall, …)
routes/                FastAPI routers, one per domain
models/                SQLAlchemy and Pydantic models
schemas/               Pydantic request/response schemas
utils/
  appwrite_*.py        Appwrite auth + admin client
  auth_deps.py         FastAPI dependency injection for current user / role
  jwtutils.py          JWT helpers
  content_filter.py    4-layer report-text filter
  redis_client.py      Async Redis client
  websocket_manager.py Socket.IO server instance
  risk_engine.py       CERI calculator
  risk_scheduler.py    Periodic CERI refresh (every 6 h)
  admin_analytics_cache.py    Admin dashboard cache + refresher
  officer_analytics_cache.py  Officer dashboard cache + refresher
  cloudflareStorage.py, r2_clients.py   Object storage for article + profile media
alembic/               Postgres migrations
scripts/               One-off scripts (run_tests, ensure_indexes, generate_historical_ceri)
tests/                 Pytest suite with offline fallbacks
trigger_ceri.py        Manual CERI run entrypoint
```

The ASGI entrypoint is `main:app`, which is a `socketio.ASGIApp` wrapping the FastAPI instance — Socket.IO is mounted at `/socket.io` and the API key middleware lets that path through unauthenticated so the WebSocket handshake works.

## API surface

All routes are mounted directly under the root (no `/api` prefix).

| Prefix | Purpose |
|---|---|
| `/users` | Appwrite-synced user profile, settings, profile picture |
| `/diseases` | Disease catalog CRUD |
| `/map` | Locations, nearest-location lookup, district listing |
| `/reports` | Public read endpoints — locations, metadata, historical chart, weekly records, risk scores, CERI history, manual recompute |
| `/user_reports` | Citizen submit / update / delete / vote / unvote |
| `/officer` | Officer dashboard — disease CRUD, reports CRUD, bulk + file upload, thresholds, history pattern, analytics, settings, moderation |
| `/admin` | Admin dashboard — admin and officer management, user moderation, historical data, diseases, districts, notifications, population |
| `/rainfall` | Sync, list, and edit per-district rainfall data |
| `/articles` | Officer-authored articles + public reads + AI summaries / analysis |
| `/chat` | Chat history CRUD, message append, disease-aware context |
| `/notifications` | Notification list, unread count, mark-read, delete |
| `/socket.io` | Socket.IO transport for chat and live notifications |

## CERI — risk scoring

`utils/risk_engine.py` computes, for each (disease, district, ISO week):

```
CERI = DSM × (0.45·RD + 0.35·VC + 0.20·TU)
```

- **DSM** — Disease Severity Multiplier from AI-extracted severity and confidence
- **RD** — Report Density (confidence-weighted reports per active user)
- **VC** — Vote Credibility (community validation)
- **TU** — Temporal Urgency (week-over-week growth)

The score is bucketed into `low (0–15)`, `moderate (16–40)`, `high (41–65)`, `critical (66–100)`. The scheduler in `utils/risk_scheduler.py` runs CERI immediately on startup, then every 6 hours. `scripts/generate_historical_ceri.py` backfills past weeks, and `trigger_ceri.py` runs a single calculation on demand.

## Content filter

`utils/content_filter.py` runs every citizen report through:

1. **Regex link & phrase detection** (< 1 ms) — blocks URLs, bare domains, URL shorteners, and obvious call-to-action spam.
2. **Spam, profanity, keyword detection** (< 5 ms) — short / repeated / spammy text.
3. **Detoxify toxicity scoring** (50–200 ms, optional) — skipped if the model isn't installed.
4. **Groq health-relevance classifier** (500–1500 ms, optional) — requires `GROQ_API_KEY`.

Layers 1–2 fail with a user-friendly `ValueError`. Layers 3–4 fail silently so the API never goes down because an ML dependency is missing.

## Requirements

- Python 3.12+
- MongoDB (local or Atlas)
- PostgreSQL 14+
- Redis (recommended; the app degrades gracefully without it)
- Appwrite project + server API key
- Optional: Groq API key (health-relevance filter), Cloudflare R2 credentials (media uploads)
- Optional: Docker + Docker Compose

## Environment variables

Create a `.env` file in the project root:

```env
# App security
API_SECRET_KEY=your_shared_api_key
FRONTEND_URL=http://localhost:3000

# PostgreSQL
POSTGRE_HOST=localhost
POSTGRE_PORT=5432
POSTGRE_DBNAME=epilanka
POSTGRE_USER=postgres
POSTGRE_PASSWORD=your_password

# MongoDB
MONGODB_URI=mongodb://127.0.0.1:27017/epilanka

# Redis
REDIS_URL=redis://localhost:6379/0
# REDIS_PUBLIC_URL is also recognised if your host provides it

# Appwrite
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_PROJECT_ID=your_project_id
APPWRITE_API_KEY=your_server_api_key

# Optional AI / storage
GROQ_API_KEY=your_groq_key
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
```

## Quick start

```powershell
# 1. Virtual environment
python -m venv venv
.\venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run Postgres migrations
alembic upgrade head

# 4. (Optional) Create MongoDB indexes
python scripts/ensure_indexes.py

# 5. Run the API
uvicorn main:app --reload
```

The server listens on `http://localhost:8000`. Swagger and ReDoc are intentionally disabled in `main.py`.

## Docker

A single-service Docker image and a Compose file that also starts MongoDB are included:

```powershell
docker compose up --build
```

The API will be available at `http://localhost:8000` and MongoDB at `localhost:27017`.

## Database migrations

PostgreSQL schema is managed with Alembic:

```powershell
alembic revision --autogenerate -m "describe change"
alembic upgrade head
alembic downgrade -1
```

Existing migrations cover the disease and district catalog, weekly historical records, rainfall data, per-district population, threshold value columns, an `actual_count` column on reports, and the merge between the risk and reports heads.

## Background services

Started inside the FastAPI lifespan when not in testing mode:

- `start_admin_analytics_background_service()` — refreshes admin dashboard cache.
- `start_officer_analytics_background_service()` — refreshes officer dashboard cache.
- `start_risk_calculation_service()` — runs CERI immediately, then every 6 hours.

All three are stopped cleanly on shutdown, along with MongoDB, PostgreSQL, and Redis connections.

## Testing

The test suite runs offline. Set `TESTING=1` to bypass the API-key middleware and any service that would otherwise need real credentials.

```powershell
$env:TESTING='1'
python -m pytest tests -q
```

Convenience runner with HTML reports and optional coverage:

```powershell
python scripts/run_tests.py            # quick (skips slow marker)
python scripts/run_tests.py --full     # everything
python scripts/run_tests.py --html     # writes reports/pytest_report.html
python scripts/run_tests.py --coverage # coverage over controllers/routes/utils/models
```

The suite covers admin, officer, user, report, user-report, notification, chat, content-filter, and domain endpoints.

## Authentication & authorization

- Every non-test request must include `x-api-key: <API_SECRET_KEY>`. CORS preflight (`OPTIONS`) and the `/socket.io` handshake are exempted.
- User identity comes from an Appwrite JWT — `utils/appwrite_auth.py` verifies it and `utils/auth_deps.py` exposes FastAPI dependencies for current user, role, and admin/officer checks.
- Roles enforced today: `user`, `officer`, `admin`. Officer and admin routes reject other roles at the dependency layer.

## Project layout (top-level)

| Path | Purpose |
|---|---|
| `main.py` | ASGI entrypoint — FastAPI wrapped with Socket.IO, middleware, lifespan |
| `config/` | MongoDB and PostgreSQL connection helpers |
| `controllers/` | Per-domain business logic |
| `routes/` | FastAPI routers per domain |
| `models/` | SQLAlchemy + Pydantic models |
| `schemas/` | Pydantic request/response schemas |
| `utils/` | Auth, content filter, Redis, WebSocket, risk engine + scheduler, analytics caches, storage |
| `alembic/` | PostgreSQL migrations |
| `scripts/` | Test runner, index creation, historical CERI backfill |
| `tests/` | Pytest suite with offline fallbacks |
| `Dockerfile`, `docker-compose.yml` | Container build + local MongoDB stack |

## Notes

- API requests outside the test environment require `x-api-key`.
- `/docs` and `/redoc` are disabled by design — the API is consumed by trusted first-party clients.
- The app degrades gracefully: if Redis, Detoxify, or Groq are unavailable, the affected feature is skipped and the rest of the API keeps serving.

## License

Add your license here.
