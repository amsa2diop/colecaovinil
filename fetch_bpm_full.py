#!/usr/bin/env python3
"""
fetch_bpm_full.py
=================
Preenche BPM para faixas sem BPM no backup_bpm.csv.

Estágios (em ordem, salvando incrementalmente):
  1. Deezer multi-query   → varre múltiplas queries e TODOS os resultados até achar BPM > 0
  2. Deezer preview+audio → baixa preview de 30s e analisa com librosa (requer: pip install librosa)
  3. GetSongBPM API       → fallback final (requer chave grátis em getsongbpm.com/api)

Uso:
  python fetch_bpm_full.py
  python fetch_bpm_full.py --songbpm-key SUA_CHAVE_AQUI
  python fetch_bpm_full.py --skip-audio   # pula estágio 2
"""

import sys, re, time, unicodedata, argparse, tempfile, os, urllib.request
import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher

try:
    import requests
except ImportError:
    sys.exit("Instale requests: pip install requests")

WORK_DIR   = Path(__file__).parent
BPM_CSV    = WORK_DIR / "backup_bpm.csv"
TRACKS_CSV = WORK_DIR / "backup_matched.csv"

DEEZER_DELAY  = 0.30   # segundos entre chamadas Deezer
SAVE_EVERY    = 25     # salva CSV a cada N faixas processadas
BPM_MIN, BPM_MAX = 60, 200  # fora desse range → descarta

# ── helpers ──────────────────────────────────────────────────────────────────

def norm(s):
    """Remove acentos, pontuação, lowercase."""
    if not s: return ""
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()

def clean_title(t):
    """Remove sufixos comuns que confundem a busca: (feat. X), (Live), - Remix…"""
    if not t: return t
    t = re.sub(r"\s*\(feat\..*?\)", "", t, flags=re.I)
    t = re.sub(r"\s*\(ft\..*?\)", "", t, flags=re.I)
    t = re.sub(r"\s*-\s*(lp|ep|single|remix|remaster|live|version|edit|mix)\b.*$", "", t, flags=re.I)
    t = re.sub(r"\s*\((lp|ep|single|remix|remaster|live|version|edit|mix)\b.*?\)", "", t, flags=re.I)
    return t.strip()

def sim(a, b):
    return SequenceMatcher(None, norm(a), norm(b)).ratio()

def normalize_bpm(bpm):
    """Mantém BPM em 70–140, dobrando/dividindo."""
    if not bpm or bpm <= 0: return None
    while bpm > 140: bpm /= 2
    while bpm < 70:  bpm *= 2
    return round(bpm, 1)

# ── Deezer ───────────────────────────────────────────────────────────────────

_session = None
def _sess():
    global _session
    if _session is None:
        _session = requests.Session()
        _session.headers["User-Agent"] = "FetchBPM/1.0"
    return _session

def deezer_search(q, limit=8):
    try:
        r = _sess().get("https://api.deezer.com/search",
                        params={"q": q, "limit": limit}, timeout=12)
        if r.status_code == 200:
            return r.json().get("data", [])
    except Exception:
        pass
    return []

def deezer_track(deezer_id):
    """Retorna (bpm, preview_url) ou (None, None)."""
    try:
        r = _sess().get(f"https://api.deezer.com/track/{deezer_id}", timeout=12)
        if r.status_code == 200:
            d = r.json()
            bpm     = float(d.get("bpm") or 0)
            preview = d.get("preview") or ""
            return (bpm if bpm > 0 else None), (preview or None)
    except Exception:
        pass
    return None, None

