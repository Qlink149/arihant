import csv
from collections import Counter

file_path = r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv'

def analyze_full():
    sales_owners = []
    try:
        # Use latin-1 to avoid decode errors
        with open(file_path, mode='r', encoding='latin-1') as f:
            reader = csv.DictReader(f)
            for row in reader:
                owner = row.get('Sales owner')
                if owner:
                    sales_owners.append(owner.strip())
                else:
                    # Check other columns that might be owner
                    alt = row.get('Owner') or row.get('Sales Owner')
                    if alt:
                        sales_owners.append(alt.strip())
    except Exception as e:
        print(f"Error: {e}")
        return

    counts = Counter(sales_owners)
    unique_owners = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    print(f"Total Unique Sales Persons Found: {len(counts)}")
    print("-" * 60)
    print(f"{'No.':<4} {'Sales Person':<30} {'Leads':<10}")
    print("-" * 60)
    for i, (owner, count) in enumerate(unique_owners, 1):
        print(f"{i:<4} {owner:<30} {count:<10}")

analyze_full()
