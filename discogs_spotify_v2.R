# discogs_spotify_v2.R
# Biblioteca DJ: Discogs → Spotify (BPM + matching melhorado) → XLSX + HTML interativo
# -------------------------------------------------------------------------------------

# ============================================================
# 0. DEPENDÊNCIAS
# ============================================================
required_pkgs <- c("tidyverse","httr","jsonlite","httpuv","stringdist","stringi","openxlsx")
new_pkgs <- required_pkgs[!(required_pkgs %in% installed.packages()[,"Package"])]
if(length(new_pkgs)) {
  message("Instalando pacotes: ", paste(new_pkgs, collapse=", "))
  install.packages(new_pkgs, repos="https://cloud.r-project.org")
}
suppressPackageStartupMessages({
  library(tidyverse); library(httr); library(jsonlite)
  library(httpuv); library(stringdist); library(stringi); library(openxlsx)
})

`%||%` <- function(a, b) if(!is.null(a) && length(a) > 0 && !is.na(a[[1]])) a else b

# ============================================================
# 1. CONFIGURAÇÃO
# ============================================================
DISCOGS_USER   <- "amsa2diop"
DISCOGS_TOKEN  <- "FmUsfbDTXUFCniDqrTckrwBfJxvIljOGuMdygfVD"
SP_CLIENT_ID   <- "1ab6d898c52d42a19b737f451ce31e2a"
SP_CLIENT_SEC  <- "3c8b2f47049b44e2af6937ea835e1f2f"

# Limiar de aceitação: ajuste se necessário
# 0.72 = padrão equilibrado | 0.65 = mais permissivo | 0.80 = mais rigoroso
LIMIAR_ACEITO  <- 0.72
LIMIAR_REVISAR <- 0.55   # entre REVISAR e ACEITO → verificar manualmente

# ============================================================
# 2. AUTENTICAÇÃO SPOTIFY (com renovação automática de token)
# ============================================================
if(file.exists(".httr-oauth")) file.remove(".httr-oauth")

spotify_app <- oauth_app(
  "spotify",
  key          = SP_CLIENT_ID,
  secret       = SP_CLIENT_SEC,
  redirect_uri = "http://127.0.0.1:1410/"
)
spotify_endpoint <- oauth_endpoint(
  authorize = "https://accounts.spotify.com/authorize",
  access    = "https://accounts.spotify.com/api/token"
)

message("🔐 Abrindo navegador para autenticação Spotify...")
token_obj <- oauth2.0_token(
  spotify_endpoint, spotify_app,
  scope   = c("playlist-modify-public","playlist-modify-private"),
  use_oob = FALSE, cache = FALSE
)

.sp_access  <- token_obj$credentials$access_token
.sp_refresh <- token_obj$credentials$refresh_token
.sp_expiry  <- Sys.time() + 3300   # 55 min (token dura 60)

refresh_spotify_token <- function() {
  message("🔄 Renovando token Spotify...")
  r <- POST(
    "https://accounts.spotify.com/api/token",
    authenticate(SP_CLIENT_ID, SP_CLIENT_SEC),
    body   = list(grant_type="refresh_token", refresh_token=.sp_refresh),
    encode = "form"
  )
  resp <- content(r)
  if(!is.null(resp$access_token)) {
    .sp_access <<- resp$access_token
    .sp_expiry <<- Sys.time() + 3300
    if(!is.null(resp$refresh_token)) .sp_refresh <<- resp$refresh_token
    message("✅ Token renovado.")
  } else {
    stop("❌ Falha ao renovar token. Reinicie e autentique novamente.")
  }
}

get_token <- function() {
  if(Sys.time() >= .sp_expiry) refresh_spotify_token()
  .sp_access
}

# ============================================================
# 3. FUNÇÕES UTILITÁRIAS
# ============================================================

# Normalização agressiva para comparação (remove acentos, pontuação, etc.)
normalize_text <- function(x) {
  if(is.na(x) || !nzchar(x)) return("")
  x |>
    tolower() |>
    stri_trans_general("Latin-ASCII") |>
    str_remove_all("\\(.*?\\)") |>               # remove (...)
    str_remove_all("\\[.*?\\]") |>               # remove [...]
    str_remove_all("\\s*[-–—]\\s+.*$") |>        # remove "- subtítulo"
    str_remove_all("\\bfeat\\.?\\s.*$|\\bft\\.?\\s.*$|\\bcon\\b.*$") |>  # remove feat/ft
    str_remove_all("[^a-z0-9 ]") |>
    str_squish()
}

# Spotify key+mode → Camelot Wheel
key_to_camelot <- function(key, mode) {
  major <- c("8B","3B","10B","5B","12B","7B","2B","9B","4B","11B","6B","1B")
  minor <- c("5A","12A","7A","2A","9A","4A","11A","6A","1A","8A","3A","10A")
  case_when(
    is.na(key) ~ NA_character_,
    mode == 1  ~ major[key + 1L],
    TRUE       ~ minor[key + 1L]
  )
}

