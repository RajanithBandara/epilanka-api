import json
import logging
import os
from typing import Any

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# 7 days cache window for heavy read endpoints.
DEFAULT_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

_redis_client: Redis | None = None


def _build_redis_url() -> str | None:
    # Prefer REDIS_URL, fallback to REDIS_PUBLIC_URL for current deployment setup.
    raw = (os.getenv("REDIS_URL") or os.getenv("REDIS_PUBLIC_URL") or "").strip()
    if not raw:
        return None

    if "://" in raw:
        return raw

    return f"redis://{raw}"


def get_redis() -> Redis | None:
    global _redis_client

    if _redis_client is not None:
        return _redis_client

    redis_url = _build_redis_url()
    if not redis_url:
        return None

    _redis_client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=60,
        socket_timeout=60,
        retry_on_timeout=True,
        socket_keepalive=True,
        health_check_interval=30,
    )
    return _redis_client


async def cache_get_json(key: str) -> Any | None:
    client = get_redis()
    if client is None:
        return None

    try:
        raw = await client.get(key)
        if not raw:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis cache read failed for key %s: %s", key, exc)
        return None


async def cache_set_json(key: str, value: Any, ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS) -> bool:
    client = get_redis()
    if client is None:
        return False

    try:
        payload = json.dumps(value, default=str)
        await client.set(key, payload, ex=ttl_seconds)
        return True
    except Exception as exc:
        logger.warning("Redis cache write failed for key %s: %s", key, exc)
        return False


async def cache_delete_pattern(pattern: str) -> int:
    client = get_redis()
    if client is None:
        return 0

    deleted = 0
    try:
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=200)
            if keys:
                deleted += int(await client.delete(*keys))
            if cursor == 0:
                break
    except Exception as exc:
        logger.warning("Redis cache delete failed for pattern %s: %s", pattern, exc)
    return deleted


async def close_redis_connection() -> None:
    global _redis_client

    if _redis_client is None:
        return

    try:
        await _redis_client.aclose()
    except Exception as exc:
        logger.warning("Redis close failed: %s", exc)
    finally:
        _redis_client = None


