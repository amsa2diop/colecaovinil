#!/usr/bin/env python3
"""
Pipeline completo de sincronização CI:
  1. Atualiza backup_collection_fields.csv (campos customizados Discogs)
  2. dj_library_v2.main() — Discogs incremental + Spotify matching + BPM via Deezer
  3. Reconstrói backup_playlist_map.json (mapa URI → playlists)
  4. Gera index.html / MinhaColecao_DJ.html + MinhaColecao_DJ.xlsx
  5. Atualiza playlists Spotify (sync_playlist.sync)

Requer SPOTIFY_REFRESH_TOKEN como variável de ambiente (GitHub Actions Secret).
Os tokens Discogs e Spotify Client estão embutidos nos scripts respectivos.
"""
import sys, subprocess
from pathlib import Path

WORK_DIR = Path(__file__).parent
sys.path.insert(0, str(WORK_DIR))


# ── 1. Campos da coleção Discogs ─────────────────────────────────────────────
print("\n" + "=" * 60)
print("1/5  Atualizando campos da coleção Discogs...")
print("=" * 60)
result = subprocess.run(
    [sys.executable, str(WORK_DIR / "fetch_discogs_fields.py")],
    check=False
)
if result.returncode != 0:
    print("⚠ fetch_discogs_fields.py falhou — continuando com dados anteriores.")


# ── 2. Pipeline principal (Discogs incremental + Spotify + BPM) ──────────────
print("\n" + "=" * 60)
print("2/5  Pipeline principal: Discogs + Spotify matching + BPM Deezer...")
print("=" * 60)
import dj_library_v2 as lib

sp, df = lib.main()


# ── 3. Reconstruir mapa de playlists Spotify ──────────────────────────────────
print("\n" + "=" * 60)
print("3/5  Reconstruindo mapa de playlists Spotify...")
print("=" * 60)
try:
    import build_playlist_map
    build_playlist_map.main()
    print("✓ backup_playlist_map.json atualizado.")
except Exception as e:
    print(f"⚠ build_playlist_map.main() falhou: {e}")
    print("  Continuando com mapa anterior (backup_playlist_map.json inalterado).")


# ── 4. Gerar HTML + XLSX ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("4/5  Gerando HTML e XLSX...")
print("=" * 60)
lib.generate_html(df)
lib.generate_xlsx(df)
print("✓ HTML e XLSX gerados.")


# ── 5. Atualizar playlists Spotify ───────────────────────────────────────────
print("\n" + "=" * 60)
print("5/5  Atualizando playlists Spotify...")
print("=" * 60)
try:
    import sync_playlist
    sync_playlist.sync()
    print("✓ Playlists atualizadas.")
except Exception as e:
    print(f"⚠ sync_playlist.sync() falhou: {e}")
    # Não interrompe o pipeline — o site já foi gerado
    sys.exit(1)

print("\n" + "=" * 60)
print("✓ Pipeline CI concluído com sucesso.")
print("=" * 60)
