import asyncio
import os
from collections import Counter
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

async def check():
    client = AsyncIOMotorClient(os.environ.get('MONGO_URL'))
    db = client[os.environ.get('DB_NAME')]
    
    cursor = db.leads.find({}, {'budget': 1, 'configuration': 1, 'possession_timeline': 1, 'lead_score': 1})
    leads = await cursor.to_list(length=None)
    
    budgets = Counter(str(l.get('budget')) for l in leads)
    configs = Counter(str(l.get('configuration')) for l in leads)
    timelines = Counter(str(l.get('possession_timeline')) for l in leads)
    scores = Counter(str(l.get('lead_score')) for l in leads)
    
    print(f'Top Budgets: {budgets.most_common(5)}')
    print(f'Top Configs: {configs.most_common(5)}')
    print(f'Top Timelines: {timelines.most_common(5)}')
    print(f'Top Scores: {scores.most_common(5)}')

    client.close()

asyncio.run(check())
