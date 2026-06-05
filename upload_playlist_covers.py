"""
Faz upload da capa (playlist_cover.jpg) para as duas playlists Spotify.

Uso:
  python upload_playlist_covers.py

Requer token com escopo ugc-image-upload — rode spotify_auth.py antes se necessário.
"""
import base64, sys
from pathlib import Path
from sync_playlist import get_sp, WORK_DIR

PLAYLISTS = {
    "Discos do Amsa":      (WORK_DIR / "backup_playlist.txt"),
    "Discos do Amsa (DJ)": (WORK_DIR / "backup_playlist_dj.txt"),
}
COVER_PATH = WORK_DIR / "playlist_cover.jpg"


def _load_pid(txt_path: Path) -> str:
    val = txt_path.read_text(encoding="utf-8").strip()
    # aceita tanto URI quanto ID direto
    return val.split(":")[-1]


def upload_cover(sp, pid: str, name: str):
    data = COVER_PATH.read_bytes()
    b64  = base64.b64encode(data).decode()
    sp.playlist_upload_cover_image(pid, b64)
    print(f"  ✓ Capa enviada para '{name}'")


def main():
    if not COVER_PATH.exists():
        print(f"Arquivo não encontrado: {COVER_PATH}")
        sys.exit(1)

    print(f"Imagem: {COVER_PATH.name} ({COVER_PATH.stat().st_size // 1024} KB)")
    sp = get_sp()

    for name, txt_path in PLAYLISTS.items():
        if not txt_path.exists():
            print(f"  ⚠ {txt_path.name} não encontrado — pulando '{name}'")
            continue
        pid = _load_pid(txt_path)
        print(f"\n── {name} ({pid}) ──")
        upload_cover(sp, pid, name)

    print("\nPronto!")


if __name__ == "__main__":
    main()
