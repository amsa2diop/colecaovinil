import sys, json, re, requests, base64
from pathlib import Path

work = Path(r"C:\Users\Amsatou Diop\OneDrive - LEME LABORATORIO PARA REDUCAO DA VIOLENC\Pessoal\DJ")

code = (work / "dj_library_v2.py").read_text(encoding="utf-8")
client_id = re.search(r'SP_CLIENT_ID\s*=\s*["\']([^"\']+)["\']', code).group(1)
client_secret = re.search(r'SP_CLIENT_SEC\s*=\s*["\']([^"\']+)["\']', code).group(1)

cache = work / ".spotify_cache"
c = json.loads(cache.read_text())
print(f"refresh_token presente: {'sim' if c.get('refresh_token') else 'nao'}")

refresh_token = c.get("refresh_token", "")
if not refresh_token:
    print("Sem refresh_token — precisa fazer login novamente")
    sys.exit(1)

creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
r = requests.post(
    "https://accounts.spotify.com/api/token",
    headers={"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"},
    data={"grant_type": "refresh_token", "refresh_token": refresh_token},
    timeout=15
)
print(f"Refresh status: {r.status_code}")
if r.status_code != 200:
    print(r.text[:300])
    sys.exit(1)

new_token = r.json()["access_token"]
print(f"Novo token: {new_token[:20]}...")

tid = "5pLsXl65StWByYN0PppUhk"
af = requests.get(
    f"https://api.spotify.com/v1/audio-features/{tid}",
    headers={"Authorization": f"Bearer {new_token}"},
    timeout=10
)
print(f"audio-features status: {af.status_code}")
if af.status_code == 200:
    d = af.json()
    print(f"  BPM: {d.get('tempo')} | Key: {d.get('key')} | Energy: {d.get('energy')}")
else:
    print(f"  Resposta: {af.text[:400]}")
