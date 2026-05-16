# EpiLanka API

<p align="center">
  <strong>A FastAPI backend for disease-surveillance reporting, district analytics, user management, and real-time communication.</strong>
</p>

<p align="center">
  MongoDB • PostgreSQL • Redis • Appwrite • Socket.IO • Pytest
</p>

---

## ✨ Highlights

- **Appwrite authentication** with JWT token passing and `x-api-key` protection for server requests
- **Health report submission** with a 4-layer content filter for links, spam, toxicity, and health relevance
- **District analytics** for recent reports, metadata, historical chart data, and weekly records
- **Socket.IO support** for chat and notifications
- **Redis caching** for expensive read endpoints, with a 7-day default cache TTL
- **Offline-friendly tests** that run with `TESTING=1` to bypass live services

## 🧱 Architecture at a glance

- `main.py` wraps the FastAPI app with Socket.IO and sets up middleware, startup, and shutdown
- `config/db.py` manages MongoDB sync/async connections
- `config/postgredb.py` manages PostgreSQL async/sync engines and session factories
- `controllers/` contains the application logic for reports, users, maps, notifications, and analytics
- `routes/` exposes the FastAPI endpoints
- `utils/` contains auth, Redis, WebSocket, Appwrite, and content-filter utilities

## 🔎 Content filtering pipeline

When users submit report text, the API checks it in this order:

1. **Links / promotional phrases** — blocks URLs and obvious call-to-action spam
2. **Keywords / spam / profanity** — rejects short, repeated, or spammy content
3. **Toxicity scoring** — optional Detoxify check when installed
4. **Health relevance** — optional Groq classifier when `GROQ_API_KEY` is set

The pipeline is optimized to fail fast on cheap checks and skip expensive checks when the text is already clearly valid.

## 🛠️ Tech stack

| Layer | Tools |
|---|---|
| API | FastAPI |
| Realtime | Socket.IO (`python-socketio`) |
| Auth | Appwrite |
| Databases | MongoDB, PostgreSQL |
| Cache | Redis |
| ORM / Validation | SQLAlchemy, Motor, AsyncPG, Pydantic |
| Testing | Pytest, pytest-asyncio |
| Deployment | Uvicorn, Docker, Docker Compose, GitHub Actions |

## ✅ Requirements

- Python 3.12+
- MongoDB
- PostgreSQL
- Redis (optional, but recommended)
- Appwrite project and server API key
- Groq API key for the optional health relevance check
- Docker and Docker Compose (optional)

## 🔐 Environment variables

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
# REDIS_PUBLIC_URL can also be used if your deployment provides that instead

# Appwrite
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_PROJECT_ID=your_project_id
APPWRITE_API_KEY=your_server_api_key

# Optional AI filter
GROQ_API_KEY=your_groq_key
```

## 🚀 Quick start

### 1) Create a virtual environment

```powershell
python -m venv venv
.\venv\Scripts\activate
```

### 2) Install dependencies

```powershell
pip install -r requirements.txt
```

### 3) Run database migrations

```powershell
alembic upgrade head
```

### 4) Start the API

```powershell
uvicorn main:app --reload
```

The ASGI entrypoint is `main:app` because the FastAPI app is wrapped with Socket.IO in `main.py`.

## 🧪 Testing

The test suite is designed to run offline with test-safe fallbacks.

### Run all tests

```powershell
$env:TESTING='1'
python -m pytest tests -q
```

### Visual runners

```powershell
.\test.ps1 quick
.\test.ps1 full
.\test.ps1 report
python scripts/run_tests.py --full
python scripts/run_tests.py --html
```

## 📦 Utility scripts

- `python seed_admin_user.py` — create an admin Appwrite user
- `python seed_officer_user.py` — create an officer Appwrite user
- `python setup_notifications.py` — initialize notification setup

## 📁 Project structure

| Path | Purpose |
|---|---|
| `config/` | MongoDB and PostgreSQL connection helpers |
| `controllers/` | Business logic for reports, users, maps, notifications, and analytics |
| `models/` | SQLAlchemy and Pydantic models |
| `routes/` | FastAPI route definitions |
| `tests/` | Automated tests for endpoints and content filtering |
| `utils/` | Auth, Redis, WebSocket, Appwrite, and content-filter utilities |
| `main.py` | FastAPI entrypoint wrapped with Socket.IO |

## ⚠️ Notes

- API requests require the `x-api-key` header in non-test mode.
- Swagger / ReDoc are disabled in `main.py`.
- If Redis or Groq is not configured, the app falls back gracefully and continues serving requests.

## 📄 License

Add your license here.
