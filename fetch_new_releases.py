"""
Busca faixas no Discogs para releases novos (em backup_collection_fields.csv
mas ainda não em backup_final.csv) e os acrescenta ao backup_final.csv.

Executado pelo CI *antes* de sync_playlist.py e regen_html.py, para que
novos discos já apareçam no site e nas playlists (sem Spotify ainda —
status=PENDENTE; matching local via dj_library_v2.py quando quiser).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import dj_library_v2 as lib

WORK = lib.WORK_DIR

def main():
    # 1. Carrega backup atual de tracks (usa v2 se disponível, senão legado)
    src = WORK / "backup_matched_v2.csv"
    if not src.exists():
        src = WORK / "backup_final.csv"
    if not src.exists():
        print("Nenhum backup encontrado — nada a fazer."); return

    df_existing = pd.read_csv(src)
    existing_rids = set(df_existing["release_id"].dropna().astype(str).str.strip().astype(int))

    # 2. Carrega coleção atual
    cf_path = WORK / "backup_collection_fields.csv"
    if not cf_path.exists():
        print("backup_collection_fields.csv não encontrado."); return
    cf = pd.read_csv(cf_path)
    all_rids = set(cf["release_id"].dropna().astype(str).str.strip().astype(int))

    new_rids = all_rids - existing_rids
    if not new_rids:
        print(f"✓ Nenhum release novo (total: {len(existing_rids)})"); return

    print(f"  {len(new_rids)} novo(s) release(s) — buscando faixas via Discogs REST...")

    # 3. Busca detalhes via API
    _, df_new = lib.fetch_releases_details(list(new_rids))

    if df_new.empty:
        print("  Nenhuma faixa retornada."); return

    # 4. Garante colunas esperadas pelo backup_final / regen_html
    for col in ["status", "spotify_uri", "track_id", "match_score",
                "found_artist", "found_name", "search_strategy", "source"]:
        if col not in df_new.columns:
            df_new[col] = None
    df_new["status"] = df_new["status"].fillna("PENDENTE")

    # 5. Concatena e salva no mesmo arquivo fonte
    df_out = pd.concat([df_existing, df_new], ignore_index=True)
    out_path = WORK / "backup_final.csv"
    df_out.to_csv(out_path, index=False)
    print(f"  ✓ backup_final.csv atualizado: {df_existing['release_id'].nunique()} → "
          f"{df_out['release_id'].nunique()} releases | {len(df_out)} faixas")


if __name__ == "__main__":
    main()
