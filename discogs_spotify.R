library(tidyverse)
library(httr)
library(jsonlite)
library(httpuv)
library(stringdist)

# --- 1. CREDENCIAIS E AUTH (Padrão) ---
discogs_user  <- "amsa2diop"
discogs_token <- "FmUsfbDTXUFCniDqrTckrwBfJxvIljOGuMdygfVD"
client_id     <- "1ab6d898c52d42a19b737f451ce31e2a"
client_secret <- "3c8b2f47049b44e2af6937ea835e1f2f"

Sys.unsetenv("SPOTIFY_REDIRECT_URI")
if (file.exists(".httr-oauth")) file.remove(".httr-oauth")

spotify_app <- oauth_app("spotify", key=client_id, secret=client_secret, redirect_uri="http://127.0.0.1:1410/")
endpoint <- oauth_endpoint(authorize="https://accounts.spotify.com/authorize", access="https://accounts.spotify.com/api/token")

message("🔐 Autenticando...")
token_obj <- oauth2.0_token(endpoint, spotify_app, scope=c("playlist-modify-public", "playlist-modify-private"), use_oob=FALSE, cache=FALSE)
access_token <- token_obj$credentials$access_token

# --- 2. FUNÇÕES DE EXTRAÇÃO ---

get_discogs_data <- function(user, token) {
  # Pega Albums
  url <- paste0("https://api.discogs.com/users/", user, "/collection/folders/0/releases")
  res <- GET(url, query=list(token=token, per_page=100, sort="artist"), add_headers("User-Agent"="BPMApp/5.0"))
  data <- fromJSON(rawToChar(res$content))
  
  # Cria DF Base
  albuns <- tibble(
    release_id = data$releases$id,
    album_artist = map_chr(data$releases$basic_information$artists, ~ .x$name[1]),
    album_title = data$releases$basic_information$title, # <--- ADICIONE ESTA LINHA
    year = as.numeric(data$releases$basic_information$year),
    genres = map_chr(data$releases$basic_information$genres, ~ paste(.x, collapse = ", "))
  )
  
  message("💿 Lendo faixas dos álbuns...")
  # Pega Faixas
  colecao <- albuns %>%
    mutate(tracks = map2(release_id, album_artist, function(id, aa) {
      Sys.sleep(0.7)
      r <- GET(paste0("https://api.discogs.com/releases/", id), query=list(token=token), add_headers("User-Agent"="BPMApp/5.0"))
      if(status_code(r)!=200) return(NULL)
      cnt <- fromJSON(rawToChar(r$content))
      if(is.null(cnt$tracklist)) return(NULL)
      
      map_dfr(1:nrow(cnt$tracklist), function(i) {
        trk <- cnt$tracklist[i,]
        art <- if(!is.null(trk$artists) && length(trk$artists[[1]])>0) trk$artists[[1]]$name[1] else aa
        tibble(artist_raw = art, track_title = trk$title, type = trk$type_)
      }) %>% filter(type=="track") %>% select(-type) %>% 
        mutate(artist_clean = str_remove(artist_raw, " \\([0-9]+\\)"))
    })) %>% unnest(tracks)
  
  return(colecao)
}

# Função que SÓ busca e retorna o que achou (sem julgar se é bom ou ruim)
get_spotify_raw <- function(track_artist, album_artist, track_title, token) {
  Sys.sleep(0.5)
  query <- paste(track_artist, track_title)
  res <- GET("https://api.spotify.com/v1/search?q=", 
             query=list(q=query, type="track", limit="1"), 
             add_headers(Authorization=paste("Bearer", token)))
  
  if(status_code(res)!=200) return(list(uri=NA, name=NA, artist=NA))
  d <- fromJSON(rawToChar(res$content))
  if(length(d$tracks$items)==0) return(list(uri=NA, name=NA, artist=NA))
  
  # Retorna o que achou, doa a quem doer
  list(
    uri = d$tracks$items$uri[1],
    found_name = d$tracks$items$name[1],
    found_artist = d$tracks$items$artists[[1]]$name[1]
  )
}

