import csv
from pathlib import Path

csv_path = Path(r'D:\PyScript\hero_processor_v3\output_data\hero_skill_output_debug.csv')
with open(csv_path, encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))

def is_no_effect_col(row, lang_col):
    id_col = lang_col.replace('_lang_id', '_id')
    return row.get(id_col, '') == 'direct_effect_no_type'

search_failed, na_only, ok_heroes = set(), set(), set()
for row in rows:
    hero_id = row.get('hero_id', '')
    problem = False
    failed = False
    for col, val in row.items():
        if 'lang_id' not in col or not val:
            continue
        if col == 'de_lang_id':
            continue  # top-level DE N/A は正常
        if val == 'N/A' and is_no_effect_col(row, col):
            continue  # nested の direct_effect_no_type N/A は正常
        if val == 'SEARCH_FAILED':
            failed = True
        elif val == 'N/A':
            problem = True

    if failed:
        search_failed.add(hero_id)
    elif problem:
        na_only.add(hero_id)
    else:
        ok_heroes.add(hero_id)

print(f"総ヒーロー数       : {len(rows)}")
print(f"SEARCH_FAILED あり : {len(search_failed)}")
print(f"N/A 問題あり       : {len(na_only)}")
print(f"全て OK            : {len(ok_heroes)}")
print(f"実質問題あり合計   : {len(search_failed) + len(na_only)}")
print()
if search_failed:
    print("SEARCH_FAILED ヒーロー:")
    for h in sorted(search_failed):
        print(f"  {h}")
if na_only:
    print(f"\nN/A 問題 ヒーロー (先頭30):")
    for h in sorted(na_only)[:30]:
        print(f"  {h}")