# Escape simples de entidades HTML
html_esc <- function(x) {
  if(is.null(x) || is.na(x)) return("")
  x <- as.character(x)
  x <- str_replace_all(x, "&", "&amp;")
  x <- str_replace_all(x, "<", "&lt;")
  x <- str_replace_all(x, ">", "&gt;")
  x <- str_replace_all(x, '"', "&quot;")
  x
}

# BPM → cor (gradiente por faixa de BPM)
bpm_color <- function(bpm) {
  if(is.na(bpm)) return("#555")
  dplyr::case_when(
    bpm < 80  ~ "#8b5cf6",
    bpm < 95  ~ "#3b82f6",
    bpm < 110 ~ "#06b6d4",
    bpm < 122 ~ "#10b981",
    bpm < 132 ~ "#f59e0b",
    bpm < 145 ~ "#f97316",
    TRUE      ~ "#ef4444"
  )
}

# GET com tratamento de rate limit (429)
safe_get <- function(url, ..., max_tries=3) {
  for(attempt in seq_len(max_tries)) {
    res <- GET(url, ...)
    if(status_code(res) != 429) return(res)
    wait <- as.numeric(headers(res)$`retry-after` %||% "5") + 1
    message(sprintf("⏳ Rate limit (tentativa %d/%d), aguardando %ds...", attempt, max_tries, wait))
    Sys.sleep(wait)
  }
  res
}

# ============================================================
# 4. DISCOGS: COLETA DE ÁLBUNS (com paginação)
# ============================================================
get_discogs_albums <- function(user, token) {
  message("📀 Coletando coleção do Discogs...")
  all_releases <- list()
  page <- 1L

  repeat {
    res <- safe_get(
      paste0("https://api.discogs.com/users/", user, "/collection/folders/0/releases"),
      query       = list(token=token, per_page=100, page=page, sort="artist"),
      add_headers("User-Agent" = "DJLibrary/2.0")
    )
    if(status_code(res) != 200) {
      message("❌ Discogs erro p.", page, ": HTTP ", status_code(res))
      break
    }
    data        <- fromJSON(rawToChar(res$content))
    total_pages <- data$pagination$pages
    all_releases <- c(all_releases, list(data$releases))
    message(sprintf("  p.%d/%d — %d álbuns", page, total_pages, length(data$releases$id)))
    if(page >= total_pages) break
    page <- page + 1L
    Sys.sleep(1.0)
  }

  df <- bind_rows(all_releases)

  tibble(
    release_id   = df$id,
    album_artist = map_chr(df$basic_information$artists, ~ .x$name[1]),
    album_title  = df$basic_information$title,
    year         = suppressWarnings(as.integer(df$basic_information$year)),
    genres       = map_chr(df$basic_information$genres,
                           ~ paste(.x, collapse=", ")),
    styles       = map_chr(df$basic_information$styles,
                           ~ if(length(.x)>0) paste(.x, collapse=", ") else NA_character_),
    cover_url    = coalesce(df$basic_information$cover_image,
                            df$basic_information$thumb),
    thumb_url    = df$basic_information$thumb
  )
}

# ============================================================
# 5. DISCOGS: FAIXAS DE CADA ÁLBUM
# ============================================================
get_discogs_tracks <- function(albums, token) {
  n <- nrow(albums)
  message(sprintf("💿 Lendo faixas de %d álbuns...", n))
  tracks_list <- vector("list", n)

  for(i in seq_len(n)) {
    if(i %% 10 == 0) message(sprintf("  %d/%d álbuns...", i, n))
    Sys.sleep(0.8)
    id <- albums$release_id[i]
    aa <- albums$album_artist[i]

    r <- safe_get(
      paste0("https://api.discogs.com/releases/", id),
      query       = list(token=token),
      add_headers("User-Agent" = "DJLibrary/2.0")
    )
    if(status_code(r) != 200) next
    cnt <- tryCatch(fromJSON(rawToChar(r$content)), error=function(e) NULL)
    if(is.null(cnt) || is.null(cnt$tracklist) || nrow(cnt$tracklist)==0) next

    tl <- cnt$tracklist
    rows <- map_dfr(seq_len(nrow(tl)), function(j) {
      trk <- tl[j,]
      art <- tryCatch(
        if(!is.null(trk$artists) && length(trk$artists[[1]])>0)
          trk$artists[[1]]$name[1] else aa,
        error = function(e) aa
      )
      tibble(
        position    = trk$position %||% NA_character_,
        track_title = trk$title,
        artist_raw  = art,
        type_       = trk$type_
      )
    }) |>
      filter(type_ == "track") |>
      select(-type_) |>
      mutate(
        release_id   = id,
        artist_clean = str_remove(artist_raw, "\\s*\\([0-9]+\\)$")
      )

    tracks_list[[i]] <- rows
  }
  bind_rows(tracks_list)
}

