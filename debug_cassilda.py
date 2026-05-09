import json, sys
sys.stdout.reconfigure(encoding='utf-8')

with open(r'D:\PyScript\hero_processor_v3\output_data\debug_hero_data.json', encoding='utf-8') as f:
    data = json.load(f)

# debug_hero_data はリストかdictか確認
if isinstance(data, list):
    heroes = data
elif isinstance(data, dict):
    heroes = list(data.values())
else:
    print("Unknown format"); sys.exit(1)

for h in heroes:
    if not isinstance(h, dict): continue
    if h.get('id') == 'forsaken_cassilda':
        spec = h.get('specialId_details', {})
        print("special:", spec.get('id'))
        props = spec.get('properties', [])
        for prop in props:
            if not isinstance(prop, dict): continue
            if prop.get('id') == 'chain_strike_cassilda':
                print("chain_strike_cassilda statusEffects raw:")
                ses = prop.get('statusEffects', [])
                for se in ses:
                    print(" ", type(se).__name__, ":", se if isinstance(se, str) else json.dumps(se, ensure_ascii=False)[:200])
        break
