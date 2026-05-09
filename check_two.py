import csv, sys
sys.stdout.reconfigure(encoding='utf-8')
targets = {'forsaken_cassilda', 'fleur_eumachius'}
with open(r'D:\PyScript\hero_processor_v3\output_data\hero_skill_output_debug.csv', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        if row['hero_id'] in targets:
            print(f"=== {row['hero_id']} ===")
            for k, v in row.items():
                if v and v not in ('', '{}'):
                    print(f"  {k}: {v}")
            print()