# --- 3. EXECUÇÃO DA EXTRAÇÃO (DEMORADO) ---
colecao_discogs <- get_discogs_data(discogs_user, discogs_token)

message(paste("🔍 Buscando dados brutos no Spotify para", nrow(colecao_discogs), "faixas..."))

dados_brutos <- colecao_discogs %>%
  mutate(spotify_raw = pmap(list(artist_clean, album_artist, track_title), 
                            function(a, aa, t) get_spotify_raw(a, aa, t, access_token))) %>%
  unnest_wider(spotify_raw, names_sep = "_") # Cria colunas: spotify_raw_found_name, etc.

# SALVANDO BACKUP! Se der erro depois, basta carregar esse arquivo.
# saveRDS(dados_brutos, "backup_dados_brutos.rds") 
message("✅ Dados brutos salvos! Agora vamos para a Etapa 2 (Calibragem).")








# Se você fechou o R, carregue os dados:
# dados_brutos <- readRDS("backup_dados_brutos.rds")

# --- DEFINA AQUI O RIGOR ---
# 0.55 = Padrão (Filtra erros grosseiros)
# 0.40 = Mais permissivo (Aceita "Ao Vivo", "Remix" com mais facilidade)
# 0.80 = Muito rigoroso (Tem que ser quase idêntico)
LIMIAR_ACEITACAO <- 0.90

# Função de Cálculo de Nota (Local)
calcular_score <- function(orig_track, orig_artist, orig_album_artist, found_track, found_artist) {
  if(is.na(found_track)) return(0)
  
  clean <- function(x) stringi::stri_trans_general(tolower(x), "Latin-ASCII")
  
  # Limpeza Agressiva para comparação (Remove "Ao Vivo", "Remaster", "(...)", "- ...")
  clean_ft <- str_remove_all(clean(found_track), " \\- .*| \\(.*\\)| ao vivo| live| remaster") 
  clean_ot <- str_remove_all(clean(orig_track), " \\- .*| \\(.*\\)| ao vivo| live| remaster")
  
  score_track <- stringsim(clean_ot, clean_ft, method = "jw")
  
  # Score Artista (Compara com artista da faixa E do album)
  sa1 <- stringsim(clean(orig_artist), clean(found_artist), method="jw")
  sa2 <- stringsim(clean(orig_album_artist), clean(found_artist), method="jw")
  score_artist <- max(sa1, sa2)
  
  return((score_track + score_artist) / 2)
}

# Aplica a validação
dados_calibrados <- dados_brutos %>%
  rowwise() %>%
  mutate(
    score_final = calcular_score(track_title, artist_clean, album_artist, spotify_raw_found_name, spotify_raw_found_artist),
    # A Lógica de Decisão:
    status = ifelse(score_final >= LIMIAR_ACEITACAO, "ACEITO", "REJEITADO")
  ) %>%
  ungroup()

# --- DIAGNÓSTICO ---
# Vamos ver o que está na "Zona Cinzenta" (Scores baixos mas que acharam algo)
zona_cinzenta <- dados_calibrados %>%
  filter(status == "REJEITADO" & !is.na(spotify_raw_found_name)) %>%
  select(artist_clean, track_title, spotify_raw_found_artist, spotify_raw_found_name, score_final) %>%
  arrange(desc(score_final))

message("--- RESULTADO DA CALIBRAGEM ---")
message(paste("Total Faixas:", nrow(dados_calibrados)))
message(paste("Aceitas:", sum(dados_calibrados$status == "ACEITO")))
message(paste("Rejeitadas:", sum(dados_calibrados$status == "REJEITADO")))
message("\n--- TOP 10 REJEITADOS (QUASE ENTRARAM) ---")
print(head(zona_cinzenta, 10))









message("\n📄 Gerando Relatório Final...")

