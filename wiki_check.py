"""
wiki_check.py
ランダムに20体のヒーローをサンプリングし、
Fandom Wiki の skill テキストと我々の lang_id EN テキストを比較してスコアを出す。
"""
import csv, json, re, sys, random, time, urllib.request, urllib.parse
sys.stdout.reconfigure(encoding='utf-8')

SCRIPT_DIR = __file__[:__file__.rfind('\\')]
DEBUG_CSV  = SCRIPT_DIR + r'\output_data\hero_skill_output_debug.csv'
LANG_EN    = SCRIPT_DIR + r'\data\English.csv'
SAMPLE_N   = 20
HEADERS    = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── 言語DB読み込み ────────────────────────────────────────────────
def load_lang_en(path):
    db = {}
    with open(path, encoding='utf-8-sig') as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0]:
                db[row[0]] = row[1]
    return db

# ── デバッグCSV読み込み ──────────────────────────────────────────
def load_heroes(path):
    with open(path, encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

# ── hero_id → wiki候補名リスト ────────────────────────────────────
# family prefix を除き、残りを候補として複数バリエーション生成
KNOWN_PREFIXES = {
    'beauty_beast', 'lunar_new_year', 'dark_god', 'nature_god',
    'fire_god', 'ice_god', 'holy_god', 'dire_ghost', 'shadow',
}
ONE_WORD_PREFIXES = {
    'ronin','forsaken','fleur','construct','mahayoddha','institute',
    'dryad','rodent','easter','vegetable','mimic','poseidon','santa',
    'knight','druid','barbarian','wizard','ranger','cleric','fighter',
    'monk','paladin','sorcerer','rogue','titan','costume',
}

def hero_id_to_wiki_candidates(hero_id):
    parts = hero_id.split('_')
    candidates = []
    # 2語prefix
    prefix2 = '_'.join(parts[:2])
    if prefix2 in KNOWN_PREFIXES and len(parts) > 2:
        name_parts = parts[2:]
    # 1語prefix
    elif parts[0] in ONE_WORD_PREFIXES and len(parts) > 1:
        name_parts = parts[1:]
    else:
        name_parts = parts  # そのまま

    def cap(ps): return ' '.join(p.capitalize() for p in ps)

    # 全体 / 末尾2語 / 末尾1語 の3パターン
    candidates.append(cap(name_parts))
    if len(name_parts) >= 2:
        candidates.append(cap(name_parts[-2:]))
    candidates.append(cap(name_parts[-1:]))
    return list(dict.fromkeys(candidates))  # 重複排除

# ── Wiki取得 ──────────────────────────────────────────────────────
def fetch_wiki(name):
    url = (
        "https://empiresandpuzzles.fandom.com/api.php"
        f"?action=query&titles={urllib.parse.quote(name)}"
        "&prop=revisions&rvprop=content&format=json"
    )
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
        pages = data.get('query', {}).get('pages', {})
        page  = list(pages.values())[0]
        if 'missing' in page:
            return None, name
        return page['revisions'][0]['*'], name
    except Exception as e:
        return None, f"ERROR:{e}"

def find_wiki(hero_id):
    for cand in hero_id_to_wiki_candidates(hero_id):
        wikitext, name = fetch_wiki(cand)
        time.sleep(0.3)
        if wikitext:
            return wikitext, cand
    return None, None

# ── Wikitextからeffectテキスト抽出 ───────────────────────────────
def extract_effects(wikitext):
    if not wikitext:
        return []
    lines = []
    for m in re.finditer(r'\|effect\d+\s*=\s*(.*?)(?=\n\||\}\})', wikitext, re.DOTALL):
        text = m.group(1).strip()
        text = re.sub(r'\[\[[^\]]*\|([^\]]+)\]\]', r'\1', text)  # [[link|label]] → label
        text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)           # [[link]] → link
        text = re.sub(r'\{\{[^}]*\}\}', '', text)                  # template除去
        text = re.sub(r"'{2,}", '', text)                          # bold/italic除去
        text = ' '.join(text.split())
        if text:
            lines.append(text)
    return lines

