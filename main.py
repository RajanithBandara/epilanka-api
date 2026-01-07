import os
from contextlib import asynccontextmanager

from flask.cli import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request, HTTPException
from starlette.middleware.cors import CORSMiddleware

from config.db import connect_to_mongodb, close_mongodb_connection

from routes.userRoute import router as user_router
from routes.diseaseRoute import router as disease_router
from routes.mapRoute import router as map_router
from routes.user_reportRoute import router as user_report_router
from routes.reportRoute import router as report_router

API_KEY = os.getenv("API_SECRET_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    connect_to_mongodb()
    yield
    close_mongodb_connection()

app = FastAPI(title="Epilanka API", lifespan=lifespan)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def api_key_protect(request: Request, call_next):
    # Allow docs and health check endpoints
    if request.url.path in ["/docs", "/openapi.json", "/redoc"]:
        return await call_next(request)

    # Get API key from request header
    client_key = request.headers.get("x-api-key")

    # Reject if no API key is provided
    if not client_key:
        raise HTTPException(
            status_code=401,
            detail="API key is required. Please provide 'x-api-key' header."
        )

    # Reject if API key is invalid
    if client_key != API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid API key. Access denied."
        )

    return await call_next(request)

# Route Includes
app.include_router(user_router)
app.include_router(disease_router)
app.include_router(map_router)
app.include_router(user_report_router)
app.include_router(report_router)
