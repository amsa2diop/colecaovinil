"""
Autoriza o app Spotify uma única vez e salva o token em .spotify_cache.
Execute no terminal (ou duplo-clique) — vai abrir o browser automaticamente.
Após autorizar, pode fechar a aba e rodar: python sync_playlist.py
"""
import json, base64, webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path
import requests

CLIENT_ID    = "1ab6d898c52d42a19b737f451ce31e2a"
CLIENT_SEC   = "3c8b2f47049b44e2af6937ea835e1f2f"
REDIRECT_URI = "http://127.0.0.1:1410/"
SCOPE        = "playlist-modify-public playlist-modify-private"
CACHE_PATH   = Path(__file__).parent / ".spotify_cache"

auth_code_holder = [None]

class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        auth_code_holder[0] = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            b"<h2>Autorizado! Pode fechar esta aba e voltar ao terminal.</h2>"
        )
    def log_message(self, *a): pass  # silencia logs HTTP

auth_url = (
    f"https://accounts.spotify.com/authorize"
    f"?client_id={CLIENT_ID}"
    f"&response_type=code"
    f"&redirect_uri=http%3A%2F%2F127.0.0.1%3A1410%2F"
    f"&scope={SCOPE.replace(' ', '%20')}"
)

print("Abrindo Spotify no browser para autorizar...")
webbrowser.open(auth_url)
print(f"\nSe o browser não abrir, acesse manualmente:\n  {auth_url}\n")
print("Aguardando callback em http://127.0.0.1:1410/ ...")

server = HTTPServer(("127.0.0.1", 1410), _Handler)
server.handle_request()  # espera UMA requisição e sai

code = auth_code_holder[0]
if not code:
    print("Erro: código de autorização não recebido."); exit(1)

# Troca o code pelo token
creds_b64 = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SEC}".encode()).decode()
resp = requests.post(
    "https://accounts.spotify.com/api/token",
    headers={
        "Authorization": f"Basic {creds_b64}",
        "Content-Type":  "application/x-www-form-urlencoded",
    },
    data={
        "grant_type":   "authorization_code",
        "code":          code,
        "redirect_uri":  REDIRECT_URI,
    },
)
if not resp.ok:
    print(f"Erro ao obter token: {resp.status_code} {resp.text}"); exit(1)

token = resp.json()
token["expires_at"] = 0  # força refresh na primeira chamada

CACHE_PATH.write_text(json.dumps(token), encoding="utf-8")
print(f"\n✓ Token salvo em {CACHE_PATH.name}")
print(f"  Refresh token: {token.get('refresh_token','N/A')[:24]}...")
print("\nAgora rode:  python sync_playlist.py")
