import requests, json, time, csv
from pathlib import Path

TOKEN = "FmUsfbDTXUFCniDqrTckrwBfJxvIljOGuMdygfVD"
USER  = "amsa2diop"
HDRS  = {"User-Agent": "DJLibrary/2.0", "Authorization": f"Discogs token={TOKEN}"}
WORK  = Path(__file__).parent

# 1. Busca definicoes dos campos personalizados
r = requests.get(f"https://api.discogs.com/users/{USER}/collection/fields", headers=HDRS, timeout=15)
print(f"Status campos: {r.status_code}")
if r.status_code != 200:
    print(r.text[:300]); exit(1)

fields = r.json().get("fields", [])
field_map = {f["id"]: f["name"] for f in fields}
print("Campos encontrados:", field_map)

# 2. Busca colecao completa com notas/campos personalizados
items = []
page = 1
while True:
    url = (f"https://api.discogs.com/users/{USER}/collection/folders/0/releases"
           f"?token={TOKEN}&per_page=100&page={page}&sort=added&sort_order=asc")
    resp = requests.get(url, headers=HDRS, timeout=20)
    if resp.status_code != 200:
        print(f"Erro pagina {page}: {resp.status_code}"); break
    data = resp.json()
    releases = data.get("releases", [])
    if not releases:
        break
    for item in releases:
        rel = item.get("basic_information", {})
        notes = {field_map.get(n["field_id"], f"campo_{n['field_id']}"): n["value"]
                 for n in item.get("notes", []) if "field_id" in n and "value" in n}
        items.append({
            "release_id":   rel.get("id"),
            "instance_id":  item.get("instance_id"),
            "album_title":  rel.get("title"),
            "album_artist": (rel.get("artists") or [{}])[0].get("name", ""),
            "year":         rel.get("year"),
            **notes
        })
    print(f"  Pagina {page}: {len(releases)} itens | total: {len(items)}")
    if page >= data.get("pagination", {}).get("pages", 1):
        break
    page += 1
    time.sleep(0.5)

print(f"\nTotal itens coletados: {len(items)}")

# 3. Salva
out = WORK / "backup_collection_fields.csv"
if items:
    # Coleta todos os campos possíveis (variam por item)
    all_keys = list(dict.fromkeys(k for item in items for k in item.keys()))
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(items)
    print(f"Salvo: {out.name}")
    # Mostra amostra
    print("\nAmostra dos campos:")
    for it in items[:5]:
        print(" ", {k:v for k,v in it.items() if k not in ("release_id","instance_id","year")})