# ── キーワードスコア ──────────────────────────────────────────────
STOP = {'the','a','an','to','for','of','and','or','with','in','on','at','is',
        'are','from','by','all','its','this','that','their','each','per','any'}

def keyword_score(our_text, wiki_texts):
    """our_textのキーワードがwikiテキスト全体に何割含まれるか (0-100)"""
    if not our_text or not wiki_texts:
        return 0
    wiki_blob = ' '.join(wiki_texts).lower()
    words = re.findall(r'[a-z]+', our_text.lower())
    words = [w for w in words if w not in STOP and len(w) > 2]
    if not words:
        return 0
    hit = sum(1 for w in words if w in wiki_blob)
    return round(hit / len(words) * 100)

# ── ヒーローから代表lang_idリストを取得 ─────────────────────────
def get_lang_ids(row):
    ids = []
    for prefix in ['de', 'cb']:
        lid = row.get(f'{prefix}_lang_id', '')
        if lid and lid not in ('N/A', 'SEARCH_FAILED', ''):
            ids.append(lid)
    for n in range(1, 6):
        lid = row.get(f'prop_{n}_lang_id', '')
        if not lid: break
        if lid not in ('N/A', 'SEARCH_FAILED', ''):
            ids.append(lid)
        for m in range(1, 13):
            nid = row.get(f'prop_{n}_nested_{m}_id', '')
            if not nid: break
            nlid = row.get(f'prop_{n}_nested_{m}_lang_id', '')
            if nlid and nlid not in ('N/A', 'SEARCH_FAILED', ''):
                ids.append(nlid)
    for n in range(1, 10):
        lid = row.get(f'se_{n}_lang_id', '')
        if not lid: break
        if lid not in ('N/A', 'SEARCH_FAILED', ''):
            ids.append(lid)
    return ids

# ── メイン ────────────────────────────────────────────────────────
def main():
    lang_en = load_lang_en(LANG_EN)
    heroes  = load_heroes(DEBUG_CSV)

    # SEARCH_FAILEDなし・prop_1あり を対象にサンプリング
    eligible = [
        h for h in heroes
        if h['hero_id'] != 'guestip2_hero1'
        and h.get('prop_1_lang_id', '') not in ('', 'N/A', 'SEARCH_FAILED')
    ]
    random.seed(42)
    sample = random.sample(eligible, min(SAMPLE_N, len(eligible)))

    print(f"{'hero_id':<40} {'wiki_found':<25} {'score':>5}  lang_ids")
    print('-' * 100)

    scores = []
    for row in sample:
        hero_id = row['hero_id']
        lang_ids = get_lang_ids(row)

        # wiki取得
        wikitext, wiki_name = find_wiki(hero_id)
        wiki_effects = extract_effects(wikitext)

        # 我々のENテキスト結合
        our_texts = [lang_en.get(lid, '') for lid in lang_ids if lang_en.get(lid)]
        our_blob  = ' '.join(our_texts)

        score = keyword_score(our_blob, wiki_effects)
        scores.append(score)

        wiki_label = wiki_name if wiki_name else 'NOT FOUND'
        ids_short  = ', '.join(lang_ids[:3]) + ('...' if len(lang_ids) > 3 else '')
        flag = '  ' if score >= 60 else ('??' if score >= 30 else 'XX')
        print(f"{flag} {hero_id:<38} {wiki_label:<25} {score:>4}%  {ids_short}")

        # wiki effectsと我々のテキストを並べて表示
        if wiki_effects:
            print(f"   [wiki] {' | '.join(wiki_effects[:3])[:120]}")
        if our_blob:
            print(f"   [ours] {our_blob[:120]}")
        print()

    if scores:
        print(f"\n--- 平均スコア: {sum(scores)/len(scores):.1f}%  "
              f"(60%以上: {sum(1 for s in scores if s>=60)}/{len(scores)}体) ---")

if __name__ == '__main__':
    main()
