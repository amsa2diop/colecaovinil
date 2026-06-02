"""
fetch_discogs_country.py
Busca country + year de cada release via Discogs API e salva em backup_country.csv.
Usa rate-limit seguro: 1 req/s (Discogs permite 60/min para autenticados).
"""
import time, csv, requests
from pathlib import Path
import pandas as pd

WORK      = Path(__file__).parent
TOKEN     = "FmUsfbDTXUFCniDqrTckrwBfJxvIljOGuMdygfVD"
OUT_FILE  = WORK / "backup_country.csv"

df = pd.read_csv(WORK / "backup_tracks.csv")
release_ids = df["release_id"].dropna().astype(int).unique().tolist()
print(f"{len(release_ids)} releases únicos para buscar country")

# Carrega cache existente para não re-buscar
existing = {}
if OUT_FILE.exists():
    ex_df = pd.read_csv(OUT_FILE, dtype=str)
    for _, r in ex_df.iterrows():
        existing[str(r["release_id"])] = dict(r)
    print(f"  Cache: {len(existing)} releases já buscados")

session = requests.Session()
session.headers.update({
    "Authorization": f"Discogs token={TOKEN}",
    "User-Agent": "DJLibrary/2.0",
})

results = dict(existing)
new_fetched = 0

for i, rid in enumerate(release_ids):
    key = str(rid)
    if key in results:
        continue  # já no cache

    url = f"https://api.discogs.com/releases/{rid}"
    try:
        r = session.get(url, timeout=15)
        if r.status_code == 200:
            data = r.json()
            results[key] = {
                "release_id": rid,
                "country": data.get("country", ""),
                "year":    data.get("year", ""),
            }
            new_fetched += 1
        elif r.status_code == 429:
            print(f"\n  Rate limit (429) — aguardando 60s...")
            time.sleep(60)
            continue
        else:
            results[key] = {"release_id": rid, "country": "", "year": ""}
    except Exception as e:
        results[key] = {"release_id": rid, "country": "", "year": ""}

    if (i + 1) % 10 == 0 or (i + 1) == len(release_ids):
        pct = int(100 * (i + 1) / len(release_ids))
        print(f"\r  {i+1}/{len(release_ids)} ({pct}%) | novos: {new_fetched}", end="", flush=True)

    time.sleep(1.1)  # ~54 req/min, abaixo do limite

print(f"\n\nTotal: {len(results)} releases | {new_fetched} novos buscados")

rows = list(results.values())
with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=["release_id", "country", "year"])
    w.writeheader()
    w.writerows(rows)
print(f"Salvo: {OUT_FILE.name}")

# Mostra distribuição de countries
countries = [r["country"] for r in rows if r["country"]]
from collections import Counter
top = Counter(countries).most_common(10)
print("\nTop países:")
for c, n in top:
    print(f"  {c}: {n}")