# ============================================================
# 6. SPOTIFY: BUSCA COM MATCHING MELHORADO (multi-estratégia)
# ============================================================
search_spotify_track <- function(artist, album_artist, title) {
  token  <- get_token()
  Sys.sleep(0.4)
  empty  <- list(spotify_uri=NA_character_, found_name=NA_character_,
                 found_artist=NA_character_, track_id=NA_character_,
                 match_score=0.0, search_strategy=NA_character_)

  run_search <- function(q) {
    tryCatch({
      r <- safe_get(
        "https://api.spotify.com/v1/search",
        query       = list(q=q, type="track", limit=5),
        add_headers(Authorization=paste("Bearer", token))
      )
      if(status_code(r) != 200) return(NULL)
      d <- fromJSON(rawToChar(r$content))
      items <- d$tracks$items
      if(is.null(items) || !is.data.frame(items) || nrow(items)==0) return(NULL)
      items
    }, error=function(e) NULL)
  }

  # Estratégia 1: campos específicos artist: + track: (maior precisão)
  strategy <- "field_search"
  items    <- run_search(sprintf('artist:"%s" track:"%s"', artist, title))

  # Estratégia 2: texto livre artista + título
  if(is.null(items)) {
    Sys.sleep(0.25); strategy <- "free_text"
    items <- run_search(paste(artist, title))
  }

  # Estratégia 3: álbum-artista + título (coletâneas / V.A.)
  if(is.null(items) && !identical(artist, album_artist)) {
    Sys.sleep(0.25); strategy <- "album_artist"
    items <- run_search(paste(album_artist, title))
  }

  # Estratégia 4: só o título (último recurso)
  if(is.null(items)) {
    Sys.sleep(0.25); strategy <- "title_only"
    items <- run_search(sprintf('track:"%s"', title))
  }

  if(is.null(items)) return(empty)

  # Avalia todos os candidatos retornados e escolhe o melhor
  norm_t  <- normalize_text(title)
  norm_a  <- normalize_text(artist)
  norm_aa <- normalize_text(album_artist)

  best_score <- -Inf
  best       <- empty

  for(i in seq_len(min(nrow(items), 5L))) {
    fn <- items$name[i] %||% ""
    fa <- tryCatch(items$artists[[i]]$name[1], error=function(e) "")

    norm_fn <- normalize_text(fn)
    norm_fa <- normalize_text(fa)

    # Similaridade: título (65%) + artista (35%)
    st  <- stringsim(norm_t,  norm_fn, method="jw")
    sa  <- max(
      stringsim(norm_a,  norm_fa, method="jw"),
      stringsim(norm_aa, norm_fa, method="jw")
    )
    score <- st * 0.65 + sa * 0.35

    # Penalizações para versões não desejadas
    fn_lo <- tolower(fn)
    t_lo  <- tolower(title)
    if(grepl("\\blive\\b|ao vivo|concert|en vivo", fn_lo) &&
       !grepl("live|ao vivo|concert|en vivo", t_lo)) score <- score - 0.20
    if(grepl("\\bremix\\b|\\bedit\\b|rework|dub mix", fn_lo) &&
       !grepl("remix|edit|rework|dub", t_lo))           score <- score - 0.15
    if(grepl("remaster|remastered", fn_lo) &&
       !grepl("remaster", t_lo))                        score <- score - 0.05

    if(score > best_score) {
      best_score <- score
      best <- list(
        spotify_uri    = items$uri[i],
        found_name     = fn,
        found_artist   = fa,
        track_id       = str_extract(items$uri[i], "[^:]+$"),
        match_score    = score,
        search_strategy = strategy
      )
    }
  }
  best
}

# ============================================================
# 7. SPOTIFY: BPM via Audio Features (lotes de 100)
# ============================================================
get_audio_features <- function(track_ids) {
  valid <- na.omit(unique(track_ids))
  if(length(valid) == 0) {
    return(tibble(track_id=character(), bpm=numeric(), energy=numeric(),
                  danceability=numeric(), valence=numeric(),
                  key=integer(), mode=integer(), camelot=character()))
  }
  message(sprintf("🎵 Buscando BPM para %d faixas (lotes de 100)...", length(valid)))
  chunks  <- split(valid, ceiling(seq_along(valid)/100))
  results <- list()

  for(i in seq_along(chunks)) {
    Sys.sleep(0.5)
    tkn <- get_token()
    r   <- safe_get(
      "https://api.spotify.com/v1/audio-features",
      query       = list(ids=paste(chunks[[i]], collapse=",")),
      add_headers(Authorization=paste("Bearer", tkn))
    )
    if(status_code(r) != 200) {
      message(sprintf("⚠️ audio-features erro lote %d: HTTP %d", i, status_code(r)))
      next
    }
    feats <- fromJSON(rawToChar(r$content))$audio_features
    if(!is.null(feats) && is.data.frame(feats) && nrow(feats)>0)
      results <- c(results, list(feats))
    message(sprintf("  BPM: lote %d/%d ✓", i, length(chunks)))
  }

  if(length(results) == 0)
    return(tibble(track_id=character(), bpm=numeric(), energy=numeric(),
                  danceability=numeric(), valence=numeric(),
                  key=integer(), mode=integer(), camelot=character()))

  bind_rows(results) |>
    filter(!is.na(id)) |>
    transmute(
      track_id     = id,
      bpm          = round(tempo, 1),
      energy       = round(energy, 2),
      danceability = round(danceability, 2),
      valence      = round(valence, 2),
      key          = as.integer(key),
      mode         = as.integer(mode),
      camelot      = key_to_camelot(key, mode)
    )
}

