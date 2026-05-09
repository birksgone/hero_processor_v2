"""
viewer_gen.py
hero_skill_output_debug.csv を読み込み、lang_id → EN/JA テキストを展開した
静的 HTML ビューアを output_data/viewer.html に生成する。
"""
import csv
import html as html_mod
from pathlib import Path

# ── パス設定 ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
DEBUG_CSV    = SCRIPT_DIR / "output_data" / "hero_skill_output_debug.csv"
OUTPUT_HTML  = SCRIPT_DIR / "output_data" / "viewer.html"

_FALLBACK_DIR = Path(r"D:\Nox Screeshot\Nox SS Directory\Download\v32\Download\Download\V85\V8502\TextAsset-V8502")
_LOCAL_EN = SCRIPT_DIR / "data" / "English.csv"
_LOCAL_JA = SCRIPT_DIR / "data" / "Japanese.csv"
LANG_EN_CSV  = _LOCAL_EN if _LOCAL_EN.exists() else _FALLBACK_DIR / "English.csv"
LANG_JA_CSV  = _LOCAL_JA if _LOCAL_JA.exists() else _FALLBACK_DIR / "Japanese.csv"


# ── データ読み込み ────────────────────────────────────────────────────

def load_lang(path: Path) -> dict[str, str]:
    db = {}
    with open(path, encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0]:
                db[row[0]] = row[1]
    return db


