import os
import asyncio, motor.motor_asyncio
import json
from dotenv import load_dotenv

load_dotenv()
MONGO_URL = os.getenv('MONGO_URL', 'mongodb://localhost:27017/')

async def main():
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URL)
    db = client['arihant_crm']
    
    _INVALID_PROJECT_PART_REGEX = r'(?i)^\s*(unknown|na|n/a|others?|null|sold\s*out\s*enquiry|homepage\s*enquiry|all\s*projects?|commercial\s*space|upcoming\s*commercial)\s*$'
    
    pipeline = [
        {'$match': {}},
        {
            '$addFields': {
                '_project_parts': {
                    '$filter': {
                        'input': {
                            '$map': {
                                'input': {'$split': [{'$ifNull': ['$project', '']}, ';']},
                                'as': 'p',
                                'in': {'$trim': {'input': '$$p'}}
                            }
                        },
                        'as': 'p',
                        'cond': {
                            '$and': [
                                {'$gt': [{'$strLenCP': '$$p'}, 0]},
                                {'$not': {'$regexMatch': {'input': '$$p', 'regex': _INVALID_PROJECT_PART_REGEX}}}
                            ]
                        }
                    }
                }
            }
        },
        {'$unwind': '$_project_parts'},
        {'$group': {'_id': '$_project_parts', 'count': {'$sum': 1}}},
        {'$sort': {'count': -1}},
        {'$limit': 50}
    ]
    
    docs = await db.leads.aggregate(pipeline).to_list(50)
    print(f'Count from DB pipeline: {len(docs)}')
    for d in docs[:10]:
        print(f"{d.get('_id')}: {d.get('count')}")

asyncio.run(main())
