# AGENTS.md

## Project Role

This directory is `hero_processor_v3`, the **プロセッサー** for Empires &
Puzzles hero data.

The processor owns data formatting, JSON/CSV generation, lang_id resolution,
parameter calculation, and rule files used to turn game JSON into current parsed
data.

The local dashboard at `D:\PyScript\hero_dashboard` is the main orchestrator UI.
It consumes this project's output files, imports them into SQLite, and displays
preview/structure views for review. Keep the boundary file-based unless the user
explicitly asks otherwise.

## Primary Responsibilities

- Resolve raw game data into structured hero data.
- Select lang_id candidates and explain why a candidate was selected.
- Calculate skill, passive, and family parameters from game JSON.
- Normalize display-ready params such as `+35`, `10`, `+65`, `-30`, and damage
  totals.
- Maintain external rule files under `rules\` when a recurring calculation or
  lang_id rule is found.
- Generate stable output files for the dashboard.
- When the user reports a dashboard mismatch, determine whether the bug belongs
  to processor output, rule configuration, dashboard ETL, dashboard rendering, or
  stale cache/server state.

## Out of Scope

- Do not make processor_v3 perform production scraping by default.
- Use `D:\PyScript\Hero Text Scraper` for external text acquisition, Google
  Sheets hints, source scoring, and web/source review workflows.
- Do not treat processor output as final Master / Adopted Data. It is current
  parsed data for review.

## Python

Use the local Windows Python executable directly. Python is not on PATH.

```text
C:\Users\sages\AppData\Local\Programs\Python\Python312\python.exe
```

## Git

Do not push from AI sessions. The user handles Git operations manually.

Do not run destructive Git commands. Do not commit unless explicitly asked.

## Model Usage

Conserve usage limits by choosing the smallest suitable Codex model/reasoning
setting for the work.

- Planning, architecture, and difficult design review: Codex 5.5 high.
- Implementation and non-trivial code changes: Codex 5.4 high.
- Simple UI work and minor display fixes: Codex 5.4 low.
- If the active session cannot switch models, treat this as handoff guidance for
  the next agent/session.

## Key Files

- `hero_main.py`: main pipeline.
- `hero_data_loader.py`: JSON/CSV/rules loader.
- `hero_parser.py`: parser, lang_id selection, param calculation.
- `rules\family_lang_rules.json`: family lang_id overrides and candidate
  patterns.
- `rules\property_extra_rules.json`: property tooltip/addinfo rules.
- `rules\passive_master.csv`: current passive hint/master rows.
- `rules\param_calc_rules.json`: external parameter calculation rules. Current
  schema is v2.

Generated files live under `output_data\`:

- `debug_hero_data.json`
- `hero_skill_output.csv`
- `hero_skill_output_debug.csv`
- `hero_family_output.json`
- `familiar_parameter_log.csv`

These generated outputs are local artifacts and should remain ignored by Git.

## Rule Strategy

Prefer broad reusable rules over hero-specific patches.

Use these rulebook layer nicknames in user-facing discussion and handoffs:

```text
グローバル       -> global_rules
ファミリールール -> family_rules
スキルルール     -> skill_rules
Heroルール       -> hero_rules
```

Rulebook application order:

1. グローバル: rules that apply to every hero, such as final integer display,
   directEffect baseline handling, and the broad signed/unsigned policy.
2. ファミリールール: rules shared by a family or family group, such as Legends
   Elemental Link ordering or Moths family parameter context.
3. スキルルール: rules for a specific skill pattern or related skill ID group,
   such as Stack, Growth, Wither, Increasing, Elemental Link, Cleanse, Dispel,
   or MoonBeam-style compound skills.
4. Heroルール: final per-hero overrides for cases that cannot be generalized.

Keep calculation/parameter rules separate from display-order rules. Display
ordering should eventually support the same layers: global, family, skill
pattern, and hero.

`rules\param_calc_rules.json` is v2-only. Do not add or revive legacy top-level
`semantic_rules`, `status_effects`, `properties`, or `families` sections.
`statusEffect` belongs inside a `match` condition in `skill_rules`, not as a
top-level rule category.

When a bug is found:

1. Identify the raw JSON block and selected lang_id.
2. Identify the placeholder, raw key, context, and current calculated value.
3. Decide whether this is a recurring rule, a known exception, or bad upstream
   source data.
4. If recurring, put the rule in an external config file under `rules\` when
   practical.
5. Keep only traversal, fallback search, and generic mechanics in Python code.

Parameter rules are expected to grow. The canonical rulebook is:

```text
rules\param_calc_rules.json
```

Initial externalization targets:

- `IncreasingDefenseModifier`
- `IncreasingCounterAttack`

The rule file should express calculation type, source keys, increment keys,
context policy, signed display, and compound cap logic.

## Dashboard Coordination

After processor changes that affect output:

1. Run the processor.
2. Rebuild the dashboard DB.
3. Restart FastAPI if needed.
4. Verify the local URL for the specific hero.

Commands:

```powershell
$py = "C:\Users\sages\AppData\Local\Programs\Python\Python312\python.exe"

Set-Location "D:\PyScript\hero_processor_v3"
& $py hero_main.py

Set-Location "D:\PyScript\hero_dashboard"
& $py scripts\build_db.py --rebuild
```

If the dashboard still shows old values after processor output changed, check:

- whether `output_data\hero_skill_output_debug.csv` has the expected params
- whether `D:\PyScript\hero_dashboard\data\heroes.db` has the expected rows
- whether the FastAPI process needs restart
- whether the issue is preview rendering rather than processor params

Local dashboard URL:

```text
http://127.0.0.1:8765/
```

## Bug Report Workflow

The user may provide only a local URL, hero_id, skill/lang_id, and expected text.
Use that as enough context to inspect the dashboard and processor output.

For each bug report, report:

- target hero and skill block
- wrong current output
- expected output
- root cause category: processor rule / data model / dashboard ETL / dashboard
  rendering / stale server or cache
- files changed
- verification performed

Do not rely on a screenshot alone when a local URL and hero_id are available.
Inspect local output files or dashboard HTML directly.

## Documentation

Durable processor planning and checkpoints live in:

```text
D:\Obsidian\aivault\AI Vault\Projects\Empires Hero Workflow\Hero_Processor_v3.md
D:\Obsidian\aivault\AI Vault\Projects\Empires Hero Workflow\Hero_Processor_Agent.md
D:\Obsidian\aivault\AI Vault\Projects\Empires Hero Workflow\Hero_Workflow_Index.md
```

When the user asks to save state or when a large rule/design change is made,
update the AI Vault markdown files.

