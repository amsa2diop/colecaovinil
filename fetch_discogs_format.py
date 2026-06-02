"""
fetch_discogs_format.py
Busca Format (LP/12"/10"/7", Compilation) e Label (Selo) via Discogs API.
Salva em backup_format.csv.

Uso:
  python fetch_discogs_format.py          # todos os releases
  python fetch_discogs_format.py --sample 5   # só 5, para validar
"""
import sys, time, csv, requests
from pathlib import Path
import pandas as pd

WORK  = Path(__file__).parent
TOKEN = "FmUsfbDTXUFCniDqrTckrwBfJxvIljOGuMdygfVD"
OUT   = WORK / "backup_format.csv"

sample_n = 0
if "--sample" in sys.argv:
    idx = sys.argv.index("--sample")
    sample_n = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 5

df = pd.read_csv(WORK / "backup_tracks.csv")
release_ids = df["release_id"].dropna().astype(int).unique().tolist()
if sample_n:
    release_ids = release_ids[:sample_n]
    print(f"AMOSTRA: {sample_n} releases")

# Cache existente
existing = {}
if OUT.exists():
    ex = pd.read_csv(OUT, dtype=str).fillna("")
    for _, r in ex.iterrows():
        existing[str(r["release_id"])] = dict(r)
    print(f"Cache: {len(existing)} releases já buscados")

print(f"Total: {len(release_ids)} releases para processar")

session = requests.Session()
session.headers.update({
    "Authorization": f"Discogs token={TOKEN}",
    "User-Agent": "DJLibrary/2.0",
})

def extract_format(data):
    """Extrai label, is_compilation, format_size e format_raw do release."""
    # Label
    labels = data.get("labels") or []
    label = labels[0]["name"] if labels else ""

    # Formats
    formats = data.get("formats") or []
    descriptions = []
    for f in formats:
        descriptions += f.get("descriptions") or []

    is_compilation = "Compilation" in descriptions

    # Tamanho: prioridade 7" > 10" > 12" > LP > Other
    if '7"' in descriptions:      size = '7"'
    elif '10"' in descriptions:   size = '10"'
    elif '12"' in descriptions:   size = '12"'
    elif "LP" in descriptions:    size = "LP"
    elif "EP" in descriptions:    size = "EP"
    else:                         size = "Other"

    format_raw = ", ".join(dict.fromkeys(descriptions))  # sem duplicatas

    return {
        "label":          label,
        "is_compilation": "1" if is_compilation else "0",
        "format_size":    size,
        "format_raw":     format_raw,
    }

results = dict(existing)
new_fetched = 0

for i, rid in enumerate(release_ids):
    key = str(rid)
    if key in results:
        continue

    try:
        r = session.get(f"https://api.discogs.com/releases/{rid}", timeout=15)
        if r.status_code == 200:
            d = extract_format(r.json())
            d["release_id"] = rid
            results[key] = d
            new_fetched += 1
            if sample_n:
                print(f"  {rid}: label={d['label']!r} | size={d['format_size']} | compilation={d['is_compilation']} | raw={d['format_raw']!r}")
        elif r.status_code == 429:
            print(f"\n  Rate limit — aguardando 60s...")
            time.sleep(60); continue
        else:
            results[key] = {"release_id": rid, "label": "", "is_compilation": "0", "format_size": "", "format_raw": ""}
    except Exception as e:
        results[key] = {"release_id": rid, "label": "", "is_compilation": "0", "format_size": "", "format_raw": ""}

    if not sample_n and ((i + 1) % 10 == 0 or (i + 1) == len(release_ids)):
        print(f"\r  {i+1}/{len(release_ids)} | novos: {new_fetched}", end="", flush=True)

    time.sleep(1.1)

print(f"\n\nTotal: {len(results)} | {new_fetched} novos")

rows = list(results.values())
fieldnames = ["release_id", "label", "is_compilation", "format_size", "format_raw"]
with open(OUT, "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
print(f"Salvo: {OUT.name}")

if not sample_n:
    # Resumo
    import pandas as pd
    r = pd.read_csv(OUT)
    print("\nFormato (top sizes):", dict(r["format_size"].value_counts()))
    print("Compilações:", r["is_compilation"].astype(str).eq("1").sum())
    print("Top selos:", dict(r["label"].value_counts().head(8)))
