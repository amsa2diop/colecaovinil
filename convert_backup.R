suppressPackageStartupMessages(library(tidyverse))
setwd("C:/Users/Amsatou Diop/OneDrive - LEME LABORATORIO PARA REDUCAO DA VIOLENC/Pessoal/DJ")

albums <- readRDS("backup_01_albums.rds")
tracks <- readRDS("backup_02_tracks.rds")

cat("Albums:", nrow(albums), "\n")
cat("Tracks:", nrow(tracks), "\n")
cat("Cols albums:", paste(names(albums), collapse=", "), "\n")
cat("Cols tracks:", paste(names(tracks), collapse=", "), "\n")

# Junta campos do album que faltam nas tracks
join_cols <- setdiff(
  intersect(c("cover_url","thumb_url","styles","genres","year","album_title","album_artist"), names(albums)),
  names(tracks)
)
cat("Colunas a juntar:", paste(join_cols, collapse=", "), "\n")

if(length(join_cols) > 0) {
  albums_dedup <- albums %>% distinct(release_id, .keep_all=TRUE)
  tracks <- left_join(tracks, albums_dedup[c("release_id", join_cols)], by="release_id")
}

write.csv(tracks, "backup_tracks.csv", row.names=FALSE, fileEncoding="UTF-8")
cat("Salvo: backup_tracks.csv com", nrow(tracks), "linhas e", ncol(tracks), "colunas\n")
