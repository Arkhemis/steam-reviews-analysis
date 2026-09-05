CREATE SCHEMA IF NOT EXISTS raw;
CREATE EXTENSION IF NOT EXISTS citus;
CREATE EXTENSION IF NOT EXISTS citus_columnar;
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
    last_backfill_at   TIMESTAMPTZ,
    last_seen_timestamp_updated BIGINT
);

-- Migration idempotente : peut être rejouée sur une base déjà initialisée
-- (ce script n'est exécuté automatiquement par Postgres qu'au premier
-- démarrage sur un volume vide, cf. docker-entrypoint-initdb.d).
ALTER TABLE raw.steam_review_counts
    ADD COLUMN IF NOT EXISTS total_reviews_backfilled BIGINT;


CREATE TABLE IF NOT EXISTS raw.steam_reviews (
    recommendation_id  BIGINT NOT NULL,
    app_id             BIGINT NOT NULL,
    payload            JSONB  NOT NULL,
    timestamp_created  BIGINT,
    timestamp_updated  BIGINT NOT NULL,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
) USING columnar; --sauve énormement en stockage

-- ---------------------------------------------------------------------------
-- Annonces Steam par jeu (patch notes, MAJ, actus)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.steam_events (
    -- identifiant du patch/annonce
    gid                TEXT   NOT NULL, 
    app_id             BIGINT NOT NULL,
    payload            JSONB  NOT NULL,
    -- Date de publication : la borne du croisement avec la courbe de reviews.
    rtime32_start_time BIGINT,
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (app_id, gid)
);