def deezer_bpm_and_preview(artist, title, found_artist=None, found_title=None):
    """
    Tenta múltiplas queries no Deezer.
    Retorna (bpm, deezer_id, preview_url).
    bpm pode ser None se não encontrou; preview_url pode existir mesmo sem bpm.
    """
    # monta variantes de query em ordem de prioridade
    t_clean  = clean_title(title)
    ft_clean = clean_title(found_title) if found_title else None

    queries = []
    if artist and t_clean:
        queries.append(f"{norm(artist)} {norm(t_clean)}")
    if found_artist and ft_clean:
        queries.append(f"{norm(found_artist)} {norm(ft_clean)}")
    if artist and title and title != t_clean:
        queries.append(f"{norm(artist)} {norm(title)}")
    if t_clean:
        queries.append(norm(t_clean))
    if found_title and found_title != t_clean:
        queries.append(norm(clean_title(found_title)))
    # remove duplicatas preservando ordem
    seen, unique_q = set(), []
    for q in queries:
        if q and q not in seen:
            seen.add(q); unique_q.append(q)

    best_preview = None
    best_deezer_id = None

    for q in unique_q:
        results = deezer_search(q)
        time.sleep(DEEZER_DELAY)
        for res in results:
            # verifica relevância mínima (artista ou título bate)
            r_artist = res.get("artist", {}).get("name", "")
            r_title  = res.get("title", "")
            title_ok  = sim(t_clean or title, r_title) > 0.45 or sim(found_title or "", r_title) > 0.45
            artist_ok = not artist or sim(artist, r_artist) > 0.4 or sim(found_artist or "", r_artist) > 0.4
            if not (title_ok and artist_ok):
                continue

            bpm, preview = deezer_track(res["id"])
            time.sleep(DEEZER_DELAY)

            if bpm and BPM_MIN < bpm < BPM_MAX:
                return normalize_bpm(bpm), str(res["id"]), preview  # sucesso

            # sem BPM mas tem preview → guarda para estágio 2
            if preview and not best_preview:
                best_preview    = preview
                best_deezer_id  = str(res["id"])

    return None, best_deezer_id, best_preview

# ── Estágio 2: librosa via preview ───────────────────────────────────────────

def bpm_from_preview(preview_url):
    """Baixa preview de 30s e detecta BPM com librosa."""
    try:
        import librosa
        import numpy as np
    except ImportError:
        return None

    tmp = None
    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        urllib.request.urlretrieve(preview_url, tmp.name)
        tmp.close()
        y, sr = librosa.load(tmp.name, sr=22050, duration=30, mono=True)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = float(tempo) if hasattr(tempo, '__float__') else float(tempo[0])
        return normalize_bpm(bpm) if BPM_MIN < bpm < BPM_MAX else None
    except Exception as e:
        return None
    finally:
        if tmp and os.path.exists(tmp.name):
            try: os.unlink(tmp.name)
            except: pass

# ── Estágio 3: GetSongBPM ────────────────────────────────────────────────────

def songbpm_search(api_key, artist, title):
    """Busca BPM no GetSongBPM API (500 req/dia gratuitos)."""
    if not api_key: return None
    try:
        r = _sess().get(
            "https://api.getsongbpm.com/search/",
            params={"api_key": api_key, "type": "song",
                    "lookup": f"song:{clean_title(title)} artist:{artist}"},
            timeout=15,
        )
        if r.status_code == 200:
            songs = r.json().get("search", [])
            for s in songs:
                bpm_s = s.get("tempo", "") or ""
                if bpm_s:
                    try:
                        bpm = normalize_bpm(float(bpm_s))
                        if bpm: return bpm
                    except ValueError:
                        pass
    except Exception:
        pass
    return None

# ── main ─────────────────────────────────────────────────────────────────────

def load_data():
    tracks = pd.read_csv(TRACKS_CSV, dtype=str).fillna("")
    bpm_df = pd.read_csv(BPM_CSV, dtype=str) if BPM_CSV.exists() else pd.DataFrame(
        columns=["track_id","bpm","energy","danceability","valence","key","mode","camelot","deezer_id","source"])
    # garante colunas extras
    for col in ["deezer_id", "source"]:
        if col not in bpm_df.columns:
            bpm_df[col] = ""
    return tracks, bpm_df

def save_bpm(bpm_df):
    bpm_df.to_csv(BPM_CSV, index=False)

