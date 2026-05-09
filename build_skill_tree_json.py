"""
build_skill_tree_json.py

Build a review-friendly skill tree JSON from hero_skill_output.csv.

This script is intentionally standalone. It reads the existing processor output and
writes a separate JSON artifact without changing hero_main.py behavior.
"""
from __future__ import annotations

import argparse
import ast
import csv
import json
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).parent
INPUT_CSV = SCRIPT_DIR / "output_data" / "hero_skill_output.csv"
OUTPUT_JSON = SCRIPT_DIR / "output_data" / "hero_skill_tree.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def parse_literal(value: str, fallback: Any = None) -> Any:
    if value is None or value == "":
        return fallback
    try:
        return ast.literal_eval(value)
    except (SyntaxError, ValueError):
        return fallback


def normalize_node(item: dict[str, Any], path: str) -> dict[str, Any]:
    node: dict[str, Any] = {
        "path": path,
        "item_id": item.get("id", ""),
        "lang_id": item.get("lang_id", ""),
        "params": parse_literal(item.get("params", ""), fallback={}) or {},
        "text": {
            "en": item.get("en") or item.get("description_en") or "",
            "ja": item.get("ja") or item.get("description_ja") or "",
        },
        "title": {
            "en": item.get("title_en", ""),
            "ja": item.get("title_ja", ""),
        },
        "children": [],
    }

    if extra := item.get("extra"):
        if isinstance(extra, dict):
            node["tooltip"] = {
                "lang_id": extra.get("lang_id", ""),
                "params": parse_literal(extra.get("params", ""), fallback={}) or {},
                "text": {
                    "en": extra.get("en", ""),
                    "ja": extra.get("ja", ""),
                },
            }

    nested = item.get("nested_effects") or []
    if isinstance(nested, list):
        node["children"] = [
            normalize_node(child, f"{path}.children[{index}]")
            for index, child in enumerate(nested)
            if isinstance(child, dict)
        ]

    return node


def normalize_skill_group(value: Any, group_name: str) -> list[dict[str, Any]]:
    if not value:
        return []
    items = value if isinstance(value, list) else [value]
    return [
        normalize_node(item, f"{group_name}[{index}]")
        for index, item in enumerate(items)
        if isinstance(item, dict)
    ]


def build_record(row: dict[str, str]) -> dict[str, Any]:
    hero_id = row.get("id") or row.get("hero_id") or ""
    skill_descriptions = parse_literal(row.get("skillDescriptions", ""), fallback={}) or {}

    tree = {
        "direct_effect": normalize_skill_group(skill_descriptions.get("directEffect"), "direct_effect"),
        "clear_buffs": normalize_skill_group(skill_descriptions.get("clear_buffs"), "clear_buffs"),
        "properties": normalize_skill_group(skill_descriptions.get("properties"), "properties"),
        "status_effects": normalize_skill_group(skill_descriptions.get("statusEffects"), "status_effects"),
        "familiars": normalize_skill_group(skill_descriptions.get("familiars"), "familiars"),
        "passives": normalize_skill_group(skill_descriptions.get("passiveSkills"), "passives"),
    }

    return {
        "hero_id": hero_id,
        "name": row.get("name") or row.get("hero_name") or "",
        "element": row.get("element", ""),
        "family": row.get("family", ""),
        "rarity": row.get("rarity", ""),
        "class_type": row.get("classType", ""),
        "mana_speed_id": row.get("manaSpeedId", ""),
        "special_id": row.get("specialId", ""),
        "tree": tree,
    }


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build review-friendly hero skill tree JSON.")
    parser.add_argument("--input", type=Path, default=INPUT_CSV)
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON)
    parser.add_argument("--heroes", nargs="*", help="Optional hero ids to include.")
    args = parser.parse_args()

    if not args.input.exists():
        raise SystemExit(f"Input not found: {args.input}")

    wanted = set(args.heroes or [])
    records = []
    for row in load_rows(args.input):
        hero_id = row.get("id") or row.get("hero_id") or ""
        if wanted and hero_id not in wanted:
            continue
        records.append(build_record(row))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(records)} hero skill trees to {args.output}")


if __name__ == "__main__":
    main()

