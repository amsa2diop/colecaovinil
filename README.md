# Discos do Amsa — DJ Library

Webapp estático que transforma uma coleção do [Discogs](https://www.discogs.com) em um catálogo interativo de vinis, publicado via GitHub Pages.

**Site ao vivo:** https://amsa2diop.github.io/colecaovinil/

---

## O que faz

- **View Discos** — grade de álbuns com capa, metadados, BPM range, campos personalizados (Loja, Preço, Condição, etc.)
- **View Faixas** — todas as faixas ordenáveis por BPM, com links Spotify/Deezer para preview
- **Filtros unificados** — Década, Origem, Tipo, Loja, Para discotecar, Para trocar, Recebido, BPM — sincronizados entre as duas views
- **Ordenação** — por data de adição, ano, artista (Discos); BPM, ano, artista (Faixas)
- **Edição inline** — edita campos personalizados do Discogs diretamente no browser, sem precisar abrir o Discogs
- **Stories** — slideshow estilo Instagram acessível pelo logo do header; suporta fotos e vídeos
- **Sync semanal automático** — GitHub Actions atualiza os dados toda segunda-feira

---

## Arquitetura

```
dj_library_v2.py          # script principal — gera HTML + XLSX a partir das APIs
regen_html.py             # regenera HTML rapidamente a partir dos CSVs em cache
fetch_discogs_fields.py   # baixa campos personalizados da coleção Discogs
fetch_bpm_full.py         # preenche BPMs via Deezer (campo + análise de preview) e GetSongBPM
fetch_cover_colors.py     # extrai cor dominante das capas (para gradiente dos cards)
fetch_discogs_country.py  # obtém país de origem dos releases
fetch_discogs_format.py   # obtém formato físico (LP/12"/7"/etc.) e selo

backup_matched.csv        # match Discogs ↔ Spotify/Deezer de todas as faixas
backup_bpm.csv            # BPMs por faixa (preenchido pelo fetch_bpm_full.py)
backup_collection_fields.csv  # campos personalizados + date_added por release
backup_cover_colors.csv   # cor dominante por release_id
backup_country.csv        # país de origem por release_id
backup_format.csv         # formato físico e selo por release_id

index.html                # HTML gerado (= MinhaColecao_DJ.html) — publicado pelo Pages
MinhaColecao_DJ.html      # idem
MinhaColecao_DJ.xlsx      # planilha exportada
preview.jpg               # imagem de preview para redes sociais (OG / WhatsApp)
preview_squared.jpg       # favicon do site (tab do browser)
stories/                  # imagens/vídeos do slideshow (1.jpg, 2.jpg … em ordem numérica)

.github/workflows/weekly_sync.yml  # GitHub Actions: sync automático semanal
```

---

## Como rodar localmente

### Pré-requisitos

```bash
pip install pandas openpyxl requests thefuzz python-Levenshtein unidecode discogs-client spotipy
```

Para análise de BPM por áudio:
```bash
pip install librosa
```

### Gerar o HTML a partir dos CSVs em cache (rápido)

```bash
python regen_html.py
```

### Rodar o pipeline completo (busca dados frescos no Discogs e Spotify)

```bash
python dj_library_v2.py
```

> ⚠ Lento — faz centenas de requisições de API. Use só quando quiser reprocessar tudo do zero.

### Preencher BPMs faltantes

```bash
# Fases 1+2: Deezer (campo BPM) + análise de áudio de preview
python fetch_bpm_full.py

# Com fallback GetSongBPM (500 req/dia grátis — registre em getsongbpm.com/api)
python fetch_bpm_full.py --songbpm-key SUA_CHAVE
```

### Publicar

```bash
git add index.html MinhaColecao_DJ.html MinhaColecao_DJ.xlsx backup_bpm.csv
git commit -m "chore: atualiza biblioteca"
git push web master   # remote 'web' aponta para amsa2diop/colecaovinil.git
```

---

## Modo de edição (browser)

Permite editar campos personalizados do Discogs diretamente no site, sem abrir o Discogs.

1. Clique no ícone **✎** na barra de ferramentas (ao lado do botão ↑)
2. No modal, informe:
   - **Usuário Discogs** (ex: `amsa2diop`)
   - **Token pessoal** — gere em [discogs.com/settings/developers](https://www.discogs.com/settings/developers)
   - **Pasta** — normalmente `1` (All)
3. Clique **Conectar** — o site busca os IDs dos campos e opções de dropdown automaticamente
4. Clique **✎ Editar** em qualquer card e edite os campos
5. **Salvar** envia direto ao Discogs via API e persiste as mudanças no `localStorage` do browser

> As edições ficam visíveis imediatamente e sobrevivem a reloads via `localStorage`. Na próxima sincronização automática (semanal), o HTML é regenerado com os dados oficiais do Discogs.

---

## Stories (slideshow do header)

Clique no logo do site (header) para abrir o slideshow estilo Instagram.

- Coloque imagens ou vídeos na pasta `stories/` com nomes numéricos: `1.jpg`, `2.jpg`, ..., `12.jpg`
- Formatos suportados: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`, `.mp4`, `.webm`, `.mov`
- A ordem é numérica (não lexicográfica) — `1, 2, 3 … 12`, não `1, 10, 11, 12, 2 …`
- **Desktop:** setas ← → nas laterais + teclado (← → Esc) + clicar nas barras de progresso no topo
- **Mobile:** toque na metade esquerda (voltar) ou direita (avançar) da tela
- Auto-avança em 5s por foto; vídeos avançam ao terminar
- Ao chegar na última, volta para a primeira (loop)
- Após adicionar ou remover arquivos em `stories/`, rode `python regen_html.py` para atualizar o `index.html`

---

## Sync automático semanal (GitHub Actions)

O workflow `.github/workflows/weekly_sync.yml` roda toda segunda às 06:00 UTC e:

1. Baixa campos atualizados de todos os discos via API Discogs
2. Regenera `index.html` e `MinhaColecao_DJ.html`
3. Faz commit e push automaticamente se houver mudanças

Para rodar manualmente: **Actions → "Sync semanal Discogs" → Run workflow**

---

## Configuração de credenciais

As credenciais de API são referenciadas diretamente nos scripts Python. Para um terceiro rodar o pipeline:

| Variável | Onde configurar | Para que serve |
|----------|----------------|----------------|
| `DISCOGS_TOKEN` | `dj_library_v2.py` e `fetch_discogs_fields.py` | Acesso à coleção Discogs |
| `SP_CLIENT_ID` / `SP_CLIENT_SEC` | `dj_library_v2.py` | Match Spotify (somente para pipeline completo) |

> **Segurança:** não commite tokens reais em repositórios públicos. Os arquivos `.spotify_cache` e `.env` estão no `.gitignore`.

---

## Estrutura dos dados principais

### `backup_collection_fields.csv`
| Coluna | Descrição |
|--------|-----------|
| `release_id` | ID do release no Discogs |
| `instance_id` | ID da instância na coleção (necessário para edição via API) |
| `date_added` | Data/hora de adição à coleção (ISO 8601) |
| `album_title`, `album_artist`, `year` | Metadados básicos |
| `Origem` | Loja onde foi comprado (campo personalizado — dropdown) |
| `DJ` | Para discotecar: Sim / Parcial / Não |
| `PA` | Para trocar: Sim / Em breve / Não |
| `Recebido?` | Se o disco já foi recebido: Sim / Não |
| `$` | Preço pago |
| `Notas` | Notas livres |

### `backup_bpm.csv`
| Coluna | Descrição |
|--------|-----------|
| `track_id` | ID da faixa no Spotify/Deezer |
| `bpm` | BPM normalizado (range 70–140) |
| `deezer_id` | ID no Deezer (quando fonte = Deezer) |
| `source` | `deezer` / `deezer_preview` / `songbpm` |

---

## Tech stack

- **Backend/geração:** Python 3.10+, pandas, openpyxl, requests, discogs-client, spotipy, thefuzz
- **Frontend:** HTML/CSS/JS vanilla — sem frameworks, sem bundler
- **Hospedagem:** GitHub Pages (repositório `amsa2diop/colecaovinil`)
- **CI/CD:** GitHub Actions
- **APIs externas:** Discogs REST, Deezer API, GetSongBPM API (opcional)