# ============================================================
# 8. EXECUÇÃO PRINCIPAL
# ============================================================
# Se já tem backup das etapas anteriores, pode carregar e pular:
# albums_df    <- readRDS("backup_01_albums.rds")
# tracks_df    <- readRDS("backup_02_tracks.rds")
# colecao_matched <- readRDS("backup_03_matched.rds")
# colecao_final   <- readRDS("backup_04_final.rds")

# Etapa A: Discogs
albums_df <- get_discogs_albums(DISCOGS_USER, DISCOGS_TOKEN)
saveRDS(albums_df, "backup_01_albums.rds")

tracks_df <- get_discogs_tracks(albums_df, DISCOGS_TOKEN)
saveRDS(tracks_df, "backup_02_tracks.rds")

colecao <- left_join(tracks_df, albums_df, by="release_id")
message(sprintf("\n📦 Total: %d faixas em %d álbuns\n", nrow(colecao), nrow(albums_df)))

# Etapa B: Spotify matching
message(sprintf("🔍 Iniciando matching Spotify para %d faixas...", nrow(colecao)))

spotify_results <- map_dfr(seq_len(nrow(colecao)), function(i) {
  if(i %% 50 == 0) message(sprintf("  %d/%d faixas buscadas...", i, nrow(colecao)))
  res <- search_spotify_track(
    colecao$artist_clean[i],
    colecao$album_artist[i],
    colecao$track_title[i]
  )
  as_tibble(res)
})

colecao_matched <- bind_cols(colecao, spotify_results) |>
  mutate(status = case_when(
    match_score >= LIMIAR_ACEITO  ~ "ACEITO",
    match_score >= LIMIAR_REVISAR & !is.na(track_id) ~ "REVISAR",
    TRUE ~ "REJEITADO"
  ))

saveRDS(colecao_matched, "backup_03_matched.rds")
message(sprintf(
  "\n✅ Aceitos: %d | 👀 Revisar: %d | ❌ Rejeitados: %d",
  sum(colecao_matched$status=="ACEITO"),
  sum(colecao_matched$status=="REVISAR"),
  sum(colecao_matched$status=="REJEITADO")
))

# Etapa C: BPM
aceitos_ids  <- colecao_matched |> filter(status=="ACEITO") |> pull(track_id)
bpm_data     <- get_audio_features(aceitos_ids)
colecao_final <- left_join(colecao_matched, bpm_data, by="track_id")
saveRDS(colecao_final, "backup_04_final.rds")

# ============================================================
# 9. OUTPUT: XLSX
# ============================================================
message("\n📊 Gerando XLSX...")

xlsx_cols <- c(
  "status","album_artist","artist_clean","track_title","album_title",
  "year","genres","styles","bpm","camelot","energy","danceability","valence",
  "match_score","found_artist","found_name","search_strategy","spotify_uri","track_id"
)

wb <- createWorkbook()
add_sheet <- function(wb, name, df) {
  addWorksheet(wb, name)
  if(nrow(df) > 0) {
    writeDataTable(wb, name, df, tableStyle="TableStyleMedium2")
    setColWidths(wb, name, cols=seq_len(ncol(df)), widths="auto")
  } else {
    writeData(wb, name, "Nenhum dado nesta categoria.")
  }
}

df_base    <- colecao_final |> select(any_of(xlsx_cols))
add_sheet(wb, "Todos (por album)",     df_base |> arrange(album_artist, album_title, position))
add_sheet(wb, "Aceitos (por BPM)",     df_base |> filter(status=="ACEITO") |> arrange(bpm))
add_sheet(wb, "Para Revisar",          df_base |> filter(status=="REVISAR") |> arrange(desc(match_score)))
add_sheet(wb, "Nao Encontrados",       df_base |> filter(status=="REJEITADO"))

saveWorkbook(wb, "MinhaColecao_DJ.xlsx", overwrite=TRUE)
message("✅ MinhaColecao_DJ.xlsx gerado!")

# ============================================================
# 10. PLAYLIST SPOTIFY (ordenada por BPM)
# ============================================================
message("\n🎧 Criando playlist no Spotify...")

pl_df  <- colecao_final |>
  filter(status=="ACEITO", !is.na(spotify_uri)) |>
  arrange(coalesce(bpm, 999.0))
uris   <- pl_df$spotify_uri

