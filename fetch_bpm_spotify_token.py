"""
fetch_bpm_spotify_token.py
Usa um token do Spotify Web Player (copiado do DevTools) para buscar audio_features
de todas as faixas aceitas no backup_final.csv.

Como obter o token:
1. Abra open.spotify.com com sua playlist
2. Ative o modo DJ
3. DevTools (F12) → aba Network → filtre por "audio-features"
4. Clique em qualquer requisição → Headers → copie o valor de "Authorization"
   (remova o prefixo "Bearer ", mantenha só o token)
5. Cole abaixo ou passe como argumento: python fetch_bpm_spotify_token.py SEU_TOKEN
"""
import sys, json, time, csv, requests
from pathlib import Path

WORK = Path(__file__).parent

TOKEN = sys.argv[1] if len(sys.argv) > 1 else input("Cole o token Spotify (sem 'Bearer '): ").strip()

import pandas as pd
df = pd.read_csv(WORK / "backup_final.csv")
track_ids = df[df["status"] == "ACEITO"]["track_id"].dropna().unique().tolist()
print(f"{len(track_ids)} faixas únicas para buscar BPM")

headers = {"Authorization": f"Bearer {TOKEN}"}
chunks  = [track_ids[i:i+100] for i in range(0, len(track_ids), 100)]

def camelot(key, mode):
    maj = ["B","F#/Gb","Db","Ab","Eb","Bb","F","C","G","D","A","E"]
    min_ = ["Ab/G#","Eb/D#","Bb","F","C","G","D","A","E","B","F#","C#"]
    if key is None or key < 0: return ""
    try:
        n = int(key)
        if mode == 1: return f"{[maj.index(m)+1 if m in maj else 0 for m in maj][n]}B"
        else:         return f"{[min_.index(m)+1 if m in min_ else 0 for m in min_][n]}A"
    except: return ""

CAM = {
    (0,1):"8B",(1,1):"3B",(2,1):"10B",(3,1):"5B",(4,1):"12B",(5,1):"7B",
    (6,1):"2B",(7,1):"9B",(8,1):"4B",(9,1):"11B",(10,1):"6B",(11,1):"1B",
    (0,0):"5A",(1,0):"12A",(2,0):"7A",(3,0):"2A",(4,0):"9A",(5,0):"4A",
    (6,0):"11A",(7,0):"6A",(8,0):"1A",(9,0):"8A",(10,0):"3A",(11,0):"10A",
}

results = {}
for i, chunk in enumerate(chunks):
    ids_str = ",".join(chunk)
    r = requests.get(
        f"https://api.spotify.com/v1/audio-features",
        params={"ids": ids_str},
        headers=headers,
        timeout=15,
    )
    print(f"  Chunk {i+1}/{len(chunks)}: {r.status_code}", end="")
    if r.status_code == 200:
        feats = r.json().get("audio_features", [])
        ok = sum(1 for f in feats if f)
        for f in feats or []:
            if f:
                results[f["id"]] = {
                    "track_id":     f["id"],
                    "bpm":          round(f["tempo"], 1),
                    "energy":       round(f["energy"], 2),
                    "danceability": round(f["danceability"], 2),
                    "valence":      round(f["valence"], 2),
                    "key":          f["key"],
                    "mode":         f["mode"],
                    "camelot":      CAM.get((f["key"], f["mode"]), ""),
                    "source":       "spotify_webplayer",
                }
        print(f" | {ok} com BPM")
    elif r.status_code == 401:
        print(f"\n  Token expirado (401). Copie um novo token do DevTools.")
        break
    elif r.status_code == 403:
        print(f"\n  Token sem acesso (403) — token do web player deve funcionar.")
        break
    else:
        print(f" | {r.text[:100]}")
    time.sleep(0.3)

print(f"\nTotal: {len(results)} BPMs encontrados de {len(track_ids)} faixas")

if results:
    out = WORK / "backup_bpm_spotify.csv"
    rows = list(results.values())
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"Salvo: {out.name}")
    print("\nPara usar este BPM no HTML, delete backup_bpm.csv e execute dj_library_v2.py")
    print("(ou copie backup_bpm_spotify.csv → backup_bpm.csv)")
