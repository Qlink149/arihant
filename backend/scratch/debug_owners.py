import csv
from collections import Counter

file_path = r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv'

def analyze_debug():
    owners = []
    try:
        with open(file_path, mode='r', encoding='latin-1') as f:
            reader = csv.reader(f)
            header = next(reader)
            # Find index of 'Sales owner'
            try:
                idx = header.index('Sales owner')
            except ValueError:
                print("Could not find Sales owner in header")
                return
                
            for row in reader:
                if len(row) > idx:
                    owners.append(row[idx].strip())
    except Exception as e:
        print(f"Error: {e}")
        return

    counts = Counter(owners)
    unique_owners = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    print(f"Unique owners found: {len(counts)}")
    for i, (owner, count) in enumerate(unique_owners):
        print(f"'{owner}': {count}")

analyze_debug()
