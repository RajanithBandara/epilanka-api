import os
from appwrite.client import Client
from appwrite.services.account import Account
from appwrite.services.users import Users

APPWRITE_ENDPOINT = os.getenv("APPWRITE_ENDPOINT", "https://sgp.cloud.appwrite.io/v1")
APPWRITE_PROJECT_ID = os.getenv("APPWRITE_PROJECT_ID", "")
APPWRITE_API_KEY = os.getenv("APPWRITE_API_KEY", "")


def get_server_client() -> Client:
    """Appwrite client with full server-side API key (for admin operations)."""
    client = Client()
    client.set_endpoint(APPWRITE_ENDPOINT)
    client.set_project(APPWRITE_PROJECT_ID)
    client.set_key(APPWRITE_API_KEY)
    return client


def get_jwt_client(jwt: str) -> Client:
    """Appwrite client scoped to a specific user JWT (for token verification)."""
    client = Client()
    client.set_endpoint(APPWRITE_ENDPOINT)
    client.set_project(APPWRITE_PROJECT_ID)
    client.set_jwt(jwt)
    return client


def get_account_service(jwt: str) -> Account:
    """Account service authenticated as the JWT bearer."""
    return Account(get_jwt_client(jwt))


def get_users_service() -> Users:
    """Server-side Users service (requires API key)."""
    return Users(get_server_client())