def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--songbpm-key", default="", help="Chave API GetSongBPM")
    parser.add_argument("--skip-audio",  action="store_true", help="Pula análise de preview (librosa)")
    parser.add_argument("--limit",       type=int, default=0, help="Limita a N faixas (teste)")
    args = parser.parse_args()

    tracks, bpm_df = load_data()

    # faixas únicas
    dedup = tracks.drop_duplicates(["release_id","position"]).copy()

    # quais ainda não têm BPM
    has_bpm = set(
        bpm_df.loc[bpm_df["bpm"].notna() & (bpm_df["bpm"].astype(str).str.strip() != ""), "track_id"]
    )
    missing = dedup[~dedup["track_id"].isin(has_bpm) & (dedup["track_id"].str.strip() != "")].copy()

    print(f"\n{'─'*55}")
    print(f"  Faixas sem BPM: {len(missing)}")
    print(f"    ACEITO (Spotify): {(missing['status']=='ACEITO').sum()}")
    print(f"    Sem match:        {(missing['status']!='ACEITO').sum()}")
    print(f"{'─'*55}\n")

    if missing.empty:
        print("Nada a fazer — todas as faixas já têm BPM.")
        return

    if args.limit > 0:
        print(f"  ⚠  Modo teste: processando apenas {args.limit} faixas.\n")
        missing = missing.head(args.limit)

    # verifica librosa
    librosa_ok = False
    if not args.skip_audio:
        try:
            import librosa
            librosa_ok = True
            print("librosa encontrado — estágio 2 (preview+audio) ativo.\n")
        except ImportError:
            print("librosa nao instalado — estágio 2 desativado.")
            print("  Para ativar: pip install librosa\n")

    new_rows      = []
    preview_queue = []   # (row, preview_url, deezer_id) para estágio 2
    not_found     = []   # para estágio 3

    total = len(missing)
    found_deezer = found_audio = found_songbpm = 0

    print(f"[FASE 1] Deezer multi-query ({total} faixas)…")
    for i, (_, row) in enumerate(missing.iterrows(), 1):
        tid    = row.get("track_id", "")
        title  = row.get("track_title", "")
        artist = row.get("artist_clean", "")
        found_name   = row.get("found_name", "")
        found_artist = row.get("found_artist", "")

        bpm, dz_id, preview = deezer_bpm_and_preview(
            artist, title, found_artist, found_name
        )

        if bpm:
            new_rows.append({"track_id": tid, "bpm": str(bpm),
                             "deezer_id": dz_id or "", "source": "deezer"})
            found_deezer += 1
            tag = f"BPM={bpm}"
        elif preview:
            preview_queue.append((row, preview, dz_id))
            tag = "preview→queue"
        else:
            not_found.append(row)
            tag = "nao encontrado"

        # progresso
        bar_len = 30
        done = int(bar_len * i / total)
        bar  = "█" * done + "░" * (bar_len - done)
        sys.stdout.write(f"\r  [{bar}] {i}/{total}  {tag[:25]:<25}")
        sys.stdout.flush()

        # salva incrementalmente
        if i % SAVE_EVERY == 0 and new_rows:
            bpm_df = pd.concat([bpm_df, pd.DataFrame(new_rows)], ignore_index=True)
            save_bpm(bpm_df); new_rows = []

    if new_rows:
        bpm_df = pd.concat([bpm_df, pd.DataFrame(new_rows)], ignore_index=True)
        save_bpm(bpm_df); new_rows = []

    print(f"\n  Fase 1: +{found_deezer} BPMs  |  {len(preview_queue)} para áudio  |  {len(not_found)} sem match\n")

    # ── Fase 2: preview + librosa ────────────────────────────────────────────
    if librosa_ok and preview_queue:
        print(f"[FASE 2] Audio preview via librosa ({len(preview_queue)} faixas)…")
        still_missing_after_audio = []
        for i, (row, preview_url, dz_id) in enumerate(preview_queue, 1):
            tid   = row.get("track_id", "")
            title = row.get("track_title", "")
            bpm   = bpm_from_preview(preview_url)
            if bpm:
                new_rows.append({"track_id": tid, "bpm": str(bpm),
                                 "deezer_id": dz_id or "", "source": "deezer_preview"})
                found_audio += 1
                tag = f"BPM={bpm}"
            else:
                still_missing_after_audio.append(row)
                tag = "audio falhou"
            sys.stdout.write(f"\r  {i}/{len(preview_queue)}  {title[:30]:<30}  {tag}")
            sys.stdout.flush()
            if i % SAVE_EVERY == 0 and new_rows:
                bpm_df = pd.concat([bpm_df, pd.DataFrame(new_rows)], ignore_index=True)
                save_bpm(bpm_df); new_rows = []
        not_found = still_missing_after_audio
        if new_rows:
            bpm_df = pd.concat([bpm_df, pd.DataFrame(new_rows)], ignore_index=True)
            save_bpm(bpm_df); new_rows = []
        print(f"\n  Fase 2: +{found_audio} BPMs  |  {len(not_found)} ainda sem BPM\n")
    elif not librosa_ok and preview_queue:
        not_found = [row for row, _, _ in preview_queue] + not_found
        print(f"  (Instale librosa para recuperar +{len(preview_queue)} faixas via áudio)\n")

    # ── Fase 3: GetSongBPM ────────────────────────────────────────────────────
    if not_found and args.songbpm_key:
        print(f"[FASE 3] GetSongBPM API ({len(not_found)} faixas)…")
        for i, row in enumerate(not_found, 1):
            tid    = row.get("track_id", "") if hasattr(row, "get") else row["track_id"]
            title  = row.get("track_title", "") if hasattr(row, "get") else row["track_title"]
            artist = row.get("artist_clean", "") if hasattr(row, "get") else row["artist_clean"]
            bpm = songbpm_search(args.songbpm_key, artist, title)
            if bpm:
                new_rows.append({"track_id": tid, "bpm": str(bpm),
                                 "deezer_id": "", "source": "songbpm"})
                found_songbpm += 1
                tag = f"BPM={bpm}"
            else:
                tag = "nao encontrado"
            time.sleep(0.5)
            sys.stdout.write(f"\r  {i}/{len(not_found)}  {str(title)[:30]:<30}  {tag}")
            sys.stdout.flush()
            if i % SAVE_EVERY == 0 and new_rows:
                bpm_df = pd.concat([bpm_df, pd.DataFrame(new_rows)], ignore_index=True)
                save_bpm(bpm_df); new_rows = []
        if new_rows:
            bpm_df = pd.concat([bpm_df, pd.DataFrame(new_rows)], ignore_index=True)
            save_bpm(bpm_df); new_rows = []
        print(f"\n  Fase 3: +{found_songbpm} BPMs\n")
    elif not_found and not args.songbpm_key:
        print(f"[FASE 3] Pulada — sem chave GetSongBPM.")
        print(f"  Registre em https://getsongbpm.com/api e rode:")
        print(f"  python fetch_bpm_full.py --songbpm-key SUA_CHAVE\n")

    # ── Relatório final ───────────────────────────────────────────────────────
    bpm_df_final = pd.read_csv(BPM_CSV, dtype=str)
    total_com_bpm = bpm_df_final["bpm"].notna().sum()
    total_faixas  = len(dedup)
    residual = len(not_found) - found_songbpm if not args.songbpm_key else 0

    print(f"\n{'═'*55}")
    print(f"  RESULTADO FINAL")
    print(f"{'─'*55}")
    print(f"  Deezer (campo BPM): +{found_deezer}")
    print(f"  Deezer (audio):     +{found_audio}")
    print(f"  GetSongBPM:         +{found_songbpm}")
    print(f"  Total com BPM:      {total_com_bpm}/{total_faixas} faixas")
    still = total_faixas - total_com_bpm
    print(f"  Ainda sem BPM:      {still}")
    if still > 0:
        print(f"\n  Próximos passos para o resíduo ({still} faixas):")
        if not librosa_ok:
            print(f"    1. pip install librosa  →  rode novamente")
        if not args.songbpm_key:
            print(f"    2. Registre em getsongbpm.com/api  →  rode com --songbpm-key")
        print(f"    3. Entrada manual no Discogs para as mais importantes")
    print(f"{'═'*55}\n")
    print(f"  backup_bpm.csv atualizado. Rode regen_html.py para publicar.\n")

if __name__ == "__main__":
    main()