if(length(uris) > 0) {
  tkn <- get_token()
  uid <- content(GET("https://api.spotify.com/v1/me",
                     add_headers(Authorization=paste("Bearer", tkn))))$id
  now_str <- format(Sys.time(), "%d/%m/%Y %H:%M")

  res_pl <- POST(
    paste0("https://api.spotify.com/v1/users/", uid, "/playlists"),
    add_headers(Authorization=paste("Bearer", tkn)),
    body = toJSON(list(
      name        = "Meu Discogs — por BPM",
      description = paste0("Coleção de vinis ordenada por BPM | ", now_str),
      public      = FALSE
    ), auto_unbox=TRUE)
  )
  pid    <- content(res_pl)$id
  chunks <- split(uris, ceiling(seq_along(uris)/100))
  for(i in seq_along(chunks)) {
    tkn <- get_token()
    POST(paste0("https://api.spotify.com/v1/playlists/", pid, "/tracks"),
         add_headers(Authorization=paste("Bearer", tkn)),
         body = toJSON(list(uris=chunks[[i]]), auto_unbox=TRUE))
    Sys.sleep(0.5)
    message(sprintf("  Playlist: lote %d/%d", i, length(chunks)))
  }
  message(sprintf("🎉 Playlist criada com %d faixas (ordenada por BPM)!", length(uris)))
} else {
  message("⚠️ Nenhuma faixa aceita para playlist.")
}

# ============================================================
# 11. HTML: BIBLIOTECA DJ INTERATIVA
# ============================================================
message("\n🌐 Gerando HTML da biblioteca DJ...")

html_data <- colecao_final |>
  arrange(album_artist, album_title, position)

# Gera HTML de uma faixa individual
make_track_html <- function(r) {
  bpm    <- r$bpm
  cam    <- r$camelot %||% NA
  energy <- r$energy  %||% NA
  dance  <- r$danceability %||% NA
  uri    <- r$spotify_uri  %||% NA

  bpm_txt  <- if(!is.na(bpm)) sprintf("%.0f", bpm) else "—"
  bpm_clr  <- bpm_color(bpm)
  cam_txt  <- if(!is.na(cam) && nchar(cam)>0) cam else ""
  ener_pct <- if(!is.na(energy)) round(energy * 100) else 0L
  dance_pct<- if(!is.na(dance))  round(dance  * 100) else 0L

  status_dot <- switch(r$status, "ACEITO"="dot-ok", "REVISAR"="dot-warn", "dot-rej")

  # Embed via clique (não carrega automaticamente — melhor performance)
  embed_block <- if(!is.na(uri) && nchar(uri)>0) {
    tid <- str_extract(uri, "[^:]+$")
    sprintf(
      '<div class="embed-placeholder" onclick="loadEmbed(this,\'%s\')" title="Ouvir prévia"><span class="play-icon">&#9654;</span> Ouvir prévia</div>',
      tid
    )
  } else {
    '<div class="no-embed">Não encontrado no Spotify</div>'
  }

  cam_span <- if(nchar(cam_txt)>0) {
    clr <- if(grepl("A$", cam_txt)) "#2563eb" else "#d97706"
    sprintf('<span class="cam-badge" style="background:%s">%s</span>', clr, cam_txt)
  } else ""

  sprintf(
    '<div class="track" data-bpm="%s" data-status="%s">
  <div class="track-main">
    <span class="status-dot %s" title="%s"></span>
    <div class="track-text">
      <div class="track-artist">%s</div>
      <div class="track-title">%s</div>
    </div>
    <div class="track-badges">
      <span class="bpm-badge" style="background:%s">%s BPM</span>%s
    </div>
    <div class="track-bars">
      <span class="bar-lbl">E</span>
      <div class="bar-bg"><div class="bar-fill" style="width:%d%%;background:#f97316"></div></div>
      <span class="bar-lbl">D</span>
      <div class="bar-bg"><div class="bar-fill" style="width:%d%%;background:#10b981"></div></div>
    </div>
  </div>
  %s
</div>',
    ifelse(is.na(bpm), "999", as.character(round(bpm))),
    r$status, status_dot, r$status,
    html_esc(r$artist_clean), html_esc(r$track_title),
    bpm_clr, bpm_txt, cam_span,
    ener_pct, dance_pct,
    embed_block
  )
}

# Gera HTML de um álbum (card com faixas)
make_album_html <- function(adf) {
  first      <- adf[1,]
  cover      <- html_esc(first$cover_url %||% "")
  bpm_vals   <- na.omit(adf$bpm)
  bpm_range  <- if(length(bpm_vals)>0)
    sprintf("%.0f–%.0f BPM", min(bpm_vals), max(bpm_vals))
  else "BPM n/d"
  min_bpm    <- if(length(bpm_vals)>0) round(min(bpm_vals)) else 999L
  n_ok       <- sum(adf$status=="ACEITO", na.rm=TRUE)
  n_total    <- nrow(adf)
  year_s     <- if(!is.na(first$year) && first$year>0) as.character(first$year) else ""
  genres_s   <- html_esc(first$genres %||% "")
  styles_s   <- html_esc(first$styles %||% "")

  img_tag    <- if(nchar(cover)>4)
    sprintf('<img class="cover-img" src="%s" alt="%s" loading="lazy" onerror="this.style.display=\'none\'">',
            cover, html_esc(first$album_title))
  else '<div class="cover-ph">♪</div>'

  styles_tag <- if(nchar(styles_s)>0)
    sprintf('<span class="tag style-tag">%s</span>', styles_s) else ""

  tracks_html <- paste(map_chr(seq_len(n_total), ~ make_track_html(adf[.x,])), collapse="\n")

  sprintf(
    '<article class="album-card" data-genres="%s" data-styles="%s" data-year="%s" data-min-bpm="%d">
  <header class="album-header" onclick="toggleAlbum(this)">
    <div class="cover-wrap">%s</div>
    <div class="album-info">
      <div class="alb-artist">%s</div>
      <div class="alb-title">%s</div>
      <div class="alb-tags">
        <span class="tag year-tag">%s</span>
        <span class="tag genre-tag">%s</span>%s
      </div>
      <div class="alb-bpm">%s</div>
      <div class="alb-ratio">%d/%d faixas no Spotify</div>
    </div>
    <button class="toggle-btn" aria-label="expandir">▼</button>
  </header>
  <div class="tracks-list collapsed">%s</div>
</article>',
    tolower(genres_s), tolower(styles_s), year_s, min_bpm,
    img_tag,
    html_esc(first$album_artist), html_esc(first$album_title),
    year_s, genres_s, styles_tag,
    bpm_range, n_ok, n_total,
    tracks_html
  )
}

