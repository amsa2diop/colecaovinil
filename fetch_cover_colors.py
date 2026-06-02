"""
fetch_cover_colors.py
Extrai cor dominante de cada capa de álbum e salva em backup_colors.csv.
Requer: pip install colorthief requests
Cor é pastelizada (mistura com branco) para não ficar muito forte no card.
"""
import time, csv, io, requests
from pathlib import Path
import pandas as pd

try:
    from colorthief import ColorThief
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "colorthief"])
    from colorthief import ColorThief

WORK     = Path(__file__).parent
OUT_FILE = WORK / "backup_colors.csv"

df = pd.read_csv(WORK / "backup_tracks.csv")
covers = (df[["release_id","cover_url","thumb_url"]]
          .drop_duplicates(subset=["release_id"])
          .dropna(subset=["cover_url"]))
print(f"{len(covers)} capas para processar")

# Carrega cache existente
existing = {}
if OUT_FILE.exists():
    ex_df = pd.read_csv(OUT_FILE, dtype=str)
    for _, r in ex_df.iterrows():
        existing[str(r["release_id"])] = dict(r)
    print(f"  Cache: {len(existing)} capas já processadas")

session = requests.Session()
session.headers.update({"User-Agent": "DJLibrary/2.0"})

def pastelizar(r, g, b, fator=0.62):
    """Mistura a cor com branco pelo fator dado (0=cor pura, 1=branco)."""
    pr = int(r + (255 - r) * fator)
    pg = int(g + (255 - g) * fator)
    pb = int(b + (255 - b) * fator)
    return pr, pg, pb

def rgb_to_hex(r, g, b):
    return f"#{r:02X}{g:02X}{b:02X}"

results = dict(existing)
new_fetched = 0
errors = 0

for i, (_, row) in enumerate(covers.iterrows()):
    rid = str(int(row["release_id"]))
    if rid in results:
        continue

    url = row.get("cover_url") or row.get("thumb_url") or ""
    if not url or str(url) == "nan":
        results[rid] = {"release_id": rid, "color_hex": "", "color_pastel": ""}
        continue

    try:
        resp = session.get(url, timeout=12)
        if resp.status_code == 200:
            img_data = io.BytesIO(resp.content)
            ct = ColorThief(img_data)
            dom = ct.get_color(quality=5)  # (r, g, b)
            pastel = pastelizar(*dom, fator=0.62)
            results[rid] = {
                "release_id":   rid,
                "color_hex":    rgb_to_hex(*dom),
                "color_pastel": rgb_to_hex(*pastel),
            }
            new_fetched += 1
        else:
            results[rid] = {"release_id": rid, "color_hex": "", "color_pastel": ""}
            errors += 1
    except Exception as e:
        results[rid] = {"release_id": rid, "color_hex": "", "color_pastel": ""}
        errors += 1

    if (i + 1) % 10 == 0 or (i + 1) == len(covers):
        print(f"\r  {i+1}/{len(covers)} | novas: {new_fetched} | erros: {errors}", end="", flush=True)

    time.sleep(0.3)

print(f"\n\nTotal: {len(results)} | {new_fetched} cores extraídas | {errors} erros")

rows = list(results.values())
with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["release_id", "color_hex", "color_pastel"])
    w.writeheader()
    w.writerows(rows)
print(f"Salvo: {OUT_FILE.name}")
