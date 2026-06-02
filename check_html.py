import re, statistics
from pathlib import Path

h = Path("MinhaColecao_DJ.html").read_text(encoding="utf-8")

print("=== Origem filter ===")
print(f"origem-chip ocorrencias: {h.count('origem-chip')}")
print(f"setOrigemFilter: {h.count('setOrigemFilter')}")
print(f"data-origem atributos: {h.count('data-origem')}")

vals = re.findall(r'data-val="([^"]*)"', h)
print(f"Valores nos chips de Origem: {sorted(set(vals))}")

print("\n=== BPM ===")
bpms = [int(b) for b in re.findall(r'data-bpm="(\d+)"', h) if int(b) > 0]
print(f"Faixas com BPM > 0: {len(bpms)}")
if bpms:
    print(f"Range: {min(bpms)}-{max(bpms)} BPM")
    print(f"Media: {statistics.mean(bpms):.0f} BPM")

print("\n=== Campos personalizados ===")
print(f"field-item spans: {h.count('class=\"field-item\"')}")
print(f"Campos Origem no HTML: {h.count('<strong>Origem:</strong>')}")
print(f"Campos DJ no HTML: {h.count('<strong>DJ:</strong>')}")
print(f"Campos Notas no HTML: {h.count('field-notes')}")
