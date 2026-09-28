-- DDL de raw, joué par l'image au premier démarrage (volume vide).
-- Les tables ReplacingMergeTree ne dédupliquent qu'à la fusion : lire avec
-- final = 1 (réglage de session de dbt et du site).
CREATE DATABASE IF NOT EXISTS raw;

-- ---------------------------------------------------------------------------
-- Liste des jeux (source IGDB)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.igdb_games (
    igdb_id            UInt64,
    -- NULL si pas de lien Steam
    steam_app_id       Nullable(UInt32),
    name               Nullable(String),
    first_release_date Nullable(Date32),
    genres             Array(String),
    developers         Array(String),
    publishers         Array(String),
    cover_url          Nullable(String),
    loaded_at          DateTime64(6, 'UTC') DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY igdb_id;

-- ---------------------------------------------------------------------------
-- Recensement : reviews count par jeu
-- ---------------------------------------------------------------------------
-- Table d'état, modifiée par UPDATE légers. Une ligne par app_id : le
-- recensement n'insère que les absents, un test dbt vérifie l'unicité.
-- steam_count est le compteur GetItems du jour, synced_steam_count sa valeur à
-- la dernière synchronisation des reviews. Tant qu'ils diffèrent, le jeu a bougé.
CREATE TABLE IF NOT EXISTS raw.steam_review_counts (
    app_id                      UInt32,
    total_reviews               Nullable(Int64),
    total_positive              Nullable(Int64),
    total_negative              Nullable(Int64),
    review_score                Nullable(Int32),
    review_score_desc           Nullable(String),
    checked_at                  DateTime64(6, 'UTC') DEFAULT now64(6),
    prev_total_reviews          Nullable(Int64),
    last_backfill_at            Nullable(DateTime64(6, 'UTC')),
    last_seen_timestamp_updated Nullable(Int64),
    total_reviews_backfilled    Nullable(Int64),
    steam_count                 Nullable(Int64),
    synced_steam_count          Nullable(Int64),
    steam_count_checked_at      Nullable(DateTime64(6, 'UTC'))
) ENGINE = MergeTree
ORDER BY app_id
SETTINGS enable_block_number_column = 1, enable_block_offset_column = 1;

-- ---------------------------------------------------------------------------
-- Reviews, toutes versions
-- ---------------------------------------------------------------------------
-- Une même version capturée deux fois le même mois fusionne. La partition par
-- mois de chargement borne la lecture incrémentale aux partitions récentes.
CREATE TABLE IF NOT EXISTS raw.steam_reviews (
    recommendation_id UInt64,
    app_id            UInt32,
    payload           JSON,
    timestamp_created Int64 CODEC(Delta, ZSTD),
    timestamp_updated Int64 CODEC(Delta, ZSTD),
    loaded_at         DateTime64(6, 'UTC') DEFAULT now64(6) CODEC(Delta, ZSTD)
) ENGINE = ReplacingMergeTree(loaded_at)
PARTITION BY toYYYYMM(loaded_at)
ORDER BY (app_id, recommendation_id, timestamp_updated);

-- ---------------------------------------------------------------------------
-- Annonces Steam par jeu (patch notes, MAJ, actus)
-- ---------------------------------------------------------------------------
-- payload en String : le corps des annonces domine, JSON n'y gagnerait rien.
-- payload_hash (calculé par le chargeur) repère les annonces modifiées.
CREATE TABLE IF NOT EXISTS raw.steam_events (
    gid                String,
    app_id             UInt32,
    payload            String CODEC(ZSTD(3)),
    payload_hash       UInt64,
    -- Date de publication : la borne du croisement avec la courbe de reviews.
    rtime32_start_time Nullable(Int64),
    loaded_at          DateTime64(6, 'UTC') DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY (app_id, gid);

-- ---------------------------------------------------------------------------
-- Fiches store Steam par jeu (type, DLC parent, early access, dates)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.steam_game_details (
    app_id    UInt32,
    -- Item brut de IStoreBrowseService/GetItems, apps retirées comprises.
    payload   String CODEC(ZSTD(3)),
    loaded_at DateTime64(6, 'UTC') DEFAULT now64(6)
) ENGINE = ReplacingMergeTree(loaded_at)
ORDER BY app_id;
