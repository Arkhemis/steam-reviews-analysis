# Game Marts (IGDB enrichment + dbt marts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dbt marts (plus the IGDB metadata they need) that `steam-reviews-website` requires to render its game detail page: game stats/metadata, score-over-time, language distribution, and top reviews.

**Architecture:** Extend the existing `igdb_games` Dagster asset to enrich its JSONB payload with genre/developer/publisher/cover data pulled from four additional IGDB dumps (no DDL change — `raw.igdb_games.payload` is already JSONB). Add two thin dbt staging models (`igdb_game`, `steam_review_count`) alongside the existing `steam_review` staging model, then build four dbt marts on top of staging, following this repo's existing schema-per-folder convention (`staging/`, `marts/`).

**Tech Stack:** Python 3.13, Dagster (asset extension), dbt-core/dbt-postgres 1.9, PostgreSQL, pytest, SQLFluff.

**Out of scope for this plan** (deferred to later plans, per `steam-reviews-website`'s `2026-07-26-visual-design-spike-design.md`):
- A global leaderboard/"rising vs falling" mart across all games — tied to the Home page plan. `game_review_trends` (Task 6) gives per-game monthly trend data that a future leaderboard mart can rank across games, but no cross-game ranking model is built here.
- Any Battle-specific comparison mart — Battle is backlog, not scheduled.
- Sub-national language zones (Québec, Wallonie/Flandre, Romandie/Deutschschweiz) — there is no data source that lets a review be attributed to a region or even a country, only a self-declared Steam `language` field. `game_language_distribution` (Task 7) is therefore language-level only; any country/region display on the map is a static front-end association, not a computed aggregate, and is out of scope here.

## Global Constraints

- Python `3.13.*` (from `pyproject.toml`).
- `dbt-core>=1.9`, `dbt-postgres>=1.9` — no `dbt_utils` or any other dbt package is installed; use only dbt-core built-in generic tests (`unique`, `not_null`, `relationships`). Composite-column uniqueness must use the built-in `unique` test's expression form (e.g. `column_name: "app_id || '-' || period_month"`), not `dbt_utils.unique_combination_of_columns`.
- SQLFluff (`dialect = postgres`): keywords and functions in `UPPERCASE`, identifiers in `snake_case`, 4-space indentation, max line length 140. Run `uv run sqlfluff lint dbt/models/...` before committing SQL.
- dbt materialization defaults to `table` for every model (`dbt_project.yml` top-level `+materialized: table`) — don't override unless a task says so.
- Schema is derived from folder path by the `generate_schema_name` macro: anything under `models/staging/` lands in the `staging` schema, anything under `models/marts/` lands in `marts`.
- Model file names follow the existing convention: **no `stg_`/`mart_` prefix** — the existing staging model for `raw.steam_reviews` is named `steam_review` (singular, no prefix), referenced as `{{ ref('steam_review') }}`. New models must follow the same bare-noun convention.
- IGDB cover image URLs follow the fixed pattern: `https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg` (verified against the live IGDB API).
- This plan lives entirely in `steam-reviews-analysis`. It does not touch `steam-reviews-website` — the site consumes these marts in a later, separate plan.

---

## Context for the implementer

`stg_steam_review` already exists (`dbt/models/staging/steam_review.sql`) and exposes, per review: `recommendation_id`, `app_id`, `language`, `voted_up`, `votes_up`, `weighted_vote_score`, `author_playtime_at_review_minutes`, `primarily_steam_deck`, `refunded`, `review_text`, `created_at`. Full column list: read `dbt/models/staging/steam_review.sql` and `steam_review.yml` if unsure of a column name.

`raw.igdb_games` (declared in `db/init.sql`, NOT yet in `dbt/models/sources.yml`) has columns `igdb_id`, `steam_app_id`, `name`, `payload` (JSONB), `loaded_at`. Today `payload` only contains `{id, name, slug, steam_app_id}` — this plan enriches it.

`raw.steam_review_counts` (already declared in `dbt/models/sources.yml`) has columns `app_id`, `total_reviews`, `total_positive`, `total_negative`, `review_score`, `review_score_desc`, `checked_at`, `prev_total_reviews`, `last_backfill_at`. No staging model exists yet for it.

The IGDB ingestion asset (`orchestration/assets/igdb.py`) currently downloads two dumps via `igdb.download_dump(endpoint, tmp_dir)`: `external_games` (to map `igdb_id -> steam_app_id`) and `games` (name/slug, upserted into `raw.igdb_games`). This plan adds four more dumps. Their real CSV schemas (verified live against the IGDB API on 2026-07-26):

- **`games.csv`** (relevant columns among many): `id`, `name`, `slug`, `cover` (single LONG id, e.g. `467132`, empty string if none), `genres` (Postgres array literal, e.g. `{12,15,16}`, `{}` if none), `involved_companies` (Postgres array literal, same format), `first_release_date` (already a formatted timestamp string like `2014-01-12 00:00:00`, empty string if unknown).
- **`genres.csv`**: `id,name,created_at,updated_at,slug,url,checksum`.
- **`involved_companies.csv`**: `id,created_at,updated_at,game,company,publisher,developer,supporting,porting,checksum` — booleans are the strings `t`/`f` (Postgres COPY format), not `true`/`false`.
- **`companies.csv`**: `id,name,...` (many other columns, only `id`/`name` are needed here).
- **`covers.csv`**: `id,url,image_id,width,height,alpha_channel,animated,game,checksum,game_localization,image_type` — `game` is the game's id, `image_id` is the string used to build the cover URL.

---

### Task 1: IGDB enrichment lookup helpers (pure functions)

**Files:**
- Create: `orchestration/assets/igdb_lookups.py`
- Test: `tests/assets/test_igdb_lookups.py`

**Interfaces:**
- Produces:
  - `parse_pg_array(raw: str | None) -> list[int]`
  - `load_genre_names(path: Path) -> dict[int, str]`
  - `load_company_names(path: Path) -> dict[int, str]`
  - `load_involved_companies(path: Path) -> dict[int, tuple[int, bool, bool]]` (maps `involved_company.id -> (company_id, is_developer, is_publisher)`)
  - `load_cover_image_ids(path: Path) -> dict[int, str]` (maps `game.id -> image_id`)
  - `enrich_game(genre_ids: list[int], involved_company_ids: list[int], cover_id: int | None, genre_names: dict[int, str], involved_companies: dict[int, tuple[int, bool, bool]], company_names: dict[int, str], cover_image_ids: dict[int, str]) -> dict` returning `{"genres": list[str], "developers": list[str], "publishers": list[str], "cover_url": str | None}`

This repo has no `tests/` directory yet — create it as part of this task (no `__init__.py` needed; `pyproject.toml` already sets `testpaths = ["tests"]`).

- [ ] **Step 1: Write the failing tests**

Create `tests/assets/test_igdb_lookups.py`:

```python
from orchestration.assets.igdb_lookups import (
    enrich_game,
    load_company_names,
    load_cover_image_ids,
    load_genre_names,
    load_involved_companies,
    parse_pg_array,
)


def test_parse_pg_array_parses_values():
    assert parse_pg_array("{12,15,16}") == [12, 15, 16]


def test_parse_pg_array_handles_empty_braces():
    assert parse_pg_array("{}") == []


def test_parse_pg_array_handles_none_and_empty_string():
    assert parse_pg_array(None) == []
    assert parse_pg_array("") == []


def test_load_genre_names(tmp_path):
    csv_path = tmp_path / "genres.csv"
    csv_path.write_text(
        "id,name,created_at,updated_at,slug,url,checksum\n"
        "12,Role-playing (RPG),,,,,\n"
        "15,Strategy,,,,,\n"
    )

    assert load_genre_names(csv_path) == {12: "Role-playing (RPG)", 15: "Strategy"}


def test_load_company_names(tmp_path):
    csv_path = tmp_path / "companies.csv"
    csv_path.write_text("id,name\n510,Larian Studios\n")

    assert load_company_names(csv_path) == {510: "Larian Studios"}


def test_load_involved_companies(tmp_path):
    csv_path = tmp_path / "involved_companies.csv"
    csv_path.write_text(
        "id,created_at,updated_at,game,company,publisher,developer,supporting,porting,checksum\n"
        "334788,,,119171,510,t,t,f,f,\n"
        "214383,,,119171,47197,f,f,f,f,\n"
    )

    result = load_involved_companies(csv_path)

    assert result[334788] == (510, True, True)
    assert result[214383] == (47197, False, False)


def test_load_cover_image_ids(tmp_path):
    csv_path = tmp_path / "covers.csv"
    csv_path.write_text(
        "id,url,image_id,width,height,alpha_channel,animated,game,checksum,game_localization,image_type\n"
        "289025,,co670h,,,,,119171,,,\n"
    )

    assert load_cover_image_ids(csv_path) == {119171: "co670h"}


def test_enrich_game_builds_genres_developers_publishers_and_cover_url():
    result = enrich_game(
        genre_ids=[12, 15],
        involved_company_ids=[334788, 214383],
        cover_id=289025,
        genre_names={12: "Role-playing (RPG)", 15: "Strategy"},
        involved_companies={
            334788: (510, True, True),
            214383: (47197, False, False),
        },
        company_names={510: "Larian Studios", 47197: "Wushu Studios"},
        cover_image_ids={289025: "co670h"},
    )

    assert result == {
        "genres": ["Role-playing (RPG)", "Strategy"],
        "developers": ["Larian Studios"],
        "publishers": ["Larian Studios"],
        "cover_url": "https://images.igdb.com/igdb/image/upload/t_cover_big/co670h.jpg",
    }


def test_enrich_game_handles_missing_cover():
    result = enrich_game(
        genre_ids=[],
        involved_company_ids=[],
        cover_id=None,
        genre_names={},
        involved_companies={},
        company_names={},
        cover_image_ids={},
    )

    assert result == {
        "genres": [],
        "developers": [],
        "publishers": [],
        "cover_url": None,
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/assets/test_igdb_lookups.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'orchestration.assets.igdb_lookups'`

- [ ] **Step 3: Write the minimal implementation**

Create `orchestration/assets/igdb_lookups.py`:

```python
"""Pure parsing/lookup helpers for enriching IGDB games (genres, developers, publishers, cover)."""

import csv
from pathlib import Path


def parse_pg_array(raw: str | None) -> list[int]:
    """Parse a Postgres array literal (e.g. '{12,15,16}') into a list of ints."""
    if not raw or raw == "{}":
        return []
    return [int(value) for value in raw.strip("{}").split(",") if value]


def load_genre_names(path: Path) -> dict[int, str]:
    """Map genre id -> genre name from a `genres` IGDB dump."""
    names: dict[int, str] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            names[int(row["id"])] = row["name"]
    return names


def load_company_names(path: Path) -> dict[int, str]:
    """Map company id -> company name from a `companies` IGDB dump."""
    names: dict[int, str] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            names[int(row["id"])] = row["name"]
    return names


def load_involved_companies(path: Path) -> dict[int, tuple[int, bool, bool]]:
    """Map involved_company id -> (company_id, is_developer, is_publisher)."""
    result: dict[int, tuple[int, bool, bool]] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            result[int(row["id"])] = (
                int(row["company"]),
                row["developer"] == "t",
                row["publisher"] == "t",
            )
    return result


def load_cover_image_ids(path: Path) -> dict[int, str]:
    """Map game id -> cover image_id from a `covers` IGDB dump."""
    result: dict[int, str] = {}
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            game_id = row.get("game")
            image_id = row.get("image_id")
            if game_id and image_id:
                result[int(game_id)] = image_id
    return result


def enrich_game(
    genre_ids: list[int],
    involved_company_ids: list[int],
    cover_id: int | None,
    genre_names: dict[int, str],
    involved_companies: dict[int, tuple[int, bool, bool]],
    company_names: dict[int, str],
    cover_image_ids: dict[int, str],
) -> dict:
    """Build the {genres, developers, publishers, cover_url} enrichment for one game."""
    genres = [genre_names[gid] for gid in genre_ids if gid in genre_names]

    developers: list[str] = []
    publishers: list[str] = []
    for involved_id in involved_company_ids:
        involved = involved_companies.get(involved_id)
        if involved is None:
            continue
        company_id, is_developer, is_publisher = involved
        company_name = company_names.get(company_id)
        if company_name is None:
            continue
        if is_developer:
            developers.append(company_name)
        if is_publisher:
            publishers.append(company_name)

    cover_url = None
    if cover_id is not None:
        image_id = cover_image_ids.get(cover_id)
        if image_id:
            cover_url = f"https://images.igdb.com/igdb/image/upload/t_cover_big/{image_id}.jpg"

    return {
        "genres": genres,
        "developers": developers,
        "publishers": publishers,
        "cover_url": cover_url,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/assets/test_igdb_lookups.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check orchestration/assets/igdb_lookups.py tests/assets/test_igdb_lookups.py
git add orchestration/assets/igdb_lookups.py tests/assets/test_igdb_lookups.py
git commit -m "feat: add IGDB enrichment lookup helpers (genres, developers, publishers, cover)"
```

---

### Task 2: Wire enrichment into the `igdb_games` asset

**Files:**
- Modify: `orchestration/assets/igdb.py`

**Interfaces:**
- Consumes: all functions from Task 1 (`orchestration/assets/igdb_lookups.py`).
- Produces: `raw.igdb_games.payload` now additionally contains `genres: list[str]`, `developers: list[str]`, `publishers: list[str]`, `cover_url: str | None`, `first_release_date: str | None` (ISO-ish `"YYYY-MM-DD HH:MM:SS"` string or `None`).

No DDL change is needed — `payload` is already `JSONB`.

- [ ] **Step 1: Download the four extra dumps and build lookups**

In `orchestration/assets/igdb.py`, inside the `igdb_games` asset function, after the existing `external_path = igdb.download_dump("external_games", tmp_dir)` line and before downloading `games`, add:

```python
        genres_path = igdb.download_dump("genres", tmp_dir)
        genre_names = load_genre_names(genres_path)

        companies_path = igdb.download_dump("companies", tmp_dir)
        company_names = load_company_names(companies_path)

        involved_companies_path = igdb.download_dump("involved_companies", tmp_dir)
        involved_companies = load_involved_companies(involved_companies_path)

        covers_path = igdb.download_dump("covers", tmp_dir)
        cover_image_ids = load_cover_image_ids(covers_path)
```

Add the import at the top of the file:

```python
from orchestration.assets.igdb_lookups import (
    enrich_game,
    load_company_names,
    load_cover_image_ids,
    load_genre_names,
    load_involved_companies,
    parse_pg_array,
)
```

- [ ] **Step 2: Enrich each game's payload in the existing loop**

Replace the existing payload-building block:

```python
                payload = {
                    "id": igdb_id,
                    "name": row.get("name"),
                    "slug": row.get("slug"),
                    "steam_app_id": steam_app_id,
                }
```

with:

```python
                cover_raw = row.get("cover")
                enrichment = enrich_game(
                    genre_ids=parse_pg_array(row.get("genres")),
                    involved_company_ids=parse_pg_array(row.get("involved_companies")),
                    cover_id=int(cover_raw) if cover_raw else None,
                    genre_names=genre_names,
                    involved_companies=involved_companies,
                    company_names=company_names,
                    cover_image_ids=cover_image_ids,
                )

                payload = {
                    "id": igdb_id,
                    "name": row.get("name"),
                    "slug": row.get("slug"),
                    "steam_app_id": steam_app_id,
                    "first_release_date": row.get("first_release_date") or None,
                    **enrichment,
                }
```

- [ ] **Step 3: Manually verify against the live pipeline**

This step touches live IGDB API + Postgres and can't run as a pytest unit test. Verify with:

```bash
uv run dg dev
```

In the Dagster UI, materialize the `igdb_games` asset. Once it completes, check the enrichment landed:

```bash
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "SELECT payload FROM raw.igdb_games WHERE steam_app_id = 1086940;"
```

Expected: the `payload` JSON for Baldur's Gate 3 (`steam_app_id = 1086940`) includes non-empty `genres`, `developers` (containing `"Larian Studios"`), `publishers`, and a `cover_url` starting with `https://images.igdb.com/igdb/image/upload/`.

- [ ] **Step 4: Lint and commit**

```bash
uv run ruff check orchestration/assets/igdb.py
git add orchestration/assets/igdb.py
git commit -m "feat: enrich igdb_games payload with genres, developers, publishers, cover"
```

---

### Task 3: `igdb_games` dbt source + `igdb_game` staging model

**Files:**
- Modify: `dbt/models/sources.yml`
- Create: `dbt/models/staging/igdb_game.sql`
- Create: `dbt/models/staging/igdb_game.yml`

**Interfaces:**
- Consumes: `raw.igdb_games` (via new `source('raw', 'igdb_games')`).
- Produces: dbt model `igdb_game` (schema `staging`), columns: `igdb_id`, `steam_app_id`, `name`, `genres` (`text[]`), `developers` (`text[]`), `publishers` (`text[]`), `cover_url`, `first_release_date` (`timestamp`), `loaded_at`.

- [ ] **Step 1: Declare the source**

Add to `dbt/models/sources.yml`, inside the existing `raw` source's `tables:` list (alongside `steam_review_counts` and `steam_reviews`):

```yaml
      - name: igdb_games
        description: Jeux IGDB liés à un app_id Steam, avec métadonnées enrichies (genres, studios, cover) dans le payload JSON.
        columns:
          - name: igdb_id
            description: Identifiant IGDB du jeu (clé primaire).
            data_tests:
              - unique
              - not_null
          - name: steam_app_id
            description: Identifiant de l'application Steam liée.
            data_tests:
              - not_null
          - name: payload
            description: Payload JSON enrichi (nom, genres, développeurs, éditeurs, cover, date de sortie).
          - name: loaded_at
            description: Horodatage de chargement par Dagster.
```

- [ ] **Step 2: Run dbt to verify the source tests pass on their own**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select source:raw.igdb_games`
Expected: PASS — the `unique`/`not_null` tests on `igdb_id`/`steam_app_id` run against `raw.igdb_games` directly and pass. No `igdb_game` model exists yet at this point.

- [ ] **Step 3: Write the staging model**

Create `dbt/models/staging/igdb_game.sql`:

```sql
WITH source AS (

    SELECT
        igdb_id,
        steam_app_id,
        payload,
        loaded_at
    FROM {{ source('raw', 'igdb_games') }}

),

renamed AS (

    SELECT
        igdb_id,
        steam_app_id,

        payload ->> 'name' AS name,
        ARRAY(SELECT jsonb_array_elements_text(payload -> 'genres')) AS genres,
        ARRAY(SELECT jsonb_array_elements_text(payload -> 'developers')) AS developers,
        ARRAY(SELECT jsonb_array_elements_text(payload -> 'publishers')) AS publishers,
        payload ->> 'cover_url' AS cover_url,
        (payload ->> 'first_release_date')::TIMESTAMP AS first_release_date,

        loaded_at

    FROM source

)

SELECT * FROM renamed
```

Create `dbt/models/staging/igdb_game.yml`:

```yaml
version: 2

models:
  - name: igdb_game
    description: Jeux IGDB aplatis à partir du payload JSON enrichi (une ligne par jeu lié à Steam).
    columns:
      - name: igdb_id
        description: Identifiant IGDB du jeu.
        data_tests:
          - unique
          - not_null

      - name: steam_app_id
        description: Identifiant de l'application Steam liée.
        data_tests:
          - unique
          - not_null

      - name: name
        description: Nom du jeu.

      - name: genres
        description: Genres du jeu (noms IGDB).

      - name: developers
        description: Studios développeurs (companies IGDB marquées developer=true).

      - name: publishers
        description: Éditeurs (companies IGDB marquées publisher=true).

      - name: cover_url
        description: URL de la jaquette du jeu (CDN IGDB).

      - name: first_release_date
        description: Date de première sortie du jeu.

      - name: loaded_at
        description: Horodatage de chargement de la fiche IGDB par Dagster.
```

- [ ] **Step 4: Run dbt to verify it fails before the model file exists**

Temporarily rename `igdb_game.sql` (e.g. append `.tmp`), run:
Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select igdb_game`
Expected: FAIL — `Patch target not found... 'igdb_game'` (the yml declares tests for a model dbt can't find). Restore the file name.

- [ ] **Step 5: Run dbt to verify the model builds and tests pass**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select igdb_game`
Expected: PASS — model builds in schema `staging`, all `unique`/`not_null` tests pass.

- [ ] **Step 6: Lint and commit**

```bash
uv run sqlfluff lint dbt/models/staging/igdb_game.sql
git add dbt/models/sources.yml dbt/models/staging/igdb_game.sql dbt/models/staging/igdb_game.yml
git commit -m "feat: add igdb_games source and igdb_game staging model"
```

---

### Task 4: `steam_review_count` staging model

**Files:**
- Create: `dbt/models/staging/steam_review_count.sql`
- Create: `dbt/models/staging/steam_review_count.yml`

**Interfaces:**
- Consumes: `source('raw', 'steam_review_counts')` (already declared in `sources.yml`).
- Produces: dbt model `steam_review_count` (schema `staging`), columns: `app_id`, `total_reviews`, `total_positive`, `total_negative`, `review_score`, `review_score_desc`, `checked_at`.

- [ ] **Step 1: Write the staging model**

Create `dbt/models/staging/steam_review_count.sql`:

```sql
WITH source AS (

    SELECT
        app_id,
        total_reviews,
        total_positive,
        total_negative,
        review_score,
        review_score_desc,
        checked_at
    FROM {{ source('raw', 'steam_review_counts') }}

)

SELECT * FROM source
```

Create `dbt/models/staging/steam_review_count.yml`:

```yaml
version: 2

models:
  - name: steam_review_count
    description: Compteurs de reviews par jeu, tels que recensés par Steam (source officielle du score).
    columns:
      - name: app_id
        description: Identifiant de l'application Steam (clé primaire).
        data_tests:
          - unique
          - not_null

      - name: total_reviews
        description: Nombre total de reviews.

      - name: total_positive
        description: Nombre de reviews positives.

      - name: total_negative
        description: Nombre de reviews négatives.

      - name: review_score
        description: Score de review Steam (0-9).

      - name: review_score_desc
        description: Libellé du score de review.

      - name: checked_at
        description: Horodatage du dernier recensement.
```

- [ ] **Step 2: Run dbt to verify it fails before the model file exists**

Temporarily rename `steam_review_count.sql` (e.g. append `.tmp`), run:
Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select steam_review_count`
Expected: FAIL — `Patch target not found... 'steam_review_count'`. Restore the file name.

- [ ] **Step 3: Run dbt to verify the model builds and tests pass**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select steam_review_count`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
uv run sqlfluff lint dbt/models/staging/steam_review_count.sql
git add dbt/models/staging/steam_review_count.sql dbt/models/staging/steam_review_count.yml
git commit -m "feat: add steam_review_count staging model"
```

---

### Task 5: `game_stats` mart

**Files:**
- Create: `dbt/models/marts/game_stats.sql`
- Create: `dbt/models/marts/game_stats.yml`

**Interfaces:**
- Consumes: `ref('steam_review_count')` (Task 4), `ref('igdb_game')` (Task 3), `ref('steam_review')` (existing).
- Produces: dbt model `game_stats` (schema `marts`), grain = one row per `app_id`. Columns: `app_id`, `name`, `genres`, `developers`, `publishers`, `cover_url`, `first_release_date`, `total_reviews`, `total_positive`, `total_negative`, `review_score`, `review_score_desc`, `pct_positive`, `collected_review_count`, `playtime_median_minutes`, `pct_steam_deck`, `pct_refunded`.

- [ ] **Step 1: Write the model**

Create `dbt/models/marts/game_stats.sql`:

```sql
WITH review_agg AS (

    SELECT
        app_id,
        COUNT(*) AS collected_review_count,
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY author_playtime_at_review_minutes) AS playtime_median_minutes,
        AVG(primarily_steam_deck::INT) AS pct_steam_deck,
        AVG(refunded::INT) AS pct_refunded
    FROM {{ ref('steam_review') }}
    GROUP BY app_id

),

joined AS (

    SELECT
        counts.app_id,
        game.name,
        game.genres,
        game.developers,
        game.publishers,
        game.cover_url,
        game.first_release_date,

        counts.total_reviews,
        counts.total_positive,
        counts.total_negative,
        counts.review_score,
        counts.review_score_desc,
        CASE
            WHEN counts.total_reviews > 0
                THEN counts.total_positive::NUMERIC / counts.total_reviews
        END AS pct_positive,

        review_agg.collected_review_count,
        review_agg.playtime_median_minutes,
        review_agg.pct_steam_deck,
        review_agg.pct_refunded

    FROM {{ ref('steam_review_count') }} AS counts
    LEFT JOIN {{ ref('igdb_game') }} AS game
        ON counts.app_id = game.steam_app_id
    LEFT JOIN review_agg
        ON counts.app_id = review_agg.app_id

)

SELECT * FROM joined
```

Create `dbt/models/marts/game_stats.yml`:

```yaml
version: 2

models:
  - name: game_stats
    description: Statistiques et métadonnées agrégées par jeu (une ligne par app_id) — alimente la fiche jeu.
    columns:
      - name: app_id
        description: Identifiant de l'application Steam (clé primaire).
        data_tests:
          - unique
          - not_null

      - name: name
        description: Nom du jeu (IGDB).

      - name: genres
        description: Genres du jeu.

      - name: developers
        description: Studios développeurs.

      - name: publishers
        description: Éditeurs.

      - name: cover_url
        description: URL de la jaquette.

      - name: first_release_date
        description: Date de première sortie.

      - name: total_reviews
        description: Nombre total de reviews (recensement Steam officiel).

      - name: total_positive
        description: Nombre de reviews positives (recensement Steam officiel).

      - name: total_negative
        description: Nombre de reviews négatives (recensement Steam officiel).

      - name: review_score
        description: Score de review Steam (0-9).

      - name: review_score_desc
        description: Libellé du score de review.

      - name: pct_positive
        description: Pourcentage de reviews positives (total_positive / total_reviews).

      - name: collected_review_count
        description: Nombre de reviews individuelles collectées (peut différer de total_reviews si le backfill est partiel).

      - name: playtime_median_minutes
        description: Playtime médian au moment de la review, en minutes, sur les reviews collectées.

      - name: pct_steam_deck
        description: Proportion des reviews collectées jouées principalement sur Steam Deck.

      - name: pct_refunded
        description: Proportion des reviews collectées dont l'achat a été remboursé.
```

- [ ] **Step 2: Run dbt to verify it fails before the model exists**

Temporarily rename `game_stats.sql` (e.g. append `.tmp`), run:
Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_stats`
Expected: FAIL — `Patch target not found... 'game_stats'`. Restore the file name.

- [ ] **Step 3: Run dbt to verify the model builds and tests pass**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_stats+`
Expected: PASS — builds on top of `steam_review_count`, `igdb_game`, `steam_review`; `unique`/`not_null` tests on `app_id` pass.

- [ ] **Step 4: Lint and commit**

```bash
uv run sqlfluff lint dbt/models/marts/game_stats.sql
git add dbt/models/marts/game_stats.sql dbt/models/marts/game_stats.yml
git commit -m "feat: add game_stats mart"
```

---

### Task 6: `game_review_trends` mart

**Files:**
- Create: `dbt/models/marts/game_review_trends.sql`
- Create: `dbt/models/marts/game_review_trends.yml`

**Interfaces:**
- Consumes: `ref('steam_review')`.
- Produces: dbt model `game_review_trends` (schema `marts`), grain = one row per `(app_id, period_month)`. Columns: `app_id`, `period_month`, `reviews_in_period`, `positive_in_period`, `pct_positive_period`.

- [ ] **Step 1: Write the model**

Create `dbt/models/marts/game_review_trends.sql`:

```sql
WITH monthly AS (

    SELECT
        app_id,
        DATE_TRUNC('month', created_at) AS period_month,
        COUNT(*) AS reviews_in_period,
        SUM(voted_up::INT) AS positive_in_period
    FROM {{ ref('steam_review') }}
    GROUP BY app_id, DATE_TRUNC('month', created_at)

)

SELECT
    app_id,
    period_month,
    reviews_in_period,
    positive_in_period,
    positive_in_period::NUMERIC / NULLIF(reviews_in_period, 0) AS pct_positive_period
FROM monthly
```

Create `dbt/models/marts/game_review_trends.yml`:

```yaml
version: 2

models:
  - name: game_review_trends
    description: Évolution mensuelle du volume et du taux de reviews positives par jeu — alimente le graphique d'évolution du score.
    columns:
      - name: app_id
        description: Identifiant de l'application Steam.
        data_tests:
          - not_null

      - name: period_month
        description: Premier jour du mois concerné.
        data_tests:
          - not_null

      - name: reviews_in_period
        description: Nombre de reviews créées ce mois-ci.

      - name: positive_in_period
        description: Nombre de reviews positives créées ce mois-ci.

      - name: pct_positive_period
        description: Taux de reviews positives sur le mois.

      - name: app_id_period_month
        description: Combinaison (app_id, period_month) — vérifie que la grain du mart est unique.
        data_tests:
          - unique:
              column_name: "app_id || '-' || period_month"
```

- [ ] **Step 2: Run dbt to verify it fails before the model exists**

Temporarily rename `game_review_trends.sql` (append `.tmp`), run:
Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_review_trends`
Expected: FAIL — `Patch target not found... 'game_review_trends'`. Restore the file name.

- [ ] **Step 3: Run dbt to verify the model builds and tests pass**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_review_trends`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
uv run sqlfluff lint dbt/models/marts/game_review_trends.sql
git add dbt/models/marts/game_review_trends.sql dbt/models/marts/game_review_trends.yml
git commit -m "feat: add game_review_trends mart"
```

---

### Task 7: `game_language_distribution` mart

**Files:**
- Create: `dbt/models/marts/game_language_distribution.sql`
- Create: `dbt/models/marts/game_language_distribution.yml`

**Interfaces:**
- Consumes: `ref('steam_review')`.
- Produces: dbt model `game_language_distribution` (schema `marts`), grain = one row per `(app_id, language)`. Columns: `app_id`, `language`, `review_count`, `pct_of_total`.

- [ ] **Step 1: Write the model**

Create `dbt/models/marts/game_language_distribution.sql`:

```sql
WITH by_language AS (

    SELECT
        app_id,
        language,
        COUNT(*) AS review_count
    FROM {{ ref('steam_review') }}
    WHERE language IS NOT NULL
    GROUP BY app_id, language

)

SELECT
    app_id,
    language,
    review_count,
    review_count::NUMERIC / SUM(review_count) OVER (PARTITION BY app_id) AS pct_of_total
FROM by_language
```

Create `dbt/models/marts/game_language_distribution.yml`:

```yaml
version: 2

models:
  - name: game_language_distribution
    description: >
      Répartition des reviews par langue déclarée, par jeu et globalement (agréger sans filtrer sur app_id
      côté consommateur pour la vue globale). Langue = champ auto-déclaré par le reviewer, pas une
      géolocalisation réelle.
    columns:
      - name: app_id
        description: Identifiant de l'application Steam.
        data_tests:
          - not_null

      - name: language
        description: Langue déclarée de la review (code langue Steam).
        data_tests:
          - not_null

      - name: review_count
        description: Nombre de reviews dans cette langue pour ce jeu.

      - name: pct_of_total
        description: Proportion des reviews de ce jeu dans cette langue.

      - name: app_id_language
        description: Combinaison (app_id, language) — vérifie que la grain du mart est unique.
        data_tests:
          - unique:
              column_name: "app_id || '-' || language"
```

- [ ] **Step 2: Run dbt to verify it fails before the model exists**

Temporarily rename `game_language_distribution.sql` (append `.tmp`), run:
Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_language_distribution`
Expected: FAIL — `Patch target not found... 'game_language_distribution'`. Restore the file name.

- [ ] **Step 3: Run dbt to verify the model builds and tests pass**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_language_distribution`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
uv run sqlfluff lint dbt/models/marts/game_language_distribution.sql
git add dbt/models/marts/game_language_distribution.sql dbt/models/marts/game_language_distribution.yml
git commit -m "feat: add game_language_distribution mart"
```

---

### Task 8: `game_top_reviews` mart

**Files:**
- Create: `dbt/models/marts/game_top_reviews.sql`
- Create: `dbt/models/marts/game_top_reviews.yml`

**Interfaces:**
- Consumes: `ref('steam_review')`.
- Produces: dbt model `game_top_reviews` (schema `marts`), grain = one row per `recommendation_id`, limited to the top 5 best-voted reviews per `(app_id, voted_up)`. Columns: `recommendation_id`, `app_id`, `review_text`, `language`, `voted_up`, `votes_up`, `weighted_vote_score`, `author_playtime_at_review_minutes`, `rank_in_game`.

- [ ] **Step 1: Write the model**

Create `dbt/models/marts/game_top_reviews.sql`:

```sql
WITH ranked AS (

    SELECT
        recommendation_id,
        app_id,
        review_text,
        language,
        voted_up,
        votes_up,
        weighted_vote_score,
        author_playtime_at_review_minutes,
        ROW_NUMBER() OVER (
            PARTITION BY app_id, voted_up
            ORDER BY weighted_vote_score DESC, votes_up DESC
        ) AS rank_in_game
    FROM {{ ref('steam_review') }}
    WHERE review_text IS NOT NULL AND review_text != ''

)

SELECT
    recommendation_id,
    app_id,
    review_text,
    language,
    voted_up,
    votes_up,
    weighted_vote_score,
    author_playtime_at_review_minutes,
    rank_in_game
FROM ranked
WHERE rank_in_game <= 5
```

Create `dbt/models/marts/game_top_reviews.yml`:

```yaml
version: 2

models:
  - name: game_top_reviews
    description: Top 5 des reviews les mieux votées (positives et négatives séparément) par jeu — alimente la section "reviews notables" de la fiche jeu.
    columns:
      - name: recommendation_id
        description: Identifiant unique de la review.
        data_tests:
          - unique
          - not_null

      - name: app_id
        description: Identifiant de l'application Steam.
        data_tests:
          - not_null

      - name: review_text
        description: Texte de la review.

      - name: language
        description: Langue déclarée de la review.

      - name: voted_up
        description: Vrai si la review est positive.

      - name: votes_up
        description: Nombre de votes "utile" reçus.

      - name: weighted_vote_score
        description: Score de pertinence pondéré Steam.

      - name: author_playtime_at_review_minutes
        description: Playtime de l'auteur au moment de la review, en minutes.

      - name: rank_in_game
        description: Rang de la review au sein de son jeu et de son camp (positif/négatif), 1 = la mieux votée.
```

- [ ] **Step 2: Run dbt to verify it fails before the model exists**

Temporarily rename `game_top_reviews.sql` (append `.tmp`), run:
Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_top_reviews`
Expected: FAIL — `Patch target not found... 'game_top_reviews'`. Restore the file name.

- [ ] **Step 3: Run dbt to verify the model builds and tests pass**

Run: `uv run dbt build --project-dir dbt --profiles-dir dbt --select game_top_reviews`
Expected: PASS.

- [ ] **Step 4: Lint and commit**

```bash
uv run sqlfluff lint dbt/models/marts/game_top_reviews.sql
git add dbt/models/marts/game_top_reviews.sql dbt/models/marts/game_top_reviews.yml
git commit -m "feat: add game_top_reviews mart"
```

---

### Task 9: Update README (marts landed)

**Files:**
- Modify: `README.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Update the Progress checklist and pipeline diagram**

In `README.md`, change:

```markdown
- [ ] dbt marts (actionable metrics) — **in progress**
```

to:

```markdown
- [x] dbt marts (actionable metrics): `game_stats`, `game_review_trends`, `game_language_distribution`, `game_top_reviews`
```

And update the mermaid diagram line:

```mermaid
    STG -.mart in progress.-> MART[(marts)]
```

to:

```mermaid
    STG --> MART[(marts: game_stats, game_review_trends,\ngame_language_distribution, game_top_reviews)]
```

Also update the pipeline step 5 text:

```markdown
5. **dbt (marts)** — in progress.
```

to:

```markdown
5. **dbt (marts)** — `game_stats`, `game_review_trends`, `game_language_distribution`, `game_top_reviews`, built on `steam_review`, `igdb_game`, and `steam_review_count`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: mark dbt marts as landed in README"
```
