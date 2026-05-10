import json
import re
import math
import pandas as pd

# --- Helper Functions (used only by the parsers) ---

def flatten_json(y):
    """ Flattens a nested dictionary and list structure. """
    out = {}
    def flatten(x, name=''):
        if type(x) is dict:
            for a in x: flatten(x[a], name + a + '_')
        elif type(x) is list:
            i = 0
            for a in x:
                flatten(a, name + str(i) + '_')
                i += 1
        else: out[name[:-1]] = x
    flatten(y)
    return out

def generate_description(lang_id: str, lang_params: dict, lang_db: dict) -> dict:
    """Generates a description string by filling a template with parameters."""
    template = lang_db.get(lang_id, {"en": f"NO_TEMPLATE_FOR_{lang_id}", "ja": f"NO_TEMPLATE_FOR_{lang_id}"})
    desc_en, desc_ja = template.get("en", ""), template.get("ja", "")
    for key, value in lang_params.items():
        desc_en = desc_en.replace(f"{{{key}}}", str(value))
        desc_ja = desc_ja.replace(f"{{{key}}}", str(value))
    return {"en": desc_en, "ja": desc_ja}

def format_value(value):
    """Formats numbers for display, removing trailing .0 and noisy decimals."""
    if isinstance(value, float):
        rounded = round(value, 4)
        if rounded.is_integer():
            return int(rounded)
        return f"{rounded:g}"
    return value


def _format_signed(value):
    formatted = format_value(value)
    if isinstance(value, (int, float)) and value > 0:
        return f"+{formatted}"
    return formatted


def _leveled_permil_percent(data: dict, base_key: str, inc_key: str, max_level: int):
    value = _leveled_fixed_value(data, base_key, inc_key, max_level)
    if value is None:
        return None
    return value / 10


def _leveled_modifier_percent(data: dict, base_key: str, inc_key: str, max_level: int):
    value = _leveled_fixed_value(data, base_key, inc_key, max_level)
    if value is None:
        return None
    return (value - 1000) / 10


def _increasing_status_effect_params(data_block: dict, max_level: int, placeholders: set[str]) -> dict:
    """
    Explicit param rules for Increasing* status effects.

    These are common patterns, not hero-specific exceptions:
    - stat modifier bases are relative to 1000 permil and need +/- signs
    - per-turn increments use their own increment keys
    - CAP / MAXDEFLECTION include the base value plus max stacked increases
    """
    params = {}

    if "DEFENSE" in placeholders and "defenseMultiplierPerMil" in data_block:
        defense = _leveled_modifier_percent(
            data_block,
            "defenseMultiplierPerMil",
            "defenseMultiplierIncrementPerLevelPerMil",
            max_level,
        )
        if defense is not None:
            params["DEFENSE"] = _format_signed(defense)

    if "DEFLECTION" in placeholders and "damageDeflectionPerMil" in data_block:
        deflection = _leveled_permil_percent(
            data_block,
            "damageDeflectionPerMil",
            "damageDeflectionPerLevelPerMil",
            max_level,
        )
        if deflection is not None:
            params["DEFLECTION"] = format_value(deflection)

    if "INCREASEPERTURN" in placeholders:
        if "damageDeflectionIncrementPerTurnPerMil" in data_block:
            value = _leveled_permil_percent(
                data_block,
                "damageDeflectionIncrementPerTurnPerMil",
                "damageDeflectionIncrementPerTurnPerLevelPerMil",
                max_level,
            )
            if value is not None:
                params["INCREASEPERTURN"] = _format_signed(value)
        elif "defenseMultiplierIncrementPerTurnPerMil" in data_block:
            value = _leveled_permil_percent(
                data_block,
                "defenseMultiplierIncrementPerTurnPerMil",
                "defenseMultiplierIncrementPerTurnPerLevelPerMil",
                max_level,
            )
            if value is not None:
                params["INCREASEPERTURN"] = format_value(value)

    if "CAP" in placeholders and "maxIncreases" in data_block:
        base = _leveled_modifier_percent(
            data_block,
            "defenseMultiplierPerMil",
            "defenseMultiplierIncrementPerLevelPerMil",
            max_level,
        )
        step = _leveled_permil_percent(
            data_block,
            "defenseMultiplierIncrementPerTurnPerMil",
            "defenseMultiplierIncrementPerTurnPerLevelPerMil",
            max_level,
        )
        count = data_block.get("maxIncreases")
        if isinstance(base, (int, float)) and isinstance(step, (int, float)) and isinstance(count, (int, float)):
            params["CAP"] = _format_signed(base + step * count)

    if "MAXDEFLECTION" in placeholders and "maxIncrementCount" in data_block:
        base = _leveled_permil_percent(
            data_block,
            "damageDeflectionPerMil",
            "damageDeflectionPerLevelPerMil",
            max_level,
        )
        step = _leveled_permil_percent(
            data_block,
            "damageDeflectionIncrementPerTurnPerMil",
            "damageDeflectionIncrementPerTurnPerLevelPerMil",
            max_level,
        )
        count = data_block.get("maxIncrementCount")
        if isinstance(base, (int, float)) and isinstance(step, (int, float)) and isinstance(count, (int, float)):
            params["MAXDEFLECTION"] = _format_signed(base + step * count)

    return params


def _placeholder_keywords(p_holder: str) -> list[str]:
    raw = p_holder.lower()
    collapsed = re.sub(r"[^a-z0-9]+", "", raw).replace("increment", "increase")
    keywords = {collapsed}
    if collapsed.startswith("max") and len(collapsed) > 3:
        keywords.add(collapsed[3:])
    if "perturn" in collapsed:
        keywords.add("perturn")
        keywords.add(collapsed.replace("perturn", ""))
    if "chance" in collapsed:
        keywords.add("chance")
    if "damage" in collapsed:
        keywords.add("damage")
    if "deflection" in collapsed:
        keywords.add("deflection")
    if "defense" in collapsed:
        keywords.add("defense")
    return [kw for kw in keywords if len(kw) >= 3]

# --- NEW: Centralized Tooltip Parsing Helper (Robust Version) ---
def _find_and_parse_extra_description(
    categories: list, skill_name: str, search_context: dict, main_params: dict,
    lang_db: dict, hero_id: str, rules: dict, parsers: dict
) -> dict:
    """
    A generic helper to find and parse tooltip (.extra) descriptions.
    Searches for keys containing all required components, regardless of structure.
    """
    if not skill_name or not categories:
        return {}

    skill_name_lower = skill_name.lower()

    # Find all candidate keys that contain the skill name and '.extra'
    candidates = [
        key for key in parsers['extra_lang_ids']
        if skill_name_lower in key and '.extra' in key
    ]

    # From the candidates, find one that also contains one of the category names
    extra_lang_id = None
    for key in candidates:
        if any(cat in key for cat in categories):
            extra_lang_id = key
            break  # Found the first and best match

    if extra_lang_id and extra_lang_id in lang_db:
        extra_params = {}
        extra_template_text = lang_db.get(extra_lang_id, {}).get("en", "")
        extra_placeholders = set(re.findall(r'\{(\w+)\}', extra_template_text))

        # Inherit params from main description if placeholder exists in both
        for p in extra_placeholders:
            if p in main_params:
                extra_params[p] = main_params[p]

        # Find any remaining params needed only for the tooltip
        remaining_placeholders = extra_placeholders - set(extra_params.keys())
        for p_holder in remaining_placeholders:
            value, _ = find_and_calculate_value(
                p_holder, search_context, search_context.get("maxLevel", 8),
                hero_id, rules, is_modifier=False
            )
            if value is not None:
                extra_params[p_holder] = value

        formatted_extra_params = {k: format_value(v) for k, v in extra_params.items()}
        extra_desc = generate_description(extra_lang_id, formatted_extra_params, lang_db)

        return {
            "lang_id": extra_lang_id,
            "params": json.dumps(extra_params),
            "en": re.sub(r'\[\*\]|\n\s*\n', '\n・', extra_desc.get("en", "")).strip(),
            "ja": re.sub(r'\[\*\]|\n\s*\n', '\n・', extra_desc.get("ja", "")).strip()
        }
    return {}

def _has_extra_description(game_db: dict, key: str) -> bool:
    """Returns whether battle.json marks a game-data key as having tooltip text."""
    return bool(key) and key.lower() in game_db.get("extra_description_keys", set())


def _leveled_fixed_value(data: dict, base_key: str, inc_key: str, max_level: int):
    base = data.get(base_key)
    inc = data.get(inc_key, 0)
    if base is None and inc_key not in data:
        return None
    if not isinstance(base, (int, float)):
        base = 0
    if not isinstance(inc, (int, float)):
        inc = 0
    value = base + inc * (max_level - 1)
    return int(value) if isinstance(value, float) and value.is_integer() else value


def _base_stat_property_lang_id(prop_data: dict, lang_db: dict) -> str:
    """Builds exact lang_id for Wither/Growth fixed ability-score changes."""
    property_type = prop_data.get("propertyType", "")
    if property_type not in {"Wither", "Growth"}:
        return ""

    stat_parts = []
    attack_value = (prop_data.get("baseAttackIncrease") or 0) + (prop_data.get("baseAttackIncreasePerLevel") or 0)
    defense_value = (prop_data.get("baseDefenseIncrease") or 0) + (prop_data.get("baseDefenseIncreasePerLevel") or 0)
    if attack_value:
        stat_parts.append("attack")
    if defense_value:
        stat_parts.append("defense")
    if not stat_parts:
        return ""

    key = ".".join([
        "specials.v2.property",
        property_type.lower(),
        "none",
        str(prop_data.get("targetType", "")).lower(),
        str(prop_data.get("sideAffected", "")).lower(),
        ".".join(stat_parts),
    ])
    return key if key in lang_db else ""


