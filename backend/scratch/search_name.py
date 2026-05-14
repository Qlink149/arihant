import csv
from collections import Counter

files = [
    r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv',
    r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\Contacts.csv'
]

target = "Akshata"

def search_name(file_path):
    print(f"\nSearching in: {file_path}")
    found_names = set()
    total_matches = 0
    try:
        with open(file_path, mode='r', encoding='latin-1') as f:
            reader = csv.DictReader(f)
            for row in reader:
                owner = row.get('Sales owner') or row.get('Owner') or ""
                if target.lower() in owner.lower():
                    found_names.add(owner.strip())
                    total_matches += 1
    except Exception as e:
        print(f"Error: {e}")
        return

    if found_names:
        print(f"MATCHES FOUND:")
        for name in found_names:
            print(f" - {name}")
        print(f"Total leads for this name: {total_matches}")
    else:
        print(f"No names containing '{target}' found.")

for f in files:
    search_name(f)
