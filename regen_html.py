"""Regenera apenas o HTML (sem re-fetch de dados ou playlist)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

# Importa funções do script principal
import dj_library_v2 as lib
import pandas as pd

WORK = lib.WORK_DIR

# Carrega dados já processados (usa v2 se disponível, senão legado)
_src = WORK / "backup_matched_v2.csv"
if not _src.exists():
    _src = WORK / "backup_final.csv"
df = pd.read_csv(_src)

# Carrega BPM do backup
BPM_COLS = ["bpm","energy","danceability","valence","key","mode","camelot","deezer_id"]
bpm_path = WORK / "backup_bpm.csv"
if bpm_path.exists():
    bpm_df  = pd.read_csv(bpm_path).dropna(subset=["track_id"])
    bpm_map = {str(r["track_id"]): r for _, r in bpm_df.iterrows()}
    for col in BPM_COLS:
        df[col] = None
    for i, row in df.iterrows():
        tid = str(row.get("track_id") or "")
        if tid and tid in bpm_map:
            for col in BPM_COLS:
                df.at[i, col] = bpm_map[tid].get(col)
    df["bpm"] = df["bpm"].apply(lambda v: lib.normalize_bpm(lib.safe_float(v)))
    filled = df["bpm"].apply(lib.safe_float).notna().sum()
    print(f"BPM carregado para {filled} faixas")

lib.generate_html(df)
lib.generate_xlsx(df)
print("Pronto!")
