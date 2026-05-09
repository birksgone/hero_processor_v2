import argparse
import csv
import json
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
DEFAULT_SOURCE = Path(r"D:\PyScript\Hero Text Scraper\data\source_text\google_sheets_skill\tales2_dularfulr_costume_engineer.json")
DEFAULT_DEBUG = SCRIPT_DIR / "output_data" / "debug_hero_data.json"
DEFAULT_EN = SCRIPT_DIR / "data" / "English.csv"
DEFAULT_JA = SCRIPT_DIR / "data" / "Japanese.csv"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "output_data" / "lang_reverse_search"


def read_lang_csv(path: Path) -> dict[str, str]:
    data = {}
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0].strip():
                data[row[0].strip()] = row[1].strip()
    return data


def load_lang_records(en_path: Path, ja_path: Path) -> list[dict]:
    en = read_lang_csv(en_path)
    ja = read_lang_csv(ja_path)
    records = []
    for key in sorted(set(en) | set(ja)):
        records.append({"id": key, "en": en.get(key, ""), "ja": ja.get(key, "")})
    return records


def find_passive(hero: dict, passive_id: str) -> dict:
    for passive in hero.get("passiveSkills", []):
        if passive.get("id") == passive_id:
            return passive
    for passive in hero.get("costumeBonusPassiveSkillIds", []):
        if passive.get("id") == passive_id:
            return passive
    return {}


def passive_context(passive: dict) -> dict:
    status_effect = (passive.get("statusEffects") or [{}])[0]
    extra_configs = status_effect.get("extraDamageModifierConfigs") or []
    familiar_types = []
    for config in extra_configs:
        familiar_types.extend(config.get("requiredFamiliarTypes") or [])
    direct_effects_on_resist = passive.get("directEffectsOnResist") or []
    direct_effect_types = [effect.get("effectType", "") for effect in direct_effects_on_resist if isinstance(effect, dict)]
    resist_types = passive.get("resistTypes") or []
    return {
        "passiveSkillType": passive.get("passiveSkillType", ""),
        "resistTypes": sorted(set(resist_types)),
        "directEffectsOnResist": sorted(set(direct_effect_types)),
        "statusEffect": status_effect.get("statusEffect", ""),
        "buff": status_effect.get("buff", ""),
        "target": status_effect.get("statusTargetType", ""),
        "side": status_effect.get("sideAffected", ""),
        "modifier": status_effect.get("modifier", ""),
        "has_extra_damage": bool(extra_configs),
        "familiar_types": sorted(set(familiar_types)),
    }


def passive_params(passive: dict) -> dict:
    params = {}
    if "resistChancePerMil" in passive:
        params["CHANCE"] = passive["resistChancePerMil"] / 10
    for effect in passive.get("directEffectsOnResist") or []:
        effect_type = effect.get("effectType", "")
        if effect_type == "HealthBoost" and "fixedPower" in effect:
            params["HEALTHBOOST"] = effect["fixedPower"]
        if effect_type == "AddMana" and "powerMultiplierPerMil" in effect:
            params["MANA"] = effect["powerMultiplierPerMil"] / 10
    return {
        key: int(value) if isinstance(value, float) and value.is_integer() else value
        for key, value in params.items()
    }


def strength_token(buff: str) -> str:
    lowered = (buff or "").lower()
    if "minor" in lowered:
        return "minor"
    if "major" in lowered:
        return "major"
    if "permanent" in lowered:
        return "permanent"
    return ""


def target_token(target: str) -> str:
    return {
        "All": "all",
        "NearToTarget": "neartotarget",
        "Single": "single",
    }.get(target or "", (target or "").lower())


def side_token(side: str) -> str:
    return {
        "Enemies": "enemies",
        "Allies": "allies",
    }.get(side or "", (side or "").lower())


