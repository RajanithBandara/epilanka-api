# Epilanka API

Epilanka API is a robust backend service built with FastAPI, designed to manage disease-related reports, user profiles, and geographical mapping for the Epilanka platform. It utilizes a multi-database architecture and integrates with various modern services for authentication, storage, real-time communication, and AI-driven features.

## Features

- **User Management**: Profile management synchronized with Appwrite authentication.
- **Disease Data CRUD**: Manage disease information including names, descriptions, and thresholds.
- **Reporting System**: Submit and process disease occurrences with image support (stored in R2).
- **Geographical Mapping**: Coordinate-based location services and population density data.
- **Real-time Notifications**: Live updates via Socket.IO for critical alerts and chat.
- **AI Integration**: Content filtering and data extraction powered by Gemini and Groq.
- **Security**: 
  - `x-api-key` protection for all endpoints.
  - JWT-based authorization (via Appwrite).
  - CORS middleware for secure frontend integration.
- **Database Migrations**: PostgreSQL schema management using Alembic.
- **Caching**: Performance optimization using Redis for heavy read operations.
- **Containerization**: Fully dockerized for consistent development and deployment.

## Technologies Used

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Real-time**: [python-socketio](https://python-socketio.readthedocs.io/) (Socket.IO)
- **AI/ML**: [Google Gemini](https://ai.google.dev/), [Groq](https://groq.com/), [Detoxify](https://github.com/unitaryai/detoxify)
- **Databases**: 
  - [PostgreSQL](https://www.postgresql.org/) (SQLAlchemy & asyncpg) — Relational data & reporting.
  - [MongoDB](https://www.mongodb.com/) (Motor for async) — Profile & unstructured data.
  - [Redis](https://redis.io/) — Read-through caching.
- **Authentication**: [Appwrite](https://appwrite.io/)
- **Storage**: [Cloudflare R2](https://www.cloudflare.com/products/r2/) (S3-compatible) — Image uploads.
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Testing**: [Pytest](https://docs.pytest.org/)
- **Containerization**: Docker & Docker Compose

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL instance
- MongoDB instance (local or Atlas)
- Redis instance
- Appwrite Project (for authentication)
- Cloudflare R2 Bucket (for image storage)
- Gemini & Groq API Keys (for AI features)
- Docker & Docker Compose (optional)

### Environment Variables

Create a `.env` file in the root directory based on the following template:

```env
# General
API_SECRET_KEY=your_shared_api_key
FRONTEND_URL=http://localhost:3000
JWT_SECRET=your_jwt_secret

# PostgreSQL
POSTGRE_HOST=localhost
POSTGRE_PORT=5432
POSTGRE_DBNAME=epilanka
POSTGRE_USER=postgres
POSTGRE_PASSWORD=your_password

# MongoDB
MONGODB_URI=mongodb+srv://...

# Redis
REDIS_PUBLIC_URL=redis://...

# Appwrite
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_PROJECT_ID=your_project_id
APPWRITE_API_KEY=your_server_api_key
APPWRITE_PROJECT_NAME=epilanka
APPWRITE_CHAT_DB_ID=...
APPWRITE_CHAT_COLLECTION_ID=...

# Cloudflare R2
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY=your_access_key
R2_SECRET_KEY=your_secret_key
R2_BUCKET_NAME=epilanka
R2_PUBLIC_BASE_URL=https://...

# AI APIs
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
```

### Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd epilanka-api
   ```

2. **Setup Virtual Environment**:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Linux/macOS:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Migrations**:
   ```bash
   alembic upgrade head
   ```

5. **Run the Application**:
   ```bash
   uvicorn main:app --reload
   ```
   The API will be available at `http://localhost:8000`.

### Using Docker

```bash
docker-compose up --build
```

## Project Structure

- `alembic/`: Database migration scripts and configuration.
- `config/`: Database connection managers (MongoDB, PostgreSQL).
- `controllers/`: Business logic and database operations.
- `models/`: SQLAlchemy (Postgres) and Pydantic models.
- `routes/`: FastAPI route definitions.
- `schemas/`: Pydantic schemas for data validation.
- `scripts/`: Helper scripts including the test runner.
- `tests/`: Pytest test suite.
- `utils/`: Utilities for Auth, Storage, Redis, WebSockets, and AI filters.
- `main.py`: Entry point wrapping FastAPI with Socket.IO.

## Scripts & Commands

- **Seeding**:
  - `python seed_admin_user.py`: Populate initial admin user data.
  - `python seed_officer_user.py`: Populate initial officer user data.
- **Setup**:
  - `python setup_notifications.py`: Initialize notification templates/settings.
- **Testing**:
  - `test.bat [quick|full|report|coverage|watch]`: Windows test runner.
  - `python scripts/run_tests.py [--full] [--html] [--coverage]`: Platform-independent test runner.
  - `pytest`: Run tests directly using the configuration in `pytest.ini`.

## API Documentation

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

*Note: All requests require the `x-api-key` header matching your `API_SECRET_KEY`.*

## License

[TODO: Add License Information]
