#!/usr/bin/env python3
"""
dj_library_v2.py — Biblioteca DJ
Discogs + Spotify: álbum-first matching, BPM via Deezer API,
gera XLSX e HTML interativo com views por LP e por Faixas.
"""

import sys, os, re, time, html as html_module, math, threading, webbrowser
import http.server, urllib.parse
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# ==============================================================================
# 0. DEPENDÊNCIAS
# ==============================================================================
import subprocess

def pip_install(*pkgs):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *pkgs])

try:
    import discogs_client
except ImportError:
    print("Instalando discogs-client..."); pip_install("discogs-client")
    import discogs_client

try:
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth
except ImportError:
    print("Instalando spotipy..."); pip_install("spotipy")
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

try:
    from thefuzz import fuzz
except ImportError:
    print("Instalando thefuzz..."); pip_install("thefuzz", "python-Levenshtein")
    from thefuzz import fuzz

try:
    from unidecode import unidecode
except ImportError:
    print("Instalando unidecode..."); pip_install("unidecode")
    from unidecode import unidecode

try:
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter
except ImportError:
    print("Instalando openpyxl..."); pip_install("openpyxl")
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.utils import get_column_letter

import pandas as pd
import json, requests

# ==============================================================================
# 1. CONFIGURAÇÃO
# ==============================================================================
DISCOGS_USER   = "amsa2diop"
DISCOGS_TOKEN  = "FmUsfbDTXUFCniDqrTckrwBfJxvIljOGuMdygfVD"
SP_CLIENT_ID   = "1ab6d898c52d42a19b737f451ce31e2a"
SP_CLIENT_SEC  = "3c8b2f47049b44e2af6937ea835e1f2f"
SP_REDIRECT    = "http://127.0.0.1:1410/"
SP_SCOPE       = "playlist-modify-public playlist-modify-private"

LIMIAR_ACEITO   = 72
LIMIAR_REVISAR  = 55
LIMIAR_ALBUM    = 58   # score mínimo para aceitar match de álbum

VA_KEYWORDS = {"various", "v.a.", "varios", "variados", "aa.vv.", "various artists"}

WORK_DIR = Path(__file__).parent


# ==============================================================================
# 2. AUTENTICAÇÃO SPOTIFY
# ==============================================================================
def spotify_auth():
    sp_oauth = SpotifyOAuth(
        client_id     = SP_CLIENT_ID,
        client_secret = SP_CLIENT_SEC,
        redirect_uri  = SP_REDIRECT,
        scope         = SP_SCOPE,
        cache_path    = str(WORK_DIR / ".spotify_cache"),
        open_browser  = False,
    )
    token_info = sp_oauth.get_cached_token()
    if token_info and not sp_oauth.is_token_expired(token_info):
        print("✓ Token Spotify em cache (válido).")
        return spotipy.Spotify(auth_manager=sp_oauth)

    auth_code_holder = [None]

    class OAuthHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                auth_code_holder[0] = params["code"][0]
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<h2>Autenticado. Pode fechar esta aba.</h2>")
            else:
                self.send_response(400); self.end_headers()
        def log_message(self, *a): pass

    server = http.server.HTTPServer(("127.0.0.1", 1410), OAuthHandler)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    auth_url = sp_oauth.get_authorize_url()
    print(f"\nAbrindo navegador para autenticação Spotify...")
    webbrowser.open(auth_url)
    t.join(timeout=120)
    server.server_close()
    if not auth_code_holder[0]:
        raise TimeoutError("Autenticação não completada em 120s.")
    sp_oauth.get_access_token(auth_code_holder[0])
    return spotipy.Spotify(auth_manager=sp_oauth)


# ==============================================================================
# 3. UTILITÁRIOS
# ==============================================================================
def normalize(text):
    if not text: return ""
    text = unidecode(str(text)).lower()
    text = re.sub(r"\(.*?\)|\[.*?\]", "", text)
    text = re.sub(r"\s*[-–—]\s+.*$", "", text)
    text = re.sub(r"\bfeat\.?\b.*$|\bft\.?\b.*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^a-z0-9 ]", "", text)
    return text.strip()


def match_score(disc_track, disc_artist, sp_track, sp_artist, album_artist=""):
    dt = normalize(disc_track)
    da = normalize(disc_artist)
    aa = normalize(album_artist)
    st = normalize(sp_track)
    sa = normalize(sp_artist)

    score_track  = fuzz.token_sort_ratio(dt, st)
    score_artist = max(
        fuzz.token_sort_ratio(da, sa),
        fuzz.token_sort_ratio(aa, sa) if aa else 0,
    )
    score = score_track * 0.65 + score_artist * 0.35

    sp_lo = sp_track.lower()
    di_lo = disc_track.lower()
    if re.search(r"\blive\b|ao vivo|concert|en vivo", sp_lo) and \
       not re.search(r"live|ao vivo|concert", di_lo):
        score -= 20
    if re.search(r"\bremix\b|\bedit\b|rework|dub mix", sp_lo) and \
       not re.search(r"remix|edit|rework|dub", di_lo):
        score -= 15
    if re.search(r"remaster", sp_lo) and not re.search(r"remaster", di_lo):
        score -= 5
    return max(0, score)


def is_va(artist_name):
    return normalize(artist_name) in VA_KEYWORDS or "various" in normalize(artist_name)


def key_to_camelot(key, mode):
    major = ["8B","3B","10B","5B","12B","7B","2B","9B","4B","11B","6B","1B"]
    minor = ["5A","12A","7A","2A","9A","4A","11A","6A","1A","8A","3A","10A"]
    if key is None or (isinstance(key, float) and math.isnan(key)):
        return ""
    return major[int(key)] if mode == 1 else minor[int(key)]


def bpm_color(bpm):
    if not bpm: return "#9C8070"
    try: bpm = float(bpm)
    except: return "#9C8070"
    if bpm < 70:  return "#5B3DC8"
    if bpm < 80:  return "#3B72C0"
    if bpm < 90:  return "#2898A8"
    if bpm < 100: return "#289870"
    if bpm < 110: return "#88A028"
    if bpm < 120: return "#C87820"
    if bpm < 130: return "#C05020"
    if bpm < 140: return "#B03020"
    return "#882020"