# Processa todos os álbuns
all_albums_html <- html_data |>
  group_by(release_id) |>
  group_split() |>
  map_chr(function(grp) {
    tryCatch(make_album_html(as.data.frame(grp)), error=function(e) {
      message("⚠️ Erro em álbum: ", conditionMessage(e)); ""
    })
  }) |>
  paste(collapse="\n")

# Stats para o header
n_albums  <- n_distinct(html_data$release_id)
n_tracks  <- nrow(html_data)
n_matched <- sum(html_data$status=="ACEITO", na.rm=TRUE)
avg_bpm   <- round(mean(html_data$bpm, na.rm=TRUE))
pct_cov   <- round(n_matched / n_tracks * 100)
avg_bpm_s <- if(is.nan(avg_bpm)) "—" else as.character(avg_bpm)

genres_list <- html_data |> pull(genres) |> na.omit() |>
  str_split(", ") |> unlist() |> str_squish() |>
  Filter(nzchar, x=_) |> unique() |> sort()
genres_opts <- paste(
  sprintf('<option value="%s">%s</option>', tolower(genres_list), genres_list),
  collapse="\n"
)

# Template HTML completo
html_out <- sprintf('<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DJ Library</title>
<style>
:root{--bg:#09090f;--surf:#13131e;--surf2:#1c1c2c;--bdr:#2a2a3e;--acc:#1db954;--text:#e2e2e8;--muted:#6b6b90;--r:12px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Segoe UI",system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
/* HEADER */
.site-header{background:linear-gradient(135deg,#0d1117 0%%,#1a1a3e 60%%,#0f3460 100%%);padding:2rem 2.5rem 1.5rem;border-bottom:2px solid var(--acc)}
.site-header h1{font-size:2.2rem;color:var(--acc);font-weight:800;letter-spacing:-1px}
.site-header p{color:var(--muted);margin-top:.3rem;font-size:.9rem}
.stats-row{display:flex;gap:1.2rem;margin-top:1.2rem;flex-wrap:wrap}
.stat-card{background:rgba(255,255,255,.05);border:1px solid rgba(29,185,84,.25);border-radius:var(--r);padding:.6rem 1.2rem;text-align:center;min-width:85px}
.stat-val{font-size:1.5rem;font-weight:700;color:var(--acc);line-height:1}
.stat-lbl{font-size:.65rem;color:var(--muted);text-transform:uppercase;letter-spacing:.5px;margin-top:.2rem}
/* CONTROLS */
.controls{position:sticky;top:0;z-index:50;background:rgba(9,9,15,.95);backdrop-filter:blur(10px);border-bottom:1px solid var(--bdr);padding:.7rem 2rem;display:flex;gap:.7rem;flex-wrap:wrap;align-items:center}
.ctrl-input{flex:1;min-width:180px;background:var(--surf2);border:1px solid var(--bdr);color:var(--text);padding:.5rem .9rem;border-radius:8px;font-size:.9rem;outline:none}
.ctrl-input:focus{border-color:var(--acc)}
.ctrl-sel{background:var(--surf2);border:1px solid var(--bdr);color:var(--text);padding:.5rem .8rem;border-radius:8px;font-size:.85rem;outline:none;cursor:pointer}
.ctrl-btn{background:var(--surf2);border:1px solid var(--bdr);color:var(--text);padding:.5rem .9rem;border-radius:8px;font-size:.82rem;cursor:pointer;white-space:nowrap;transition:border-color .2s,color .2s}
.ctrl-btn:hover,.ctrl-btn.active{border-color:var(--acc);color:var(--acc);background:rgba(29,185,84,.08)}
/* MAIN */
.main{max-width:1300px;margin:0 auto;padding:1.5rem 2rem}
.results-bar{font-size:.83rem;color:var(--muted);margin-bottom:.8rem}
.albums-grid{display:flex;flex-direction:column;gap:1rem}
/* ALBUM CARD */
.album-card{background:var(--surf);border:1px solid var(--bdr);border-radius:var(--r);overflow:hidden;transition:border-color .2s}
.album-card:hover{border-color:rgba(29,185,84,.35)}
.album-card.hidden{display:none}
.album-header{display:flex;align-items:center;gap:1.2rem;padding:1rem 1.2rem;cursor:pointer;user-select:none;transition:background .15s}
.album-header:hover{background:rgba(255,255,255,.025)}
.cover-wrap{flex-shrink:0}
.cover-img{width:95px;height:95px;object-fit:cover;border-radius:8px;display:block}
.cover-ph{width:95px;height:95px;border-radius:8px;background:var(--surf2);display:flex;align-items:center;justify-content:center;font-size:2.2rem;color:var(--muted)}
.album-info{flex:1;min-width:0}
.alb-artist{font-weight:700;font-size:1rem;color:var(--text)}
.alb-title{color:var(--muted);font-size:.87rem;margin-top:.1rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.alb-tags{display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.45rem}
.tag{padding:.18rem .55rem;border-radius:20px;font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.3px}
.genre-tag{background:rgba(29,185,84,.12);color:#1db954;border:1px solid rgba(29,185,84,.25)}
.style-tag{background:rgba(59,130,246,.12);color:#60a5fa;border:1px solid rgba(59,130,246,.25)}
.year-tag{background:rgba(245,158,11,.12);color:#fbbf24;border:1px solid rgba(245,158,11,.25)}
.alb-bpm{font-size:.8rem;color:var(--muted);margin-top:.4rem}
.alb-ratio{font-size:.72rem;color:var(--muted);margin-top:.1rem}
.toggle-btn{background:none;border:none;color:var(--muted);font-size:1.1rem;cursor:pointer;padding:.3rem .5rem;transition:transform .3s,color .2s;flex-shrink:0;line-height:1}
.album-card.open .toggle-btn{transform:rotate(180deg);color:var(--acc)}
/* TRACKS */
.tracks-list{border-top:1px solid var(--bdr)}
.tracks-list.collapsed{display:none}
.track{padding:.75rem 1.2rem;border-bottom:1px solid rgba(255,255,255,.04);transition:background .12s}
.track:last-child{border-bottom:none}
.track:hover{background:rgba(255,255,255,.02)}
.track-main{display:flex;align-items:center;gap:.75rem;flex-wrap:wrap}
.status-dot{width:7px;height:7px;border-radius:50%;flex-shrink:0;cursor:default}
.dot-ok{background:#1db954}.dot-warn{background:#f59e0b}.dot-rej{background:#ef4444}
.track-text{flex:1;min-width:120px}
.track-artist{font-size:.75rem;color:var(--muted)}
.track-title{font-size:.92rem;font-weight:600;color:var(--text)}
.track-badges{display:flex;gap:.35rem;align-items:center;flex-shrink:0}
.bpm-badge{padding:.22rem .55rem;border-radius:6px;font-size:.78rem;font-weight:700;color:#fff;letter-spacing:.3px}
.cam-badge{padding:.22rem .5rem;border-radius:6px;font-size:.76rem;font-weight:700;color:#fff}
.track-bars{display:flex;align-items:center;gap:.35rem;flex-shrink:0}
.bar-lbl{font-size:.62rem;color:var(--muted);width:12px;text-align:center}
.bar-bg{background:rgba(255,255,255,.08);border-radius:3px;height:5px;width:52px;overflow:hidden}
.bar-fill{height:100%%;border-radius:3px}
/* EMBED */
.embed-placeholder{margin-top:.55rem;display:inline-flex;align-items:center;gap:.4rem;background:rgba(29,185,84,.08);border:1px solid rgba(29,185,84,.2);color:var(--acc);padding:.35rem .8rem;border-radius:6px;font-size:.8rem;cursor:pointer;transition:background .15s}
.embed-placeholder:hover{background:rgba(29,185,84,.15)}
.play-icon{font-size:.9rem}
.sp-embed{margin-top:.55rem;border-radius:8px;display:block}
.no-embed{margin-top:.55rem;font-size:.78rem;color:var(--muted);background:var(--surf2);padding:.4rem .7rem;border-radius:6px;display:inline-block}
@media(max-width:600px){.site-header{padding:1.2rem 1rem}.site-header h1{font-size:1.5rem}.controls{padding:.6rem 1rem}.main{padding:1rem}.cover-img,.cover-ph{width:70px;height:70px}}
</style>
</head>
<body>
<header class="site-header">
  <h1>&#127911; Minha Biblioteca DJ</h1>
  <p>Cole&#231;&#227;o de vinis &bull; Discogs + Spotify</p>
  <div class="stats-row">
    <div class="stat-card"><div class="stat-val">%d</div><div class="stat-lbl">&#193;lbuns</div></div>
    <div class="stat-card"><div class="stat-val">%d</div><div class="stat-lbl">Faixas</div></div>
    <div class="stat-card"><div class="stat-val">%d</div><div class="stat-lbl">No Spotify</div></div>
    <div class="stat-card"><div class="stat-val">%s</div><div class="stat-lbl">BPM m&#233;dio</div></div>
    <div class="stat-card"><div class="stat-val">%d%%</div><div class="stat-lbl">Cobertura</div></div>
  </div>
</header>
<div class="controls">
  <input class="ctrl-input" id="q" type="search" placeholder="&#128269; Artista, t&#237;tulo, &#225;lbum...">
  <select class="ctrl-sel" id="gf" onchange="applyFilters()">
    <option value="">Todos os g&#234;neros</option>
    %s
  </select>
  <select class="ctrl-sel" id="sf" onchange="applyFilters()">
    <option value="">Ordenar padr&#227;o</option>
    <option value="bpm-asc">BPM crescente</option>
    <option value="bpm-desc">BPM decrescente</option>
    <option value="year-asc">Ano (antigo)</option>
    <option value="year-desc">Ano (recente)</option>
    <option value="az">Artista A&#8594;Z</option>
  </select>
  <button class="ctrl-btn" onclick="expandAll()">Expandir tudo</button>
  <button class="ctrl-btn" onclick="collapseAll()">Recolher tudo</button>
  <button class="ctrl-btn" id="miss-btn" onclick="toggleMissing()">Ocultar n&#227;o encontrados</button>
</div>
<main class="main">
  <div class="results-bar">Mostrando <strong id="cnt">%d</strong> &#225;lbuns</div>
  <div class="albums-grid" id="grid">
%s
  </div>
</main>
<script>
var showMissing=true;
function toggleAlbum(hdr){
  var card=hdr.closest(".album-card");
  var list=card.querySelector(".tracks-list");
  card.classList.toggle("open");
  list.classList.toggle("collapsed");
}
function expandAll(){
  document.querySelectorAll(".album-card:not(.hidden)").forEach(function(c){
    c.classList.add("open");
    c.querySelector(".tracks-list").classList.remove("collapsed");
  });
}
function collapseAll(){
  document.querySelectorAll(".album-card").forEach(function(c){
    c.classList.remove("open");
    c.querySelector(".tracks-list").classList.add("collapsed");
  });
}
function toggleMissing(){
  showMissing=!showMissing;
  document.getElementById("miss-btn").textContent=
    showMissing?"Ocultar não encontrados":"Mostrar não encontrados";
  applyFilters();
}
function applyFilters(){
  var q=document.getElementById("q").value.toLowerCase().trim();
  var genre=document.getElementById("gf").value.toLowerCase();
  var sort=document.getElementById("sf").value;
  var grid=document.getElementById("grid");
  var cards=Array.from(grid.querySelectorAll(".album-card"));
  var vis=0;
  cards.forEach(function(card){
    var txt=card.textContent.toLowerCase();
    var genres=card.dataset.genres||"";
    var hasOk=card.querySelector(".dot-ok")!==null;
    var ok=((!q)||txt.includes(q))&&((!genre)||genres.includes(genre))&&(showMissing||hasOk);
    card.classList.toggle("hidden",!ok);
    if(ok) vis++;
  });
  document.getElementById("cnt").textContent=vis;
  if(sort){
    var vcards=cards.filter(function(c){return !c.classList.contains("hidden")});
    vcards.sort(function(a,b){
      if(sort==="bpm-asc")  return (+a.dataset.minBpm||999)-(+b.dataset.minBpm||999);
      if(sort==="bpm-desc") return (+b.dataset.minBpm||0)-(+a.dataset.minBpm||0);
      if(sort==="year-asc") return (+a.dataset.year||0)-(+b.dataset.year||0);
      if(sort==="year-desc")return (+b.dataset.year||0)-(+a.dataset.year||0);
      if(sort==="az")       return a.querySelector(".alb-artist").textContent.localeCompare(b.querySelector(".alb-artist").textContent);
      return 0;
    });
    vcards.forEach(function(c){grid.appendChild(c)});
  }
}
function loadEmbed(el,tid){
  var iframe=document.createElement("iframe");
  iframe.src="https://open.spotify.com/embed/track/"+tid+"?utm_source=generator";
  iframe.width="100%%"; iframe.height="80"; iframe.frameBorder="0";
  iframe.allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";
  iframe.className="sp-embed";
  el.parentNode.replaceChild(iframe,el);
}
var timer;
document.getElementById("q").addEventListener("input",function(){
  clearTimeout(timer);timer=setTimeout(applyFilters,220);
});
document.getElementById("cnt").textContent=document.querySelectorAll(".album-card").length;
</script>
</body>
</html>',
  n_albums, n_tracks, n_matched, avg_bpm_s, pct_cov,
  genres_opts,
  n_albums,
  all_albums_html
)

writeLines(html_out, "MinhaColecao_DJ.html", useBytes=FALSE)
message("✅ MinhaColecao_DJ.html gerado!")

message(sprintf("
\U0001f389 TUDO PRONTO!
  \U0001f4ca XLSX: MinhaColecao_DJ.xlsx
  \U0001f310 HTML: MinhaColecao_DJ.html
  \U0001f3a7 Playlist Spotify: 'Meu Discogs — por BPM'
  Total: %d faixas | %d no Spotify (%d%%) | BPM médio: %s
",
n_tracks, n_matched, pct_cov, avg_bpm_s
))