def score_record(record: dict, keywords: list[str], context: dict, mode: str) -> tuple[int, list[str]]:
    lang_id = record["id"].lower()
    ja = record["ja"]
    en = record["en"].lower()
    score = 0
    reasons = []
    passive_type = context.get("passiveSkillType", "").lower()
    resist_types = {item.lower() for item in context.get("resistTypes", [])}
    direct_effect_types = {item.lower() for item in context.get("directEffectsOnResist", [])}

    for keyword in keywords:
        if keyword and keyword in ja:
            score += 40
            reasons.append(f"ja keyword: {keyword}")

    if mode == "title":
        if record["id"].startswith("herocard.passive_skill.title."):
            score += 25
            reasons.append("passive title namespace")
        if "activates_on_ally_action" in lang_id and "ally_action" not in passive_type:
            score -= 15
            reasons.append("ally-action title mismatch")
    else:
        if record["id"].startswith("passiveskill."):
            score += 25
            reasons.append("passiveskill namespace")
        if record["id"].startswith("specials.v2.statuseffect."):
            score += 10
            reasons.append("special statusEffect fallback namespace")

    if passive_type and passive_type in lang_id:
        score += 25
        reasons.append("passiveSkillType token")

    for resist_type in sorted(resist_types):
        if resist_type and resist_type in lang_id:
            score += 25
            reasons.append(f"resist type token: {resist_type}")

    if direct_effect_types:
        for effect_type in sorted(direct_effect_types):
            effect_token = effect_type.lower()
            if effect_token and effect_token in lang_id:
                score += 25
                reasons.append(f"direct effect token: {effect_token}")
        if "with_effect" in lang_id:
            score += 20
            reasons.append("with_effect matches directEffectsOnResist")
        elif mode != "title":
            score -= 15
            reasons.append("JSON has directEffectsOnResist but candidate has no with_effect")

    status_effect = context.get("statusEffect", "").lower()
    if status_effect and status_effect in lang_id:
        score += 20
        reasons.append("statusEffect token")

    for token_name, token in [
        ("strength", strength_token(context.get("buff", ""))),
        ("target", target_token(context.get("target", ""))),
        ("side", side_token(context.get("side", ""))),
        ("modifier", (context.get("modifier", "") or "").lower()),
    ]:
        if token and token in lang_id:
            score += 10
            reasons.append(f"{token_name} token: {token}")

    if context.get("has_extra_damage"):
        if "extra_minion_damage" in lang_id:
            score += 35
            reasons.append("extra minion damage matches JSON")
        elif mode != "title":
            score -= 20
            reasons.append("JSON has extra damage but candidate has no extra_minion_damage")

    familiar_tokens = {t.lower() for t in context.get("familiar_types", [])}
    if familiar_tokens:
        matched = [token for token in familiar_tokens if token in lang_id or token in en]
        if matched:
            score += 5 * len(matched)
            reasons.append(f"familiar tokens: {', '.join(sorted(matched))}")

    return score, reasons


def search(records: list[dict], keywords: list[str], context: dict, mode: str, limit: int) -> list[dict]:
    scored = []
    for record in records:
        if mode == "title" and not record["id"].startswith("herocard.passive_skill.title."):
            continue
        if mode != "title" and record["id"].startswith("herocard.passive_skill.title."):
            continue
        if not any(keyword in record["ja"] for keyword in keywords):
            continue
        score, reasons = score_record(record, keywords, context, mode)
        if score <= 0:
            continue
        scored.append({**record, "score": score, "reasons": reasons})
    scored.sort(key=lambda row: (-row["score"], row["id"]))
    return scored[:limit]


def run(args: argparse.Namespace) -> dict:
    source = json.loads(Path(args.source).read_text(encoding="utf-8"))
    debug = json.loads(Path(args.debug_json).read_text(encoding="utf-8"))
    hero = debug.get(args.hero_id) or {}
    passive_id = args.passive_id
    source_passive = next(
        (
            item for item in source.get("passives", [])
            if item.get("passive_id_hint") == passive_id or item.get("slot") == args.slot
        ),
        {},
    )
    passive = find_passive(hero, passive_id)
    context = passive_context(passive)
    keywords = [kw for kw in (args.keywords or source_passive.get("keywords") or []) if kw]

    records = load_lang_records(Path(args.english_csv), Path(args.japanese_csv))
    result = {
        "hero_id": args.hero_id,
        "passive_id": passive_id,
        "source": {
            "name": source_passive.get("name", ""),
            "slot": source_passive.get("slot", args.slot),
            "keywords": keywords,
            "value_policy": source_passive.get("value_policy", "hint_only"),
        },
        "json_context": context,
        "params": passive_params(passive),
        "title_candidates": search(records, [source_passive.get("name", "")], context, "title", args.limit),
        "description_candidates": search(records, keywords, context, "description", args.limit),
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Reverse-search passive lang_id candidates from source text hints.")
    parser.add_argument("--hero-id", default="tales2_dularfulr_costume_engineer")
    parser.add_argument("--passive-id", default="molten_core_costume")
    parser.add_argument("--slot", default="PASS1")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--debug-json", default=str(DEFAULT_DEBUG))
    parser.add_argument("--english-csv", default=str(DEFAULT_EN))
    parser.add_argument("--japanese-csv", default=str(DEFAULT_JA))
    parser.add_argument("--keyword", dest="keywords", action="append", default=[])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    result = run(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.write:
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{args.hero_id}_{args.passive_id}.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
