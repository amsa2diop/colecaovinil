"""
Atualiza (ou cria) as playlists Spotify a partir dos CSVs de backup:
  • "Discos do Amsa"       — pública, todos os discos aceitos, na ordem do
                              álbum (artista A→Z, álbum A→Z, faixa na ordem do disco)
  • "Discos do Amsa (BPM)" — privada, todos os discos aceitos, ordenados por BPM
  • "Discos do Amsa (DJ)"  — privada, só discos com DJ=Sim ou Parcial, ordenados por BPM

Estratégia:
  1. Se backup_playlist*.txt contém um ID válido, atualiza essa playlist diretamente.
  2. Se não existe mais (deletada), busca por nome.
  3. Se não encontrar por nome, cria uma nova.
  Após atualizar/criar, faz upload de playlist_cover.jpg se disponível.

Funciona localmente e no GitHub Actions via SPOTIFY_REFRESH_TOKEN como variável de ambiente.
"""
from pathlib import Path
import base64, os, json, re, sys, time
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

WORK_DIR      = Path(__file__).parent
SP_CLIENT_ID  = "1ab6d898c52d42a19b737f451ce31e2a"
SP_CLIENT_SEC = "3c8b2f47049b44e2af6937ea835e1f2f"
COVER_PATH    = WORK_DIR / "playlist_cover.jpg"

# Playlist principal — pública, ordem de álbum
PLAYLIST_NAME     = "Discos do Amsa"
PLAYLIST_NAME_OLD = "Meu Discogs — por BPM"   # nome anterior — migra automaticamente

# Playlist por BPM — privada
PLAYLIST_NAME_BPM = "Discos do Amsa (BPM)"

# Playlist DJ — privada
PLAYLIST_NAME_DJ  = "Discos do Amsa (DJ)"


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
            "scope": "playlist-modify-public playlist-modify-private ugc-image-upload",
            "expires_at": 0,
        }
        Path(cache_path).write_text(json.dumps(cache_data), encoding="utf-8")

    sp_oauth = SpotifyOAuth(
        client_id=SP_CLIENT_ID,
        client_secret=SP_CLIENT_SEC,
        redirect_uri="http://127.0.0.1:1410/",
        scope="playlist-modify-public playlist-modify-private ugc-image-upload",
        cache_path=cache_path,
        open_browser=False,
    )
    return spotipy.Spotify(auth_manager=sp_oauth)


def _load_source_df():
    """Carrega o CSV de faixas com status, spotify_uri e track_id."""
    import pandas as pd
    for name in ("backup_matched_v2.csv", "backup_final.csv", "backup_matched.csv"):
        src = WORK_DIR / name
        if src.exists():
            df = pd.read_csv(src, dtype=str).fillna("")
            return df[df["status"] == "ACEITO"].copy().drop(columns=["bpm"], errors="ignore")
    print("Nenhum CSV de faixas encontrado.")
    return None


def _merge_bpm(df):
    """Mescla BPMs do backup_bpm.csv e retorna df ordenado."""
    import pandas as pd
    bpm_path = WORK_DIR / "backup_bpm.csv"
    if bpm_path.exists():
        bpm_df = pd.read_csv(bpm_path, dtype=str).fillna("")
        bpm_df["bpm"] = bpm_df["bpm"].apply(lambda v: float(v) if v else float("nan"))
        df = df.merge(bpm_df[["track_id", "bpm"]], on="track_id", how="left")
    else:
        df["bpm"] = float("nan")
    df["bpm"] = df["bpm"].apply(lambda v: float(v) if str(v) not in ("", "nan") else float("nan"))
    return df.sort_values("bpm", na_position="last")


def _extract_uris(df):
    """Retorna lista de spotify_uri únicos na ordem do df."""
    seen, uris = set(), []
    for u in df["spotify_uri"].dropna():
        u = str(u).strip()
        if u and "spotify" in u and u not in seen:
            seen.add(u); uris.append(u)
    return uris


def load_uris_sorted_by_bpm():
    """Todos os discos aceitos, ordenados por BPM."""
    df = _load_source_df()
    if df is None or df.empty:
        return []
    return _extract_uris(_merge_bpm(df))


def _position_key(pos):
    """Chave de ordenação para posições estilo Discogs (A1, A2, B1, 1, 2-3...)."""
    pos = str(pos or "").strip().upper()
    m = re.match(r"^([A-Z]*)\s*0*(\d+)?", pos)
    if m:
        letters = m.group(1) or ""
        num = int(m.group(2)) if m.group(2) else 0
        return (letters, num, pos)
    return (pos, 0, pos)


def load_uris_by_album_order():
    """Todos os discos aceitos, na ordem do álbum: artista A→Z, álbum A→Z, faixa na ordem do disco."""
    df = _load_source_df()
    if df is None or df.empty:
        return []
    df = df.copy()
    df["_pos_key"] = df["position"].apply(_position_key)
    df = df.sort_values(["album_artist", "album_title", "_pos_key"])
    return _extract_uris(df)


def load_uris_dj_sorted_by_bpm():
    """Só discos com DJ=Sim ou Parcial, ordenados por BPM."""
    import pandas as pd
    df = _load_source_df()
    if df is None or df.empty:
        return []

    fields_path = WORK_DIR / "backup_collection_fields.csv"
    if fields_path.exists():
        fields = pd.read_csv(fields_path, dtype=str).fillna("")
        dj_rids = fields[fields["DJ"].isin(["Sim", "Parcial"])]["release_id"].astype(str).unique()
        df = df[df["release_id"].astype(str).isin(dj_rids)]

    if df.empty:
        return []
    return _extract_uris(_merge_bpm(df))


