"""
probe_tunebat.py
Investiga endpoints disponíveis no tunebat.com para obter BPM por Spotify track ID.
"""
import requests, json, re, time

# Spotify track IDs reais para teste (Babidi - Canoa Furada, etc.)
# Usando IDs que sabemos que existem no Spotify
TEST_IDS = [
    "5pLsXl65StWByYN0PppUhk",  # track ID do matching existente
    "1Ya90l79BJXdW8tLlv4dZ4",
]

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://tunebat.com/",
    "Origin": "https://tunebat.com",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

s = requests.Session()
s.headers.update(HEADERS_BROWSER)

tid = TEST_IDS[0]

# Testa vários endpoints possíveis
endpoints = [
    f"https://tunebat.com/api/tracks/{tid}",
    f"https://tunebat.com/api/v1/tracks/{tid}",
    f"https://tunebat.com/api/v2/tracks/{tid}",
    f"https://api.tunebat.com/api/tracks/{tid}",
    f"https://tunebat.com/api/tracks?id={tid}",
    f"https://tunebat.com/api/search?q={tid}",
    f"https://tunebat.com/Info/{tid}",
    f"https://tunebat.com/Analyze?url=spotify:track:{tid}",
    f"https://tunebat.com/api/analyze/{tid}",
]

print("=== Testando endpoints tunebat.com ===\n")
for ep in endpoints:
    try:
        r = s.get(ep, timeout=10)
        body = r.text[:300]
        print(f"[{r.status_code}] {ep}")
        if r.status_code == 200:
            print(f"  Content-Type: {r.headers.get('content-type','?')}")
            print(f"  Body: {body[:200]}")
        print()
        time.sleep(0.8)
    except Exception as e:
        print(f"[ERR] {ep} → {e}\n")

# Tenta também a página principal para pegar tokens/cookies
print("=== Página principal ===")
r = s.get("https://tunebat.com/", timeout=10)
print(f"Status: {r.status_code}")
# Procura por referências a API no HTML
api_refs = re.findall(r'https?://[^\s"\'<>]+api[^\s"\'<>]*', r.text[:5000])
print("Referências a API encontradas:", api_refs[:10])

# Procura tokens de auth ou endpoints
tokens = re.findall(r'"(apiKey|endpoint|baseUrl|api_url)":\s*"([^"]+)"', r.text)
print("Tokens/endpoints:", tokens[:5])
