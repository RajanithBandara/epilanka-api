import asyncio
import os
import sys

# Add the project root to sys.path so utils can be imported
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils.redis_client import cache_delete_pattern

async def main():
    await cache_delete_pattern("reports:metadata:*")
    await cache_delete_pattern("officer:analytics:*")
    print("Cache cleared")

if __name__ == "__main__":
    asyncio.run(main())