def safe_float(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except: return None


def normalize_bpm(bpm):
    """Divide BPM > 140 by 2 repeatedly to land in 70-140 range."""
    if bpm is None: return None
    b = float(bpm)
    while b > 140:
        b /= 2
    return round(b, 1) if b > 0 else None


def esc(v):
    if v is None or (isinstance(v, float) and math.isnan(v)): return ""
    return html_module.escape(str(v))


# ==============================================================================
# 4. DISCOGS: COLETA DE ÁLBUNS E FAIXAS
# ==============================================================================
def get_discogs_collection():
    print("Coletando coleção do Discogs...")
    d    = discogs_client.Client("DJLibrary/2.0", user_token=DISCOGS_TOKEN)
    user = d.user(DISCOGS_USER)
    col  = user.collection_folders[0].releases

    albums, tracks = [], []
    total, done = col.count, 0

    for item in col:
        try:
            rel = item.release
            album_artist = rel.artists[0].name if rel.artists else "Unknown"
            album_artist = re.sub(r"\s*\(\d+\)$", "", album_artist)
            album_title  = rel.title
            release_id   = rel.id
            year         = getattr(rel, "year", None)
            genres       = ", ".join(getattr(rel, "genres", []) or [])
            styles       = ", ".join(getattr(rel, "styles", []) or [])
            images       = getattr(rel, "images", []) or []
            cover_url    = images[0].get("uri", "") if images else ""
            thumb_url    = images[0].get("uri150", cover_url) if images else ""

            albums.append(dict(
                release_id=release_id, album_artist=album_artist,
                album_title=album_title, year=year, genres=genres,
                styles=styles, cover_url=cover_url, thumb_url=thumb_url,
            ))

            for trk in rel.tracklist:
                if trk.type_ != "track" or not trk.position:
                    continue
                trk_artist = trk.artists[0].name if trk.artists else album_artist
                trk_artist = re.sub(r"\s*\(\d+\)$", "", trk_artist)
                tracks.append(dict(
                    release_id=release_id, album_artist=album_artist,
                    album_title=album_title, year=year, genres=genres,
                    styles=styles, cover_url=cover_url, thumb_url=thumb_url,
                    position=trk.position, track_title=trk.title,
                    artist_raw=trk.artists[0].name if trk.artists else album_artist,
                    artist_clean=trk_artist,
                ))

            done += 1
            print(f"\r  {done}/{total} albums | {len(tracks)} tracks", end="", flush=True)
            time.sleep(0.5)

        except Exception as e:
            done += 1
            print(f"\n  Aviso album #{done}: {e}")
            time.sleep(2)

    print(f"\n✓ {done} albums | {len(tracks)} tracks")
    return pd.DataFrame(albums), pd.DataFrame(tracks)


# ==============================================================================
# 5. SPOTIFY: ALBUM-FIRST MATCHING
# ==============================================================================
def sp_search(sp, q, stype="track", limit=5):
    try:
        res = sp.search(q=q, type=stype, limit=limit)
        items = res[stype + "s"]["items"]
        return items or []
    except Exception:
        time.sleep(1)
        return []


def find_spotify_album(sp, album_title, album_artist, year=None):
    """Busca o álbum no Spotify. Retorna (album_obj, score) ou (None, 0)."""
    # Constrói variantes do nome do artista (para casos como "Igor Babidi" → "Babidi")
    words = album_artist.split()
    artist_variants = list(dict.fromkeys([
        album_artist,
        words[-1] if len(words) > 1 else None,       # última palavra
        words[0] if len(words) > 1 else None,         # primeira palavra
        " ".join(words[1:]) if len(words) > 2 else None,  # sem primeira palavra
    ]))
    artist_variants = [v for v in artist_variants if v]

    queries = []
    for av in artist_variants:
        queries.append(f'album:"{album_title}" artist:"{av}"')
    queries.append(f'{album_artist} {album_title}')
    if year:
        queries.insert(1, f'album:"{album_title}" artist:"{album_artist}" year:{year}')

    best, best_score = None, 0

    for q in queries:
        time.sleep(0.25)
        albums = sp_search(sp, q, stype="album", limit=5)
        for alb in albums:
            sp_title  = alb.get("name", "")
            sp_artist = alb["artists"][0]["name"] if alb.get("artists") else ""
            sc_title  = fuzz.token_sort_ratio(normalize(album_title), normalize(sp_title))
            sc_artist = max(
                fuzz.token_sort_ratio(normalize(av), normalize(sp_artist))
                for av in artist_variants
            )
            score = sc_title * 0.6 + sc_artist * 0.4
            if score > best_score:
                best_score = score
                best = alb
        if best_score >= 75:
            break

    return (best, best_score) if best_score >= LIMIAR_ALBUM else (None, 0)


def get_album_tracks(sp, album_id):
    """Retorna lista completa de faixas de um álbum Spotify."""
    tracks = []
    try:
        page = sp.album_tracks(album_id, limit=50)
        while page:
            tracks.extend(page["items"])
            page = sp.next(page) if page.get("next") else None
    except Exception:
        pass
    return tracks


def match_disc_to_album(disc_tracks_df, sp_tracks, album_artist):
    """
    Tenta fazer match das faixas Discogs com as faixas do álbum Spotify.
    Retorna dict {idx: match_dict} e lista de índices não encontrados.
    """
    matched, unmatched = {}, []

    for idx, row in disc_tracks_df.iterrows():
        best_score, best_sp = 0, None
        for sp_t in sp_tracks:
            sp_name   = sp_t.get("name", "")
            sp_artist = sp_t["artists"][0]["name"] if sp_t.get("artists") else ""
            # Dentro do álbum: peso maior para título
            sc_title  = fuzz.token_sort_ratio(normalize(row["track_title"]), normalize(sp_name))
            sc_artist = fuzz.token_sort_ratio(normalize(row["artist_clean"]), normalize(sp_artist))
            sc = sc_title * 0.80 + sc_artist * 0.20
            # Penalizações
            if re.search(r"\blive\b|ao vivo|concert", sp_name.lower()) and \
               not re.search(r"live|ao vivo|concert", row["track_title"].lower()):
                sc -= 20
            if re.search(r"\bremix\b|\bedit\b|rework", sp_name.lower()) and \
               not re.search(r"remix|edit|rework", row["track_title"].lower()):
                sc -= 15
            sc = max(0, sc)
            if sc > best_score:
                best_score, best_sp = sc, sp_t

        if best_sp and best_score >= LIMIAR_ACEITO:
            matched[idx] = dict(
                spotify_uri     = best_sp["uri"],
                found_name      = best_sp["name"],
                found_artist    = best_sp["artists"][0]["name"] if best_sp.get("artists") else "",
                track_id        = best_sp["id"],
                match_score     = round(best_score, 1),
                search_strategy = "album_first",
            )
        else:
            unmatched.append(idx)

    return matched, unmatched


def search_track_fallback(sp, artist, album_artist, title):
    """Busca individual de faixa — fallback para faixas não encontradas no álbum."""
    time.sleep(0.3)

    def run(q, limit=5):
        return sp_search(sp, q, stype="track", limit=limit)

    items = run(f'artist:"{artist}" track:"{title}"')
    if not items: time.sleep(0.2); items = run(f"{artist} {title}")
    if not items and artist.lower() != album_artist.lower():
        time.sleep(0.2); items = run(f"{album_artist} {title}")
    if not items: time.sleep(0.2); items = run(f'track:"{title}"')

    empty = dict(spotify_uri=None, found_name=None, found_artist=None,
                 track_id=None, match_score=0.0, search_strategy="not_found")
    if not items: return empty

    best_score, best = -1, empty
    for item in items[:5]:
        sp_name   = item.get("name", "")
        sp_artist = item["artists"][0]["name"] if item.get("artists") else ""
        sc = match_score(title, artist, sp_name, sp_artist, album_artist)
        if sc > best_score:
            best_score = sc
            best = dict(
                spotify_uri     = item["uri"],
                found_name      = sp_name,
                found_artist    = sp_artist,
                track_id        = item["id"],
                match_score     = round(sc, 1),
                search_strategy = "track",
            )
    return best


def run_album_first_matching(sp, df):
    """
    Matching completo com lógica álbum-first.
    - Para álbuns não-V.A.: primeiro busca o álbum Spotify, depois faz
      match das faixas nele. Faixas não encontradas no álbum fazem
      busca individual como fallback.
    - Para V.A./coletâneas: busca individual para cada faixa.
    """
    sp_cols = ["spotify_uri","found_name","found_artist","track_id",
               "match_score","search_strategy"]
    for col in sp_cols:
        df[col] = None

    albums = df.groupby("release_id")
    total_albums = len(albums)
    done_albums  = 0
    done_tracks  = 0

    for release_id, group in albums:
        first      = group.iloc[0]
        alb_artist = str(first["album_artist"])
        alb_title  = str(first["album_title"])
        year       = first.get("year")
        n_tracks   = len(group)

        if is_va(alb_artist):
            # V.A.: busca individual
            for idx, row in group.iterrows():
                res = search_track_fallback(sp, row["artist_clean"], alb_artist, row["track_title"])
                for k, v in res.items():
                    df.at[idx, k] = v
                done_tracks += 1
        else:
            # Álbum normal: tenta album-first
            sp_album, alb_score = find_spotify_album(sp, alb_title, alb_artist, year)

            if sp_album:
                sp_tracks = get_album_tracks(sp, sp_album["id"])
                matched, unmatched = match_disc_to_album(group, sp_tracks, alb_artist)

                for idx, res in matched.items():
                    for k, v in res.items():
                        df.at[idx, k] = v
                    done_tracks += 1

                # Fallback individual para não encontrados no álbum
                for idx in unmatched:
                    row = df.loc[idx]
                    res = search_track_fallback(sp, row["artist_clean"], alb_artist, row["track_title"])
                    for k, v in res.items():
                        df.at[idx, k] = v
                    done_tracks += 1
            else:
                # Álbum não encontrado: busca individual para todas as faixas
                for idx, row in group.iterrows():
                    res = search_track_fallback(sp, row["artist_clean"], alb_artist, row["track_title"])
                    for k, v in res.items():
                        df.at[idx, k] = v
                    done_tracks += 1

        done_albums += 1
        print(f"\r  {done_albums}/{total_albums} albums | {done_tracks}/{len(df)} faixas",
              end="", flush=True)

    print(f"\n✓ Matching concluído")

    df["status"] = df["match_score"].apply(
        lambda s: "ACEITO"   if pd.notna(s) and s >= LIMIAR_ACEITO
        else ("REVISAR"      if pd.notna(s) and s >= LIMIAR_REVISAR
        else "REJEITADO")
    )
    return df


# ==============================================================================
# 6. BPM — Deezer API (gratuita) + Spotify fallback
# ==============================================================================
_DEEZER_SESSION = None

def _deezer_session():
    global _DEEZER_SESSION
    if _DEEZER_SESSION is None:
        _DEEZER_SESSION = requests.Session()
        _DEEZER_SESSION.headers.update({
            "User-Agent": "DJLibrary/2.0",
            "Accept": "application/json",
        })
    return _DEEZER_SESSION


def _deezer_search_bpm(artist, title):
    """
    Busca BPM no Deezer por artista+título.
    Retorna (bpm_float, deezer_id_str) ou (None, None).
    """
    q = f"{normalize(artist)} {normalize(title)}"
    try:
        r = _deezer_session().get(
            "https://api.deezer.com/search",
            params={"q": q, "limit": 5},
            timeout=12,
        )
        if r.status_code == 429:
            time.sleep(10)
            return None, None
        if r.status_code != 200:
            return None, None
        hits = r.json().get("data", [])
        if not hits:
            return None, None

        # Escolhe a melhor correspondência por fuzzy
        t_norm = normalize(title)
        a_norm = normalize(artist)
        best_id = None
        best_sc = 0
        for hit in hits:
            sc_t = fuzz.token_sort_ratio(t_norm, normalize(hit.get("title", "")))
            sc_a = fuzz.token_sort_ratio(a_norm, normalize(hit.get("artist", {}).get("name", "")))
            sc = sc_t * 0.7 + sc_a * 0.3
            if sc > best_sc:
                best_sc = sc
                best_id = hit["id"]

        if best_sc < 60 or not best_id:
            return None, None

        # Busca detalhes da track (tem BPM)
        r2 = _deezer_session().get(f"https://api.deezer.com/track/{best_id}", timeout=12)
        if r2.status_code != 200:
            return None, None
        bpm = r2.json().get("bpm", 0)
        if bpm and float(bpm) > 0:
            return normalize_bpm(float(bpm)), str(best_id)
        return None, None
    except Exception:
        return None, None


def get_bpm_deezer(df):
    """
    Busca BPM via Deezer API (gratuita, sem autenticação) para faixas aceitas.
    Usa found_artist + found_name (nomes do Spotify) como query de busca.
    Retorna dict {track_id: {bpm, source}}.
    """
    accepted = df[df["status"] == "ACEITO"].copy()
    # Agrupa por track_id para não buscar duplicatas
    unique_tracks = accepted.dropna(subset=["track_id"]).drop_duplicates(subset=["track_id"])
    total = len(unique_tracks)
    if total == 0:
        return {}

    print(f"\nBuscando BPM no Deezer para {total} faixas únicas...")
    results = {}
    found = 0

    for i, (_, row) in enumerate(unique_tracks.iterrows()):
        tid = str(row.get("track_id", "") or "")
        artist = str(row.get("found_artist", "") or row.get("album_artist", "") or "")
        title  = str(row.get("found_name", "") or row.get("track_title", "") or "")

        bpm, deezer_id = _deezer_search_bpm(artist, title)
        if bpm:
            results[tid] = {"bpm": bpm, "deezer_id": deezer_id or "", "source": "deezer"}
            found += 1

        if (i + 1) % 50 == 0 or (i + 1) == total:
            print(f"\r  {i+1}/{total} | com BPM: {found}", end="", flush=True)
        time.sleep(0.25)  # ~4 req/s, bem abaixo do limite do Deezer

    print(f"\r  {total}/{total} | com BPM: {found} ({100*found//max(total,1)}%)")
    if found == 0:
        print("  ⚠ Deezer não retornou BPM — verifique conexão.")
    return results


def get_bpm_spotify(sp, track_ids):
    """Tenta buscar BPM via Spotify audio_features (pode falhar com 403)."""
    valid   = [t for t in track_ids if t]
    results = {}
    chunks  = [valid[i:i+100] for i in range(0, len(valid), 100)]

    for chunk in chunks:
        time.sleep(0.4)
        try:
            feats = sp.audio_features(chunk)
            for f in feats or []:
                if f:
                    results[f["id"]] = {
                        "bpm":          round(f["tempo"], 1),
                        "energy":       round(f["energy"], 2),
                        "danceability": round(f["danceability"], 2),
                        "valence":      round(f["valence"], 2),
                        "key":          f["key"],
                        "mode":         f["mode"],
                        "camelot":      key_to_camelot(f["key"], f["mode"]),
                        "source":       "spotify",
                    }
        except Exception as e:
            if "403" in str(e):
                print("\n  ✗ Spotify audio_features: 403 — app sem acesso (depreciado para novos apps).")
                return results  # Não tenta mais
            pass
    return results


def fetch_bpm(sp, df):
    """
    Busca BPM para faixas aceitas.
    Estratégia: 1) Spotify audio_features  2) Deezer API (gratuita)
    """
    bpm_cols = ["bpm","energy","danceability","valence","key","mode","camelot","deezer_id"]
    for col in bpm_cols:
        if col not in df.columns:
            df[col] = None

    # Checa se já tem BPM preenchido
    existing_bpm = df["bpm"].apply(safe_float).notna().sum()
    if existing_bpm > 0:
        print(f"✓ BPM já preenchido para {existing_bpm} faixas (carregado do backup).")
        return df

    accepted_ids = df[df["status"]=="ACEITO"]["track_id"].dropna().unique().tolist()
    if not accepted_ids:
        print("Nenhuma faixa aceita para buscar BPM.")
        return df

    # 1. Tenta Spotify
    print(f"\nTentando Spotify audio_features para {len(accepted_ids)} faixas...")
    bpm_map = get_bpm_spotify(sp, accepted_ids)

    # 2. Se Spotify falhou, usa Deezer
    if len(bpm_map) < len(accepted_ids) * 0.1:
        deezer_map = get_bpm_deezer(df)
        bpm_map.update(deezer_map)

    # Aplica BPM ao dataframe
    for i, row in df.iterrows():
        tid = str(row.get("track_id") or "")
        if tid and tid in bpm_map:
            entry = bpm_map[tid]
            df.at[i, "bpm"] = entry.get("bpm")
            # Deezer: salva deezer_id para embed; Spotify: salva campos extras
            for k in ["energy","danceability","valence","key","mode","camelot","deezer_id"]:
                if k in entry:
                    df.at[i, k] = entry.get(k)

    found = df["bpm"].apply(safe_float).notna().sum()
    print(f"✓ BPM obtido para {found}/{len(accepted_ids)} faixas aceitas")
    return df


# ==============================================================================
# 7. EXECUÇÃO PRINCIPAL
# ==============================================================================
def main():
    sp = spotify_auth()
    print("✓ Spotify autenticado.\n")

    # ── Discogs ──────────────────────────────────────────────────────────────
    backup_tracks = WORK_DIR / "backup_tracks.csv"
    if backup_tracks.exists():
        print(f"Carregando backup Discogs: {backup_tracks.name}")
        df = pd.read_csv(backup_tracks)
    else:
        _, df = get_discogs_collection()
        df.to_csv(backup_tracks, index=False)

    print(f"  {df['release_id'].nunique()} albums | {len(df)} faixas\n")

    # ── Matching ─────────────────────────────────────────────────────────────
    backup_v2  = WORK_DIR / "backup_matched_v2.csv"
    backup_old = WORK_DIR / "backup_final.csv"

    if backup_v2.exists():
        print(f"Carregando backup v2: {backup_v2.name}")
        df_matched = pd.read_csv(backup_v2)
    elif backup_old.exists():
        print(f"Carregando backup existente: {backup_old.name}")
        df_matched = pd.read_csv(backup_old)
        print("  (Para re-executar com album-first matching, delete backup_matched_v2.csv)")
    else:
        print("Executando album-first matching...")
        df_matched = run_album_first_matching(sp, df.copy())
        df_matched.to_csv(backup_v2, index=False)
        print(f"  Salvo: {backup_v2.name}")

    aceitos   = (df_matched["status"]=="ACEITO").sum()
    revisao   = (df_matched["status"]=="REVISAR").sum()
    rejeitado = (df_matched["status"]=="REJEITADO").sum()
    print(f"\n  Aceitos: {aceitos} | Revisar: {revisao} | Rejeitados: {rejeitado}\n")

    # ── BPM ──────────────────────────────────────────────────────────────────
    BPM_COLS   = ["bpm","energy","danceability","valence","key","mode","camelot","deezer_id"]
    backup_bpm = WORK_DIR / "backup_bpm.csv"

    existing_bpm = df_matched["bpm"].apply(safe_float).notna().sum() if "bpm" in df_matched.columns else 0

    if existing_bpm > 0:
        print(f"✓ BPM já disponível para {existing_bpm} faixas.")
    elif backup_bpm.exists():
        print(f"Carregando BPM do backup: {backup_bpm.name}")
        bpm_df  = pd.read_csv(backup_bpm).dropna(subset=["track_id"])
        # Normaliza BPMs > 140 (divide por 2 até ficar em 70-140)
        bpm_df["bpm"] = bpm_df["bpm"].apply(lambda v: normalize_bpm(safe_float(v)))
        bpm_map = {str(r["track_id"]): r for _, r in bpm_df.iterrows()}
        for col in BPM_COLS:
            df_matched[col] = None
        for i, row in df_matched.iterrows():
            tid = str(row.get("track_id") or "")
            if tid and tid in bpm_map:
                for col in BPM_COLS:
                    df_matched.at[i, col] = bpm_map[tid].get(col)
        filled = df_matched["bpm"].apply(safe_float).notna().sum()
        print(f"  BPM carregado para {filled} faixas")
    else:
        df_matched = fetch_bpm(sp, df_matched)
        bpm_found  = df_matched[df_matched["bpm"].apply(safe_float).notna()]
        if len(bpm_found) > 0:
            bpm_found[["track_id"] + BPM_COLS].to_csv(backup_bpm, index=False)
            print(f"  BPM salvo: {backup_bpm.name}")

    return sp, df_matched


# ==============================================================================
# 8. XLSX
# ==============================================================================
def generate_xlsx(df):
    print("\nGerando XLSX...")
    path = WORK_DIR / "MinhaColecao_DJ.xlsx"
    wb   = openpyxl.Workbook()

    hdr_fill  = PatternFill("solid", fgColor="7B3020")
    hdr_font  = Font(color="FAF7F3", bold=True)
    ok_fill   = PatternFill("solid", fgColor="DDF0E8")
    warn_fill = PatternFill("solid", fgColor="FDF3DC")
    rej_fill  = PatternFill("solid", fgColor="F5E0DC")

    cols = ["status","album_artist","artist_clean","track_title","album_title",
            "year","genres","styles","bpm","camelot","energy","danceability",
            "valence","match_score","found_artist","found_name",
            "search_strategy","spotify_uri","cover_url"]

    def write_sheet(ws, data, name):
        ws.title = name
        if data.empty:
            ws.append(["Nenhum dado."]); return
        sub = data[[c for c in cols if c in data.columns]].copy()
        ws.append(list(sub.columns))
        for cell in ws[1]:
            cell.fill = hdr_fill; cell.font = hdr_font
            cell.alignment = Alignment(horizontal="center")
        status_idx = list(sub.columns).index("status") + 1 if "status" in sub.columns else None
        for _, row in sub.iterrows():
            ws.append([None if isinstance(v, float) and math.isnan(v) else v for v in row])
        if status_idx:
            for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
                val  = row[status_idx - 1].value
                fill = ok_fill if val=="ACEITO" else (warn_fill if val=="REVISAR" else rej_fill)
                for cell in row: cell.fill = fill
        for i, col in enumerate(ws.columns, 1):
            max_len = max((len(str(c.value or "")) for c in col), default=8)
            ws.column_dimensions[get_column_letter(i)].width = min(max_len + 2, 50)

    ws1 = wb.active
    write_sheet(ws1, df.sort_values(["album_artist","album_title","position"],
                na_position="last"), "Todos (por album)")

    ws2 = wb.create_sheet()
    df_ok = df[df["status"]=="ACEITO"].copy()
    df_ok["bpm"] = pd.to_numeric(df_ok["bpm"], errors="coerce")
    write_sheet(ws2, df_ok.sort_values("bpm", na_position="last"), "Aceitos (por BPM)")

    ws3 = wb.create_sheet()
    write_sheet(ws3, df[df["status"]=="REVISAR"].sort_values("match_score", ascending=False),
                "Para Revisar")

    ws4 = wb.create_sheet()
    write_sheet(ws4, df[df["status"]=="REJEITADO"], "Nao Encontrados")

    wb.save(path)
    print(f"✓ {path.name} salvo")
    return path


# ==============================================================================
# 9. PLAYLIST SPOTIFY
# ==============================================================================
def create_playlist(sp, df):
    print("\nCriando playlist Spotify (por BPM)...")
    df_pl = df[df["status"]=="ACEITO"].copy()
    df_pl["bpm"] = pd.to_numeric(df_pl["bpm"], errors="coerce")
    df_pl = df_pl.sort_values("bpm", na_position="last")
    uris  = df_pl["spotify_uri"].dropna().tolist()
    if not uris:
        print("  Nenhuma faixa aceita para playlist."); return

    from datetime import datetime
    uid = sp.current_user()["id"]
    pl  = sp.user_playlist_create(
        user=uid, name="Meu Discogs — por BPM", public=False,
        description=f"Vinil ordenado por BPM | {datetime.now().strftime('%d/%m/%Y')}",
    )
    pid = pl["id"]
    chunks = [uris[i:i+100] for i in range(0, len(uris), 100)]
    for i, chunk in enumerate(chunks):
        sp.playlist_add_items(pid, chunk); time.sleep(0.3)
        print(f"\r  Lote {i+1}/{len(chunks)}", end="", flush=True)
    print(f"\n✓ Playlist criada com {len(uris)} faixas")
    pl_url = f"https://open.spotify.com/playlist/{pid}"
    (WORK_DIR / "backup_playlist.txt").write_text(pl_url, encoding="utf-8")
    print(f"  {pl_url}")


# ==============================================================================
# 10. HTML — DESIGN BEGE/TERROSO, DUAS VIEWS
# ==============================================================================
CSS = """
:root{
  --bg:#FFFFFF;--bg2:#F5F1EB;--card:#FAF8F5;--card2:#F0EBE3;
  --text:#1A0C06;--text2:#5C4030;--text3:#A08070;
  --acc:#6B1A0D;--acc2:#9B3A20;
  --bdr:#EAE3DB;--bdr2:#F2EDE7;--tag:#EDE5D8;
  --bpm-col:#6B1A0D;
  --r:14px;--r-sm:8px;
  --shadow:0 2px 12px rgba(0,0,0,.06),0 1px 3px rgba(0,0,0,.03);
  --shadow-h:0 4px 20px rgba(0,0,0,.10),0 2px 6px rgba(0,0,0,.05);
}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"Helvetica Neue",Arial,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
h1,h2,h3,.serif{font-family:Georgia,"Times New Roman",serif}

/* HEADER — dashboard single-line */
.site-header{background:var(--bg);border-bottom:1px solid var(--bdr);
  display:flex;align-items:center;gap:1.4rem;padding:0 2.5rem;
  height:54px;position:sticky;top:0;z-index:100;flex-shrink:0}
.logo{display:flex;align-items:center;gap:.45rem;text-decoration:none;flex-shrink:0}
.logo-mark{color:var(--acc);font-size:.65rem}
.logo-name{font-family:Georgia,serif;font-weight:normal;color:var(--acc);
  font-size:1.15rem;letter-spacing:.04em;white-space:nowrap}
.header-sep{width:1px;height:22px;background:var(--bdr);flex-shrink:0}
.site-stats{display:flex;gap:.55rem;align-items:center;flex:1;min-width:0}
.stat-item{font-size:.65rem;color:var(--text3);white-space:nowrap}
.stat-item strong{color:var(--text2);font-weight:600}
.stat-dot{color:var(--bdr2);font-size:.55rem}
.header-tabs{display:flex;margin-left:auto;flex-shrink:0}
.tab-btn{padding:0 1.1rem;height:54px;font-size:.68rem;letter-spacing:.12em;
  text-transform:uppercase;cursor:pointer;background:none;border:none;
  border-bottom:2px solid transparent;color:var(--text3);
  transition:color .18s,border-color .18s;white-space:nowrap}
.tab-btn.active{color:var(--acc);border-bottom-color:var(--acc)}
.tab-btn:hover:not(.active){color:var(--text2)}

/* COPY BADGE */
.copy-badge{display:inline-block;padding:.1rem .42rem;border-radius:4px;font-size:.6rem;
  font-weight:700;letter-spacing:.07em;text-transform:uppercase;
  background:rgba(107,26,13,.1);color:var(--acc);border:1px solid rgba(107,26,13,.18);
  margin-left:.35rem;vertical-align:middle}

/* DISCOGS LINK */
.discogs-link{display:inline-flex;align-items:center;gap:.25rem;font-size:.65rem;
  color:var(--text3);text-decoration:none;border:1px solid var(--bdr);
  padding:.18rem .5rem;border-radius:6px;transition:color .15s,border-color .15s}
.discogs-link:hover{color:var(--acc);border-color:var(--acc2)}

/* CUSTOM FIELDS */
.fields-row{display:flex;flex-wrap:wrap;gap:.25rem .7rem;margin-top:.45rem}
.field-item{font-size:.65rem;color:var(--text3)}
.field-item strong{color:var(--text2);font-weight:600}
.field-notes{font-size:.68rem;color:var(--text2);font-style:italic;
  margin-top:.3rem;padding:.28rem .5rem;background:var(--bg2);
  border-left:2px solid var(--bdr);border-radius:0 4px 4px 0}

/* tabs already inside .site-header — keep rule for compat */
.tab-nav{display:none}
.tab-btn{padding:.85rem 1.5rem;font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;
  cursor:pointer;background:none;border:none;border-bottom:2px solid transparent;
  color:var(--text3);transition:color .2s,border-color .2s}
.tab-btn.active{color:var(--acc);border-bottom-color:var(--acc)}
.tab-btn:hover:not(.active){color:var(--text2)}

/* VIEW */
.view{display:none}.view.active{display:block}

/* CONTROLS */
.controls{z-index:50;background:rgba(255,255,255,.96);backdrop-filter:blur(10px);
  border-bottom:1px solid var(--bdr);padding:.5rem 2.5rem;
  display:flex;flex-direction:column;gap:.38rem}
.ctrl-row{display:flex;gap:.45rem;align-items:center;flex-wrap:wrap}
.ctrl-input{background:var(--bg2);border:1px solid var(--bdr);color:var(--text);
  padding:.4rem .9rem;border-radius:20px;font-size:.84rem;outline:none;
  flex:1;min-width:160px;transition:border-color .15s}
.ctrl-input:focus{border-color:var(--acc)}
.ctrl-sel{background:var(--bg2);border:1px solid var(--bdr);color:var(--text);
  padding:.4rem .7rem;border-radius:8px;font-size:.79rem;outline:none;cursor:pointer}
.ctrl-btn{background:transparent;border:1px solid var(--bdr);color:var(--text2);
  padding:.36rem .8rem;border-radius:8px;font-size:.72rem;letter-spacing:.04em;
  text-transform:uppercase;cursor:pointer;white-space:nowrap;transition:all .18s}
.ctrl-btn:hover{border-color:var(--acc);color:var(--acc)}

/* CHIPS */
.chips-row{display:flex;gap:.28rem;flex-wrap:wrap;align-items:center}
.chip{padding:.26rem .62rem;border-radius:20px;font-size:.69rem;letter-spacing:.03em;
  cursor:pointer;border:1px solid var(--bdr);background:transparent;color:var(--text3);
  transition:all .15s;white-space:nowrap}
.chip.active{background:var(--acc);border-color:var(--acc);color:#fff}
.chip.multi-active{background:var(--acc2);border-color:var(--acc2);color:#fff}
.chip:hover:not(.active):not(.multi-active){border-color:var(--acc2);color:var(--acc)}
.chips-label{font-size:.62rem;color:var(--text3);white-space:nowrap;letter-spacing:.05em;
  text-transform:uppercase}

/* PLAYLIST BUTTON */
.playlist-btn{display:inline-flex;align-items:center;gap:.35rem;padding:.32rem .8rem;
  border-radius:20px;font-size:.7rem;font-weight:600;letter-spacing:.04em;
  background:#1DB954;color:#fff;border:none;cursor:pointer;text-decoration:none;
  transition:opacity .15s;white-space:nowrap}
.playlist-btn:hover{opacity:.85}

/* MAIN */
.main{max-width:1200px;margin:0 auto;padding:1.4rem 2.5rem}
.results-bar{font-size:.7rem;color:var(--text3);letter-spacing:.06em;
  text-transform:uppercase;margin-bottom:1rem}

/* BPM NOTICE */
.bpm-notice{background:rgba(107,26,13,.05);border:1px solid rgba(107,26,13,.12);
  border-radius:var(--r-sm);padding:.55rem 1.1rem;font-size:.76rem;
  color:var(--text2);margin-bottom:1rem}

/* ── LP VIEW ── */
.albums-grid{display:flex;flex-direction:column;gap:.45rem}
.album-card{background:var(--card);border:1px solid var(--bdr);border-radius:var(--r);
  overflow:hidden;transition:box-shadow .2s;box-shadow:var(--shadow);position:relative}
.album-card:hover{box-shadow:var(--shadow-h)}
.album-card.hidden{display:none}
.cover-blur{position:absolute;inset:0;background-size:cover;background-position:center;
  filter:blur(40px) saturate(3) brightness(.5);opacity:.09;transform:scale(1.15);pointer-events:none}
.album-header{display:flex;align-items:center;gap:1rem;padding:1rem 1.2rem;
  cursor:pointer;user-select:none;position:relative;z-index:1}
.cover-wrap{flex-shrink:0}
.cover-img{width:90px;height:90px;object-fit:cover;border-radius:var(--r-sm);display:block;
  box-shadow:0 2px 8px rgba(0,0,0,.18)}
.cover-ph{width:90px;height:90px;border-radius:var(--r-sm);background:var(--bg2);
  display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:1.8rem}
.album-info{flex:1;min-width:0}
.alb-artist{font-weight:600;font-size:.94rem;color:var(--text)}
.alb-title{color:var(--text2);font-size:.81rem;margin-top:.1rem;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.alb-meta{display:flex;flex-wrap:wrap;gap:.28rem;margin-top:.48rem;align-items:center}
.tag{padding:.11rem .42rem;border-radius:5px;font-size:.59rem;font-weight:600;
  letter-spacing:.06em;text-transform:uppercase;background:var(--bg2);color:var(--text3)}
.tag-acc{background:rgba(107,26,13,.08);color:var(--acc)}
.alb-tracks-info{font-size:.65rem;color:var(--text3);margin-top:.32rem}
.toggle-btn{background:none;border:none;color:var(--text3);cursor:pointer;
  padding:.3rem .6rem;font-size:.85rem;flex-shrink:0;transition:transform .25s,color .2s;
  position:relative;z-index:1}
.album-card.open .toggle-btn{transform:rotate(180deg);color:var(--acc)}
.tracks-list{border-top:1px solid var(--bdr2);background:rgba(255,255,255,.75)}
.tracks-list.collapsed{display:none}

/* TRACK ITEM (LP view) */
.track{padding:.58rem 1.2rem;border-bottom:1px solid var(--bdr2);
  display:flex;align-items:center;gap:.65rem;transition:background .1s}
.track:last-child{border-bottom:none}
.track:hover{background:rgba(107,26,13,.025)}
.trk-pos{font-size:.61rem;color:var(--text3);width:22px;flex-shrink:0;letter-spacing:.03em}
.trk-info{flex:1;min-width:100px}
.trk-artist{font-size:.67rem;color:var(--text3)}
.trk-name{font-size:.87rem;font-weight:500;color:var(--text)}
.trk-badges{display:flex;gap:.3rem;align-items:center}
.badge-bpm{padding:.15rem .42rem;border-radius:5px;font-size:.71rem;font-weight:700;
  background:rgba(107,26,13,.1);color:var(--bpm-col)}
.trk-status{width:5px;height:5px;border-radius:50%;flex-shrink:0;margin-left:.15rem}
.s-ok{background:#3A9060}.s-rev{background:#C08020}.s-rej{background:var(--bdr)}

/* EMBED */
.embed-ph{margin-top:.38rem;display:inline-flex;align-items:center;gap:.3rem;
  border:1px solid var(--bdr);color:var(--text3);padding:.22rem .58rem;
  border-radius:20px;font-size:.7rem;cursor:pointer;transition:all .15s}
.embed-ph:hover{border-color:var(--acc2);color:var(--acc)}
.sp-embed{margin-top:.38rem;border-radius:var(--r-sm);display:block}
.no-spotify{margin-top:.3rem;font-size:.67rem;color:var(--text3);font-style:italic}

/* ── TRACK VIEW ── */
.track-rows{display:flex;flex-direction:column;gap:.38rem}
.track-row{background:var(--card);border:1px solid var(--bdr);border-radius:var(--r);
  padding:.8rem 1rem;display:flex;align-items:center;gap:.85rem;
  transition:box-shadow .15s;box-shadow:var(--shadow);position:relative;overflow:hidden}
.track-row:hover{box-shadow:var(--shadow-h)}
.track-row.hidden{display:none}
.track-row .cover-blur{opacity:.06}
.tr-thumb{width:56px;height:56px;object-fit:cover;border-radius:var(--r-sm);
  flex-shrink:0;box-shadow:0 2px 6px rgba(0,0,0,.14);position:relative;z-index:1}
.tr-thumb-ph{width:56px;height:56px;background:var(--bg2);border-radius:var(--r-sm);
  display:flex;align-items:center;justify-content:center;color:var(--text3);
  font-size:1.2rem;flex-shrink:0;position:relative;z-index:1}
.tr-info{flex:1;min-width:140px;position:relative;z-index:1}
.tr-name{font-weight:600;font-size:.9rem;color:var(--text)}
.tr-artist{font-size:.72rem;color:var(--text3);margin-top:.07rem}
.tr-album{font-size:.67rem;color:var(--text3);margin-top:.04rem;
  font-style:italic;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:220px}
.tr-meta{font-size:.63rem;color:var(--text3);margin-top:.12rem}
.tr-discogs-link{font-size:.6rem;color:var(--text3);text-decoration:none;
  border:1px solid var(--bdr);border-radius:4px;padding:.04rem .3rem;
  margin-top:.1rem;display:inline-block;transition:color .15s,border-color .15s}
.tr-discogs-link:hover{color:var(--acc);border-color:var(--acc2)}
.tr-bpm-area{flex-shrink:0;text-align:center;min-width:60px;position:relative;z-index:1}
.tr-bpm-num{font-family:Georgia,serif;font-size:2rem;font-weight:bold;
  color:var(--bpm-col);line-height:1}
.tr-bpm-lbl{font-size:.53rem;color:var(--text3);text-transform:uppercase;
  letter-spacing:.1em;margin-top:.08rem}
.tr-src{font-size:.52rem;color:var(--text3);letter-spacing:.04em;
  border:1px solid var(--bdr);border-radius:3px;padding:.04rem .28rem;
  margin-top:.15rem;display:inline-block}
.tr-play{flex-shrink:0;position:relative;z-index:1}
.tr-play-btn{border:1px solid var(--bdr);background:transparent;color:var(--text3);
  padding:.28rem .62rem;border-radius:20px;font-size:.7rem;cursor:pointer;
  transition:all .15s;white-space:nowrap}
.tr-play-btn:hover{border-color:var(--acc2);color:var(--acc)}

/* RESPONSIVE */
@media(max-width:640px){
  .site-header{padding:0 1rem;gap:.8rem}
  .site-stats{display:none}
  .header-sep{display:none}
  .controls{padding:.45rem .9rem}.main{padding:.9rem .9rem}
  .album-header{gap:.7rem;padding:.8rem .9rem}
  .cover-img,.cover-ph{width:68px;height:68px}
  .tr-bpm-num{font-size:1.5rem}
}
"""

JS = r"""
// ── VIEW SWITCHING ────────────────────────────────────────────────────────────
function switchView(v){
  document.querySelectorAll('.view').forEach(function(el){el.classList.remove('active')});
  document.querySelectorAll('.tab-btn').forEach(function(el){el.classList.remove('active')});
  document.getElementById('view-'+v).classList.add('active');
  document.querySelector('[data-v="'+v+'"]').classList.add('active');
}

// ── LP VIEW ───────────────────────────────────────────────────────────────────
function toggleAlbum(hdr){
  var c=hdr.closest('.album-card'),l=c.querySelector('.tracks-list');
  c.classList.toggle('open');l.classList.toggle('collapsed');
}
function expandAll(){
  document.querySelectorAll('#grid-lp .album-card:not(.hidden)').forEach(function(c){
    c.classList.add('open');c.querySelector('.tracks-list').classList.remove('collapsed');
  });
}
function collapseAll(){
  document.querySelectorAll('#grid-lp .album-card').forEach(function(c){
    c.classList.remove('open');c.querySelector('.tracks-list').classList.add('collapsed');
  });
}
var origemFilter='all';
var nacionalFilter='all'; // 'all' | 'nacional' | 'internacional'
var decadeFilter=new Set(); // vazio = todos

function setOrigemFilter(val,el){
  origemFilter=val;
  document.querySelectorAll('.origem-chip').forEach(function(c){c.classList.remove('active')});
  el.classList.add('active');
  filterLP();
}
function setNacionalFilter(val,el){
  nacionalFilter=val;
  document.querySelectorAll('.nac-chip').forEach(function(c){c.classList.remove('active')});
  el.classList.add('active');
  filterLP();
}
function setDecadeFilter(val,el){
  if(val==='all'){
    decadeFilter.clear();
    document.querySelectorAll('.decade-chip').forEach(function(c){
      c.classList.remove('active');c.classList.remove('multi-active');
    });
    el.classList.add('active');
  } else {
    document.querySelector('.decade-chip[data-val="all"]').classList.remove('active');
    if(decadeFilter.has(val)){
      decadeFilter.delete(val);
      el.classList.remove('multi-active');
    } else {
      decadeFilter.add(val);
      el.classList.add('multi-active');
    }
    if(decadeFilter.size===0){
      document.querySelector('.decade-chip[data-val="all"]').classList.add('active');
    }
  }
  filterLP();
}
function filterLP(){
  var q=document.getElementById('q-lp').value.toLowerCase().trim();
  var s=document.getElementById('sort-lp').value;
  var grid=document.getElementById('grid-lp');
  var cards=Array.from(grid.querySelectorAll('.album-card'));
  var vis=0;
  cards.forEach(function(c){
    var qOk=!q||c.dataset.search.includes(q);
    var origOk=origemFilter==='all'||(origemFilter===''?!c.dataset.origem:c.dataset.origem===origemFilter);
    var isBrazil=c.dataset.country==='brazil';
    var nacOk=nacionalFilter==='all'||(nacionalFilter==='nacional'&&isBrazil)||(nacionalFilter==='internacional'&&!isBrazil);
    var decOk=decadeFilter.size===0||decadeFilter.has(c.dataset.decade);
    var ok=qOk&&origOk&&nacOk&&decOk;
    c.classList.toggle('hidden',!ok);if(ok)vis++;
  });
  document.getElementById('cnt-lp').textContent=vis;
  if(s){
    var vc=cards.filter(function(c){return!c.classList.contains('hidden')});
    vc.sort(function(a,b){
      if(s==='bpm-asc') return(+a.dataset.minBpm||999)-(+b.dataset.minBpm||999);
      if(s==='bpm-desc')return(+b.dataset.minBpm||0)-(+a.dataset.minBpm||0);
      if(s==='year-asc') return(+a.dataset.year||0)-(+b.dataset.year||0);
      if(s==='year-desc')return(+b.dataset.year||0)-(+a.dataset.year||0);
      if(s==='az')return(a.dataset.artist||'').localeCompare(b.dataset.artist||'');
      return 0;
    });
    vc.forEach(function(c){grid.appendChild(c)});
  }
}

// ── TRACK VIEW ────────────────────────────────────────────────────────────────
var activeBpmRange='all';
var bpmPresenceFilter='all'; // 'all' | 'with' | 'without'

function setBpmPresence(mode,el){
  bpmPresenceFilter=mode;
  document.querySelectorAll('.bpm-pres-chip').forEach(function(c){c.classList.remove('active')});
  el.classList.add('active');
  filterTracks();
}
function setBpmRange(range,el){
  activeBpmRange=range;
  document.querySelectorAll('.bpm-range-chip').forEach(function(c){c.classList.remove('active')});
  el.classList.add('active');
  filterTracks();
}
function bpmInRange(bpm,range){
  if(range==='all')return true;
  if(range==='nobpm')return!bpm||bpm===0;
  if(!bpm||bpm===0)return false;
  if(range==='sub70')return bpm<70;
  if(range==='140plus')return bpm>=140;
  var parts=range.split('-');
  return bpm>=+parts[0]&&bpm<+parts[1];
}
function filterTracks(){
  var q=document.getElementById('q-faixas').value.toLowerCase().trim();
  var s=document.getElementById('sort-faixas').value;
  var grid=document.getElementById('grid-faixas');
  var rows=Array.from(grid.querySelectorAll('.track-row'));
  var vis=0;
  rows.forEach(function(r){
    var bpm=+r.dataset.bpm||0;
    var hasBpm=r.dataset.hasbpm==='1';
    var presOk=(bpmPresenceFilter==='all')||(bpmPresenceFilter==='with'&&hasBpm)||(bpmPresenceFilter==='without'&&!hasBpm);
    var ok=((!q)||r.dataset.search.includes(q))&&bpmInRange(bpm,activeBpmRange)&&presOk;
    r.classList.toggle('hidden',!ok);if(ok)vis++;
  });
  document.getElementById('cnt-faixas').textContent=vis;
  if(s){
    var vr=rows.filter(function(r){return!r.classList.contains('hidden')});
    vr.sort(function(a,b){
      if(s==='bpm-asc'){var ba=+a.dataset.bpm||999,bb=+b.dataset.bpm||999;return ba-bb;}
      if(s==='bpm-desc'){var ba=+a.dataset.bpm||0,bb=+b.dataset.bpm||0;return bb-ba;}
      if(s==='az')return(a.dataset.artist||'').localeCompare(b.dataset.artist||'');
      return 0;
    });
    vr.forEach(function(r){grid.appendChild(r)});
  }
}

// ── EMBED ──────────────────────────────────────────────────────────────────────
function loadEmbed(el,tid){
  var iframe=document.createElement('iframe');
  iframe.src='https://open.spotify.com/embed/track/'+tid+'?utm_source=generator';
  iframe.width='100%';iframe.height='80';iframe.frameBorder='0';
  iframe.allow='autoplay;clipboard-write;encrypted-media;fullscreen;picture-in-picture';
  iframe.className='sp-embed';
  el.parentNode.replaceChild(iframe,el);
}
function loadDeezerEmbed(el,did){
  var iframe=document.createElement('iframe');
  iframe.src='https://widget.deezer.com/widget/light/track/'+did;
  iframe.width='100%';iframe.height='80';iframe.frameBorder='0';
  iframe.allow='autoplay;clipboard-write;encrypted-media;fullscreen;picture-in-picture';
  iframe.className='sp-embed';
  el.parentNode.replaceChild(iframe,el);
}

// ── INIT ──────────────────────────────────────────────────────────────────────
var t1;document.getElementById('q-lp').addEventListener('input',function(){clearTimeout(t1);t1=setTimeout(filterLP,200)});
var t2;document.getElementById('q-faixas').addEventListener('input',function(){clearTimeout(t2);t2=setTimeout(filterTracks,200)});
document.getElementById('cnt-lp').textContent=document.querySelectorAll('#grid-lp .album-card').length;
document.getElementById('cnt-faixas').textContent=document.querySelectorAll('#grid-faixas .track-row').length;
"""


def render_track_lp(row):
    """Renderiza uma faixa dentro da view LP."""
    bpm_f     = safe_float(row.get("bpm"))
    uri       = str(row.get("spotify_uri") or "")
    status    = str(row.get("status") or "REJEITADO")
    deezer_id = str(row.get("deezer_id") or "")
    deezer_id = "" if deezer_id in ("nan", "None", "none", "") else deezer_id

    bpm_txt = f"{bpm_f:.0f}" if bpm_f else "—"
    dot_cls = {"ACEITO":"s-ok","REVISAR":"s-rev"}.get(status,"s-rej")

    embed = ""
    if deezer_id:
        embed = (f'<div class="embed-ph" onclick="loadDeezerEmbed(this,\'{deezer_id}\')">'
                 f'&#9654; Ouvir</div>')
    elif uri and uri != "nan" and "spotify" in uri:
        tid = uri.split(":")[-1]
        embed = (f'<div class="embed-ph" onclick="loadEmbed(this,\'{tid}\')">'
                 f'&#9654; Ouvir</div>')
    elif status == "ACEITO":
        embed = '<div class="no-spotify">sem prévia</div>'

    return f'''<div class="track" data-bpm="{int(bpm_f) if bpm_f else 999}">
  <span class="trk-pos">{esc(row.get("position"))}</span>
  <span class="trk-status {dot_cls}"></span>
  <div class="trk-info">
    <div class="trk-artist">{esc(row.get("artist_clean"))}</div>
    <div class="trk-name">{esc(row.get("track_title"))}</div>
    {embed}
  </div>
  <div class="trk-badges">
    <span class="badge-bpm">{bpm_txt}</span>
  </div>
</div>'''


def render_album_lp(group, copy_count=1, fields=None, country="", color_pastel=""):
    """Renderiza um card de álbum (LP view)."""
    fields    = fields or {}
    first     = group.iloc[0]
    cover     = esc(first.get("cover_url") or "")
    bpm_vals  = group["bpm"].apply(safe_float).dropna()
    min_bpm   = int(bpm_vals.min()) if len(bpm_vals) else 999
    bpm_range = f"{bpm_vals.min():.0f}–{bpm_vals.max():.0f} BPM" if len(bpm_vals) else ""
    n_ok      = (group["status"] == "ACEITO").sum()
    year_s    = str(int(first["year"])) if safe_float(first.get("year")) else ""
    styles_s  = esc(first.get("styles") or "")
    genres_s  = esc(first.get("genres") or "")
    release_id = first.get("release_id", "")
    country_s  = esc(country or "")

    # Genre + Style unificados
    genre_parts = [p.strip() for p in (genres_s + ", " + styles_s).split(",") if p.strip() and p.strip() != "nan"]
    seen = set(); genre_parts_dedup = [p for p in genre_parts if not (p in seen or seen.add(p))]
    genre_style_s = " · ".join(genre_parts_dedup[:5])

    # Decade key para filtro JS
    year_int = int(first["year"]) if safe_float(first.get("year")) else 0
    if year_int < 1970:    decade_key = "pre70"
    elif year_int < 1980:  decade_key = "70s"
    elif year_int < 1990:  decade_key = "80s"
    elif year_int < 2000:  decade_key = "90s"
    elif year_int < 2010:  decade_key = "2000s"
    elif year_int < 2020:  decade_key = "2010s"
    elif year_int > 0:     decade_key = "2020s"
    else:                  decade_key = ""

    # Cor do card
    card_style = ""
    if color_pastel and len(color_pastel) == 7:
        card_style = f' style="background:linear-gradient(135deg,{color_pastel}55 0%,var(--card) 55%)"'

    img_tag = (f'<img class="cover-img" src="{cover}" alt="" loading="lazy" '
               f'onerror="this.style.display=\'none\'">'
               if cover else '<div class="cover-ph">&#9836;</div>')

    tags = ""
    if year_s:       tags += f'<span class="tag">{year_s}</span>'
    if country_s:    tags += f'<span class="tag">{country_s}</span>'
    if genre_style_s: tags += f'<span class="tag tag-acc">{genre_style_s[:50]}</span>'
    if bpm_range:    tags += f'<span class="tag">{bpm_range}</span>'

    copy_badge = f'<span class="copy-badge">{copy_count} c&#243;pias</span>' if copy_count > 1 else ""

    discogs_url  = f"https://www.discogs.com/release/{release_id}"
    discogs_link = (f'<a class="discogs-link" href="{discogs_url}" target="_blank" '
                    f'onclick="event.stopPropagation()" title="Ver no Discogs">'
                    f'&#9675; Discogs</a>')

    custom_html = ""
    field_items = []
    if fields.get("Origem"):   field_items.append(f'<span class="field-item"><strong>Origem:</strong> {esc(fields["Origem"])}</span>')
    if fields.get("DJ"):       field_items.append(f'<span class="field-item"><strong>DJ:</strong> {esc(fields["DJ"])}</span>')
    if fields.get("PA"):       field_items.append(f'<span class="field-item"><strong>PA:</strong> {esc(fields["PA"])}</span>')
    if fields.get("$"):        field_items.append(f'<span class="field-item"><strong>$:</strong> {esc(fields["$"])}</span>')
    if fields.get("Recebido?"): field_items.append(f'<span class="field-item"><strong>Recebido:</strong> {esc(fields["Recebido?"])}</span>')
    mc = fields.get("Media Condition",""); sc = fields.get("Sleeve Condition","")
    if mc or sc:
        field_items.append(f'<span class="field-item"><strong>Cond:</strong> {esc(" / ".join(filter(None,[mc,sc])))}</span>')
    if field_items:
        custom_html += f'<div class="fields-row">{"".join(field_items)}</div>'
    if fields.get("Notas"):
        custom_html += f'<div class="field-notes">{esc(fields["Notas"])}</div>'

    track_titles = " ".join(str(r.get("track_title","")) for _, r in group.iterrows())
    search_str = html_module.escape(
        f'{first.get("album_artist","")} {first.get("album_title","")} '
        f'{styles_s} {genres_s} {year_s} {country} {track_titles} '
        f'{fields.get("Origem","")} {fields.get("Notas","")}'.lower()
    )

    group_dedup = group.drop_duplicates(subset=["position"])
    tracks_html = "\n".join(render_track_lp(r) for _, r in group_dedup.iterrows())
    origem_val = (fields.get("Origem") or "").strip().lower()
    country_key = country.strip().lower()

    return f'''<article class="album-card"{card_style}
  data-search="{search_str}"
  data-artist="{esc(first.get('album_artist',''))}"
  data-year="{year_s}"
  data-min-bpm="{min_bpm}"
  data-origem="{esc(origem_val)}"
  data-country="{esc(country_key)}"
  data-decade="{decade_key}">
  {f'<div class="cover-blur" style="background-image:url(\'{cover}\')"></div>' if cover else ''}
  <header class="album-header" onclick="toggleAlbum(this)">
    <div class="cover-wrap">{img_tag}</div>
    <div class="album-info">
      <div class="alb-artist">{esc(first.get("album_artist",""))}{copy_badge}</div>
      <div class="alb-title">{esc(first.get("album_title",""))}</div>
      <div class="alb-meta">{tags} {discogs_link}</div>
      {custom_html}
      <div class="alb-tracks-info">{n_ok} de {len(group_dedup)} faixas</div>
    </div>
    <button class="toggle-btn" aria-label="expandir">&#8964;</button>
  </header>
  <div class="tracks-list collapsed">{tracks_html}</div>
</article>'''


def render_track_row(row, country="", color_pastel=""):
    """Renderiza uma linha de faixa (Track view)."""
    bpm_f     = safe_float(row.get("bpm"))
    uri       = str(row.get("spotify_uri") or "")
    status    = str(row.get("status") or "REJEITADO")
    thumb     = esc(row.get("thumb_url") or row.get("cover_url") or "")
    deezer_id = str(row.get("deezer_id") or "")
    deezer_id = "" if deezer_id in ("nan", "None", "none", "") else deezer_id
    release_id = row.get("release_id", "")
    year_s     = str(int(row["year"])) if safe_float(row.get("year")) else ""
    styles_s   = str(row.get("styles") or "")
    genres_s   = str(row.get("genres") or "")

    # Genre + Style unificados
    genre_parts = [p.strip() for p in (genres_s + ", " + styles_s).split(",") if p.strip() and p.strip() != "nan"]
    seen = set(); genre_parts_dedup = [p for p in genre_parts if not (p in seen or seen.add(p))]
    genre_style_s = " · ".join(genre_parts_dedup[:4])

    bpm_txt = f"{bpm_f:.0f}" if bpm_f else "—"
    bpm_int = int(bpm_f) if bpm_f else 0
    has_bpm = "1" if bpm_f else "0"

    play_btn = ""
    if deezer_id:
        play_btn = (f'<button class="tr-play-btn" onclick="loadDeezerEmbed(this,\'{deezer_id}\')">'
                    f'&#9654; Prévia</button>')
    elif uri and "spotify" in uri and status == "ACEITO":
        tid = uri.split(":")[-1]
        play_btn = (f'<button class="tr-play-btn" onclick="loadEmbed(this,\'{tid}\')">'
                    f'&#9654; Prévia</button>')

    img_tag = (f'<img class="tr-thumb" src="{thumb}" alt="" loading="lazy" '
               f'onerror="this.style.display=\'none\'">'
               if thumb else '<div class="tr-thumb-ph">&#9836;</div>')

    blur_div = (f'<div class="cover-blur" style="background-image:url(\'{thumb}\')"></div>'
                if thumb else '')

    discogs_url = f"https://www.discogs.com/release/{release_id}"
    discogs_link = (f'<a class="tr-discogs-link" href="{discogs_url}" target="_blank" '
                    f'title="Ver no Discogs">&#9675; Discogs</a>' if release_id else "")

    meta_parts = [p for p in [year_s, esc(country), esc(genre_style_s)] if p]
    meta_html = f'<div class="tr-meta">{" · ".join(meta_parts)}</div>' if meta_parts else ""

    row_style = ""
    if color_pastel and len(color_pastel) == 7:
        row_style = f' style="background:linear-gradient(135deg,{color_pastel}44 0%,var(--card) 50%)"'

    search_str = html_module.escape(
        f'{row.get("track_title","")} {row.get("artist_clean","")} '
        f'{row.get("album_title","")} {country} {genres_s} {styles_s} {year_s}'.lower()
    )
    artist_str = html_module.escape(str(row.get("artist_clean") or ""))

    return f'''<div class="track-row"{row_style}
  data-bpm="{bpm_int}"
  data-hasbpm="{has_bpm}"
  data-search="{search_str}"
  data-artist="{artist_str}">
  {blur_div}
  {img_tag}
  <div class="tr-info">
    <div class="tr-name">{esc(row.get("track_title"))}</div>
    <div class="tr-artist">{esc(row.get("artist_clean"))}</div>
    <div class="tr-album">{esc(row.get("album_title"))}</div>
    {meta_html}
    {discogs_link}
  </div>
  <div class="tr-bpm-area">
    <div class="tr-bpm-num">{bpm_txt}</div>
    <div class="tr-bpm-lbl">bpm</div>
  </div>
  <div class="tr-play">{play_btn}</div>
</div>'''


def load_collection_fields():
    """
    Carrega backup_collection_fields.csv (gerado por fetch_discogs_fields.py).
    Retorna:
      - fields_map: {release_id: {campo: valor}} com os campos da primeira instância
      - copy_counts: {release_id: n_cópias}
    """
    path = WORK_DIR / "backup_collection_fields.csv"
    if not path.exists():
        return {}, {}

    import pandas as pd
    cf = pd.read_csv(path, dtype=str).fillna("")
    fields_map  = {}
    copy_counts = {}

    for rid, group in cf.groupby("release_id"):
        copy_counts[str(rid)] = len(group)
        # Agrega campos: usa a primeira linha, mas mescla Notas de múltiplas instâncias
        row = group.iloc[0].to_dict()
        notas_all = " | ".join(r for r in group.get("Notas", pd.Series([])).tolist() if r.strip())
        if notas_all:
            row["Notas"] = notas_all
        fields_map[str(rid)] = row

    return fields_map, copy_counts


def load_country_map():
    """Retorna {release_id: country} de backup_country.csv."""
    path = WORK_DIR / "backup_country.csv"
    if not path.exists():
        return {}
    import pandas as pd
    df = pd.read_csv(path, dtype=str).fillna("")
    return {str(r["release_id"]): r.get("country", "") for _, r in df.iterrows()}


def load_cover_colors():
    """Retorna {release_id: color_pastel_hex} de backup_colors.csv."""
    path = WORK_DIR / "backup_colors.csv"
    if not path.exists():
        return {}
    import pandas as pd
    df = pd.read_csv(path, dtype=str).fillna("")
    return {str(r["release_id"]): r.get("color_pastel", "") for _, r in df.iterrows()}


def load_playlist_url():
    """Retorna URL da playlist Spotify salva, ou string vazia."""
    path = WORK_DIR / "backup_playlist.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def generate_html(df):
    print("\nGerando HTML...")
    path = WORK_DIR / "MinhaColecao_DJ.html"

    # Carrega campos, country, cores e playlist
    fields_map, copy_counts = load_collection_fields()
    country_map  = load_country_map()
    colors_map   = load_cover_colors()
    playlist_url = load_playlist_url()

    n_unique  = df["release_id"].nunique()
    n_items   = sum(copy_counts.get(str(rid), 1) for rid in df["release_id"].unique()) if copy_counts else n_unique
    n_tracks  = len(df.drop_duplicates(subset=["release_id","position"]))  # sem duplicatas de cópia
    n_matched = (df.drop_duplicates(subset=["release_id","position"])["status"] == "ACEITO").sum()
    pct       = round(n_matched / n_tracks * 100) if n_tracks else 0
    bpm_vals  = df["bpm"].apply(safe_float).dropna()
    has_bpm   = len(bpm_vals) > 0

    # ── LP view ──────────────────────────────────────────────────────────────
    albums_html = "\n".join(
        render_album_lp(
            g,
            copy_count   = copy_counts.get(str(rid), 1),
            fields       = fields_map.get(str(rid), {}),
            country      = country_map.get(str(rid), ""),
            color_pastel = colors_map.get(str(rid), ""),
        )
        for rid, g in df.sort_values(["album_artist","album_title"]).groupby("release_id", sort=False)
    )

    # ── Track view: sorted by BPM (deduplica cópias) ─────────────────────────
    df_tracks = df.drop_duplicates(subset=["release_id","position"]).copy()
    df_tracks["_bpm_sort"] = df_tracks["bpm"].apply(
        lambda v: safe_float(v) if safe_float(v) else 9999
    )
    df_tracks = df_tracks.sort_values("_bpm_sort")
    tracks_html = "\n".join(
        render_track_row(
            r,
            country      = country_map.get(str(r.get("release_id","")), ""),
            color_pastel = colors_map.get(str(r.get("release_id","")), ""),
        )
        for _, r in df_tracks.iterrows()
    )

    bpm_notice = ""
    if not has_bpm:
        bpm_notice = ('<div style="background:#F5F0E8;border:1px solid #D8CCC0;'
                      'padding:.6rem 1.2rem;border-radius:3px;font-size:.78rem;'
                      'color:#5C4030;margin-bottom:1rem;">'
                      'BPM n&#227;o dispon&#237;vel — execute dj_library_v2.py novamente para buscar via Deezer.</div>')

    copy_note = f" ({n_unique} &#250;nicos, {n_items-n_unique} duplicatas)" if n_items != n_unique else ""
    stats = (f'<div class="stats-row">'
             f'<div class="stat"><div class="stat-val">{n_items}</div>'
             f'<div class="stat-lbl">Itens{copy_note}</div></div>'
             f'<div class="stat"><div class="stat-val">{n_tracks}</div>'
             f'<div class="stat-lbl">Faixas</div></div>'
             f'<div class="stat"><div class="stat-val">{n_matched}</div>'
             f'<div class="stat-lbl">No Spotify</div></div>'
             f'<div class="stat"><div class="stat-val">{pct}%</div>'
             f'<div class="stat-lbl">Cobertura</div></div>'
             f'</div>')

    bpm_chips = (''.join(
        f'<button class="chip bpm-range-chip{" active" if r[0]=="all" else ""}" '
        f'data-range="{r[0]}" onclick="setBpmRange(\'{r[0]}\',this)">{r[1]}</button>'
        for r in [
            ("all","Todos"),("sub70","70–"),("70-80","70–80"),("80-90","80–90"),
            ("90-100","90–100"),("100-110","100–110"),("110-120","110–120"),
            ("120-130","120–130"),("130-140","130–140"),("140plus","140+"),
            ("nobpm","Sem BPM"),
        ]
    ))

    bpm_pres_chips = (''.join(
        f'<button class="chip bpm-pres-chip{" active" if m=="all" else ""}" '
        f'data-mode="{m}" onclick="setBpmPresence(\'{m}\',this)">{lbl}</button>'
        for m, lbl in [("all","Todos"),("with","Com BPM"),("without","Sem BPM")]
    ))

    # Origem filter chips
    origem_vals = sorted(set(
        (v.get("Origem") or "").strip()
        for v in fields_map.values()
        if (v.get("Origem") or "").strip()
    ))
    origem_chips_html = ""
    if origem_vals:
        chips = (
            '<button class="chip origem-chip active" data-val="all" onclick="setOrigemFilter(this.dataset.val,this)">Todos</button>'
            + ''.join(
                f'<button class="chip origem-chip" data-val="{esc(v.lower())}"'
                f' onclick="setOrigemFilter(this.dataset.val,this)">{esc(v)}</button>'
                for v in origem_vals
            )
            + '<button class="chip origem-chip" data-val="" onclick="setOrigemFilter(this.dataset.val,this)">Sem origem</button>'
        )
        origem_chips_html = f'<div class="chips-row"><span class="chips-label">Origem:</span>{chips}</div>'

    # Nacional/Internacional chips
    nac_chips_html = (
        '<div class="chips-row">'
        '<button class="chip nac-chip active" onclick="setNacionalFilter(\'all\',this)">Tudo</button>'
        '<button class="chip nac-chip" onclick="setNacionalFilter(\'nacional\',this)">&#127463;&#127479; Nacional</button>'
        '<button class="chip nac-chip" onclick="setNacionalFilter(\'internacional\',this)">Internacional</button>'
        '</div>'
    )

    # Decade chips (multi-select)
    decade_chips_html = (
        '<div class="chips-row"><span class="chips-label">D&#233;cada:</span>'
        '<button class="chip decade-chip active" data-val="all" onclick="setDecadeFilter(this.dataset.val,this)">Todas</button>'
        + ''.join(
            f'<button class="chip decade-chip" data-val="{dk}" onclick="setDecadeFilter(this.dataset.val,this)">{lbl}</button>'
            for dk, lbl in [
                ("pre70","–1970"),("70s","1970–80"),("80s","1980–90"),
                ("90s","1990–00"),("2000s","2000–10"),("2010s","2010–20"),("2020s","2020–"),
            ]
        )
        + '</div>'
    )

    # Playlist Spotify button
    playlist_btn_html = ""
    if playlist_url:
        playlist_btn_html = (
            f'<a class="playlist-btn" href="{playlist_url}" target="_blank">'
            f'&#9654; Playlist no Spotify</a>'
        )

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DJ Amsa &mdash; Biblioteca</title>
<style>{CSS}</style>
</head>
<body>

<header class="site-header">
  <span class="logo-mark">&#9670;</span>
  <span class="logo-name">DJ Amsa</span>
  <div class="header-sep"></div>
  <div class="site-stats">
    <span class="stat-item"><strong>{n_items}</strong> LPs</span>
    <span class="stat-dot">&#8226;</span>
    <span class="stat-item"><strong>{n_tracks}</strong> faixas</span>
    <span class="stat-dot">&#8226;</span>
    <span class="stat-item"><strong>{n_matched}</strong> no Spotify</span>
    <span class="stat-dot">&#8226;</span>
    <span class="stat-item"><strong>{int(df["bpm"].apply(safe_float).notna().sum())}</strong> com BPM</span>
  </div>
  <div class="header-tabs">
    <button class="tab-btn active" data-v="lp" onclick="switchView('lp')">LP</button>
    <button class="tab-btn" data-v="faixas" onclick="switchView('faixas')">Faixas</button>
  </div>
  {playlist_btn_html}
</header>

<!-- ═══════════════ LP VIEW ═══════════════ -->
<div id="view-lp" class="view active">
  <div class="controls">
    <div class="ctrl-row">
      <input class="ctrl-input" id="q-lp" type="search" placeholder="Buscar artista, &#225;lbum ou faixa...">
      <select class="ctrl-sel" id="sort-lp" onchange="filterLP()">
        <option value="">Artista A&#8594;Z</option>
        <option value="year-desc">Ano (recente)</option>
        <option value="year-asc">Ano (antigo)</option>
        <option value="bpm-asc">BPM crescente</option>
        <option value="bpm-desc">BPM decrescente</option>
      </select>
    </div>
    {nac_chips_html}
    {decade_chips_html}
    {origem_chips_html}
  </div>
  <main class="main">
    {bpm_notice}
    <div class="results-bar"><strong id="cnt-lp">{n_unique}</strong> &#225;lbuns</div>
    <div class="albums-grid" id="grid-lp">{albums_html}</div>
  </main>
</div>

<!-- ═══════════════ TRACK VIEW ═══════════════ -->
<div id="view-faixas" class="view">
  <div class="controls">
    <div class="ctrl-row">
      <input class="ctrl-input" id="q-faixas" type="search" placeholder="Buscar artista, &#225;lbum ou faixa...">
      <select class="ctrl-sel" id="sort-faixas" onchange="filterTracks()">
        <option value="bpm-asc">BPM crescente</option>
        <option value="bpm-desc">BPM decrescente</option>
        <option value="az">Artista A&#8594;Z</option>
      </select>
    </div>
    <div class="chips-row">{bpm_pres_chips}</div>
    <div class="chips-row">{bpm_chips}</div>
  </div>
  <main class="main">
    <div class="results-bar"><strong id="cnt-faixas">{n_tracks}</strong> faixas</div>
    <div class="track-rows" id="grid-faixas">{tracks_html}</div>
  </main>
</div>

<script>{JS}</script>
</body>
</html>"""

    path.write_text(html, encoding="utf-8")
    print(f"✓ {path.name} salvo ({path.stat().st_size // 1024} KB)")
    return path


# ==============================================================================
# ENTRY POINT
# ==============================================================================
if __name__ == "__main__":
    sp, df_final = main()
    generate_xlsx(df_final)
    create_playlist(sp, df_final)
    generate_html(df_final)

    n_tracks  = len(df_final)
    n_matched = (df_final["status"] == "ACEITO").sum()
    n_albums  = df_final["release_id"].nunique()
    bpm_count = df_final["bpm"].apply(safe_float).notna().sum()

    print(f"""
CONCLUIDO!
  MinhaColecao_DJ.xlsx
  MinhaColecao_DJ.html
  Playlist Spotify: "Meu Discogs - por BPM"
  {n_tracks} faixas | {n_matched} no Spotify | {n_albums} albums | BPM: {bpm_count} faixas
""")
