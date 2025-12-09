import os
from contextlib import asynccontextmanager
from os import close

from flask.cli import load_dotenv

load_dotenv()

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from config.db import connect_to_mongodb, close_mongodb_connection

from routes.userRoute import router as user_router
from routes.diseaseRoute import router as disease_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    connect_to_mongodb()
    yield
    close_mongodb_connection()

app = FastAPI(lifespan=lifespan)

app = FastAPI(title="Epilanka API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("FRONTEND_URL")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(user_router)
app.include_router(disease_router)
