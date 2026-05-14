import csv
from collections import Counter
import os

files = [
    r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv',
    r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\Contacts.csv'
]

def analyze_file(file_path):
    print(f"\nAnalyzing file: {os.path.basename(file_path)}")
    sales_owners = []
    try:
        # Try different encodings
        for encoding in ['utf-8', 'latin-1', 'cp1252']:
            try:
                with open(file_path, mode='r', encoding=encoding) as f:
                    # Sniff the delimiter just in case
                    sample = f.read(1024)
                    f.seek(0)
                    dialect = csv.Sniffer().sniff(sample)
                    reader = csv.DictReader(f, dialect=dialect)
                    
                    for row in reader:
                        # Try different possible column names for owner
                        owner = row.get('Sales owner') or row.get('Owner') or row.get('Sales Owner')
                        if owner:
                            sales_owners.append(owner.strip())
                        else:
                            # If we can't find the column, let's look at all columns
                            pass
                break # If successful, stop trying encodings
            except (UnicodeDecodeError, csv.Error):
                continue
    except Exception as e:
        print(f"Error processing file: {e}")
        return

    counts = Counter(sales_owners)
    unique_owners = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    print(f"Total rows processed: {len(sales_owners)}")
    print(f"Total unique sales owners: {len(counts)}")
    print("Top 10 Lead counts per owner:")
    for owner, count in unique_owners[:10]:
        print(f" - {owner}: {count}")

for f in files:
    analyze_file(f)
