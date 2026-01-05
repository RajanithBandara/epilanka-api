# File: `database.py`
import os
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from dotenv import load_dotenv
from motor.motor_asyncio import AsyncIOMotorClient

# Load environment variables from .env
load_dotenv()

# Get MongoDB URI from environment
MONGODB_URI = os.getenv("MONGODB_URI")

# MongoDB client and database
client = None
db = None

def connect_to_mongodb():
    """Connect to MongoDB Atlas"""
    global client, db
    try:
        client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=20000,
            socketTimeoutMS=20000
        )
        # Test connection
        client.admin.command('ping')
        # Select database (replace 'your_database_name' with your actual database name)
        db = client["epilanka"]
        print("✅ Connected to MongoDB Atlas successfully")
        return db
    except ConnectionFailure as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        raise

def get_database():
    """Get database instance"""
    global db
    if db is None:
        connect_to_mongodb()
    return db

def get_async_database():
    return AsyncIOMotorClient(MONGODB_URI).epilanka

def close_mongodb_connection():
    """Close MongoDB connection"""
    global client
    if client:
        client.close()
        print("✅ MongoDB connection closed")
