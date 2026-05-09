# AGENTS.md

## Project

This directory is `hero_processor_v3`, the parser/data generator for Empires &
Puzzles hero skill data.

The dashboard at `D:\PyScript\hero_dashboard` consumes this project's output files.
Keep that boundary file-based unless the user explicitly asks otherwise.

## Python

Use the local Windows Python executable directly. Python is not on PATH.

```text
C:\Users\sages\AppData\Local\Programs\Python\Python312\python.exe
```

## Git

Do not push from AI sessions. The user handles Git operations manually.

Do not run destructive Git commands. Do not commit unless explicitly asked.

## Main Outputs

Generated files live under `output_data\`:

- `debug_hero_data.json`
- `hero_skill_output.csv`
- `hero_skill_output_debug.csv`
- `viewer.html`
- additional local review/scrape outputs

The current `.gitignore` ignores CSV and JSON outputs.

## Current Architecture

`hero_main.py` is the main parser pipeline:

1. integrate raw game data into `debug_hero_data.json`
2. parse skill structures and resolve lang_ids
3. write final/debug CSV outputs

`wiki_check.py` is a validation script, not part of the main pipeline.

Do not add production scraping or source comparison workflows here by default.
Use `D:\PyScript\Hero Text Scraper` for external text acquisition, source
comparison, Google Sheets review workflows, and future source scoring.
