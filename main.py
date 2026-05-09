import os
from contextlib import asynccontextmanager

import socketio

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware
from starlette.responses import JSONResponse

from config.db import (
    connect_to_mongodb,
    connect_to_mongodb_async,
    close_mongodb_connection,
    close_mongodb_async_connection
)
from config.postgredb import close_postgres_connection
from utils.redis_client import close_redis_connection

from routes.userRoute import router as user_router
from routes.diseaseRoute import router as disease_router
from routes.mapRoute import router as map_router
from routes.user_reportRoute import router as user_report_router
from routes.reportRoute import router as report_router
from routes.adminRoutes import router as admin_report_router
from routes.officerRoute import router as officer_router
from routes.notificationRoute import router as notification_router
from routes.chatRoute import router as chat_router
from utils.websocket_manager import sio

load_dotenv()

API_KEY = os.getenv("API_SECRET_KEY")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting up...")
    connect_to_mongodb()  # Sync MongoDB connection
    connect_to_mongodb_async()  # Async MongoDB connection
    print("✅ All connections initialized")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down...")
    close_mongodb_connection()  # Close sync MongoDB
    await close_mongodb_async_connection()  # Close async MongoDB
    await close_postgres_connection()  # Close PostgreSQL
    await close_redis_connection()  # Close Redis client
    print("✅ All connections closed")


_frontend = os.getenv("FRONTEND_URL", "http://localhost:3000")
_allowed_origins = [
    _frontend,
    "http://localhost:3000",
    "http://localhost:3001",
    "https://epilanka.app",
    "https://www.epilanka.app",
]

fastapi_app = FastAPI(
    title="Epilanka API",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    middleware=[
        Middleware(
            CORSMiddleware,  # type: ignore[arg-type]
            allow_origins=_allowed_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ],
)

@fastapi_app.middleware("http")
async def api_key_protect(request: Request, call_next):
    if os.getenv("TESTING") == "1" or os.getenv("PYTEST_CURRENT_TEST"):
        return await call_next(request)

    # Allow Swagger docs
    if request.url.path in ["/docs", "/openapi.json", "/redoc"]:
        return await call_next(request)

    # CORS preflight — must pass through so CORSMiddleware can respond
    if request.method == "OPTIONS":
        return await call_next(request)

    # Allow Socket.IO handshake and polling transport requests.
    if request.url.path.startswith("/socket.io"):
        return await call_next(request)

    client_key = request.headers.get("x-api-key")

    if not client_key:
        return JSONResponse(
            status_code=401,
            content={"detail": "API key is required."}
        )

    if client_key != API_KEY:
        return JSONResponse(
            status_code=403,
            content={"detail": "Invalid API key. Access denied."}
        )

    return await call_next(request)

# Route Includes
fastapi_app.include_router(user_router)
fastapi_app.include_router(disease_router)
fastapi_app.include_router(map_router)
fastapi_app.include_router(user_report_router)
fastapi_app.include_router(report_router)
fastapi_app.include_router(admin_report_router)
fastapi_app.include_router(officer_router)
fastapi_app.include_router(notification_router)
fastapi_app.include_router(chat_router)

app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app, socketio_path="socket.io")

