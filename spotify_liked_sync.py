"""
Sincroniza "Músicas Curtidas" com as playlists criadas pelo usuário.

Objetivo final:
  - Toda música presente em alguma playlist própria também está em "Curtidas".
  - Toda música "Curtida" está presente em pelo menos uma playlist própria
    (as que não estiverem em nenhuma vão para uma playlist nova "Para categorizar").

Uso:
  python spotify_liked_sync.py analyze     # só lê e gera relatório (backup_liked_*.csv) - SEM ALTERAR NADA
  python spotify_liked_sync.py like        # marca como Curtidas as faixas de playlists que ainda não estão
  python spotify_liked_sync.py categorize  # cria/atualiza playlist "Para categorizar" com curtidas fora de playlists

Sempre rode "analyze" primeiro e revise os CSVs gerados antes de "like"/"categorize".
"""
from pathlib import Path
import sys, time, csv

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WORK_DIR = Path(__file__).parent
SP_CLIENT_ID  = "1ab6d898c52d42a19b737f451ce31e2a"
SP_CLIENT_SEC = "3c8b2f47049b44e2af6937ea835e1f2f"

# Cache separado do usado pelo sync_playlist.py, pois precisa de escopos extras
CACHE_PATH = WORK_DIR / ".spotify_cache_liked"

CATEGORIZE_PLAYLIST_NAME = "Para categorizar"
CATEGORIZE_FILE = WORK_DIR / "backup_playlist_categorizar.txt"

CSV_TO_LIKE       = WORK_DIR / "backup_liked_to_add.csv"
CSV_TO_CATEGORIZE = WORK_DIR / "backup_liked_to_categorize.csv"
CSV_PLAYLISTS     = WORK_DIR / "backup_liked_playlists.csv"


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
    sp_oauth = SpotifyOAuth(
        client_id=SP_CLIENT_ID,
        client_secret=SP_CLIENT_SEC,
        redirect_uri="http://127.0.0.1:1410/",
        scope="user-library-read user-library-modify "
              "playlist-read-private playlist-read-collaborative "
              "playlist-modify-public playlist-modify-private",
        cache_path=str(CACHE_PATH),
        open_browser=True,
    )
    return spotipy.Spotify(auth_manager=sp_oauth, requests_timeout=30, retries=5)


def fetch_my_playlists(sp, uid):
    """Playlists cujo dono é o próprio usuário."""
    playlists = []
    res = sp.current_user_playlists(limit=50)
    while res:
        for pl in res["items"]:
            if pl.get("owner", {}).get("id") == uid:
                playlists.append(pl)
        res = sp.next(res) if res.get("next") else None
    return playlists


def fetch_playlist_track_uris(sp, pid):
    """Todas as URIs de faixas (ignora locais/sem URI) de uma playlist."""
    uris = []
    res = sp.playlist_items(pid, fields="items.track.uri,items.track.is_local,next", additional_types=["track"])
    while res:
        for item in res["items"]:
            tr = item.get("track")
            if not tr or item.get("is_local") or tr.get("is_local"):
                continue
            uri = tr.get("uri")
            if uri and uri.startswith("spotify:track:"):
                uris.append(uri)
        res = sp.next(res) if res.get("next") else None
    return uris


def fetch_liked_track_uris(sp):
    """Todas as URIs das faixas curtidas, na ordem (mais recentes primeiro)."""
    uris = []
    res = sp.current_user_saved_tracks(limit=50)
    while res:
        for item in res["items"]:
            tr = item.get("track")
            if tr and tr.get("uri"):
                uris.append(tr["uri"])
        res = sp.next(res) if res.get("next") else None
    return uris


def _track_labels(sp, uris):
    """Retorna {uri: 'Artista - Faixa'} buscando em lotes de 50."""
    labels = {}
    ids = [u.split(":")[-1] for u in uris]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i+50]
        res = sp.tracks(chunk)
        for tid, tr in zip(chunk, res["tracks"]):
            uri = f"spotify:track:{tid}"
            if tr:
                artists = ", ".join(a["name"] for a in tr["artists"])
                labels[uri] = f"{artists} - {tr['name']}"
            else:
                labels[uri] = uri
        print(f"\r  nomes: {min(i+50, len(ids))}/{len(ids)}", end="", flush=True)
    print()
    return labels