def load_debug_csv() -> list[dict]:
    with open(DEBUG_CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


# ── スキルセクション収集 ──────────────────────────────────────────────

def collect_sections(row: dict) -> list[dict]:
    sections = []

    def add(label, id_, lang_id, params, extra="", nested=None, passive=False):
        sections.append({
            "label": label, "id": id_, "lang_id": lang_id,
            "params": params, "extra": extra,
            "nested": nested or [], "passive": passive,
        })

    # Clear Buffs
    if row.get("cb_lang_id"):
        add("Clear Buffs", row.get("cb_id",""), row["cb_lang_id"], row.get("cb_params","{}"))

    # Direct Effect
    if row.get("de_lang_id"):
        add("Direct Effect", row.get("de_id",""), row["de_lang_id"], row.get("de_params","{}"))

    # Properties
    for n in range(1, 6):
        lid = row.get(f"prop_{n}_lang_id", "")
        if not lid:
            break
        nested = []
        for m in range(1, 13):
            nid = row.get(f"prop_{n}_nested_{m}_id", "")
            if not nid:
                break  # IDがなければ本当に終端
            nlid = row.get(f"prop_{n}_nested_{m}_lang_id", "")
            if not nlid:
                continue  # heading など lang_id なし → スキップ
            nested.append({
                "label": f"└ Nested {m}", "id": nid,
                "lang_id": nlid, "params": row.get(f"prop_{n}_nested_{m}_params","{}"),
                "extra": row.get(f"prop_{n}_nested_{m}_extra_lang_id",""),
                "nested": [], "passive": False,
            })
        add(f"Property {n}", row.get(f"prop_{n}_id",""), lid,
            row.get(f"prop_{n}_params","{}"),
            extra=row.get(f"prop_{n}_extra_lang_id",""), nested=nested)

    # Status Effects
    for n in range(1, 10):
        lid = row.get(f"se_{n}_lang_id", "")
        if not lid:
            break
        nested = []
        for m in range(1, 4):
            nlid = row.get(f"se_{n}_nested_{m}_lang_id", "")
            if not nlid:
                break
            nested.append({
                "label": f"└ Nested {m}", "id": row.get(f"se_{n}_nested_{m}_id",""),
                "lang_id": nlid, "params": row.get(f"se_{n}_nested_{m}_params","{}"),
                "extra": row.get(f"se_{n}_nested_{m}_extra_lang_id",""),
                "nested": [], "passive": False,
            })
        add(f"Status Effect {n}", row.get(f"se_{n}_id",""), lid,
            row.get(f"se_{n}_params","{}"),
            extra=row.get(f"se_{n}_extra_lang_id",""), nested=nested)

    # Familiars
    for n in range(1, 5):
        lid = row.get(f"fam_{n}_lang_id", "")
        if not lid:
            break
        add(f"Familiar {n}", row.get(f"fam_{n}_id",""), lid, row.get(f"fam_{n}_params","{}"))

    # Passives（debug CSV に lang_id なし → ID + params のみ）
    for n in range(1, 6):
        pid = row.get(f"passive_{n}_id", "")
        if not pid:
            break
        add(f"Passive {n}", pid, "", row.get(f"passive_{n}_params","{}"), passive=True)

    return sections


# ── 判定 ─────────────────────────────────────────────────────────────

def status_cls(lang_id: str, passive: bool = False) -> str:
    if passive:
        return "passive"
    if lang_id in ("", "N/A"):
        return "na"
    if lang_id == "SEARCH_FAILED":
        return "failed"
    return "ok"


def _is_no_effect(item: dict) -> bool:
    return item.get("id") == "direct_effect_no_type" and item.get("lang_id") == "N/A"


def hero_has_issues(sections: list[dict]) -> bool:
    for s in sections:
        if s["passive"]:
            continue
        if _is_no_effect(s):
            continue
        if s["lang_id"] in ("SEARCH_FAILED", "N/A", ""):
            return True
        for n in s["nested"]:
            if _is_no_effect(n):
                continue
            if n["lang_id"] in ("SEARCH_FAILED", "N/A", ""):
                return True
    return False


# ── HTML 生成 ─────────────────────────────────────────────────────────

ICON = {"ok": "✅", "failed": "🔴", "na": "⚪", "passive": "🔵"}


def render_item(item: dict, lang_en: dict, lang_ja: dict, indent: int = 0) -> str:
    cls     = status_cls(item["lang_id"], item["passive"])
    icon    = ICON.get(cls, "❓")
    lid     = item["lang_id"]
    en_text = lang_en.get(lid, "")[:300] if lid else ""
    ja_text = lang_ja.get(lid, "")[:300] if lid else ""
    e = html_mod.escape

    pad = "  " * indent
    lines = [f'{pad}<div class="skill-item {cls}">']
    lines.append(f'{pad}  <span class="skill-hdr">{icon} <b>{e(item["label"])}</b>'
                 f' <span class="sid">{e(item["id"])}</span></span>')

    if not item["passive"]:
        lines.append(f'{pad}  <div class="lid">{e(lid or "(none)")}</div>')
        if en_text:
            lines.append(f'{pad}  <div class="txt en">EN: {e(en_text)}</div>')
        if ja_text:
            lines.append(f'{pad}  <div class="txt ja">JA: {e(ja_text)}</div>')
    else:
        p = item["params"]
        if p and p != "{}":
            lines.append(f'{pad}  <div class="txt passive">params: {e(p)}</div>')

    # Extra (tooltip)
    ex = item.get("extra", "")
    if ex and ex not in ("", "N/A"):
        ex_en = lang_en.get(ex, "")[:300]
        ex_ja = lang_ja.get(ex, "")[:300]
        lines.append(f'{pad}  <div class="extra">')
        lines.append(f'{pad}    <div class="lid extra-lid">Extra: {e(ex)}</div>')
        if ex_en:
            lines.append(f'{pad}    <div class="txt en">EN: {e(ex_en)}</div>')
        if ex_ja:
            lines.append(f'{pad}    <div class="txt ja">JA: {e(ex_ja)}</div>')
        lines.append(f'{pad}  </div>')

    for nested in item["nested"]:
        lines.append(render_item(nested, lang_en, lang_ja, indent + 1))

    lines.append(f'{pad}</div>')
    return "\n".join(lines)


CSS = """
body{font-family:monospace;background:#1e1e1e;color:#d4d4d4;margin:0;padding:20px}
h1{color:#569cd6;margin-bottom:8px}
#toolbar{display:flex;gap:12px;align-items:center;margin-bottom:12px}
#search{padding:7px 12px;font-size:14px;background:#2d2d2d;color:#d4d4d4;
        border:1px solid #555;border-radius:4px;width:360px}
#filter-fail{cursor:pointer;padding:6px 12px;background:#3a2020;color:#f88;
             border:1px solid #f44;border-radius:4px;font-size:13px}
#filter-fail.active{background:#f44;color:#fff}
#stats{color:#888;font-size:13px}
.hero-item{margin-bottom:3px}
.hero-item>summary{cursor:pointer;padding:5px 10px;border-radius:4px;
                    list-style:none;display:flex;align-items:center;gap:6px}
.hero-item>summary::-webkit-details-marker{display:none}
.hero-item.has-issues>summary{background:#2a1a1a;border-left:3px solid #f44}
.hero-item.ok>summary{background:#1a2a1a;border-left:3px solid #3a3}
.hero-item>summary:hover{filter:brightness(1.25)}
.hero-body{padding:8px 12px 12px;background:#252526;border-radius:0 0 4px 4px;
           border-left:1px solid #333}
.skill-item{margin:5px 0;padding:7px 10px;border-radius:4px;border-left:3px solid #555}
.skill-item.ok{border-color:#3a3;background:#192919}
.skill-item.failed{border-color:#f44;background:#291919}
.skill-item.na{border-color:#555;background:#222}
.skill-item.passive{border-color:#569cd6;background:#191e29}
.skill-hdr{display:block;margin-bottom:3px}
.sid{color:#888;font-size:.85em;margin-left:6px}
.lid{color:#ce9178;font-size:.88em;word-break:break-all}
.txt.en{color:#9cdcfe;font-size:.88em;margin-top:2px;white-space:pre-wrap}
.txt.ja{color:#dcdcaa;font-size:.88em;margin-top:2px;white-space:pre-wrap}
.txt.passive{color:#777;font-size:.84em}
.extra{margin-left:16px;margin-top:4px;padding:4px 8px;
       border-left:2px dashed #555;border-radius:2px}
.extra-lid{color:#b5a}
.hidden{display:none}
"""

JS = """
const search   = document.getElementById('search');
const btnFail  = document.getElementById('filter-fail');
const stats    = document.getElementById('stats');
const items    = [...document.querySelectorAll('.hero-item')];
let showFailOnly = false;

function update() {
    const q = search.value.toLowerCase();
    let vis = 0, iss = 0;
    items.forEach(el => {
        const id    = el.dataset.id || '';
        const fail  = el.classList.contains('has-issues');
        const match = !q || id.includes(q);
        const show  = match && (!showFailOnly || fail);
        el.classList.toggle('hidden', !show);
        if (show) { vis++; if (fail) iss++; }
    });
    stats.textContent = `表示: ${vis}体 / 🔴 要確認: ${iss}体`;
}

btnFail.addEventListener('click', () => {
    showFailOnly = !showFailOnly;
    btnFail.classList.toggle('active', showFailOnly);
    update();
});
search.addEventListener('input', update);
update();
"""


def generate_html(heroes: list[dict], lang_en: dict, lang_ja: dict) -> str:
    blocks = []
    issues_total = 0

    for row in heroes:
        hero_id   = row.get("hero_id", "")
        hero_name = row.get("hero_name", "")
        sections  = collect_sections(row)
        has_iss   = hero_has_issues(sections)
        if has_iss:
            issues_total += 1

        cls  = "has-issues" if has_iss else "ok"
        icon = "🔴" if has_iss else "✅"
        name = f" ({hero_name})" if hero_name and hero_name not in ("", "N/A") else ""
        body = "\n".join(render_item(s, lang_en, lang_ja) for s in sections)
        e    = html_mod.escape

        blocks.append(
            f'<details class="hero-item {cls}" data-id="{e(hero_id)}">\n'
            f'  <summary>{icon} {e(hero_id)}{e(name)}</summary>\n'
            f'  <div class="hero-body">\n{body}\n  </div>\n'
            f'</details>'
        )

    total = len(heroes)
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>Hero Skill Viewer</title>
<style>{CSS}</style>
</head>
<body>
<h1>🎮 Hero Skill Viewer</h1>
<div id="toolbar">
  <input type="text" id="search" placeholder="ヒーローIDで絞り込み (例: poseidon3)">
  <button id="filter-fail">🔴 要確認のみ表示</button>
</div>
<div id="stats">計 {total}体 / 🔴 要確認: {issues_total}体</div>
{"".join(blocks)}
<script>{JS}</script>
</body>
</html>"""


# ── エントリポイント ──────────────────────────────────────────────────

def main():
    print("Loading language CSVs...")
    lang_en = load_lang(LANG_EN_CSV)
    lang_ja = load_lang(LANG_JA_CSV)
    print(f"  EN: {len(lang_en)} / JA: {len(lang_ja)} keys")

    print("Loading debug CSV...")
    heroes = load_debug_csv()
    print(f"  {len(heroes)} heroes")

    print("Generating HTML...")
    content = generate_html(heroes, lang_en, lang_ja)

    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(content)

    size_mb = OUTPUT_HTML.stat().st_size / 1024 / 1024
    print(f"Done! {size_mb:.1f} MB → {OUTPUT_HTML}")


if __name__ == "__main__":
    main()
