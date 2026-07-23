-- Steam reviews pipeline — DDL des schémas raw (cf. PLAN §5)
-- Idempotent : peut être rejoué sans erreur (IF NOT EXISTS partout).

CREATE SCHEMA IF NOT EXISTS raw;

-- ---------------------------------------------------------------------------
-- Liste des jeux (source IGDB)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.igdb_games (
    igdb_id      BIGINT PRIMARY KEY,
    steam_app_id BIGINT,               -- peut être NULL si pas de lien Steam
    name         TEXT,
    payload      JSONB NOT NULL,
    loaded_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_igdb_games_steam_app_id
    ON raw.igdb_games (steam_app_id);

-- ---------------------------------------------------------------------------
-- Recensement : compte de reviews par jeu (sonde légère quotidienne)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.steam_review_counts (
    app_id             BIGINT PRIMARY KEY,
    total_reviews      BIGINT,
    total_positive     BIGINT,
    total_negative     BIGINT,
    review_score       INT,
    review_score_desc  TEXT,
    checked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    prev_total_reviews BIGINT          -- pour détecter l'activité jour à jour
);

-- ---------------------------------------------------------------------------
-- Reviews brutes : APPEND-ONLY, une ligne par review renvoyée par l'API.
-- Pas de contrainte d'unicité : une review modifiée réapparaît (dédup en dbt).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.steam_reviews (
    recommendation_id  BIGINT NOT NULL,
    app_id             BIGINT NOT NULL,
    payload            JSONB  NOT NULL,   -- la review complète, telle quelle
    timestamp_created  BIGINT,
    timestamp_updated  BIGINT NOT NULL,   -- extrait pour l'incrémental / la dédup
    loaded_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_steam_reviews_rec_ts
    ON raw.steam_reviews (recommendation_id, timestamp_updated DESC);
CREATE INDEX IF NOT EXISTS idx_steam_reviews_app_id
    ON raw.steam_reviews (app_id);
CREATE INDEX IF NOT EXISTS idx_steam_reviews_loaded_at
    ON raw.steam_reviews (loaded_at);

-- ---------------------------------------------------------------------------
-- État de collecte par jeu : cœur de la reprennabilité
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS raw.steam_fetch_state (
    app_id                 BIGINT PRIMARY KEY,
    backfill_status        TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done | failed
    last_cursor            TEXT,          -- dernier cursor Steam (peut expirer, cf. §9)
    max_timestamp_updated  BIGINT,        -- high-water mark pour l'incrémental
    last_success_at        TIMESTAMPTZ,
    last_error             TEXT,
    reviews_fetched        BIGINT DEFAULT 0,
    last_full_check_at     TIMESTAMPTZ,   -- dernier check complet (rattrapage modifs invisibles)
    retry_count            INT NOT NULL DEFAULT 0  -- échecs consécutifs backfill ; seuil -> 'failed'
);
CREATE INDEX IF NOT EXISTS idx_steam_fetch_state_status
    ON raw.steam_fetch_state (backfill_status);

-- Idempotent : ajoute retry_count si la table existait déjà avant cette colonne
-- (CREATE TABLE IF NOT EXISTS ci-dessus est un no-op sur une base déjà initialisée).
ALTER TABLE raw.steam_fetch_state
    ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
