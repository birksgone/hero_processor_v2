"""
update_lang.py
R2 から最新の言語CSVをダウンロードして data/ に保存する。
hero_main.py から自動呼び出しされるか、単体で実行可能。
"""
import urllib.request
import shutil
from pathlib import Path

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

EN_URL = "https://pub-bb8f01301f874d39b58143bac81dbae8.r2.dev/English.csv"
JA_URL = "https://pub-bb8f01301f874d39b58143bac81dbae8.r2.dev/Japanese.csv"

DATA_DIR = Path(__file__).parent / "data"


def download_lang_files(force: bool = False) -> bool:
    DATA_DIR.mkdir(exist_ok=True)
    en_path = DATA_DIR / "English.csv"
    ja_path = DATA_DIR / "Japanese.csv"

    updated = False
    for url, dest in [(EN_URL, en_path), (JA_URL, ja_path)]:
        tmp = dest.with_suffix(".tmp")
        try:
            print(f"  Downloading {dest.name}...", end=" ", flush=True)
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            new_size = tmp.stat().st_size
            old_size = dest.stat().st_size if dest.exists() else 0
            if force or new_size != old_size:
                shutil.move(str(tmp), str(dest))
                print(f"updated ({old_size} → {new_size} bytes)")
                updated = True
            else:
                tmp.unlink()
                print("no change")
        except Exception as e:
            if tmp.exists():
                tmp.unlink()
            print(f"FAILED: {e}")
    return updated


if __name__ == "__main__":
    print("=== Updating language files from R2 ===")
    download_lang_files(force=True)
    print("Done.")
