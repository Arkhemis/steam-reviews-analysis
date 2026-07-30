CREATE SCHEMA IF NOT EXISTS raw;

-- ---------------------------------------------------------------------------
-- Liste des jeux (source IGDB)
-- ---------------------------------------------------------------------------
-- Enrichissement issu des dumps genres / involved_companies / companies /
-- covers, en colonnes dédiées (cf. orchestration/assets/igdb.py).
CREATE TABLE IF NOT EXISTS raw.igdb_games (
    igdb_id            BIGINT PRIMARY KEY,
    steam_app_id       BIGINT,         -- peut être NULL si pas de lien Steam
    name               TEXT,
    first_release_date DATE,
    genres             TEXT [],
    developers         TEXT [],
    publishers         TEXT [],
    cover_url          TEXT,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_igdb_games_steam_app_id
    ON raw.igdb_games (steam_app_id);
CREATE INDEX IF NOT EXISTS idx_igdb_games_genres
    ON raw.igdb_games USING GIN (genres);

-- ---------------------------------------------------------------------------
-- Recensement : reviews count par jeu
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.steam_review_counts (
    app_id             BIGINT PRIMARY KEY,
    total_reviews      BIGINT,
    total_positive     BIGINT,
    total_negative     BIGINT,
    review_score       INT,
    review_score_desc  TEXT,
    checked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    prev_total_reviews BIGINT,
    last_backfill_at      TIMESTAMPTZ
);


CREATE TABLE IF NOT EXISTS raw.steam_reviews (
    recommendation_id  BIGINT PRIMARY KEY,
    app_id             BIGINT NOT NULL,
    payload            JSONB  NOT NULL,   -- la review complète, telle quelle
    timestamp_created  BIGINT,
    timestamp_updated  BIGINT NOT NULL,   -- extrait pour l'incrémental / la dédup
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_steam_reviews_app_id
    ON raw.steam_reviews (app_id);
CREATE INDEX IF NOT EXISTS idx_steam_reviews_loaded_at
    ON raw.steam_reviews (loaded_at);