def _base_stat_property_params(prop_data: dict, max_level: int) -> dict:
    params = {}
    attack = _leveled_fixed_value(prop_data, "baseAttackIncrease", "baseAttackIncreasePerLevel", max_level)
    defense = _leveled_fixed_value(prop_data, "baseDefenseIncrease", "baseDefenseIncreasePerLevel", max_level)
    if attack:
        params["ATTACKINCREASE"] = attack
    if defense:
        params["DEFENSEINCREASE"] = defense
    return params


def _extra_from_rule(rule: dict, lang_db: dict) -> dict:
    lang_id = (rule or {}).get("extra_lang_id", "")
    params = (rule or {}).get("params", {})
    if not lang_id or lang_id not in lang_db:
        return {}
    desc = generate_description(lang_id, {k: format_value(v) for k, v in params.items()}, lang_db)
    return {
        "lang_id": lang_id,
        "params": json.dumps(params, ensure_ascii=False),
        **desc,
    }


def _moonbeam_lang_id(data_block: dict, lang_key_subset: list) -> str:
    if data_block.get("statusEffect") != "MoonBeamStatusEffectSkill":
        return ""

    buff_map = {"MinorDebuff":"minor","MajorDebuff":"major","MinorBuff":"minor","MajorBuff":"major",
                "StackMinorDebuff":"minor","StackMajorDebuff":"major",
                "StackMinorBuff":"minor","StackMajorBuff":"major",
                "PermanentDebuff":"permanent","PermanentBuff":"permanent"}
    intensity = buff_map.get(data_block.get("buff"), "minor")
    target = str(data_block.get("statusTargetType", "")).lower()
    side = str(data_block.get("sideAffected", "")).lower()
    if not target or not side:
        return ""

    effect_parts = []
    append_with_chance = False
    for effect in data_block.get("directEffects") or []:
        effect_type = effect.get("effectType", "")
        target_type = str(effect.get("typeOfTarget", "Random")).lower()
        if effect_type == "Damage":
            effect_parts.extend(["damage", target_type, "enemies"])
        elif effect_type == "AddMana":
            effect_parts.extend(["addmana", target_type, "enemies"])
        elif effect_type == "ReduceMaxHealth":
            effect_parts.extend(["reducemaxhealth", target_type, "enemies"])
            append_with_chance = True
    if not effect_parts:
        return ""

    parts = [
        "specials.v2.statuseffect",
        intensity,
        "moonbeamstatuseffectskill",
        target,
        side,
        "on",
        "turnend",
        *effect_parts,
    ]
    if append_with_chance:
        parts.append("with_chance")
    lang_id = ".".join(parts)
    return lang_id if lang_id in lang_key_subset else ""


def _moonbeam_params(data_block: dict, max_level: int) -> dict:
    params = {}
    for index, effect in enumerate(data_block.get("directEffects") or [], start=1):
        effect_type = effect.get("effectType", "")
        if effect_type == "Damage":
            value = _leveled_fixed_value(
                effect,
                "powerMultiplierPerMil",
                "powerMultiplierIncrementPerLevelPerMil",
                max_level,
            )
            if value is not None:
                params[f"POWER{index}"] = value / 10
        elif effect_type == "ReduceMaxHealth":
            value = _leveled_fixed_value(effect, "fixedPower", "fixedPowerIncrementPerLevel", max_level)
            if value is not None:
                params[f"REDUCTION{index}"] = -abs(value)
        elif effect_type == "AddMana":
            value = _leveled_fixed_value(
                effect,
                "powerMultiplierPerMil",
                "powerMultiplierIncrementPerLevelPerMil",
                max_level,
            )
            if value is not None:
                params[f"ABSPOWER{index}"] = abs(value / 10)
                params[f"POWER{index}"] = value / 10
    return {
        key: int(value) if isinstance(value, float) and value.is_integer() else value
        for key, value in params.items()
    }


def _clean_lang_markup(text: str) -> str:
    """Removes display markup used by the game language files."""
    if not text:
        return ""
    return re.sub(r"\[#!\]|\[#\]", "", text)


def _family_effect_lang_key(effect_id: str, lang_db: dict) -> str:
    """Maps a concrete family effect id to the shared family bonus lang key."""
    if not effect_id:
        return ""
    parts = effect_id.split("_")
    if len(parts) > 2:
        base_effect_id = "_".join(parts[:2])
        base_key = f"familybonuses.description.long.{base_effect_id}"
        if base_effect_id in {"attack_multiplier", "defense_multiplier", "heal_multiplier"} and base_key in lang_db:
            return base_key
    exact_key = f"familybonuses.description.long.{effect_id}"
    if exact_key in lang_db:
        return exact_key
    if len(parts) > 2:
        return f"familybonuses.description.long.{base_effect_id}"
    return exact_key


def _candidate_record(lang_id: str, lang_db: dict, source: str) -> dict:
    return {
        "lang_id": lang_id,
        "exists": bool(lang_id and lang_id in lang_db),
        "source": source,
    }