def analyze():
    print("Conectando ao Spotify...")
    sp = get_sp()
    uid = sp.current_user()["id"]

    print("Buscando playlists do usuário...")
    playlists = fetch_my_playlists(sp, uid)
    print(f"  {len(playlists)} playlists próprias encontradas.")

    playlist_uris = set()
    with open(CSV_PLAYLISTS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["playlist_id", "playlist_name", "n_faixas"])
        for i, pl in enumerate(playlists, 1):
            print(f"  [{i}/{len(playlists)}] {pl['name']} ({pl['tracks']['total']} faixas)...")
            uris = fetch_playlist_track_uris(sp, pl["id"])
            playlist_uris.update(uris)
            w.writerow([pl["id"], pl["name"], len(uris)])
            time.sleep(0.05)

    print(f"\nTotal de faixas únicas em playlists próprias: {len(playlist_uris)}")

    print("Buscando músicas Curtidas...")
    liked_uris = set(fetch_liked_track_uris(sp))
    print(f"Total de músicas Curtidas: {len(liked_uris)}")

    to_like = playlist_uris - liked_uris
    to_categorize = liked_uris - playlist_uris

    print(f"\n=> Faixas em playlists que NÃO estão Curtidas: {len(to_like)}")
    print(f"=> Faixas Curtidas que NÃO estão em nenhuma playlist própria: {len(to_categorize)}")

    print("\nBuscando nomes das faixas para os relatórios (pode demorar)...")
    print("to_like:")
    labels_like = _track_labels(sp, sorted(to_like))
    with open(CSV_TO_LIKE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["spotify_uri", "faixa"])
        for uri in sorted(to_like):
            w.writerow([uri, labels_like.get(uri, uri)])

    print("to_categorize:")
    labels_cat = _track_labels(sp, sorted(to_categorize))
    with open(CSV_TO_CATEGORIZE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["spotify_uri", "faixa"])
        for uri in sorted(to_categorize):
            w.writerow([uri, labels_cat.get(uri, uri)])

    print("\nRelatórios gerados:")
    print(f"  {CSV_PLAYLISTS.name}")
    print(f"  {CSV_TO_LIKE.name}  ({len(to_like)} faixas a marcar como Curtidas)")
    print(f"  {CSV_TO_CATEGORIZE.name}  ({len(to_categorize)} faixas Curtidas fora de playlists)")
    print("\nRevise os CSVs antes de rodar 'like' ou 'categorize'.")


def like():
    if not CSV_TO_LIKE.exists():
        print(f"Rode 'analyze' primeiro ({CSV_TO_LIKE.name} não existe).")
        return
    with open(CSV_TO_LIKE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    uris = [r["spotify_uri"] for r in rows]
    print(f"{len(uris)} faixas serão marcadas como Curtidas.")
    if not uris:
        print("Nada a fazer.")
        return
    confirm = input("Confirma? Esta ação NÃO é facilmente reversível em massa. Digite SIM para continuar: ")
    if confirm.strip().upper() != "SIM":
        print("Cancelado.")
        return

    sp = get_sp()
    ids = [u.split(":")[-1] for u in uris]
    BATCH = 20
    chunks = [ids[i:i+BATCH] for i in range(0, len(ids), BATCH)]
    for i, chunk in enumerate(chunks, 1):
        sp.current_user_saved_tracks_add(tracks=chunk)
        print(f"\r  Lote {i}/{len(chunks)}", end="", flush=True)
        time.sleep(0.2)
    print(f"\n✓ {len(ids)} faixas marcadas como Curtidas.")


def categorize():
    if not CSV_TO_CATEGORIZE.exists():
        print(f"Rode 'analyze' primeiro ({CSV_TO_CATEGORIZE.name} não existe).")
        return
    with open(CSV_TO_CATEGORIZE, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    uris = [r["spotify_uri"] for r in rows]
    print(f"{len(uris)} faixas serão adicionadas à playlist '{CATEGORIZE_PLAYLIST_NAME}'.")
    if not uris:
        print("Nada a fazer.")
        return
    confirm = input(f"Confirma a criação/atualização da playlist '{CATEGORIZE_PLAYLIST_NAME}'? Digite SIM para continuar: ")
    if confirm.strip().upper() != "SIM":
        print("Cancelado.")
        return

    sp = get_sp()
    uid = sp.current_user()["id"]

    pid = None
    if CATEGORIZE_FILE.exists():
        candidate = CATEGORIZE_FILE.read_text(encoding="utf-8").strip().split(":")[-1]
        try:
            if sp.playlist(candidate, fields="id").get("id"):
                pid = candidate
        except Exception:
            pid = None

    if pid is None:
        # procura por nome entre as playlists do usuário
        res = sp.current_user_playlists(limit=50)
        while res and pid is None:
            for pl in res["items"]:
                if pl["name"] == CATEGORIZE_PLAYLIST_NAME and pl.get("owner", {}).get("id") == uid:
                    pid = pl["id"]
                    break
            res = sp.next(res) if (res.get("next") and pid is None) else None

    if pid is None:
        print(f"Criando playlist '{CATEGORIZE_PLAYLIST_NAME}'...")
        pl = sp.user_playlist_create(user=uid, name=CATEGORIZE_PLAYLIST_NAME, public=False,
                                       description="Curtidas que ainda não estão em nenhuma playlist organizada.")
        pid = pl["id"]
    else:
        print(f"Playlist existente encontrada ({pid}). As faixas serão adicionadas (sem remover as já existentes).")

    # Evita duplicar faixas já presentes na playlist
    existing = set(fetch_playlist_track_uris(sp, pid))
    new_uris = [u for u in uris if u not in existing]
    print(f"  {len(new_uris)} novas faixas a adicionar (de {len(uris)}, {len(uris) - len(new_uris)} já estavam na playlist).")

    chunks = [new_uris[i:i+100] for i in range(0, len(new_uris), 100)]
    for i, chunk in enumerate(chunks, 1):
        if chunk:
            sp.playlist_add_items(pid, chunk)
        print(f"\r  Lote {i}/{max(1,len(chunks))}", end="", flush=True)
        time.sleep(0.2)
    print()

    CATEGORIZE_FILE.write_text(f"spotify:playlist:{pid}", encoding="utf-8")
    print(f"✓ Playlist '{CATEGORIZE_PLAYLIST_NAME}' atualizada ({pid}). URI salva em {CATEGORIZE_FILE.name}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "analyze"
    if cmd == "analyze":
        analyze()
    elif cmd == "like":
        like()
    elif cmd == "categorize":
        categorize()
    else:
        print("Uso: python spotify_liked_sync.py [analyze|like|categorize]")
