import asyncio
import os
from collections import Counter
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def check():
    client = AsyncIOMotorClient(os.environ.get('MONGO_URL'))
    db = client[os.environ.get('DB_NAME')]
    
    # Fetch all tasks
    cursor = db.tasks.find({}, {'title': 1, 'lead_id': 1, 'id': 1})
    tasks = await cursor.to_list(length=None)
    
    # Check for identical task titles for the same lead
    keys = [f"{t.get('lead_id')}_{t.get('title')}" for t in tasks if t.get('lead_id') and t.get('title')]
    dup_tasks = [k for k, v in Counter(keys).items() if v > 1]
    
    print(f'Total Tasks: {len(tasks)}')
    print(f'Duplicate Tasks (same title for same lead) Count: {len(dup_tasks)}')
    
    if len(dup_tasks) > 0:
        print(f'Sample Dup Tasks: {dup_tasks[:5]}')

    client.close()

asyncio.run(check())
