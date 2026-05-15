import csv

file_path = r'c:\Users\Admin\Desktop\clara\ArihanthCRM_-main\backend\csv\FreshSales Data - Organized (1).csv'

unique_projects = set()

# Try different encodings
encodings = ['utf-8', 'latin-1', 'cp1252']

for enc in encodings:
    try:
        with open(file_path, mode='r', encoding=enc) as f:
            reader = csv.DictReader(f)
            for row in reader:
                project_str = row.get('Project')
                if project_str:
                    # Projects are often semicolon separated
                    parts = project_str.split(';')
                    for p in parts:
                        p_clean = p.strip()
                        if p_clean and p_clean.lower() not in ['unknown', 'na', 'n/a', 'others', 'null']:
                            unique_projects.add(p_clean)
        print(f"Successfully read with {enc}")
        break
    except Exception as e:
        print(f"Error with {enc}: {e}")

print("Unique Projects found in CSV:")
for p in sorted(list(unique_projects)):
    print(f"- {p}")
