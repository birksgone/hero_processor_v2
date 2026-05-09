import csv, sys
sys.stdout.reconfigure(encoding='utf-8')
target = 'beauty_beast_pendulus_clonk'
with open(r'D:\PyScript\hero_processor_v3\output_data\hero_skill_output_debug.csv', encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        if row['hero_id'] == target:
            print(f"=== {target} ===")
            for k, v in row.items():
                if v and v not in ('', '{}'):
                    print(f"  {k}: {v}")
            break
