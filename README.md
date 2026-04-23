# Epilanka API

Epilanka API is a robust backend service built with FastAPI, designed to manage disease-related reports, user profiles, and geographical mapping for the Epilanka platform. It utilizes a multi-database architecture and integrates with various modern services for authentication, storage, and real-time communication.

## Features

- **User Management**: Profile management synchronized with Appwrite authentication.
- **Disease Data CRUD**: Manage disease information including names, descriptions, and thresholds.
- **Reporting System**: Submit and process disease occurrences with image support (stored in R2).
- **Geographical Mapping**: Coordinate-based location services and population density data.
- **Real-time Notifications**: Live updates via Socket.IO for critical alerts.
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
- **Databases**: 
  - [MongoDB](https://www.mongodb.com/) (Pymongo & Motor for async) — Profile & unstructured data.
  - [PostgreSQL](https://www.postgresql.org/) (SQLAlchemy & asyncpg) — Relational data & reporting.
  - [Redis](https://redis.io/) — Read-through caching.
- **Authentication**: [Appwrite](https://appwrite.io/)
- **Storage**: [Cloudflare R2](https://www.cloudflare.com/products/r2/) (S3-compatible) — Image uploads.
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Containerization**: Docker & Docker Compose

## Getting Started

### Prerequisites

- Python 3.9+
- MongoDB instance (local or Atlas)
- PostgreSQL instance
- Redis instance (optional, for caching)
- Appwrite Project (for authentication)
- Cloudflare R2 Bucket (for image storage)
- Docker & Docker Compose (optional)

### Environment Variables

Create a `.env` file in the root directory and configure the following:

```env
# General
API_SECRET_KEY=your_shared_api_key
FRONTEND_URL=http://localhost:3000

# MongoDB
MONGODB_URI=mongodb+srv://...

# PostgreSQL
POSTGRE_HOST=localhost
POSTGRE_PORT=5432
POSTGRE_DBNAME=epilanka
POSTGRE_USER=postgres
POSTGRE_PASSWORD=your_password

# Redis (Optional)
REDIS_URL=redis://localhost:6379/0

# Appwrite
APPWRITE_ENDPOINT=https://cloud.appwrite.io/v1
APPWRITE_PROJECT_ID=your_project_id
APPWRITE_API_KEY=your_server_api_key

# Cloudflare R2
R2_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY=your_access_key
R2_SECRET_KEY=your_secret_key
R2_BUCKET_NAME=epilanka-uploads
R2_PUBLIC_BASE_URL=https://pub-your-id.r2.dev
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
- `utils/`: Utilities for Auth (Appwrite), Storage (R2), Redis, and WebSockets.
- `main.py`: Entry point wrapping FastAPI with Socket.IO.

## Helper Scripts

- `seed_admin_user.py`: Populate initial admin user data.
- `seed_officer_user.py`: Populate initial officer user data.
- `setup_notifications.py`: Initialize notification templates/settings.
- `test_notifications.py`: Script to test WebSocket notifications.

## API Documentation

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

*Note: All requests require the `x-api-key` header matching your `API_SECRET_KEY`.*

## License

[TODO: Add License Information]
