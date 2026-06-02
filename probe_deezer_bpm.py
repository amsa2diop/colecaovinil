"""
probe_deezer_bpm.py - Testa Deezer API (gratuita, sem auth) para BPM
e songbpm.com com User-Agent de browser real
"""
import requests, json, time, re

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

s = requests.Session()
s.headers.update(HDRS)

# ── DEEZER API ────────────────────────────────────────────────────────────────
print("=== DEEZER API (gratuita, sem auth) ===\n")

# Busca por artista + título
queries = [
    ("Babidi", "Canoa Furada"),
    ("Gilberto Gil", "Aquele Abraço"),
    ("Jorge Ben", "Mas Que Nada"),
]

for artist, title in queries:
    q = f"{artist} {title}"
    r = s.get(f"https://api.deezer.com/search?q={q}&limit=5", timeout=10)
    print(f"[search '{q}'] {r.status_code}")
    if r.status_code == 200:
        data = r.json()
        hits = data.get("data", [])
        if hits:
            track = hits[0]
            print(f"  Track: {track.get('title')} | Artist: {track.get('artist',{}).get('name')}")
            print(f"  ID: {track.get('id')} | BPM direto no search: {track.get('bpm', 'N/A')}")
            # Busca detalhes da track (tem BPM?)
            r2 = s.get(f"https://api.deezer.com/track/{track['id']}", timeout=10)
            if r2.status_code == 200:
                d2 = r2.json()
                print(f"  Track detail keys: {list(d2.keys())}")
                print(f"  BPM no detail: {d2.get('bpm', 'N/A')}")
                print(f"  Gain: {d2.get('gain', 'N/A')} | Duration: {d2.get('duration')}s")
        else:
            print("  Sem resultados")
    print()
    time.sleep(0.5)

# ── MUSICSTAX.COM ─────────────────────────────────────────────────────────────
print("\n=== musicstax.com ===")
# Spotify track ID → musicstax page
sp_ids = ["5pLsXl65StWByYN0PppUhk", "1Ya90l79BJXdW8tLlv4dZ4"]
for tid in sp_ids:
    r = s.get(f"https://musicstax.com/track/{tid}", timeout=10)
    print(f"[track/{tid}] {r.status_code} | {r.headers.get('content-type','?')[:40]}")
    if r.status_code == 200:
        body = r.text
        for kw in ["bpm","tempo","BPM"]:
            idx = body.lower().find(kw.lower())
            if idx > -1:
                print(f"  '{kw}': ...{body[max(0,idx-30):idx+60]}...")
                break
    time.sleep(0.4)

# Tenta API do musicstax
print()
r = s.get("https://musicstax.com/api/track/5pLsXl65StWByYN0PppUhk", timeout=10)
print(f"[musicstax API] {r.status_code} | {r.headers.get('content-type','?')[:40]}")
if r.status_code == 200:
    print(f"  {r.text[:300]}")

# ── SONGBPM.COM - página de uma música ────────────────────────────────────────
print("\n=== songbpm.com - páginas de músicas ===")
searches = [
    "https://songbpm.com/search?q=babidi+canoa+furada",
    "https://songbpm.com/search?q=gilberto+gil+aquele+abraco",
    "https://songbpm.com/@babidi-canoa-furada",
]
for url in searches:
    r = s.get(url, timeout=12)
    print(f"[{url[-40:]}] {r.status_code}")
    if r.status_code == 200:
        body = r.text
        # Procura BPM
        bpm_matches = re.findall(r'(\d{2,3})\s*(?:BPM|bpm)', body)
        print(f"  BPMs encontrados: {bpm_matches[:5]}")
        # Procura JSON embutido
        json_blocks = re.findall(r'<script[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', body, re.DOTALL)
        for jb in json_blocks[:2]:
            try:
                d = json.loads(jb)
                txt = json.dumps(d)
                if "bpm" in txt.lower() or "tempo" in txt.lower():
                    print(f"  JSON embutido com BPM: {txt[:200]}")
            except:
                pass
        # Links de músicas
        song_links = re.findall(r'href="(/[^"]+)"', body)
        print(f"  Links encontrados: {song_links[:5]}")
    print()
    time.sleep(0.6)
