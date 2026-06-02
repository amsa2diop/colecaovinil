"""
probe_bpm_sources.py — Investiga fontes alternativas de BPM
"""
import requests, json, re, time

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Track IDs de teste (reais do Spotify)
TRACK_IDS = [
    "5pLsXl65StWByYN0PppUhk",
    "1Ya90l79BJXdW8tLlv4dZ4",
    "5UiXhxtl69RyixaI8g7pcu",
]

s = requests.Session()
s.headers.update(HDRS)

def probe(name, url, extra_headers=None):
    try:
        h = dict(HDRS)
        if extra_headers: h.update(extra_headers)
        r = s.get(url, headers=h, timeout=12)
        body = r.text[:500]
        print(f"[{name}] {r.status_code} | CT: {r.headers.get('content-type','?')[:40]}")
        if r.status_code == 200:
            # Tenta parsear JSON
            try:
                d = r.json()
                print(f"  JSON keys: {list(d.keys())[:8] if isinstance(d, dict) else 'lista'}")
                # Procura BPM
                txt = json.dumps(d)
                for kw in ["tempo","bpm","Tempo","BPM"]:
                    idx = txt.lower().find(kw.lower())
                    if idx > -1:
                        print(f"  ** Encontrou '{kw}' no JSON: ...{txt[max(0,idx-20):idx+40]}...")
                        break
            except:
                print(f"  Body: {body[:200]}")
        elif r.status_code not in (403, 404):
            print(f"  Body: {body[:150]}")
    except Exception as e:
        print(f"[{name}] ERRO: {e}")
    print()
    time.sleep(0.5)

tid = TRACK_IDS[0]

# ── skiley.net ────────────────────────────────────────────────────────────────
print("=== skiley.net ===")
probe("skiley_main", "https://skiley.net/")
probe("skiley_api_track", f"https://skiley.net/api/tracks/{tid}")
probe("skiley_api_search", f"https://skiley.net/api/search?q={tid}")

# ── songbpm.com ───────────────────────────────────────────────────────────────
print("=== songbpm.com ===")
probe("songbpm_main", "https://songbpm.com/")
probe("songbpm_search", f"https://songbpm.com/@{tid}")

# ── getsongbpm.com ────────────────────────────────────────────────────────────
print("=== getsongbpm.com ===")
probe("getsongbpm_main", "https://getsongbpm.com/")
probe("getsongbpm_api", f"https://api.getsongbpm.com/song/?api_key=test&type=spotify&lookup={tid}")

# ── bpmanalyzer.com ───────────────────────────────────────────────────────────
print("=== bpmanalyzer.com ===")
probe("bpmanal_main", "https://bpmanalyzer.com/")

# ── bpmfinder.com ─────────────────────────────────────────────────────────────
print("=== bpmfinder.com ===")
probe("bpmfinder", f"https://bpmfinder.net/search?q={tid}")

# ── Procura no bundle do skiley por endpoints internos ───────────────────────
print("=== Buscando endpoints no JS do skiley ===")
try:
    r = s.get("https://skiley.net/", timeout=10)
    if r.status_code == 200:
        # Procura scripts
        scripts = re.findall(r'src="(/[^"]+\.js)"', r.text)
        print(f"Scripts encontrados: {scripts[:5]}")
        # Procura endpoints no HTML
        apis = re.findall(r'["\']https?://[^"\']*api[^"\']*["\']', r.text[:5000])
        print(f"APIs no HTML: {apis[:5]}")
    else:
        print(f"Status skiley: {r.status_code}")
except Exception as e:
    print(f"Erro: {e}")
