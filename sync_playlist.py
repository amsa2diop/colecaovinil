"""
Atualiza (ou cria) a playlist Spotify "Discos do Amsa" a partir dos CSVs de backup.
Funciona localmente e no GitHub Actions via SPOTIFY_REFRESH_TOKEN como variável de ambiente.

Uso local:
  python sync_playlist.py        # usa .spotify_cache gerado pelo dj_library_v2.py

Uso CI:
  SPOTIFY_REFRESH_TOKEN=xxx python sync_playlist.py
"""
from pathlib import Path
import os, json, sys, time
from datetime import datetime

WORK_DIR      = Path(__file__).parent
SP_CLIENT_ID  = "1ab6d898c52d42a19b737f451ce31e2a"
SP_CLIENT_SEC = "3c8b2f47049b44e2af6937ea835e1f2f"
PLAYLIST_NAME = "Discos do Amsa"
PLAYLIST_NAME_OLD = "Meu Discogs — por BPM"  # nome anterior, para migrar automaticamente


def _ensure_spotipy():
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        return spotipy, SpotifyOAuth
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "spotipy", "-q"])
        import spotipy
        from spotipy.oauth2 import SpotifyOAuth
        return spotipy, SpotifyOAuth


def get_sp():
    spotipy, SpotifyOAuth = _ensure_spotipy()
    cache_path = str(WORK_DIR / ".spotify_cache")

    refresh_token = os.environ.get("SPOTIFY_REFRESH_TOKEN", "").strip()
    if refresh_token and not Path(cache_path).exists():
        cache_data = {
            "access_token": "",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": refresh_token,
            "scope": "playlist-modify-public playlist-modify-private",
            "expires_at": 0,
        }
        Path(cache_path).write_text(json.dumps(cache_data), encoding="utf-8")

    sp_oauth = SpotifyOAuth(
        client_id=SP_CLIENT_ID,
        client_secret=SP_CLIENT_SEC,
        redirect_uri="http://127.0.0.1:1410/",
        scope="playlist-modify-public playlist-modify-private",
        cache_path=cache_path,
        open_browser=False,
    )
    return spotipy.Spotify(auth_manager=sp_oauth)


def load_uris_sorted_by_bpm():
    """Retorna lista de spotify_uri das faixas ACEITAS, ordenadas por BPM."""
    import pandas as pd

    src = WORK_DIR / "backup_matched_v2.csv"
    if not src.exists():
        src = WORK_DIR / "backup_final.csv"
    if not src.exists():
        print("Nenhum CSV de faixas encontrado."); return []

    df = pd.read_csv(src, dtype=str).fillna("")
    df = df[df["status"] == "ACEITO"].copy()

    # Remove coluna bpm existente no CSV de faixas antes de fazer o merge
    # (evita bpm_x/bpm_y quando backup_matched já tem essa coluna)
    df = df.drop(columns=["bpm"], errors="ignore")

    bpm_path = WORK_DIR / "backup_bpm.csv"
    if bpm_path.exists():
        bpm_df = pd.read_csv(bpm_path, dtype=str).fillna("")
        bpm_df["bpm"] = bpm_df["bpm"].apply(lambda v: float(v) if v else float("nan"))
        df = df.merge(bpm_df[["track_id", "bpm"]], on="track_id", how="left")
    else:
        df["bpm"] = float("nan")

    df["bpm"] = df["bpm"].apply(lambda v: float(v) if str(v) not in ("", "nan") else float("nan"))
    df = df.sort_values("bpm", na_position="last")

    seen, uris = set(), []
    for u in df["spotify_uri"].dropna():
        u = str(u).strip()
        if u and "spotify" in u and u not in seen:
            seen.add(u)
            uris.append(u)
    return uris


def find_playlist(sp, uid):
    """Procura playlist pelo nome novo ou antigo (migração automática)."""
    found_old = None
    playlists = sp.user_playlists(uid)
    while playlists:
        for pl in playlists["items"]:
            if pl["name"] == PLAYLIST_NAME:
                return pl["id"], False          # encontrou com nome novo
            if pl["name"] == PLAYLIST_NAME_OLD:
                found_old = pl["id"]
        playlists = sp.next(playlists) if playlists.get("next") else None
    return found_old, True                       # retorna antiga (ou None) + flag de renomear


def replace_tracks(sp, pid, uris):
    sp.playlist_replace_items(pid, [])
    chunks = [uris[i:i+100] for i in range(0, len(uris), 100)]
    for i, chunk in enumerate(chunks):
        sp.playlist_add_items(pid, chunk)
        time.sleep(0.3)
        print(f"\r  Lote {i+1}/{len(chunks)}", end="", flush=True)
    print()


def sync():
    print("Carregando faixas dos CSVs...")
    uris = load_uris_sorted_by_bpm()
    if not uris:
        print("Nenhuma faixa para sincronizar."); return

    print(f"  {len(uris)} faixas (ordenadas por BPM)")
    print("Conectando ao Spotify...")
    sp = get_sp()
    uid = sp.current_user()["id"]

    desc = f"Ordenado por BPM | {datetime.now().strftime('%d/%m/%Y %H:%M')}"
    pid, needs_rename = find_playlist(sp, uid)
    if pid:
        if needs_rename:
            print(f"Renomeando playlist antiga para '{PLAYLIST_NAME}'...")
            sp.playlist_change_details(pid, name=PLAYLIST_NAME, description=desc)
        else:
            sp.playlist_change_details(pid, description=desc)
        print(f"Playlist existente ({pid}). Substituindo faixas...")
        replace_tracks(sp, pid, uris)
        print(f"✓ Playlist atualizada com {len(uris)} faixas")
    else:
        print("Criando nova playlist...")
        pl = sp.user_playlist_create(
            user=uid, name=PLAYLIST_NAME, public=False,
            description=desc,
        )
        pid = pl["id"]
        replace_tracks(sp, pid, uris)
        print(f"✓ Playlist criada com {len(uris)} faixas")

    pl_uri = f"spotify:playlist:{pid}"
    (WORK_DIR / "backup_playlist.txt").write_text(pl_uri, encoding="utf-8")
    print(f"  URI: {pl_uri}")


if __name__ == "__main__":
    sync()
