"""
probe_songbpm.py — Investiga songbpm.com e outras fontes com acesso funcional
"""
import requests, json, re, time

HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

s = requests.Session()
s.headers.update(HDRS)

# Track IDs reais do Spotify para teste
TRACK_IDS = [
    "5pLsXl65StWByYN0PppUhk",
    "1Ya90l79BJXdW8tLlv4dZ4",
]

def probe(name, url, headers=None):
    try:
        h = dict(HDRS)
        if headers: h.update(headers)
        r = s.get(url, headers=h, timeout=12)
        ct = r.headers.get("content-type","?")
        print(f"[{name}] {r.status_code} | {ct[:50]}")
        if r.status_code == 200:
            body = r.text
            try:
                d = r.json()
                txt = json.dumps(d)
                print(f"  JSON: {txt[:300]}")
                for kw in ["tempo","bpm","key","energy","danceability"]:
                    if kw in txt.lower():
                        print(f"  *** Contém '{kw}'!")
            except:
                # Procura endpoints e BPM no HTML
                # Scripts JS que podem ter endpoints
                js_files = re.findall(r'src=["\']([^"\']+\.js[^"\']*)["\']', body)
                print(f"  JS files: {js_files[:4]}")
                # Procura por padrões de API
                api_refs = re.findall(r'["\']/(api|_api|data)[^\s"\'<]*["\']', body)
                print(f"  API refs: {api_refs[:5]}")
                # Procura por "bpm" no HTML
                if "bpm" in body.lower():
                    idx = body.lower().find("bpm")
                    print(f"  BPM no HTML: ...{body[max(0,idx-50):idx+100]}...")
        print()
    except Exception as e:
        print(f"[{name}] ERRO: {e}\n")
    time.sleep(0.6)

tid = TRACK_IDS[0]

# ── songbpm.com ───────────────────────────────────────────────────────────────
print("=== songbpm.com ===")
probe("main", "https://songbpm.com/")
probe("track_by_id", f"https://songbpm.com/tracks/{tid}")
probe("search_api", f"https://songbpm.com/api/tracks/{tid}")
probe("search_api2", f"https://songbpm.com/api/search?q=babidi+canoa+furada")
probe("tracks_json", f"https://songbpm.com/api/v1/tracks/{tid}")

# Tenta pegar um dos JS bundles para encontrar endpoints
print("=== Procurando JS bundle do songbpm ===")
try:
    r = s.get("https://songbpm.com/", timeout=10)
    js_files = re.findall(r'src=["\']([^"\']*/_astro/[^"\']+\.js)["\']', r.text)
    if js_files:
        print(f"Bundles Astro: {js_files[:3]}")
        # Pega o primeiro bundle e procura endpoints
        for jf in js_files[:2]:
            url = f"https://songbpm.com{jf}" if jf.startswith('/') else jf
            rj = s.get(url, timeout=15)
            if rj.status_code == 200:
                js = rj.text
                # Procura endpoints de API
                apis = re.findall(r'["\`]https?://[^"\`<>\s]+["\`]', js)
                relevant = [a for a in apis if any(k in a.lower() for k in ["api","track","bpm","song"])]
                print(f"  {url[-50:]}: {relevant[:5]}")
                # Procura variáveis de configuração
                configs = re.findall(r'baseURL?["\s:=]+["\`]([^"\`]+)["\`]', js)
                print(f"  baseURL: {configs[:3]}")
except Exception as e:
    print(f"Erro: {e}")

# ── soundiiz.com ──────────────────────────────────────────────────────────────
print("\n=== soundiiz.com ===")
probe("soundiiz", "https://soundiiz.com/")

# ── Verifica se existe alguma maneira de usar Spotify Web API indiretamente ──
# A ideia: encontrar um app/token público que ainda tem acesso
print("\n=== Testando se o problema é de token ou de app ===")
# O token do usuário (do .spotify_cache) pode ter acesso mesmo que o app não tenha
# Testa lendo o cache
import json as json_mod
from pathlib import Path
cache = Path(r"C:\Users\Amsatou Diop\OneDrive - LEME LABORATORIO PARA REDUCAO DA VIOLENC\Pessoal\DJ\.spotify_cache")
if cache.exists():
    c = json_mod.loads(cache.read_text())
    token = c.get("access_token","")
    print(f"Token encontrado: {token[:20]}...")
    # Testa audio_features com o token diretamente
    r = requests.get(
        f"https://api.spotify.com/v1/audio-features/{tid}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=10
    )
    print(f"audio-features (token direto): {r.status_code}")
    if r.status_code == 200:
        d = r.json()
        print(f"  BPM: {d.get('tempo')} | Key: {d.get('key')} | Energy: {d.get('energy')}")
    else:
        print(f"  {r.text[:200]}")
else:
    print("Cache Spotify não encontrado")