# Prepara os dados finais
resultado_final <- dados_calibrados %>%
  arrange(year, artist_clean, track_title)

# Filtra
encontradas <- resultado_final %>% filter(status == "ACEITO")
nao_encontradas <- resultado_final %>% filter(status == "REJEITADO")

# 1. GERA O TXT FORMATADO
txt_missing <- if(nrow(nao_encontradas) > 0) {
  paste0(
    "[MISSING] ", nao_encontradas$artist_clean, " - ", nao_encontradas$track_title, 
    " [Álbum: ", nao_encontradas$album_title, "]", # <--- ADICIONE ESTA LINHA
    " (", nao_encontradas$year, ")",
    "\n   >> Spotify Sugeriu: ", nao_encontradas$spotify_raw_found_artist, " - ", 
    nao_encontradas$spotify_raw_found_name, " (Score: ", round(nao_encontradas$score_final, 2), ")"
  )
} else { "Nenhuma música faltando." }

txt_all <- paste0(
  ifelse(resultado_final$status == "ACEITO", "[OK]      ", "[MISSING]"), " ",
  resultado_final$artist_clean, " - ", resultado_final$track_title, 
  " [Álbum: ", resultado_final$album_title, "]", # <--- ADICIONE ESTA LINHA
  " (", resultado_final$year, ") [", resultado_final$genres, "]"
)

cabecalho_missing <- c("=== RELATÓRIO DE ERROS / REJEIÇÕES ===", paste("Limiar Usado:", LIMIAR_ACEITACAO), paste("Total Rejeitado:", nrow(nao_encontradas)), "", "")
cabecalho_all <- c("", "", "=== COLEÇÃO COMPLETA ===", "")

writeLines(c(cabecalho_missing, txt_missing, cabecalho_all, txt_all), "Minha_Colecao_Final.txt")
message("✅ Arquivo 'Minha_Colecao_Final.txt' gerado!")




# 2. CRIA A PLAYLIST
if(nrow(encontradas) > 0) {
  message("\n💾 Enviando para Spotify...")
  
  # --- CRIA A DATA E HORA FORMATADA ---
  # %d = dia, %m = mês, %Y = ano (4 digitos), %H = hora, %M = minuto
  data_hora <- format(Sys.time(), "%d/%m/%Y às %H:%M")
  descricao_pl <- paste("Coleção sincronizada via R em:", data_hora)
  
  # Pega o ID do usuário (URL OFICIAL CORRIGIDA)
  uid <- content(GET("https://api.spotify.com/v1/me", 
                     add_headers(Authorization = paste("Bearer", access_token))))$id
  
  pl_name <- paste0("Meu Discogs")
  
  # Cria Playlist (ADICIONADO O CAMPO DESCRIPTION)
  # URL OFICIAL CORRIGIDA
  res_pl <- POST(paste0("https://api.spotify.com/v1/users/", uid, "/playlists"), 
                 add_headers(Authorization = paste("Bearer", access_token)), 
                 body = toJSON(list(
                   name = pl_name, 
                   description = descricao_pl,  # <--- AQUI ESTÁ A MÁGICA
                   public = FALSE
                 ), auto_unbox=T))
  
  pid <- content(res_pl)$id
  
  # Adiciona as faixas
  uris <- encontradas$spotify_raw_uri
  chunks <- split(uris, ceiling(seq_along(uris)/100))
  count <- 1
  
  for(c in chunks) {
    # URL OFICIAL CORRIGIDA
    POST(paste0("https://api.spotify.com/v1/playlists/", pid, "/tracks"),
         add_headers(Authorization = paste("Bearer", access_token)), 
         body = toJSON(list(uris=c), auto_unbox=T))
    
    message(paste("Lote", count, "enviado."))
    count <- count+1
    Sys.sleep(0.5)
  }
  message("🎉 Playlist criada com sucesso! Verifique a descrição no Spotify.")
}
