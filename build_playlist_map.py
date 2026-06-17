"""
Constrói backup_playlist_map.json mapeando URIs de vinil → playlists Spotify.

Uso:
  python build_playlist_map.py

Gera backup_playlist_map.json com:
  {
    "uri_to_playlists": {"spotify:track:xxx": ["Playlist A", "Playlist B"], ...},
    "playlist_names": ["Playlist A", "Playlist B", ...]
  }

Apenas playlists cujo dono é o próprio usuário são incluídas.
Playlists de sistema geradas pelo sync são excluídas.
"""
from pathlib import Path
import sys, json, time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORK_DIR = Path(__file__).parent
OUTPUT   = WORK_DIR / "backup_playlist_map.json"

# URIs do vinyl (para filtrar só o que importa)
VINYL_CSV = WORK_DIR / "backup_matched_v2.csv"
if not VINYL_CSV.exists():
    VINYL_CSV = WORK_DIR / "backup_final.csv"

SP_CLIENT_ID  = "1ab6d898c52d42a19b737f451ce31e2a"
SP_CLIENT_SEC = "3c8b2f47049b44e2af6937ea835e1f2f"
CACHE_PATH    = WORK_DIR / ".spotify_cache"

# Playlists geradas automaticamente pelo sync — não incluir no filtro
SKIP_PLAYLISTS = {
    "Discos do Amsa",
    "Discos do Amsa (BPM)",
    "Discos do Amsa (DJ)",
    "Para categorizar",
}


def get_sp():
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "spotipy", "-q"])
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth

    sp_oauth = SpotifyOAuth(
        client_id=SP_CLIENT_ID,
        client_secret=SP_CLIENT_SEC,
        redirect_uri="http://127.0.0.1:1410/",
        scope="playlist-read-private playlist-read-collaborative",
        cache_path=str(CACHE_PATH),
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=sp_oauth, requests_timeout=30, retries=5)


def fetch_my_playlists(sp, uid):
    playlists = []
    res = sp.current_user_playlists(limit=50)
    while res:
        for pl in res["items"]:
            if pl and pl.get("owner", {}).get("id") == uid:
                if pl["name"] not in SKIP_PLAYLISTS:
                    playlists.append(pl)
        res = sp.next(res) if res.get("next") else None
    return playlists


def fetch_playlist_uris(sp, pid):
    uris = []
    res = sp.playlist_items(
        pid,
        fields="items.track.uri,items.track.is_local,next",
        additional_types=["track"],
    )
    while res:
        for item in res["items"]:
            tr = item.get("track")
            if not tr or tr.get("is_local"):
                continue
            uri = tr.get("uri")
            if uri and uri.startswith("spotify:track:"):
                uris.append(uri)
        res = sp.next(res) if res.get("next") else None
    return uris


def load_vinyl_uris():
    """Carrega URIs do vinil para filtrar (opcional — se não houver CSV, mapeia tudo)."""
    if not VINYL_CSV.exists():
        return None
    try:
        import pandas as pd
        df = pd.read_csv(VINYL_CSV)
        uris = set(str(u).strip() for u in df.get("spotify_uri", []) if u and str(u).strip() != "nan")
        print(f"URIs de vinil carregadas: {len(uris)}")
        return uris
    except Exception as e:
        print(f"Aviso: não foi possível carregar URIs do vinil ({e}). Mapeia todas as faixas.")
        return None


def main():
    print("Conectando ao Spotify...")
    sp = get_sp()
    uid = sp.current_user()["id"]
    print(f"Usuário: {uid}")

    vinyl_uris = load_vinyl_uris()

    print("\nBuscando playlists do usuário...")
    playlists = fetch_my_playlists(sp, uid)
    print(f"  {len(playlists)} playlists encontradas (excluindo as de sistema).\n")

    uri_to_playlists: dict[str, list[str]] = {}
    all_names: list[str] = sorted(pl["name"] for pl in playlists)

    for i, pl in enumerate(playlists, 1):
        name  = pl["name"]
        total = pl["tracks"]["total"]
        print(f"  [{i:3d}/{len(playlists)}] {name} ({total} faixas)...", end=" ", flush=True)
        try:
            uris = fetch_playlist_uris(sp, pl["id"])
        except Exception as e:
            print(f"ERRO: {e}")
            time.sleep(1)
            continue

        matched = 0
        for uri in uris:
            if vinyl_uris is None or uri in vinyl_uris:
                uri_to_playlists.setdefault(uri, []).append(name)
                matched += 1

        print(f"{matched} faixas de vinil" if vinyl_uris else f"{len(uris)} faixas")
        time.sleep(0.08)

    # Carrega pastas definidas pelo usuário (opcional)
    folders_path = WORK_DIR / "playlist_folders.json"
    playlist_folders: dict = {}
    if folders_path.exists():
        try:
            playlist_folders = json.loads(folders_path.read_text(encoding="utf-8"))
            print(f"\nPastas carregadas de {folders_path.name}: {len(playlist_folders)} pastas")
        except Exception as e:
            print(f"\nAviso: não foi possível carregar {folders_path.name}: {e}")
    else:
        # Gera template vazio para o usuário editar
        template = {"_instrucoes": "Mova playlists para as pastas desejadas. Remova esta chave antes de salvar."}
        template["Sem pasta"] = all_names
        folders_path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nTemplate gerado em {folders_path.name} — edite para organizar em pastas e rode novamente.")

    result = {
        "uri_to_playlists": uri_to_playlists,
        "playlist_names": all_names,
        "playlist_folders": playlist_folders,
    }
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSalvo em {OUTPUT.name}")
    print(f"  URIs mapeadas: {len(uri_to_playlists)}")
    print(f"  Playlists: {len(all_names)}")
    print(f"  Pastas: {len(playlist_folders)}")


if __name__ == "__main__":
    main()
