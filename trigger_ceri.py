import asyncio
import sys

from utils.risk_engine import calculate_ceri_scores
from config.db import close_mongodb_connection
from config.postgredb import engine

async def main():
    print("Triggering CERI Calculation...")
    result = await calculate_ceri_scores()
    print("Result:", result)
    
    # Close resources
    close_mongodb_connection()
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
