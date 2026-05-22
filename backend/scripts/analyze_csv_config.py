import csv
import os

def analyze_csv(filepath):
    if not os.path.exists(filepath):
        print(f"Not found: {filepath}")
        return
        
    print(f"\n--- Analyzing {filepath} ---")
    with open(filepath, 'r', encoding='utf-8-sig', errors='replace') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames
        print(f"Headers count: {len(headers) if headers else 0}")
        
        # Look for columns that might map to configuration
        config_cols = [h for h in headers if h and h.lower() in ('apartment type', 'configuration', 'bhk', 'unit type', 'unit size', 'preferred unit')]
        print(f"Configuration columns: {config_cols}")
        
        counts = {col: {'yes': 0, 'may_be': 0} for col in config_cols}
        
        # Also let's check all columns to see if there's a column like "Loan Required?" that has these values
        # maybe they got shifted?
        for row in reader:
            for col in config_cols:
                val = str(row.get(col, '')).strip().lower()
                if val in ('yes', 'may_be'):
                    counts[col][val] += 1
                    
        for col, cnts in counts.items():
            if cnts['yes'] > 0 or cnts['may_be'] > 0:
                print(f"Column \"{col}\" has {cnts['yes']} \"yes\" and {cnts['may_be']} \"may_be\"")

analyze_csv('csv/Contacts.csv')
analyze_csv('csv/FreshSales Data - Organized (1).csv')
