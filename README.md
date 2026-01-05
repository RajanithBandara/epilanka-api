# Epilanka API

Epilanka API is a robust backend service built with FastAPI, designed to manage disease-related reports, user authentication, and geographical mapping for the Epilanka platform. It utilizes a dual-database system (MongoDB and PostgreSQL) to ensure efficient data management and scalability.

## Features

- **User Management**: Secure registration, login, and profile editing with JWT-based authentication and Argon2 password hashing.
- **Disease Data CRUD**: Manage disease information including names and descriptions.
- **Reporting System**: Submit and process user reports related to disease occurrences.
- **Geographical Mapping**: Fetch nearest areas/locations based on coordinates.
- **Security**: 
  - API Key protection for all endpoints (via `x-api-key` header).
  - CORS middleware for frontend integration.
  - JWT token-based authentication for user-specific operations.
- **Database Migrations**: PostgreSQL schema management using Alembic.
- **Containerization**: Fully dockerized for easy deployment.

## Technologies Used

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/)
- **Databases**: 
  - [MongoDB](https://www.mongodb.com/) (using Pymongo)
  - [PostgreSQL](https://www.postgresql.org/) (using SQLAlchemy & asyncpg)
- **Security**: 
  - [Argon2](https://argon2-cffi.readthedocs.io/) (Password Hashing)
  - [PyJWT](https://pyjwt.readthedocs.io/) (Token Management)
- **Migrations**: [Alembic](https://alembic.sqlalchemy.org/)
- **Containerization**: Docker & Docker Compose

## Getting Started

### Prerequisites

- Python 3.9+
- MongoDB instance (local or Atlas)
- PostgreSQL instance
- Docker & Docker Compose (optional)

### Environment Variables

Create a `.env` file in the root directory and configure the following variables:

```env
# General
API_SECRET_KEY=your_api_key_here
JWT_SECRET=your_jwt_secret_here
FRONTEND_URL=http://localhost:3000

# MongoDB
MONGODB_URI=mongodb://localhost:27017/epilanka

# PostgreSQL
POSTGRE_HOST=localhost
POSTGRE_PORT=5432
POSTGRE_DBNAME=epilanka
POSTGRE_USER=postgres
POSTGRE_PASSWORD=your_password
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
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Run Migrations** (for PostgreSQL):
   ```bash
   alembic upgrade head
   ```

5. **Run the Application**:
   ```bash
   uvicorn main:app --reload
   ```
   The API will be available at `http://localhost:8000`.

### Using Docker

You can run the entire stack (API + MongoDB) using Docker Compose:

```bash
docker-compose up --build
```

## API Documentation

Once the server is running, you can access the interactive API documentation:
- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Authentication Note
All API requests (except for docs) require an `x-api-key` header for authentication.

## API Endpoints Summary

| Tag | Method | Endpoint | Description |
| --- | --- | --- | --- |
| **Users** | POST | `/users/register` | Register a new user |
| | POST | `/users/login` | User login (returns JWT) |
| | POST | `/users/edit` | Edit user profile |
| **Diseases** | GET | `/diseases/list` | List all diseases |
| | POST | `/diseases/add` | Add a new disease |
| | POST | `/diseases/update/{id}`| Update disease details |
| | DELETE | `/diseases/delete/{id}`| Remove a disease |
| **Map** | GET | `/map/nearestlocation` | Get nearest location by coordinates |
| **Reports** | POST | `/user_reports/submit` | Submit a disease report |

## Project Structure

```text
├── alembic/            # Database migrations
├── config/             # DB configurations (Mongo & Postgres)
├── controllers/        # Business logic
├── models/             # Pydantic and SQLAlchemy models
├── routes/             # API route definitions
├── utils/              # Utility functions (JWT, etc.)
├── main.py             # Application entry point
├── requirements.txt    # Dependencies
└── docker-compose.yml  # Docker orchestration
```
