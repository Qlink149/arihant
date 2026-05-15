import asyncio
import os
import sys
import csv

# Add backend to path
sys.path.append(os.path.join(os.getcwd(), "backend"))

from crm.core.state import db

async def check():
    print("Fetching a few leads with None project...")
    leads = await db.leads.find({"project": None}).to_list(5)
    for l in leads:
        lead_id = l.get("id")
        ext_id = l.get("external_id")
        print(f"Checking DB Lead ID: {lead_id}, External ID: {ext_id}")
        
        # Check in CSV
        csv_path = r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv'
        found = False
        try:
            with open(csv_path, mode='r', encoding='latin-1') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get('Id') == str(ext_id):
                        print(f"  Found in CSV! Project: '{row.get('Project')}'")
                        found = True
                        break
        except Exception as e:
            print(f"  Error reading CSV: {e}")
        
        if not found:
            print("  Not found in CSV by External ID.")

if __name__ == "__main__":
    asyncio.run(check())