def _dedupe_candidates(candidates: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for candidate in candidates:
        lang_id = candidate.get("lang_id", "")
        if not lang_id or lang_id in seen:
            continue
        seen.add(lang_id)
        result.append(candidate)
    return result


def _lang_template_text(lang_id: str, lang_db: dict) -> str:
    template = lang_db.get(lang_id, {})
    return f"{template.get('en', '')}\n{template.get('ja', '')}"


def _template_placeholders(lang_id: str, lang_db: dict) -> set[str]:
    return set(re.findall(r"\{(\w+)\}", _lang_template_text(lang_id, lang_db)))


def _select_family_description_lang_id(family_id: str, lang_db: dict, rules: dict) -> dict:
    rules = rules or {}
    override = (rules.get("description_lang_id_overrides") or {}).get(family_id, "")
    candidates = []
    if override:
        candidates.append(_candidate_record(override, lang_db, "override"))

    patterns = (rules.get("candidate_patterns") or {}).get("family_description", [])
    for pattern in patterns:
        candidates.append(_candidate_record(pattern.format(family_id=family_id), lang_db, "pattern"))

    candidates = _dedupe_candidates(candidates)
    selected = next((c for c in candidates if c["source"] == "override" and c["exists"]), None)
    selected = selected or next((c for c in candidates if c["exists"]), None)
    selected = selected or (candidates[0] if candidates else {"lang_id": "", "exists": False, "source": "none"})
    return {
        "lang_id": selected.get("lang_id", ""),
        "method": selected.get("source", "none"),
        "candidates": candidates,
    }


def _select_family_effect_lang_id(effect_id: str, lang_db: dict, rules: dict) -> dict:
    rules = rules or {}
    override = (rules.get("effect_lang_id_overrides") or {}).get(effect_id, "")
    candidates = []
    if override:
        candidates.append(_candidate_record(override, lang_db, "override"))

    patterns = (rules.get("candidate_patterns") or {}).get("family_effect", [])
    for pattern in patterns:
        candidates.append(_candidate_record(pattern.format(effect_id=effect_id), lang_db, "pattern"))

    # Some family effects add semantic suffixes such as .onceperturn or
    # .minordebuff. Prefer long descriptions, then short descriptions.
    prefixes = [
        f"familybonuses.description.long.{effect_id}.",
        f"familybonuses.description.short.{effect_id}.",
    ]
    for prefix in prefixes:
        for key in sorted(k for k in lang_db if k.startswith(prefix)):
            candidates.append(_candidate_record(key, lang_db, "prefix_search"))

    fallback = _family_effect_lang_key(effect_id, lang_db)
    if fallback:
        candidates.append(_candidate_record(fallback, lang_db, "fallback"))

    candidates = _dedupe_candidates(candidates)
    selected = next((c for c in candidates if c["source"] == "override" and c["exists"]), None)
    selected = selected or next((c for c in candidates if c["exists"]), None)
    selected = selected or (candidates[0] if candidates else {"lang_id": "", "exists": False, "source": "none"})
    return {
        "lang_id": selected.get("lang_id", ""),
        "method": selected.get("source", "none"),
        "candidates": candidates,
    }


def _select_family_status_effect_lang_id(effect_data: dict, lang_db: dict) -> dict:
    """Selects long family status-effect template for nested family effect text."""
    status_effects = effect_data.get("statusEffects", [])
    first_ref = status_effects[0] if status_effects and isinstance(status_effects[0], dict) else {}
    status_effect_id = first_ref.get("id", "")
    status_name = (first_ref.get("statusEffect") or "").lower()
    if not status_name and status_effect_id:
        # Resolved familyEffect status effect references usually keep the full
        # status effect data in the same dict after Phase 1.
        status_name = (first_ref.get("statusEffect") or "").lower()

    candidates = []
    prefix = "familyeffect.statuseffect.long."
    for key in sorted(k for k in lang_db if k.startswith(prefix)):
        if "statuseffectperturn" not in key:
            continue
        if status_name and status_name not in key:
            continue
        if status_effect_id and status_effect_id not in key:
            # The richer template for Moth Dust intentionally ends with
            # `moth_dust` while the concrete game id is
            # `moth_dust_with_mega_minion_wound`; keep it as a candidate if it
            # exposes the nested placeholders we need.
            template_text = _lang_template_text(key, lang_db)
            if "{STATUSEFFECTS}" not in template_text:
                continue
        candidates.append(_candidate_record(key, lang_db, "family_status_effect_search"))

    def score(candidate: dict) -> tuple[int, str]:
        text = _lang_template_text(candidate["lang_id"], lang_db)
        value = 0
        if "{STATUSEFFECTS}" in text:
            value += 10
        if re.search(r"\{1MEMBERS?TURNS\}", text):
            value += 6
        if status_effect_id and status_effect_id in candidate["lang_id"]:
            value += 2
        return (-value, candidate["lang_id"])

    candidates = _dedupe_candidates(candidates)
    selected = sorted(candidates, key=score)[0] if candidates else {"lang_id": "", "exists": False, "source": "none"}
    return {
        "lang_id": selected.get("lang_id", ""),
        "method": selected.get("source", "none"),
        "candidates": candidates,
    }


def _family_bonus_percentages(raw_values: list) -> dict:
    """
    Converts statMultiplierIncrementPerMilsForEachMember into 2/3/4/5 member
    percentage params. The first playable value is offset from 1000, and later
    values are cumulative permil increments.
    """
    params = {}
    if not isinstance(raw_values, list) or len(raw_values) < 5:
        return params

    running_permil = 0
    for member_count in range(2, 6):
        raw_value = raw_values[member_count - 1]
        if not isinstance(raw_value, (int, float)):
            continue
        if member_count == 2:
            running_permil = raw_value - 1000
        else:
            running_permil += raw_value
        percent = running_permil / 10
        key = f"{member_count}MEMBERSMULTIPLIERPERCENTCHANGE"
        params[key] = f"+{format_value(percent)}"
    return params


def _cumulative_permils(raw_values: list) -> list[float]:
    if not isinstance(raw_values, list):
        return []
    total = 0
    values = []
    for value in raw_values:
        if not isinstance(value, (int, float)):
            continue
        total += value
        values.append(total / 10)
    return values


def _member_slots_from_placeholders(placeholders: set[str]) -> list[int]:
    members = set()
    for placeholder in placeholders:
        match = re.match(r"^(\d+)MEMBERS?", placeholder.upper())
        if match:
            members.add(int(match.group(1)))
    return sorted(members)


def _build_bonus_title(members: list[int]) -> dict:
    if not members:
        return {}
    joined = "/".join(str(member) for member in members)
    return {
        "members": members,
        "source": "template_placeholders",
        "en": f"Bonus for {joined} Heroes:",
        "ja": f"英雄数が{joined}人の場合に付与されるボーナス：",
    }


def _member_turn_params(effect_data: dict, placeholders: set[str]) -> dict:
    params = {}
    members = _member_slots_from_placeholders(placeholders)
    if not members:
        return params
    status_effects = effect_data.get("statusEffects", [])
    first_ref = status_effects[0] if status_effects and isinstance(status_effects[0], dict) else {}
    base_turns = first_ref.get("turns")
    increments = effect_data.get("statusEffectDurationIncrementForEachMember", [])
    if not isinstance(base_turns, (int, float)) or not isinstance(increments, list):
        return params
    for member in members:
        increment = sum(
            value for value in increments[:member]
            if isinstance(value, (int, float))
        )
        for placeholder in placeholders:
            if re.match(rf"^{member}MEMBERS?TURNS$", placeholder.upper()):
                params[placeholder] = format_value(base_turns + increment)
    return params


def _per_mil_change(value, base: int = 1000):
    if not isinstance(value, (int, float)):
        return None
    return format_value((value - base) / 10)


def _per_mil_percent(value):
    if not isinstance(value, (int, float)):
        return None
    return format_value(value / 10)


def _find_multieffect_child_lang_id(status_effect: dict, lang_db: dict) -> str:
    status_name = (status_effect.get("statusEffect") or "").lower()
    if not status_name:
        return ""
    prefix = f"multieffectchild.statuseffect."
    candidates = [key for key in lang_db if key.startswith(prefix) and status_name in key]
    if not candidates:
        return ""
    affected = {str(v).lower() for v in status_effect.get("affectedFamiliarTypes", []) if v}

    def score(key: str) -> tuple[int, str]:
        value = 0
        if status_effect.get("fullEffectToBigFamiliars") and "fulleffecttomegaminions" in key:
            value += 4
        if affected and any(item.lower() in key for item in affected):
            value += 2
        return (-value, key)

    return sorted(candidates, key=score)[0]


def _family_status_effect_child_params(status_effect: dict) -> dict:
    params = {}
    if "manaGenerationMultiplierPerMil" in status_effect:
        params["MANAREGEN"] = _per_mil_change(status_effect.get("manaGenerationMultiplierPerMil"))
    if "healthReductionPerMil" in status_effect:
        params["HEALTHREDUCTION"] = _per_mil_percent(status_effect.get("healthReductionPerMil"))
    return {k: v for k, v in params.items() if v is not None}


def _family_data_rows(data: dict, context: str = "family") -> list[dict]:
    rows = []

    def flatten(node, prefix=""):
        if isinstance(node, dict):
            for key, value in node.items():
                full = f"{prefix}{key}" if prefix else key
                if isinstance(value, dict):
                    flatten(value, full + "_")
                elif isinstance(value, list):
                    for idx, item in enumerate(value, start=1):
                        if isinstance(item, (dict, list)):
                            flatten(item, f"{full}_{idx}_")
                        else:
                            rows.append({"key": f"{full}_{idx}", "value": item, "calc": ""})
                else:
                    rows.append({"key": full, "value": value, "calc": _family_calc(key, value)})
        elif isinstance(node, list):
            for idx, item in enumerate(node, start=1):
                flatten(item, f"{prefix}{idx}_")

    def _family_calc(key: str, value):
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return ""
        if "IncrementPerLevel" in key or key.endswith("PerLevel"):
            return "ignored in family context"
        if key == "manaGenerationMultiplierPerMil":
            change = _per_mil_change(value)
            pct = _per_mil_percent(value)
            return f"{pct}% => {change}%"
        if key in {"healthReductionPerMil", "receivedDamageMultiplierPerMil"}:
            if key == "receivedDamageMultiplierPerMil":
                return f"+{_per_mil_change(value)}%"
            return f"{_per_mil_percent(value)}%"
        if key.endswith("PerMil"):
            return f"{_per_mil_percent(value)}%"
        return ""

    flatten(data)
    return rows


def _render_status_effect_text(lang_id: str, params: dict, lang_db: dict) -> dict:
    if not lang_id:
        return {"en": "", "ja": ""}
    desc = generate_description(lang_id, params, lang_db) if lang_id in lang_db else {"en": "", "ja": ""}
    return {
        "en": _clean_lang_markup(desc.get("en", "")),
        "ja": _clean_lang_markup(desc.get("ja", "")),
    }


def _build_family_status_effects(effect_data: dict, lang_db: dict, game_db: dict) -> list[dict]:
    result = []
    for ref in effect_data.get("statusEffects", []):
        if not isinstance(ref, dict):
            continue
        status_id = ref.get("id", "")
        status_data = game_db.get("status_effects", {}).get(status_id, {}).copy()
        merged = {**status_data, **ref}
        children = []
        child_texts = {"en": [], "ja": []}
        for child_id in merged.get("statusEffects", []):
            child_data = game_db.get("status_effects", {}).get(child_id, {})
            if not child_data:
                continue
            child_lang_id = _find_multieffect_child_lang_id(child_data, lang_db)
            child_params = _family_status_effect_child_params(child_data)
            child_rendered = _render_status_effect_text(child_lang_id, child_params, lang_db)
            children.append({
                "id": child_id,
                "statusEffect": child_data.get("statusEffect", ""),
                "lang_id": child_lang_id,
                "params": json.dumps(child_params, ensure_ascii=False),
                "en": child_rendered.get("en", ""),
                "ja": child_rendered.get("ja", ""),
                "raw": child_data,
                "data_rows": _family_data_rows(child_data),
            })
            if child_rendered.get("en"):
                child_texts["en"].append(f"[*]{child_rendered['en']}")
            if child_rendered.get("ja"):
                child_texts["ja"].append(f"[*]{child_rendered['ja']}")

        removal_params = {}
        removal_effects = []
        for removal_index, removal in enumerate(merged.get("removalEffects", []), start=1):
            for se_index, removal_ref in enumerate(removal.get("statusEffects", []), start=1):
                removal_id = removal_ref.get("id", "") if isinstance(removal_ref, dict) else ""
                removal_data = game_db.get("status_effects", {}).get(removal_id, {})
                damage_modifier = _per_mil_change(removal_data.get("receivedDamageMultiplierPerMil"))
                if damage_modifier is not None:
                    removal_params[f"REMOVALEFFECT{removal_index}STATUSEFFECT{se_index}DAMAGEMODIFIER"] = damage_modifier
                removal_effects.append({
                    "id": removal_id,
                    "statusEffect": removal_data.get("statusEffect", ""),
                    "params": json.dumps({"DAMAGEMODIFIER": damage_modifier}, ensure_ascii=False),
                    "raw": removal_data,
                    "data_rows": _family_data_rows(removal_data),
                })

        result.append({
            "id": status_id,
            "statusEffect": merged.get("statusEffect", ""),
            "params": json.dumps({}, ensure_ascii=False),
            "raw": merged,
            "data_rows": _family_data_rows(merged),
            "children": children,
            "child_texts": child_texts,
            "removal_effects": removal_effects,
            "removal_params": removal_params,
        })
    return result


def _family_effect_params(effect_data: dict, lang_id: str, lang_db: dict) -> dict:
    params = _family_bonus_percentages(effect_data.get("statMultiplierIncrementPerMilsForEachMember", []))
    template = lang_db.get(lang_id, {})
    template_text = f"{template.get('en', '')}\n{template.get('ja', '')}"
    placeholders = set(re.findall(r"\{(\w+)\}", template_text))
    multiplier_values = _cumulative_permils(effect_data.get("statMultiplierIncrementPerMilsForEachMember", []))
    chance_values = _cumulative_permils(effect_data.get("chanceIncrementsPerMilForEachMember", []))

    for placeholder in placeholders:
        upper = placeholder.upper()
        index_match = re.match(r"^(\d+)MEMBERS?", upper)
        index = int(index_match.group(1)) if index_match else 1
        if "MULTIPLIERPERCENT" in upper and "PERCENTCHANGE" not in upper and multiplier_values:
            value = multiplier_values[min(index - 1, len(multiplier_values) - 1)]
            params[placeholder] = format_value(value)
        elif "CHANCE" in upper and chance_values:
            value = chance_values[min(index - 1, len(chance_values) - 1)]
            params[placeholder] = format_value(value)
    params.update(_member_turn_params(effect_data, placeholders))
    return params


def parse_family_description(hero_data: dict, lang_db: dict, game_db: dict) -> dict:
    """Builds a dedicated family bonus block separate from skillDescriptions."""
    family_id = hero_data.get("family")
    if not family_id:
        return {}

    family_data = game_db.get("families", {}).get(family_id)
    if not family_data:
        return {
            "family_id": family_id,
            "status": "missing_family_data",
            "effects": []
        }

    family_rules = game_db.get("family_lang_rules", {})
    description_resolution = _select_family_description_lang_id(family_id, lang_db, family_rules)
    description_lang_id = description_resolution["lang_id"]
    description = generate_description(description_lang_id, {}, lang_db) if description_lang_id in lang_db else {"en": "", "ja": ""}

    parsed_effects = []
    for effect_ref in family_data.get("familyEffects", []):
        effect_id = effect_ref.get("id") if isinstance(effect_ref, dict) else effect_ref
        effect_data = game_db.get("family_effects", {}).get(effect_id, {})
        effect_resolution = _select_family_effect_lang_id(effect_id, lang_db, family_rules)
        lang_id = effect_resolution["lang_id"]
        family_status_resolution = {}
        family_status_effects = []
        if effect_data.get("effectType") == "StatusEffectPerTurn" and effect_data.get("statusEffects"):
            family_status_resolution = _select_family_status_effect_lang_id(effect_data, lang_db)
            if family_status_resolution.get("lang_id"):
                lang_id = family_status_resolution["lang_id"]
            family_status_effects = _build_family_status_effects(effect_data, lang_db, game_db)

        params = _family_effect_params(effect_data, lang_id, lang_db)
        if family_status_effects:
            if "STATUSEFFECTS" in _template_placeholders(lang_id, lang_db):
                # Use language-specific nested text when rendering below. Store
                # params with Japanese child text for debug; per-language render
                # is done manually just below.
                params["STATUSEFFECTS"] = "\n".join(family_status_effects[0].get("child_texts", {}).get("ja", []))
            for status_effect in family_status_effects:
                params.update(status_effect.get("removal_params", {}))
        formatted_params = {k: v for k, v in params.items()}
        if family_status_effects and "STATUSEFFECTS" in _template_placeholders(lang_id, lang_db):
            en_params = formatted_params.copy()
            ja_params = formatted_params.copy()
            en_params["STATUSEFFECTS"] = "\n".join(family_status_effects[0].get("child_texts", {}).get("en", []))
            ja_params["STATUSEFFECTS"] = "\n".join(family_status_effects[0].get("child_texts", {}).get("ja", []))
            effect_desc = {
                "en": generate_description(lang_id, en_params, lang_db).get("en", "") if lang_id in lang_db else "",
                "ja": generate_description(lang_id, ja_params, lang_db).get("ja", "") if lang_id in lang_db else "",
            }
        else:
            effect_desc = generate_description(lang_id, formatted_params, lang_db) if lang_id in lang_db else {"en": "", "ja": ""}
        placeholders = _template_placeholders(lang_id, lang_db)
        members = _member_slots_from_placeholders(placeholders)
        parsed_effects.append({
            "id": effect_id,
            "effectType": effect_data.get("effectType", ""),
            "lang_id": lang_id,
            "lang_id_method": family_status_resolution.get("method") or effect_resolution.get("method", ""),
            "lang_id_candidates": (family_status_resolution.get("candidates") or []) + effect_resolution.get("candidates", []),
            "bonus_title": _build_bonus_title(members),
            "params": json.dumps(params),
            "raw_values": effect_data.get("statMultiplierIncrementPerMilsForEachMember", []),
            "raw": effect_data,
            "data_rows": _family_data_rows(effect_data),
            "family_status_effects": family_status_effects,
            "en": _clean_lang_markup(effect_desc.get("en", "")),
            "ja": _clean_lang_markup(effect_desc.get("ja", "")),
        })

    improved_talent = {}
    if hero_data.get("hasImprovedTalentSkill"):
        level = 20
        talent_lang_id = f"hero.talentskill.advanced.name.class_level.{level}"
        talent_name = generate_description(talent_lang_id, {}, lang_db)
        params = {
            "0": level,
            "1": {
                "en": talent_name.get("en", ""),
                "ja": talent_name.get("ja", ""),
            }
        }
        improved_lang_id = "herocard.family.description.improved_talent_skill"
        improved_talent = {
            "lang_id": improved_lang_id,
            "params": json.dumps({"0": level, "1": talent_name.get("en", "")}, ensure_ascii=False),
            "en": generate_description(improved_lang_id, {"0": level, "1": talent_name.get("en", "")}, lang_db).get("en", ""),
            "ja": generate_description(improved_lang_id, {"0": level, "1": talent_name.get("ja", "")}, lang_db).get("ja", ""),
            "talent_lang_id": talent_lang_id,
            "talent_name": params["1"],
        }

    return {
        "family_id": family_id,
        "lang_id": description_lang_id,
        "lang_id_method": description_resolution.get("method", ""),
        "lang_id_candidates": description_resolution.get("candidates", []),
        "activeOnFullyAscendedMembersOnly": family_data.get("activeOnFullyAscendedMembersOnly", False),
        "en": _clean_lang_markup(description.get("en", "")),
        "ja": _clean_lang_markup(description.get("ja", "")),
        "effects": parsed_effects,
        "improved_talent_skill": improved_talent,
        "raw": family_data,
    }


# --- Core Data Integration Logic (Unchanged) ---
def get_full_hero_data(base_data: dict, game_db: dict) -> dict:
    resolved_data = json.loads(json.dumps(base_data))
    seen_objects = set()  # メモリアドレス：同一Pythonオブジェクトの再処理防止
    _resolve_recursive(resolved_data, game_db, seen_objects, frozenset())
    return resolved_data

def _lookup_reference(item_id: str, game_db: dict, list_context: str = None, field_context: str = None) -> dict:
    context_sources = {
        "properties": "special_properties",
        "statusEffects": "status_effects",
        "statusEffectsPerHit": "status_effects",
        "statusEffectsToAdd": "status_effects",
        "statusEffectCollections": "status_effects",
        "summonedFamiliars": "familiars",
        "effects": "familiar_effects",
        "passiveSkills": "passive_skills",
        "costumeBonusPassiveSkillIds": "passive_skills",
    }
    if field_context and field_context.lower() == "specialid":
        source = game_db.get("character_specials", {})
        if item_id in source:
            return source[item_id]
    if list_context in context_sources:
        source = game_db.get(context_sources[list_context], {})
        if item_id in source:
            return source[item_id]
    return game_db.get("master_db", {}).get(item_id)

def _resolve_recursive(current_data, game_db, seen_objects, id_chain, list_context=None):
    # 同一オブジェクトの再帰防止（ループ防止）
    if id(current_data) in seen_objects: return
    seen_objects.add(id(current_data))
    ID_KEYS_FOR_LISTS = ['properties','statusEffects','statusEffectsPerHit','summonedFamiliars','effects','passiveSkills','costumeBonusPassiveSkillIds','statusEffectsToAdd','statusEffectCollections']
    EXTRA_ID_KEYS = {'specialidifconditiontrue', 'specialidifconditionfalse'}
    if isinstance(current_data, dict):
        for key, value in list(current_data.items()):
            if (key.lower().endswith('id') or key.lower() in EXTRA_ID_KEYS) and isinstance(value, str):
                # id_chain で循環参照のみ防止。同じIDが別文脈で出現する場合は独立して解決する
                ref_data = _lookup_reference(value, game_db, field_context=key)
                if ref_data and value not in id_chain:
                    new_data = json.loads(json.dumps(ref_data))
                    _resolve_recursive(new_data, game_db, seen_objects, id_chain | {value})
                    current_data[f"{key}_details"] = new_data
            elif key in ID_KEYS_FOR_LISTS and isinstance(value, list):
                _resolve_recursive(value, game_db, seen_objects, id_chain, list_context=key)
            elif isinstance(value, (dict, list)):
                _resolve_recursive(value, game_db, seen_objects, id_chain)
    elif isinstance(current_data, list):
        for i, item in enumerate(current_data):
            item_id_to_resolve = item if isinstance(item, str) else (item.get('id') if isinstance(item, dict) else None)
            ref_data = _lookup_reference(item_id_to_resolve, game_db, list_context=list_context) if item_id_to_resolve else None
            if ref_data and item_id_to_resolve not in id_chain:
                new_data = json.loads(json.dumps(ref_data))
                _resolve_recursive(new_data, game_db, seen_objects, id_chain | {item_id_to_resolve})
                if isinstance(current_data[i], str): current_data[i] = new_data
                else: current_data[i].update(new_data)
            elif isinstance(item, (dict, list)):
                _resolve_recursive(item, game_db, seen_objects, id_chain, list_context=list_context)

# --- Analysis & Parsing Functions (Unchanged) ---
def get_hero_final_stats(hero_id: str, hero_stats_db: dict) -> dict:
    hero_data = hero_stats_db.get(hero_id)
    if not hero_data: return {"max_attack": 0, "name": "N/A"}
    attack_col = "Max Attack"
    costume_num = str(hero_data.get("Costume#", "")).strip()
    if costume_num:
        costume_attack_col = f"CB{costume_num} Max Attack"
        if hero_data.get(costume_attack_col):
            attack_col = costume_attack_col
    attack = hero_data.get(attack_col) or hero_data.get("attack") or 0
    try:
        max_attack = int(float(attack))
    except (TypeError, ValueError):
        max_attack = 0
    return {"max_attack": max_attack, "name": hero_data.get("Name_EN") or hero_data.get("Name") or "N/A"}

def find_and_calculate_value(p_holder: str, data_block: dict, max_level: int, hero_id: str, rules: dict, is_modifier: bool = False, ignore_keywords: list = None) -> (any, str):
    p_holder_upper = p_holder.upper()
    rule = rules.get("hero_rules", {}).get("specific", {}).get(hero_id, {}).get(p_holder_upper)
    if not rule: rule = rules.get("hero_rules", {}).get("common", {}).get(p_holder_upper)
    if rule:
        if rule.get("calc") == "fixed":
            value_str = rule.get("value")
            try: return int(value_str), "Fixed Rule"
            except (ValueError, TypeError):
                try: return float(value_str), "Fixed Rule"
                except (ValueError, TypeError): return value_str, "Fixed Rule"
        if key_to_find := rule.get("key"):
            flat_data = flatten_json(data_block)
            matching_keys = [k for k in flat_data if k.endswith(key_to_find)]
            if len(matching_keys) == 1:
                found_key = matching_keys[0]; value = flat_data[found_key]
                if isinstance(value, (int, float)):
                    if 'permil' in found_key.lower(): return value / 10, f"Exception Rule: {found_key}"
                    return int(value), f"Exception Rule: {found_key}"
        return None, f"Exception rule key '{key_to_find}' not found or ambiguous"
    if not isinstance(data_block, dict): return None, None
    explicit_params = _increasing_status_effect_params(data_block, max_level, {p_holder_upper})
    if p_holder_upper in explicit_params:
        return explicit_params[p_holder_upper], f"Explicit Rule: {p_holder_upper}"
    flat_data = flatten_json(data_block)
    if ignore_keywords:
        keys_to_remove = {k for k in flat_data if any(ik in k.lower() for ik in ignore_keywords)}
        for k in keys_to_remove: del flat_data[k]
    ph_keywords = _placeholder_keywords(p_holder)
    candidates = []
    for key, value in flat_data.items():
        if not isinstance(value, (int, float)): continue
        key_lower = key.lower()
        normalized_key = re.sub(r"[^a-z0-9]+", "", key_lower).replace("increment", "increase")
        matched_keywords = sum(1 for kw in ph_keywords if kw in key_lower)
        matched_keywords += sum(2 for kw in ph_keywords if kw in normalized_key and kw not in key_lower)
        if matched_keywords > 0:
            score = matched_keywords * 10
            if 'power' in key_lower or 'modifier' in key_lower: score += 5
            if 'permil' in key_lower: score += 3
            candidates.append({'key': key, 'score': score})
    if not candidates: return None, None
    best_candidate = sorted(candidates, key=lambda x: (-x['score'], len(x['key'])))[0]
    found_key = best_candidate['key']; base_val = flat_data.get(found_key, 0)
    inc_key = None
    if found_key.endswith("PerMil"):
        potential_inc_key = found_key.replace("PerMil", "PerLevelPerMil")
        if potential_inc_key in flat_data: inc_key = potential_inc_key
    if not inc_key:
        potential_inc_key = found_key.replace("PerMil", "IncrementPerLevelPerMil")
        if potential_inc_key in flat_data: inc_key = potential_inc_key
    if not inc_key:
        if found_key.islower(): potential_inc_key = found_key + "incrementperlevel"
        else: potential_inc_key = re.sub(r'([a-z])([A-Z])', r'\1IncrementPerLevel\2', found_key)
        if potential_inc_key in flat_data: inc_key = potential_inc_key
    inc_val = flat_data.get(inc_key, 0)
    if not isinstance(inc_val, (int, float)): inc_val = 0
    calculated_val = base_val + inc_val * (max_level - 1)
    if is_modifier or 'modifier' in found_key.lower():
        return ((base_val - 1000) + (inc_val * (max_level - 1))) / 10, found_key
    if 'permil' in found_key.lower(): return calculated_val / 10, found_key
    return int(calculated_val), found_key

def _collect_keywords_recursively(data_block, depth=0, max_depth=2) -> list:
    if depth > max_depth: return []
    keywords = []
    if isinstance(data_block, dict):
        for key, value in data_block.items():
            if isinstance(value, str): keywords.append((value.lower(), depth))
        list_keys_to_scan = ['statusEffects','effects','statusEffectsToAdd','statusEffectCollections','properties']
        for key in list_keys_to_scan:
            if key in data_block and isinstance(data_block[key], list):
                for item in data_block[key]: keywords.extend(_collect_keywords_recursively(item, depth + 1, max_depth))
    elif isinstance(data_block, list):
        for item in data_block: keywords.extend(_collect_keywords_recursively(item, depth + 1, max_depth))
    return keywords

def find_best_lang_id(data_block: dict, lang_key_subset: list, parsers: dict, parent_block: dict = None) -> (str, str):
    if data_block.get("statusEffect") == "MoonBeamStatusEffectSkill":
        moonbeam_lang_id = _moonbeam_lang_id(data_block, lang_key_subset)
        if moonbeam_lang_id:
            return moonbeam_lang_id, None

    if 'statusEffect' in data_block:
        buff_map = {"MinorDebuff":"minor","MajorDebuff":"major","MinorBuff":"minor","MajorBuff":"major",
                    "StackMinorDebuff":"minor","StackMajorDebuff":"major",
                    "StackMinorBuff":"minor","StackMajorBuff":"major",
                    "PermanentDebuff":"permanent","PermanentBuff":"permanent"}
        intensity = buff_map.get(data_block.get('buff'))
        status_effect_val = data_block.get('statusEffect'); effect_name = status_effect_val.lower() if isinstance(status_effect_val, str) else None
        parent_block = parent_block or {}
        target_from_data = data_block.get('statusTargetType') or parent_block.get('statusTargetType', '')
        target = target_from_data.lower() if isinstance(target_from_data, str) else ''
        side_from_data = data_block.get('sideAffected') or parent_block.get('sideAffected', '')
        side = side_from_data.lower() if isinstance(side_from_data, str) else ''
        if all([intensity, effect_name, target, side]):
            constructed_id = f"specials.v2.statuseffect.{intensity}.{effect_name}.{target}.{side}"
            if constructed_id in lang_key_subset: return constructed_id, None
    contextual_block = {**data_block, "parent": parent_block}
    all_keywords_with_depth = _collect_keywords_recursively(contextual_block, depth=0)
    seen_keywords = {}
    for kw, depth in all_keywords_with_depth:
        if kw not in seen_keywords or depth < seen_keywords[kw]: seen_keywords[kw] = depth
    potential_matches = []
    for lang_key in lang_key_subset:
        score = 0; lang_key_parts = lang_key.lower().split('.')
        for kw, depth in seen_keywords.items():
            if kw in lang_key_parts: score += 100 / (2 ** depth)
        familiar_type = data_block.get("familiarType", "").lower()
        if familiar_type:
            if ("minion" in familiar_type and "allies" in lang_key_parts): score += 20
            if ("parasite" in familiar_type and "enemies" in lang_key_parts): score += 20
        if 'fixedpower' in lang_key_parts and 'hasfixedpower' in seen_keywords: score += 3
        if 'decrement' in lang_key_parts and any(isinstance(v, (int, float)) and v < 0 for v in data_block.values()): score += 2
        if score > 0: potential_matches.append({'key': lang_key, 'score': score, 'parts': lang_key_parts})
    if not potential_matches:
        primary_keyword = (data_block.get('propertyType') or data_block.get('statusEffect') or data_block.get('familiarType') or 'N/A')
        return None, f"Could not find lang_id for skill '{data_block.get('id', 'UNKNOWN')}' (type: {primary_keyword})"
    potential_matches.sort(key=lambda x: (-x['score'], len(x['key'])))
    if "familiar_debug_log" in parsers and data_block.get('familiarType'):
        log_entry = {"familiar_id":data_block.get('id'),"familiar_instance":data_block,"top_candidates":[{'score':f"{m['score']:.2f}",'key':m['key']} for m in potential_matches[:5]]}
        parsers["familiar_debug_log"].append(log_entry)
    return potential_matches[0]['key'], None

def parse_clear_buffs(special_data: dict, lang_db: dict, parsers: dict) -> (dict, list):
    if "buffToRemove" not in special_data: return None, []
    warnings = []
    try:
        buff_to_remove = special_data.get("buffToRemove", "").lower(); target_type = special_data.get("buffToRemoveTargetType", "all").lower()
        side_affected = ""
        if "debuff" in buff_to_remove: side_affected = "allies"
        elif "buff" in buff_to_remove: side_affected = "enemies"
        if not side_affected: side_affected = special_data.get("buffToRemoveSideAffected", "").lower()
        if not side_affected: side_affected = special_data.get("sideAffected", "").lower()
        if not side_affected: side_affected = special_data.get("directEffect", {}).get("sideAffected", "").lower()
        if not side_affected: side_affected = "allies" if "debuff" in buff_to_remove else "enemies"
        lang_id = f"specials.v2.clearbuffs.{buff_to_remove}.{target_type}.{side_affected}"
        if lang_id not in lang_db and lang_id + ".latest" in lang_db: lang_id += ".latest"
        description = generate_description(lang_id, {}, lang_db)
        result = {"id":"clear_buffs_effect","lang_id":lang_id,"params":"{}","nested_effects":[],**description}
        return result, warnings
    except Exception as e:
        warnings.append(f"Error parsing clear_buffs for '{special_data.get('id', 'Unknown Special')}': {e}")
        return None, warnings

def parse_direct_effect(special_data, hero_stats, lang_db, game_db, hero_id: str, rules: dict, parsers: dict):
    effect_data = special_data.get("directEffect") if isinstance(special_data, dict) else None
    if not effect_data or not effect_data.get("effectType"): return {"id": "direct_effect_no_type", "lang_id": "N/A", "params": "{}", "en": "", "ja": ""}
    try:
        effect_type_str = effect_data.get('effectType', '')
        parts = ["specials.v2.directeffect", effect_type_str.lower()]
        if t := effect_data.get('typeOfTarget'): parts.append(t.lower())
        if s := effect_data.get('sideAffected'): parts.append(s.lower())
        lang_id = ".".join(parts)
        if effect_type_str == "AddMana":
            power_value = effect_data.get('powerMultiplierPerMil', 0)
            if power_value > 0: lang_id += ".increment"
            elif power_value < 0: lang_id += ".decrement"
        if effect_data.get("hasFixedPower"): lang_id += ".fixedpower"
    except AttributeError: return {"id": "direct_effect_error", "lang_id": "N/A", "params": "{}", "en": "Error parsing", "ja": "解析エラー"}
    params = {}
    max_level = special_data.get("maxLevel", parsers.get("main_max_level", 8))
    base = effect_data.get('powerMultiplierPerMil', 0); inc = effect_data.get('powerMultiplierIncrementPerLevelPerMil', 0)
    p_map = {"Damage":"HEALTH","Heal":"HEALTH","HealthBoost":"HEALTHBOOST","AddMana":"MANA"}
    placeholder = p_map.get(effect_type_str, "VALUE")
    total_per_mil = base + inc * (max_level - 1)
    if base > 0 or inc > 0:
        final_val = round(total_per_mil) if effect_data.get("hasFixedPower") else (round(total_per_mil/100) if effect_type_str=="AddMana" else round(total_per_mil/10))
        params[placeholder] = final_val
    elif base < 0 or inc < 0:
        params[placeholder] = abs(round(total_per_mil / 100))
    desc = generate_description(lang_id, params, lang_db)
    return {"id": "direct_effect", "lang_id": lang_id, "params": json.dumps(params), **desc}

def parse_properties(properties_list: list, special_data: dict, hero_stats: dict, lang_db: dict, game_db: dict, hero_id: str, rules: dict, parsers: dict) -> (list, list):
    if not properties_list: return [], []
    parsed_items = []; warnings = []
    main_max_level = special_data.get("maxLevel", 8)
    parsers["main_max_level"] = main_max_level
    prop_lang_subset = parsers['prop_lang_subset']
    for prop_id_or_dict in properties_list:
        prop_data, prop_id = {}, None
        if isinstance(prop_id_or_dict, dict): prop_data, prop_id = prop_id_or_dict, prop_id_or_dict.get('id')
        elif isinstance(prop_id_or_dict, str): prop_id, prop_data = prop_id_or_dict, game_db['special_properties'].get(prop_id_or_dict, {})
        if not prop_data or not prop_id: continue
        property_type = prop_data.get("propertyType") or prop_data.get("statusEffect", "")
        container_types = {"changing_tides":"RotatingSpecial","charge_ninja":"ChargedSpecial","charge_magic":"ChargedSpecial"}
        if parsers.get("hero_mana_speed_id") in container_types and property_type == container_types[parsers.get("hero_mana_speed_id")]:
            container_lang_ids = {"changing_tides":"specials.v2.property.evolving_special","charge_ninja":"specials.v2.property.chargedspecial.3","charge_magic":"specials.v2.property.chargedspecial.2"}
            container_headings = {"changing_tides":{"en":["1st:","2nd:"],"ja":["第1:","第2:"]},"charge_ninja":{"en":["x1 Mana Charge:","x2 Mana Charge:","x3 Mana Charge:"],"ja":["x1マナチャージ:","x2マナチャージ:","x3マナチャージ:"]},"charge_magic":{"en":["x1 Mana Charge:","x2 Mana Charge:"],"ja":["x1マナチャージ:","x2マナチャージ:"]}}
            container_lang_id = container_lang_ids.get(parsers.get("hero_mana_speed_id"))
            container_desc = generate_description(container_lang_id, {}, lang_db)
            nested_effects = []
            sub_specials_list = prop_data.get("specialIds", [])
            headings = container_headings.get(parsers.get("hero_mana_speed_id"), {})
            for i, sub_special_data in enumerate(sub_specials_list):
                if not isinstance(sub_special_data, dict) or not sub_special_data: continue
                heading_en = headings.get("en", [])[i] if i < len(headings.get("en", [])) else f"Level {i+1}:"
                heading_ja = headings.get("ja", [])[i] if i < len(headings.get("ja", [])) else f"レベル {i+1}:"
                nested_effects.append({"id":"heading","description_en":heading_en,"description_ja":heading_ja})
                if "directEffect" in sub_special_data:
                    nested_effects.append(parsers['direct_effect'](sub_special_data, hero_stats, lang_db, game_db, hero_id, rules, parsers))
                if "properties" in sub_special_data:
                    parsed_props, new_warnings = parsers['properties'](sub_special_data.get("properties",[]), sub_special_data, hero_stats, lang_db, game_db, hero_id, rules, parsers)
                    nested_effects.extend(parsed_props); warnings.extend(new_warnings)
                if "statusEffects" in sub_special_data:
                    parsed_ses, new_warnings = parsers['status_effects'](sub_special_data.get("statusEffects",[]), sub_special_data, hero_stats, lang_db, game_db, hero_id, rules, parsers)
                    nested_effects.extend(parsed_ses); warnings.extend(new_warnings)
            parsed_items.append({"id":prop_id,"lang_id":container_lang_id,"description_en":container_desc["en"],"description_ja":container_desc["ja"],"params":"{}","nested_effects":nested_effects})
            continue
        if property_type == "BranchingSpecial":
            # 分岐条件テキストの lang_id を special.title.branching_special.* 空間から検索
            branching_lang_subset = [k for k in lang_db if k.startswith("special.title.branching_special")]
            cond_lang_id, warning = find_best_lang_id(prop_data, branching_lang_subset, parsers)
            if warning: warnings.append(warning)
            if not cond_lang_id: cond_lang_id = "SEARCH_FAILED"
            cond_desc = generate_description(cond_lang_id, {}, lang_db)
            nested_effects = []
            for branch_key, label_en, label_ja in [
                ("specialIdIfConditionTrue_details",  "If True:",  "条件True:"),
                ("specialIdIfConditionFalse_details", "If False:", "条件False:"),
            ]:
                branch_special = prop_data.get(branch_key)
                if not isinstance(branch_special, dict) or not branch_special: continue
                nested_effects.append({"id": "heading", "description_en": label_en, "description_ja": label_ja})
                if branch_special.get("directEffect", {}).get("effectType"):
                    nested_effects.append(parsers['direct_effect'](branch_special, hero_stats, lang_db, game_db, hero_id, rules, parsers))
                if "properties" in branch_special:
                    parsed_props, new_warns = parsers['properties'](branch_special.get("properties", []), branch_special, hero_stats, lang_db, game_db, hero_id, rules, parsers)
                    nested_effects.extend(parsed_props); warnings.extend(new_warns)
                if "statusEffects" in branch_special:
                    parsed_ses, new_warns = parsers['status_effects'](branch_special.get("statusEffects", []), branch_special, hero_stats, lang_db, game_db, hero_id, rules, parsers)
                    nested_effects.extend(parsed_ses); warnings.extend(new_warns)
            parsed_items.append({"id": prop_id, "lang_id": cond_lang_id, "params": "{}", "nested_effects": nested_effects, **cond_desc})
            continue
        lang_id = rules.get("lang_overrides",{}).get("specific",{}).get(hero_id,{}).get(prop_id) or rules.get("lang_overrides",{}).get("common",{}).get(prop_id)
        if not lang_id:
            lang_id = _base_stat_property_lang_id(prop_data, lang_db)
        if not lang_id:
            lang_id, warning = find_best_lang_id(prop_data, prop_lang_subset, parsers, parent_block=special_data)
            if warning: warnings.append(warning)
        if not lang_id:
            parsed_items.append({"id":prop_id,"lang_id":"SEARCH_FAILED","en":f"Failed for {prop_id}","params":"{}"}); continue
        if property_type == "BypassDefensiveBuffs" and prop_data.get("bypassChancePerMil") == 1000:
            always_lang_id = "specials.v2.property.bypassdefensivebuffs.bypass_always"
            if always_lang_id in lang_db:
                lang_id = always_lang_id
        lang_params = {}; search_context = {**prop_data, "maxLevel": main_max_level}
        if property_type in {"Wither", "Growth"}:
            lang_params.update(_base_stat_property_params(prop_data, main_max_level))
        placeholders = set(re.findall(r'\{(\w+)\}', lang_db.get(lang_id,{}).get("en","")))
        for p_holder in placeholders:
            if p_holder in lang_params:
                continue
            value, _ = find_and_calculate_value(p_holder, search_context, main_max_level, hero_id, rules, is_modifier='modifier' in property_type.lower())
            if value is not None: lang_params[p_holder] = value
        main_desc = generate_description(lang_id, {k:format_value(v) for k,v in lang_params.items()}, lang_db)
        nested_effects = []
        if 'statusEffects' in prop_data:
            parsed_ses, new_warnings = parsers['status_effects'](prop_data['statusEffects'], special_data, hero_stats, lang_db, game_db, hero_id, rules, parsers)
            nested_effects.extend(parsed_ses); warnings.extend(new_warnings)
        
        property_extra_rule = game_db.get("property_extra_rules", {}).get(property_type, {})
        if property_extra_rule:
            extra_info = _extra_from_rule(property_extra_rule, lang_db)
        elif property_type == "BypassDefensiveBuffs" and _has_extra_description(game_db, property_type) and "specials.v2.property.bypassdefensivebuffs.extra" in lang_db:
            extra_info = {"lang_id": "specials.v2.property.bypassdefensivebuffs.extra", "params": "{}", **generate_description("specials.v2.property.bypassdefensivebuffs.extra", {}, lang_db)}
        elif _has_extra_description(game_db, property_type):
            extra_info = _find_and_parse_extra_description(["specialproperty", "property"], property_type, search_context, lang_params, lang_db, hero_id, rules, parsers)
        else:
            extra_info = {}
        
        result_item = {"id":prop_id,"lang_id":lang_id,"params":json.dumps(lang_params),"nested_effects":nested_effects,**main_desc}
        if extra_info: result_item["extra"] = extra_info
        parsed_items.append(result_item)
    return parsed_items, warnings

def parse_status_effects(status_effects_list: list, special_data: dict, hero_stats: dict, lang_db: dict, game_db: dict, hero_id: str, rules: dict, parsers: dict) -> (list, list):
    if not status_effects_list: return [], []
    parsed_items = []; warnings = []
    main_max_level = special_data.get("maxLevel", 8)
    se_lang_subset = parsers['se_lang_subset']
    for effect_instance in status_effects_list:
        if not isinstance(effect_instance, dict): continue
        effect_id = effect_instance.get("id"); combined_details = effect_instance
        if not effect_id: continue
        # Phase1でbattle.jsonのデータがマージされなかった場合、game_dbから直接補完する
        if 'statusEffect' not in combined_details:
            se_from_db = game_db.get('status_effects', {}).get(effect_id, {})
            if se_from_db:
                combined_details = {**se_from_db, **combined_details}
        lang_id = rules.get("lang_overrides",{}).get("specific",{}).get(hero_id,{}).get(effect_id) or rules.get("lang_overrides",{}).get("common",{}).get(effect_id)
        if not lang_id:
            lang_id, warning = find_best_lang_id(combined_details, se_lang_subset, parsers, parent_block=special_data)
            if warning: warnings.append(warning)
        if not lang_id:
            parsed_items.append({"id":effect_id,"lang_id":"SEARCH_FAILED","en":f"Failed for {effect_id}","params":"{}"}); continue
        lang_params = {}; search_context = {**combined_details, "maxLevel": main_max_level}
        if (turns := combined_details.get("turns", 0)) > 0: lang_params["TURNS"] = turns
        if combined_details.get("statusEffect") == "MoonBeamStatusEffectSkill":
            lang_params.update(_moonbeam_params(combined_details, main_max_level))
        template_text = lang_db.get(lang_id,{}).get("en","")
        placeholders = set(re.findall(r'\{(\w+)\}', template_text))
        lang_params.update(_increasing_status_effect_params(combined_details, main_max_level, placeholders))
        for p_holder in placeholders:
            if p_holder in lang_params: continue
            value, found_key = find_and_calculate_value(p_holder, search_context, main_max_level, hero_id, rules, is_modifier='modifier' in combined_details.get('statusEffect','').lower())
            if value is not None:
                if p_holder.upper() == "DAMAGE" and "permil" in (found_key or "").lower():
                    turns_for_calc = combined_details.get("turns",0)
                    damage_per_turn = math.floor((value/100) * hero_stats.get("max_attack",0))
                    lang_params[p_holder] = damage_per_turn * (turns_for_calc or 1) if "over {TURNS} turns" in template_text else damage_per_turn
                else: lang_params[p_holder] = value
        main_desc = generate_description(lang_id, {k:format_value(v) for k,v in lang_params.items()}, lang_db)
        nested_effects = []
        if 'statusEffectsToAdd' in combined_details:
             parsed_nested_ses, new_warnings = parsers['status_effects'](combined_details['statusEffectsToAdd'], special_data, hero_stats, lang_db, game_db, hero_id, rules, parsers)
             nested_effects.extend(parsed_nested_ses); warnings.extend(new_warnings)
        status_effect_type = combined_details.get("statusEffect","")
        
        if _has_extra_description(game_db, status_effect_type) or _has_extra_description(game_db, effect_id):
            extra_info = _find_and_parse_extra_description(["statuseffect"], status_effect_type, search_context, lang_params, lang_db, hero_id, rules, parsers)
        else:
            extra_info = {}
        
        result_item = {"id":effect_id,"lang_id":lang_id,"params":json.dumps(lang_params),"nested_effects":nested_effects,**main_desc}
        if extra_info: result_item["extra"] = extra_info
        parsed_items.append(result_item)
    return parsed_items, warnings

def parse_familiars(familiars_list: list, special_data: dict, hero_stats: dict, lang_db: dict, game_db: dict, hero_id: str, rules: dict, parsers: dict) -> (list, list):
    if not familiars_list: return [], []
    parsed_items = []; warnings = []
    main_max_level = special_data.get("maxLevel", 8)
    all_familiar_lang_ids = [k for k in lang_db if k.startswith("specials.v2.")]
    for familiar_instance in familiars_list:
        familiar_id = familiar_instance.get("id")
        if not familiar_id: continue
        primary_candidates = [k for k in all_familiar_lang_ids if familiar_id in k]
        lang_id, warning = (find_best_lang_id(familiar_instance, primary_candidates, parsers) if primary_candidates else find_best_lang_id(familiar_instance, all_familiar_lang_ids, parsers))
        if warning: warnings.append(warning)
        if not lang_id:
            parsed_items.append({"id":familiar_id,"lang_id":"SEARCH_FAILED","description_en":f"Failed for familiar {familiar_id}","nested_effects":[]}); continue
        lang_params = {}; search_context = {**familiar_instance, "maxLevel": main_max_level}
        placeholders = set(re.findall(r'\{(\w+)\}', lang_db.get(lang_id,{}).get("en","")))
        health_val = familiar_instance.get('healthPerMil',0); inc_val_health = familiar_instance.get('healthPerLevelPerMil',0)
        lang_params['FAMILIARHEALTHPERCENT'] = (health_val + inc_val_health * (main_max_level - 1)) / 10.0
        log_entry = {'hero_id':hero_id,'familiar_id':familiar_id,'raw_healthPerMil':health_val,'calculated_health':lang_params['FAMILIARHEALTHPERCENT']}
        attack_found = False
        if effects := familiar_instance.get('effects'):
            for effect in effects:
                if isinstance(effect,dict) and 'attackPercentPerMil' in effect:
                    attack_val = effect.get('attackPercentPerMil',0)
                    inc_val_attack = effect.get('attackPercentIncrementPerLevelPerMil',0) if "parasite" in familiar_instance.get("familiarType","").lower() else 0
                    lang_params['FAMILIARATTACK'] = (attack_val + inc_val_attack * (main_max_level - 1)) / 10.0
                    log_entry.update({'raw_attackPercentPerMil':attack_val,'raw_attackIncrement':inc_val_attack,'calculated_attack':lang_params['FAMILIARATTACK']})
                    attack_found = True; break
        if not attack_found: log_entry['raw_attackPercentPerMil'] = 'NOT_FOUND'
        parsers["familiar_parameter_log"].append(log_entry)
        for p_holder in placeholders - set(lang_params.keys()):
            value, _ = find_and_calculate_value(p_holder, familiar_instance, main_max_level, hero_id, rules, is_modifier=False, ignore_keywords=['monster'])
            if value is not None: lang_params[p_holder] = value
        main_desc = generate_description(lang_id, {k:format_value(v) for k,v in lang_params.items()}, lang_db)
        main_desc['en'], main_desc['ja'] = main_desc['en'].replace('[*]','\n・').strip(), main_desc['ja'].replace('[*]','\n・').strip()
        nested_effects = []
        if 'effects' in familiar_instance:
            nested_effects, new_warnings = _parse_familiar_effects(familiar_instance, lang_db, hero_stats, game_db, hero_id, rules, parsers)
            warnings.extend(new_warnings)
        familiar_type = familiar_instance.get("familiarType","")
        
        extra_info = _find_and_parse_extra_description(["familiartype"], familiar_type, search_context, lang_params, lang_db, hero_id, rules, parsers)
        
        result_item = {"id":familiar_id,"lang_id":lang_id,"params":json.dumps(lang_params),"nested_effects":nested_effects,"description_en":main_desc['en'],"description_ja":main_desc['ja']}
        if extra_info: result_item["extra"] = extra_info
        parsed_items.append(result_item)
    return parsed_items, warnings

def _parse_familiar_effects(familiar_instance: dict, lang_db: dict, hero_stats: dict, game_db: dict, hero_id: str, rules: dict, parsers: dict) -> (list, list):
    effects_list = familiar_instance.get("effects", [])
    if not effects_list: return [], []
    parsed_effects = []; warnings = []
    main_max_level = parsers.get("main_max_level", 8)
    familiar_id = familiar_instance.get("id", "")
    all_effect_lang_ids = [k for k in lang_db if familiar_id in k and (k.startswith("specials.v2.") or k.startswith("familiar.statuseffect."))]
    for effect_data in effects_list:
        effect_id = effect_data.get("id"); context_block = {**familiar_instance, **effect_data}
        if not effect_id: continue
        effect_type_keyword = effect_data.get('effectType',"")
        primary_candidates = [k for k in all_effect_lang_ids if (effect_type_keyword and effect_type_keyword in k) or (effect_id and effect_id in k)]
        lang_id, warning = (find_best_lang_id(context_block, primary_candidates, parsers) if primary_candidates else find_best_lang_id(context_block, all_effect_lang_ids, parsers))
        if warning: warnings.append(warning)
        if not lang_id:
            parsed_effects.append({"id":effect_id,"lang_id":"SEARCH_FAILED","en":f"Failed for familiar effect {effect_id}","params":"{}"}); continue
        lang_params = {}; search_context = {**effect_data, "maxLevel": main_max_level}
        placeholders = set(re.findall(r'\{(\w+)\}', lang_db.get(lang_id,{}).get("en","")))
        for p_holder in placeholders:
            value, _ = find_and_calculate_value(p_holder, context_block, main_max_level, hero_id, rules, is_modifier=False)
            if value is not None: lang_params[p_holder] = value
        if 'FAMILIAREFFECTFREQUENCY' in placeholders and 'turnsBetweenNonDamageEffects' in familiar_instance:
             lang_params['FAMILIAREFFECTFREQUENCY'] = familiar_instance['turnsBetweenNonDamageEffects'] + 1
        main_desc = generate_description(lang_id, {k:format_value(v) for k,v in lang_params.items()}, lang_db)

        extra_info = _find_and_parse_extra_description(["familiareffect"], effect_type_keyword, search_context, lang_params, lang_db, hero_id, rules, parsers)
        
        result_item = {"id":effect_id,"lang_id":lang_id,"params":json.dumps(lang_params),**main_desc}
        if extra_info: result_item["extra"] = extra_info
        parsed_effects.append(result_item)
    return parsed_effects, warnings


def _source_passive_hint(game_db: dict, hero_id: str, skill_id: str, display_label: str) -> dict:
    source = game_db.get("source_texts", {}).get(hero_id, {})
    for item in source.get("passives", []):
        if item.get("passive_id_hint") == skill_id:
            return item
    for item in source.get("passives", []):
        if display_label and item.get("slot", "").replace("_", " ").lower() == display_label.lower():
            return item
    return {}


def _resolve_passive_lang_ids_from_source(skill_data: dict, source_hint: dict, lang_db: dict) -> tuple[str, str, str]:
    if not source_hint:
        return "", "", ""
    try:
        from passive_lang_reverse_search import passive_context, score_record
    except Exception:
        return "", "", ""

    context = passive_context(skill_data)
    records = [
        {"id": key, "en": value.get("en", ""), "ja": value.get("ja", "")}
        for key, value in lang_db.items()
    ]

    def best(mode: str, keywords: list[str]) -> str:
        scored = []
        for record in records:
            lang_id = record["id"]
            if mode == "title" and not lang_id.startswith("herocard.passive_skill.title."):
                continue
            if mode != "title" and lang_id.startswith("herocard.passive_skill.title."):
                continue
            if not any(keyword and keyword in record["ja"] for keyword in keywords):
                continue
            score, _reasons = score_record(record, keywords, context, mode)
            if score > 0:
                scored.append((score, lang_id))
        if not scored:
            return ""
        return sorted(scored, key=lambda item: (-item[0], item[1]))[0][1]

    title_lang_id = best("title", [source_hint.get("name", "")])
    desc_lang_id = best("description", source_hint.get("keywords", []))
    return title_lang_id, desc_lang_id, source_hint.get("icon", "")


def _passive_explicit_params(skill_data: dict, hero_stats: dict, main_max_level: int, master_row: dict = None) -> dict:
    params = {}
    change_formula = (master_row or {}).get("change_formula", "")

    for effect in skill_data.get("directEffectsOnResist") or []:
        effect_type = effect.get("effectType", "")
        if effect_type == "HealthBoost" and "fixedPower" in effect:
            params["HEALTHBOOST"] = effect.get("fixedPower")
        if effect_type == "AddMana" and "powerMultiplierPerMil" in effect:
            params["MANA"] = effect.get("powerMultiplierPerMil", 0) / 10

    for status_effect in skill_data.get("statusEffects") or []:
        if "turns" in status_effect:
            params["TURNS"] = status_effect.get("turns")

        base = status_effect.get("damageMultiplierPerMil")
        inc = status_effect.get("damageMultiplierIncrementPerLevelPerMil", 0)
        if base is not None:
            multiplier = (base + inc * (main_max_level - 1)) / 1000
            params["DAMAGEPERTURN"] = math.floor(multiplier * hero_stats.get("max_attack", 0))
        if "multiplierPerMil" in status_effect:
            if change_formula == "increment_abs":
                # CHANGE = per-turn defense modifier increment, sign preserved (e.g. molten_core, arctic_core)
                inc_per_turn = status_effect.get("multiplierIncrementPerTurnPerMil", 0)
                params["CHANGE"] = inc_per_turn / 10
            else:
                params["CHANGE"] = status_effect.get("multiplierPerMil", 0) / 10

    return {
        key: int(value) if isinstance(value, float) and value.is_integer() else value
        for key, value in params.items()
        if value is not None
    }


def parse_passive_skills(passive_skills_list: list, hero_stats: dict, lang_db: dict, game_db: dict, hero_id: str, rules: dict, parsers: dict) -> (list, list):
    if not passive_skills_list: return [], []
    parsed_items = []; warnings = []
    main_max_level = parsers.get("main_max_level", 8)
    title_lang_subset = [k for k in lang_db if k.startswith("herocard.passive_skill.title.")]
    desc_lang_subset = [k for k in lang_db if k.startswith("herocard.passive_skill.description.")]
    passive_master = game_db.get("passive_master", {})
    for skill_data in passive_skills_list:
        if not isinstance(skill_data, dict): continue
        skill_id = skill_data.get("id"); skill_type = skill_data.get("passiveSkillType","").lower()
        if not (skill_id and skill_type): continue
        master_row = passive_master.get(skill_id, {})
        title_lang_id = master_row.get("title_lang_id") if master_row else None
        desc_lang_id = master_row.get("description_lang_id") if master_row else None
        icon_file = master_row.get("icon", "") if master_row else ""
        source_hint = _source_passive_hint(game_db, hero_id, skill_id, skill_data.get("_display_label", ""))
        source_title_lang_id, source_desc_lang_id, source_icon_file = _resolve_passive_lang_ids_from_source(skill_data, source_hint, lang_db)
        if source_title_lang_id:
            title_lang_id = title_lang_id or source_title_lang_id
        if source_desc_lang_id:
            desc_lang_id = desc_lang_id or source_desc_lang_id
        if source_icon_file:
            icon_file = icon_file or source_icon_file

        direct_title_id = f"herocard.passive_skill.title.{skill_id}"
        if not title_lang_id and direct_title_id in lang_db:
            title_lang_id = direct_title_id

        if not title_lang_id:
            prefix = f"herocard.passive_skill.title.{skill_type}"
            title_candidates = [k for k in title_lang_subset if k.startswith(prefix)]
            if title_candidates:
                skill_keywords = {kw for kw, depth in _collect_keywords_recursively(skill_data)}
                title_scores = [{'key':c,'score':sum(1 for kw in skill_keywords if kw in c.split('.'))} for c in title_candidates]
                if title_scores: title_lang_id = sorted(title_scores, key=lambda x:(-x['score'],len(x['key'])))[0]['key']

        if not desc_lang_id and title_lang_id:
            ideal_desc_id = title_lang_id.replace('.title.','.description.',1)
            if ideal_desc_id in lang_db: desc_lang_id = ideal_desc_id
            else:
                prefix = f"herocard.passive_skill.description.{skill_type}"
                desc_candidates = [k for k in desc_lang_subset if k.startswith(prefix)]
                if desc_candidates:
                    skill_keywords = {kw for kw, depth in _collect_keywords_recursively(skill_data)}
                    refined_candidates = [c for c in desc_candidates if any(kw in c.split('.') for kw in skill_keywords)]
                    if refined_candidates: desc_lang_id = min(refined_candidates, key=len)
                    elif desc_candidates: desc_lang_id = min(desc_candidates, key=len)

        if title_lang_id and desc_lang_id:
            all_placeholders = set(re.findall(r'\{(\w+)\}', lang_db.get(title_lang_id,{}).get("en","") + lang_db.get(desc_lang_id,{}).get("en","")))
            lang_params = _passive_explicit_params(skill_data, hero_stats, main_max_level, master_row)
            search_context = {**skill_data, "maxLevel": main_max_level}
            for p_holder in all_placeholders:
                if p_holder in lang_params:
                    continue
                value, found_key = find_and_calculate_value(p_holder, search_context, main_max_level, hero_id, rules, is_modifier=False)
                if value is not None:
                    if p_holder.upper() == "DAMAGE" and "permil" in (found_key or "").lower():
                         lang_params[p_holder] = math.floor((value/100) * hero_stats.get("max_attack",0))
                    elif isinstance(value, float) and value.is_integer():
                        lang_params[p_holder] = int(value)
                    else: lang_params[p_holder] = value
            formatted_params = {k:format_value(v) for k,v in lang_params.items()}
            title_texts = generate_description(title_lang_id, formatted_params, lang_db)
            desc_templates = lang_db.get(desc_lang_id, {"en": "", "ja": ""})
            parsed_items.append({
                "id": skill_id,
                "source": skill_data.get("_passive_source", "base"),
                "display_label": skill_data.get("_display_label", ""),
                "display_order": skill_data.get("_display_order", 0),
                "passiveSkillType": skill_data.get("passiveSkillType", ""),
                "lang_id": desc_lang_id,
                "title_lang_id": title_lang_id,
                "description_lang_id": desc_lang_id,
                "title_en": title_texts.get("en",""),
                "title_ja": title_texts.get("ja",""),
                "description_en": desc_templates.get("en",""),
                "description_ja": desc_templates.get("ja",""),
                "en": desc_templates.get("en",""),
                "ja": desc_templates.get("ja",""),
                "params": json.dumps(lang_params, ensure_ascii=False),
                "icon": {"file": icon_file, "url": None, "source": "manual"} if icon_file else None,
            })
        else:
            warnings.append(f"Could not resolve passive lang_ids for skill '{skill_id}'")
            parsed_items.append({
                "id": skill_id,
                "source": skill_data.get("_passive_source", "base"),
                "display_label": skill_data.get("_display_label", ""),
                "display_order": skill_data.get("_display_order", 0),
                "passiveSkillType": skill_data.get("passiveSkillType", ""),
                "lang_id": "SEARCH_FAILED",
                "title_lang_id": title_lang_id or "",
                "description_lang_id": desc_lang_id or "",
                "title_en": f"FAILED: {skill_id}",
                "description_en": "lang_id resolution failed.",
                "params": "{}",
            })
    return parsed_items, warnings