def _pid_from_file(txt_path: Path):
    """Lê playlist ID do arquivo de backup. Aceita URI ou ID puro."""
    if not txt_path.exists():
        return None
    val = txt_path.read_text(encoding="utf-8").strip()
    if not val:
        return None
    return val.split(":")[-1]  # 'spotify:playlist:ID' → 'ID'


def _playlist_exists(sp, pid: str) -> bool:
    """Verifica se a playlist com esse ID ainda existe."""
    try:
        pl = sp.playlist(pid, fields="id")
        return bool(pl.get("id"))
    except Exception:
        return False


def find_playlist_by_name(sp, uid, name, old_name=None):
    """Procura playlist por nome (e nome antigo para migração). Retorna (id, needs_rename)."""
    found_old = None
    playlists = sp.user_playlists(uid)
    while playlists:
        for pl in playlists["items"]:
            if pl["name"] == name:
                return pl["id"], False
            if old_name and pl["name"] == old_name:
                found_old = pl["id"]
        playlists = sp.next(playlists) if playlists.get("next") else None
    return found_old, True


def replace_tracks(sp, pid, uris):
    sp.playlist_replace_items(pid, [])
    chunks = [uris[i:i+100] for i in range(0, len(uris), 100)]
    for i, chunk in enumerate(chunks):
        sp.playlist_add_items(pid, chunk)
        time.sleep(0.3)
        print(f"\r  Lote {i+1}/{len(chunks)}", end="", flush=True)
    print()


def _upload_cover(sp, pid: str):
    """Faz upload de playlist_cover.jpg como capa. Falha silenciosamente."""
    if not COVER_PATH.exists():
        return
    try:
        b64 = base64.b64encode(COVER_PATH.read_bytes()).decode()
        sp.playlist_upload_cover_image(pid, b64)
        print(f"  ✓ Capa enviada ({COVER_PATH.stat().st_size // 1024} KB)")
    except Exception as e:
        print(f"  ⚠ Capa não enviada: {e}")


def sync_one(sp, uid, name, uris, uri_file, old_name=None, description="", public=None):
    """Atualiza playlist existente (por ID ou nome) ou cria nova. Mantém a playlist nas pastas do usuário."""
    if not uris:
        print(f"  Sem faixas para '{name}' — pulando."); return

    txt_path = WORK_DIR / uri_file
    known_pid = _pid_from_file(txt_path)

    pid = None
    details = {"description": description}
    if public is not None:
        details["public"] = public

    # 1. Tenta pelo ID conhecido (preserva pasta/posição da playlist)
    if known_pid and _playlist_exists(sp, known_pid):
        pid = known_pid
        # Garante nome, visibilidade e descrição corretos
        pl_info = sp.playlist(pid, fields="name")
        if pl_info.get("name") != name:
            print(f"  Renomeando para '{name}'...")
            sp.playlist_change_details(pid, name=name, **details)
        else:
            sp.playlist_change_details(pid, **details)
        print(f"  Playlist existente por ID ({pid}). Substituindo {len(uris)} faixas...")

    # 2. Fallback: busca por nome (caso a playlist tenha sido deletada e recriada)
    if pid is None:
        pid, needs_rename = find_playlist_by_name(sp, uid, name, old_name)
        if pid:
            if needs_rename:
                print(f"  Renomeando '{old_name}' → '{name}'...")
                sp.playlist_change_details(pid, name=name, **details)
            else:
                sp.playlist_change_details(pid, **details)
            print(f"  Playlist encontrada por nome ({pid}). Substituindo {len(uris)} faixas...")

    # 3. Cria nova se não encontrou
    if pid is None:
        print(f"  Criando nova playlist '{name}'...")
        pl = sp.user_playlist_create(user=uid, name=name, public=bool(public), description=description)
        pid = pl["id"]
        print(f"  ✓ Criada ({pid})")

    replace_tracks(sp, pid, uris)
    print(f"  ✓ {len(uris)} faixas")

    # Salva URI atualizada
    pl_uri = f"spotify:playlist:{pid}"
    txt_path.write_text(pl_uri, encoding="utf-8")
    print(f"  URI: {pl_uri}")

    # Upload da capa
    _upload_cover(sp, pid)


def sync():
    print("Carregando faixas...")
    uris_album = load_uris_by_album_order()
    uris_bpm   = load_uris_sorted_by_bpm()
    uris_dj    = load_uris_dj_sorted_by_bpm()
    print(f"  {len(uris_album)} faixas (ordem de álbum)  |  {len(uris_bpm)} por BPM  |  {len(uris_dj)} faixas DJ (Sim+Parcial)")

    print("Conectando ao Spotify...")
    sp  = get_sp()
    uid = sp.current_user()["id"]
    now = datetime.now().strftime("%d/%m/%Y %H:%M")

    print(f"\n── Discos do Amsa ──")
    sync_one(sp, uid,
             name=PLAYLIST_NAME, uris=uris_album,
             uri_file="backup_playlist.txt",
             old_name=PLAYLIST_NAME_OLD,
             description="Garimpando grooves....",
             public=True)

    print(f"\n── Discos do Amsa (BPM) ──")
    sync_one(sp, uid,
             name=PLAYLIST_NAME_BPM, uris=uris_bpm,
             uri_file="backup_playlist_bpm.txt",
             description=f"Todos os discos, ordenados por BPM | {now}",
             public=False)

    print(f"\n── Discos do Amsa (DJ) ──")
    sync_one(sp, uid,
             name=PLAYLIST_NAME_DJ, uris=uris_dj,
             uri_file="backup_playlist_dj.txt",
             description=f"Para discotecar · Ordenado por BPM | {now}",
             public=False)


if __name__ == "__main__":
    sync()
