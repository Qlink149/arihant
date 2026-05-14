import csv

file_path = r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv'

def search_as_owner():
    count = 0
    try:
        with open(file_path, mode='r', encoding='latin-1') as f:
            reader = csv.DictReader(f)
            for row in reader:
                owner = row.get('Sales owner') or ""
                if "Akshata" in owner:
                    print(f"Found match as owner: {owner}")
                    count += 1
    except Exception as e:
        print(f"Error: {e}")
        return
    print(f"Total leads owned by Akshata: {count}")

search_as_owner()
