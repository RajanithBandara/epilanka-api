# File: `database.py`
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables from .env
load_dotenv()

# Get MongoDB URI from environment
MONGODB_URI = os.getenv("MONGODB_URI")

# MongoDB client and database
client = None
db = None
async_client = None
async_db = None

def connect_to_mongodb():
    """Connect to MongoDB Atlas with connection pooling"""
    global client, db
    try:
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=20000,
            socketTimeoutMS=20000,
            maxPoolSize=50,  # Max connections in the pool
            minPoolSize=10,  # Min connections to maintain
            maxIdleTimeMS=60000,  # Close idle connections after 60 seconds
            retryWrites=True,
            w="majority"
        )
        # Test connection
        client.admin.command('ping')
        # Select database
        db = client["epilanka"]
        print("✅ Connected to MongoDB Atlas successfully")
        return db
    except (ConnectionFailure, ServerSelectionTimeoutError) as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        raise

def connect_to_mongodb_async():
    """Create async MongoDB client with proper pooling"""
    global async_client, async_db
    try:
        async_client = AsyncIOMotorClient(
            MONGODB_URI,
            maxPoolSize=50,
            minPoolSize=10,
            maxIdleTimeMS=60000,
            retryWrites=True,
            serverSelectionTimeoutMS=5000,
        )
        async_db = async_client["epilanka"]
        print("✅ Async MongoDB client initialized successfully")
        return async_db
    except Exception as e:
        print(f"❌ Failed to initialize async MongoDB client: {e}")
        raise

def get_database():
    """Get database instance"""
    global db
    if db is None:
        connect_to_mongodb()
    return db

def get_async_database():
    """Get async database instance"""
    global async_db
    if async_db is None:
        connect_to_mongodb_async()
    return async_db

def close_mongodb_connection() -> None:
    """Close MongoDB connection properly"""
    global client, db
    if client is not None:
        try:
            client.close()
            print("✅ MongoDB sync connection closed")
        except Exception as e:
            print(f"❌ Error closing MongoDB sync connection: {e}")
        finally:
            client = None
            db = None

async def close_mongodb_async_connection() -> None:
    """Close async MongoDB connection properly"""
    global async_client, async_db
    if async_client is not None:
        try:
            async_client.close()
            print("✅ MongoDB async connection closed")
        except Exception as e:
            print(f"❌ Error closing MongoDB async connection: {e}")
        finally:
            async_client = None
            async_db = None
