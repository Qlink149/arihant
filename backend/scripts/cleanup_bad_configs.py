import asyncio
import os
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def run_cleanup():
    client = AsyncIOMotorClient(os.environ.get('MONGO_URL'))
    db = client[os.environ.get('DB_NAME')]
    
    # Update leads where configuration is 'yes', 'may_be', or 'no'
    result = await db.leads.update_many(
        {'configuration': {'$in': ['yes', 'may_be', 'no', 'yes ', 'may_be ']}},
        {'$set': {'configuration': None}}
    )
    
    print(f"Cleanup complete. Modified {result.modified_count} leads with bad configurations.")
    client.close()

if __name__ == '__main__':
    asyncio.run(run_cleanup())
