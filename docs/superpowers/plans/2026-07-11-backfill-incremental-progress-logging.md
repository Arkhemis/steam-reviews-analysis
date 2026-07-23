# Backfill/Incremental Progress Logging & Parallelization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add progress logging to `steam_reviews_backfill_job` and `steam_reviews_incremental_job`, parallelize both (currently strictly sequential, one game at a time), and make the backfill job loop internally until its queue is empty instead of processing a single bounded batch per run.

**Architecture:** Both ops keep their existing per-game pagination helpers (`_backfill_one_game`, `_incremental_one_game`) but delegate orchestration to a new plain (non-Dagster-decorated) function — `_run_backfill` / `_run_incremental` — that fans work out across a `ThreadPoolExecutor`, aggregates progress under a `threading.Lock`, and logs via `context.log`. The backfill adds a pure `_drain_queue(fetch_batch, process_batch)` control-flow helper (loop until an empty batch) and a pure `_register_failure(...)` helper that turns repeated per-game exceptions into a terminal `failed` status, so the drain loop can never spin forever on a permanently-broken game. A shared `progress_stats(done, total, elapsed_seconds)` helper in `_common.py` computes the pct/rate/ETA numbers both ops log.

**Tech Stack:** Python 3.13, Dagster (Pythonic ops/resources), psycopg3, pytest. No new dependencies.

## Global Constraints

- `raw.steam_reviews` stays append-only; no UPDATE/UPSERT is introduced anywhere in this work (CLAUDE.md rule 1).
- No Dagster dynamic partition per `app_id`; parallelism stays inside a single op via `ThreadPoolExecutor`, not Dagster partitions (CLAUDE.md rule 2).
- Steam rate limit (~1 req/s physical constraint, enforced today as a shared 10 req/s throttle + backoff in `SteamResource`) is untouched by this work — parallelizing games does not bypass or duplicate that throttle (CLAUDE.md rule 3).
- Backfill and incremental remain two separate jobs; the backfill's internal drain loop must never block or be scheduled together with the incremental (CLAUDE.md rule 4).
- `steam_reviews_backfill_job` stays unscheduled (no cron) — only `steam_reviews_incremental_job` is scheduled, per existing `schedules.py`.
- Worker counts: `BACKFILL_WORKERS = 8` and `INCREMENTAL_WORKERS = 8`, both hard-coded module constants (not Dagster `Config` fields), matching `CENSUS_WORKERS` style in `steam_census.py`.
- `BackfillConfig.batch_size` default becomes `40` (was `5`); new `BackfillConfig.max_consecutive_failures` default `3`.
- A game exceeding `max_consecutive_failures` consecutive errors gets `backfill_status='failed'` and is permanently excluded from `SELECT_QUEUE_SQL`'s `IN ('pending', 'in_progress')` filter — recovery is a manual `UPDATE` (documented, not automated).
- Out of scope: resuming pagination from `last_cursor` after a mid-game crash (`_backfill_one_game` keeps restarting at `cursor="*"`) — tracked separately per the approved design spec.

---

### Task 1: Schema — `retry_count` column + status comment

**Files:**
- Modify: `db/init.sql`

**Interfaces:**
- Produces: `raw.steam_fetch_state.retry_count` (`INT NOT NULL DEFAULT 0`), consumed by Task 4's `_register_failure` and Task 6's `_run_backfill`.

- [ ] **Step 1: Edit `db/init.sql`**

Find this block (around line 55):

```sql
CREATE TABLE IF NOT EXISTS raw.steam_fetch_state (
    app_id                 BIGINT PRIMARY KEY,
    backfill_status        TEXT NOT NULL DEFAULT 'pending',  -- pending | in_progress | done
    last_cursor            TEXT,          -- dernier cursor Steam (peut expirer, cf. §9)
    max_timestamp_updated  BIGINT,        -- high-water mark pour l'incrémental
    last_success_at        TIMESTAMPTZ,
    last_error             TEXT,
    reviews_fetched        BIGINT DEFAULT 0,
    last_full_check_at     TIMESTAMPTZ    -- dernier check complet (rattrapage modifs invisibles)
);
CREATE INDEX IF NOT EXISTS idx_steam_fetch_state_status
    ON raw.steam_fetch_state (backfill_status);
```

Replace it with:

```sql
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
```

- [ ] **Step 2: Verify the file is well-formed**

Run: `grep -n "retry_count" db/init.sql`
Expected: 3 matches — the column in `CREATE TABLE`, the comment mentioning `failed`, and the `ALTER TABLE ADD COLUMN IF NOT EXISTS` line.

If a local Postgres is reachable (`docker compose ps` shows `postgres` running), you can additionally sanity-check the SQL parses:
`docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f - < db/init.sql` — expected: no syntax errors (a second run should print `NOTICE`/no-ops only, since everything is `IF NOT EXISTS`).

- [ ] **Step 3: Commit**

```bash
git add db/init.sql
git commit -m "$(cat <<'EOF'
feat(db): ajouter retry_count à steam_fetch_state pour le statut 'failed'

Prépare la protection anti-boucle-infinie du backfill : un jeu qui échoue
au-delà d'un seuil de tentatives consécutives sortira définitivement de la
queue via backfill_status='failed'.
EOF
)"
```

---

### Task 2: Shared test fakes

**Files:**
- Create: `tests/_fakes.py`
- Create: `tests/test_fakes_smoke.py`

**Interfaces:**
- Produces: `FakeLog`, `FakeContext`, `FakeStore`, `FakeCursor`, `FakeConn`, `FakePostgres`, `FakeSteam` — all consumed by Tasks 4, 5, 6, 7's tests.
  - `FakeContext().log` exposes `.info(msg: str)`, `.error(msg: str)`, `.warning(msg: str)`, each appending to a thread-safe list (`.info_messages`, `.error_messages`).
  - `FakePostgres(fetch_all_fn=None, connect_factory=None)` exposes `.execute(sql, params=None)` (records to `.executed: list[tuple[str, tuple | None]]`), `.fetch_all(sql, params=None)` (delegates to `fetch_all_fn`), `.connect()` (delegates to `connect_factory`, defaults to a fresh `FakeConn()`).
  - `FakeConn()` is a context manager exposing `.cursor()` (returns a `FakeCursor` supporting `.executemany(sql, rows)`) and `.execute(sql, params=None)`; both record into a shared `FakeStore` (`.inserted_rows`, `.checkpoints`), thread-safe via `FakeStore.lock`.
  - `FakeSteam(pages_by_app_id: dict[int, list[SteamReviewsPage]])` exposes `.reviews_page(app_id, cursor="*", filter_="recent") -> SteamReviewsPage`, popping the next canned page per `app_id` in order (thread-safe), and records calls in `.calls: list[tuple[int, str, str]]`.

- [ ] **Step 1: Write `tests/_fakes.py`**

```python
"""Doubles de test partagés pour les jobs backfill/incrémental Steam.

Pas de mock ici : des objets minimalistes qui implémentent juste ce que
`_backfill_one_game` / `_incremental_one_game` / `_run_backfill` /
`_run_incremental` consomment sur `PostgresResource` et `SteamResource`.
"""

import threading
from typing import Any, Callable

from orchestration.resources import SteamReviewsPage


class FakeLog:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.info_messages: list[str] = []
        self.error_messages: list[str] = []

    def info(self, msg: str) -> None:
        with self._lock:
            self.info_messages.append(msg)

    def error(self, msg: str) -> None:
        with self._lock:
            self.error_messages.append(msg)

    def warning(self, msg: str) -> None:
        with self._lock:
            self.error_messages.append(msg)


class FakeContext:
    def __init__(self) -> None:
        self.log = FakeLog()


class FakeStore:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.inserted_rows: list[tuple[Any, ...]] = []
        self.checkpoints: list[tuple[Any, ...] | None] = []


class FakeCursor:
    def __init__(self, store: FakeStore) -> None:
        self.store = store

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def executemany(self, sql: str, rows: list[tuple[Any, ...]]) -> None:
        with self.store.lock:
            self.store.inserted_rows.extend(rows)


class FakeConn:
    def __init__(self, store: FakeStore | None = None) -> None:
        self.store = store or FakeStore()

    def __enter__(self) -> "FakeConn":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.store)

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        with self.store.lock:
            self.store.checkpoints.append(params)


class FakePostgres:
    def __init__(
        self,
        fetch_all_fn: Callable[[str, tuple[Any, ...] | None], list[dict[str, Any]]]
        | None = None,
        connect_factory: Callable[[], FakeConn] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.executed: list[tuple[str, tuple[Any, ...] | None]] = []
        self._fetch_all_fn = fetch_all_fn or (lambda sql, params: [])
        self._connect_factory = connect_factory or (lambda: FakeConn())

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        with self._lock:
            self.executed.append((sql, params))

    def fetch_all(
        self, sql: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        return self._fetch_all_fn(sql, params)

    def connect(self) -> FakeConn:
        return self._connect_factory()


class FakeSteam:
    def __init__(self, pages_by_app_id: dict[int, list[SteamReviewsPage]]) -> None:
        self._pages = {k: list(v) for k, v in pages_by_app_id.items()}
        self._lock = threading.Lock()
        self.calls: list[tuple[int, str, str]] = []

    def reviews_page(
        self, app_id: int, cursor: str = "*", filter_: str = "recent"
    ) -> SteamReviewsPage:
        with self._lock:
            self.calls.append((app_id, cursor, filter_))
            return self._pages[app_id].pop(0)
```

- [ ] **Step 2: Write `tests/test_fakes_smoke.py`**

```python
"""Vérifie que les doubles de test partagés se comportent comme attendu."""

from orchestration.resources import SteamReviewsPage
from tests._fakes import FakeContext, FakePostgres, FakeSteam


def test_fake_steam_pops_pages_in_order():
    page1 = SteamReviewsPage(success=1, query_summary={}, reviews=[{"a": 1}], cursor="c1")
    page2 = SteamReviewsPage(success=1, query_summary={}, reviews=[], cursor=None)
    steam = FakeSteam({570: [page1, page2]})

    assert steam.reviews_page(570, cursor="*", filter_="recent") is page1
    assert steam.reviews_page(570, cursor="c1", filter_="recent") is page2
    assert steam.calls == [(570, "*", "recent"), (570, "c1", "recent")]


def test_fake_postgres_records_execute_calls():
    postgres = FakePostgres()
    postgres.execute("UPDATE x SET y = %s", (1,))
    assert postgres.executed == [("UPDATE x SET y = %s", (1,))]


def test_fake_postgres_fetch_all_delegates():
    postgres = FakePostgres(fetch_all_fn=lambda sql, params: [{"n": 42}])
    assert postgres.fetch_all("SELECT 1", None) == [{"n": 42}]


def test_fake_context_log_records_messages():
    context = FakeContext()
    context.log.info("hello")
    context.log.error("boom")
    assert context.log.info_messages == ["hello"]
    assert context.log.error_messages == ["boom"]
```

- [ ] **Step 3: Run the smoke tests**

Run: `pytest tests/test_fakes_smoke.py -v`
Expected: 4 passed.

- [ ] **Step 4: Commit**

```bash
git add tests/_fakes.py tests/test_fakes_smoke.py
git commit -m "$(cat <<'EOF'
test: ajouter des doubles de test partagés pour les jobs Steam

Fakes réutilisables (context/log, postgres, steam) pour tester la logique
de _run_backfill/_run_incremental sans harnais Dagster ni DB réelle.
EOF
)"
```

---

### Task 3: `progress_stats` helper

**Files:**
- Modify: `orchestration/assets/_common.py`
- Create: `tests/test_common_progress_stats.py`

**Interfaces:**
- Produces: `progress_stats(done: int, total: int, elapsed_seconds: float) -> tuple[float, float, float]` returning `(pct, rate_per_second, eta_minutes)`. Consumed by Task 6 (`_run_backfill`) and Task 7 (`_run_incremental`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_common_progress_stats.py`:

```python
"""Tests de orchestration.assets._common.progress_stats (calcul pur, sans I/O)."""

import math

from orchestration.assets._common import progress_stats


def test_progress_stats_normal_case():
    pct, rate, eta_minutes = progress_stats(done=10, total=100, elapsed_seconds=10.0)
    assert pct == 0.1
    assert rate == 1.0
    assert eta_minutes == 1.5


def test_progress_stats_total_zero_reports_done():
    pct, rate, eta_minutes = progress_stats(done=0, total=0, elapsed_seconds=5.0)
    assert pct == 1.0
    assert rate == 0.0
    assert eta_minutes == math.inf


def test_progress_stats_elapsed_zero_avoids_division_by_zero():
    pct, rate, eta_minutes = progress_stats(done=0, total=10, elapsed_seconds=0.0)
    assert pct == 0.0
    assert rate == 0.0
    assert eta_minutes == math.inf
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_common_progress_stats.py -v`
Expected: FAIL — `ImportError: cannot import name 'progress_stats'`.

- [ ] **Step 3: Implement `progress_stats` in `orchestration/assets/_common.py`**

Append at the end of the file (after `insert_reviews_page`):

```python


def progress_stats(done: int, total: int, elapsed_seconds: float) -> tuple[float, float, float]:
    """Calcule (pct, jeux/s, ETA en minutes) pour les logs de progression.

    `pct=1.0` si `total == 0` (rien à faire) ; `rate=0.0` et `eta=inf` si
    aucun temps n'a encore passé ou qu'aucun jeu n'a encore été traité.
    """
    pct = done / total if total else 1.0
    rate = done / elapsed_seconds if elapsed_seconds > 0 else 0.0
    eta_minutes = (total - done) / rate / 60 if rate > 0 else float("inf")
    return pct, rate, eta_minutes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_common_progress_stats.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add orchestration/assets/_common.py tests/test_common_progress_stats.py
git commit -m "$(cat <<'EOF'
feat: ajouter progress_stats pour les logs de progression backfill/incrémental

Calcul partagé (pct, jeux/s, ETA) réutilisé par les deux jobs de collecte,
extrait en fonction pure et testée indépendamment du threading/Dagster.
EOF
)"
```

---

### Task 4: `_register_failure` + retry/failed SQL

**Files:**
- Modify: `orchestration/assets/steam_backfill.py`
- Create: `tests/test_steam_backfill.py`

**Interfaces:**
- Consumes: `PostgresResource`-shaped object with `.fetch_all(sql, params) -> list[dict]` and `.execute(sql, params) -> None` (satisfied by `FakePostgres` from Task 2 in tests, by the real `PostgresResource` in production).
- Produces: `_register_failure(postgres, app_id: int, error: str, max_consecutive_failures: int) -> str` (returns `"in_progress"` or `"failed"`), `COUNT_QUEUE_SQL`, `INCREMENT_RETRY_SQL`, `MARK_FAILED_SQL` module-level constants. Consumed by Task 6.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_steam_backfill.py`:

```python
"""Tests de orchestration.assets.steam_backfill (logique pure + fakes)."""

from orchestration.assets.steam_backfill import (
    MARK_FAILED_SQL,
    SELECT_QUEUE_SQL,
    _register_failure,
)
from tests._fakes import FakePostgres


def test_select_queue_sql_excludes_failed_games():
    assert "'failed'" not in SELECT_QUEUE_SQL
    assert "'pending'" in SELECT_QUEUE_SQL
    assert "'in_progress'" in SELECT_QUEUE_SQL


def test_register_failure_stays_in_progress_below_threshold():
    postgres = FakePostgres(fetch_all_fn=lambda sql, params: [{"retry_count": 2}])

    status = _register_failure(postgres, app_id=570, error="boom", max_consecutive_failures=3)

    assert status == "in_progress"
    assert not any(sql == MARK_FAILED_SQL for sql, _ in postgres.executed)


def test_register_failure_marks_failed_at_threshold():
    postgres = FakePostgres(fetch_all_fn=lambda sql, params: [{"retry_count": 3}])

    status = _register_failure(postgres, app_id=570, error="boom", max_consecutive_failures=3)

    assert status == "failed"
    assert (MARK_FAILED_SQL, (570,)) in postgres.executed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_steam_backfill.py -v`
Expected: FAIL — `ImportError: cannot import name '_register_failure'`.

- [ ] **Step 3: Add the SQL constants and `_register_failure`**

In `orchestration/assets/steam_backfill.py`, find:

```python
# Sélection de la file de backfill.
SELECT_QUEUE_SQL = """
SELECT s.app_id
FROM raw.steam_fetch_state s
LEFT JOIN raw.steam_review_counts c ON c.app_id = s.app_id
WHERE s.backfill_status IN ('pending', 'in_progress')
ORDER BY c.total_reviews {order} NULLS LAST
LIMIT %s;
"""
```

Replace with:

```python
# Sélection de la file de backfill ('failed' est exclu par construction : il
# n'apparaît pas dans le IN ci-dessous).
SELECT_QUEUE_SQL = """
SELECT s.app_id
FROM raw.steam_fetch_state s
LEFT JOIN raw.steam_review_counts c ON c.app_id = s.app_id
WHERE s.backfill_status IN ('pending', 'in_progress')
ORDER BY c.total_reviews {order} NULLS LAST
LIMIT %s;
"""

# Nombre de jeux encore à traiter (pour le calcul de progression/ETA).
COUNT_QUEUE_SQL = """
SELECT count(*) AS n
FROM raw.steam_fetch_state
WHERE backfill_status IN ('pending', 'in_progress');
"""
```

Then find:

```python
MARK_DONE_SQL = """
UPDATE raw.steam_fetch_state
SET backfill_status = 'done', last_success_at = now(), last_error = NULL
WHERE app_id = %s;
"""

MARK_ERROR_SQL = """
UPDATE raw.steam_fetch_state
SET last_error = %s
WHERE app_id = %s;
"""
```

Replace with:

```python
MARK_DONE_SQL = """
UPDATE raw.steam_fetch_state
SET backfill_status = 'done', retry_count = 0, last_success_at = now(), last_error = NULL
WHERE app_id = %s;
"""

# Incrémente le compteur d'échecs consécutifs, renvoie la nouvelle valeur.
INCREMENT_RETRY_SQL = """
UPDATE raw.steam_fetch_state
SET retry_count = retry_count + 1,
    last_error = %s
WHERE app_id = %s
RETURNING retry_count;
"""

MARK_FAILED_SQL = """
UPDATE raw.steam_fetch_state
SET backfill_status = 'failed'
WHERE app_id = %s;
"""


def _register_failure(
    postgres: PostgresResource,
    app_id: int,
    error: str,
    max_consecutive_failures: int,
) -> str:
    """Incrémente retry_count ; passe le jeu en 'failed' si le seuil est atteint.

    Le seuil protège `_drain_queue` (Task 5) : sans lui, un jeu qui échoue
    toujours resterait 'in_progress' et serait resélectionné à l'infini par
    `SELECT_QUEUE_SQL`, empêchant la queue de jamais se vider.

    Retourne le nouveau statut du jeu : 'in_progress' ou 'failed'.
    """
    rows = postgres.fetch_all(INCREMENT_RETRY_SQL, (error[:500], app_id))
    retry_count = rows[0]["retry_count"]
    if retry_count >= max_consecutive_failures:
        postgres.execute(MARK_FAILED_SQL, (app_id,))
        return "failed"
    return "in_progress"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_steam_backfill.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add orchestration/assets/steam_backfill.py tests/test_steam_backfill.py
git commit -m "$(cat <<'EOF'
feat: ajouter le statut 'failed' + retry_count au backfill Steam

_register_failure marque un jeu 'failed' après N échecs consécutifs, pour
que la future boucle de drainage (jusqu'à queue vide) ne tourne jamais
indéfiniment sur un jeu cassé de façon permanente.
EOF
)"
```

---

### Task 5: `_drain_queue` control-flow helper

**Files:**
- Modify: `orchestration/assets/steam_backfill.py`
- Modify: `tests/test_steam_backfill.py`

**Interfaces:**
- Produces: `_drain_queue(fetch_batch: Callable[[], list[int]], process_batch: Callable[[list[int]], None]) -> None`. Consumed by Task 6's `_run_backfill`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_steam_backfill.py`:

```python
from orchestration.assets.steam_backfill import _drain_queue


def test_drain_queue_stops_on_empty_batch():
    batches = [[1, 2], [3], []]
    processed: list[list[int]] = []

    def fetch_batch() -> list[int]:
        return batches.pop(0)

    _drain_queue(fetch_batch, processed.append)

    assert processed == [[1, 2], [3]]


def test_drain_queue_noop_when_first_batch_empty():
    calls: list[list[int]] = []

    _drain_queue(lambda: [], calls.append)

    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_steam_backfill.py -v -k drain_queue`
Expected: FAIL — `ImportError: cannot import name '_drain_queue'`.

- [ ] **Step 3: Implement `_drain_queue`**

In `orchestration/assets/steam_backfill.py`, add near the top of the file (after the `from orchestration.resources import ...` import), add the missing import:

```python
from collections.abc import Callable
```

Then add the function just before `def _backfill_one_game(`:

```python
def _drain_queue(
    fetch_batch: Callable[[], list[int]],
    process_batch: Callable[[list[int]], None],
) -> None:
    """Traite des batches jusqu'à ce que `fetch_batch` renvoie une liste vide.

    Isolé du threading/Dagster pour rester testable directement : le run de
    backfill boucle désormais sur ses propres batches au lieu de traiter un
    seul batch borné puis s'arrêter (CLAUDE.md règle 4 : ceci reste un job
    séparé de l'incrémental, non schedulé). `_register_failure` (Task 4)
    garantit que `fetch_batch` finit par renvoyer une liste vide même en
    présence de jeux en échec permanent.
    """
    while True:
        batch = fetch_batch()
        if not batch:
            break
        process_batch(batch)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_steam_backfill.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add orchestration/assets/steam_backfill.py tests/test_steam_backfill.py
git commit -m "$(cat <<'EOF'
feat: ajouter _drain_queue pour boucler le backfill jusqu'à queue vide

Contrôle de flux pur, testable sans Dagster : traite des batches successifs
jusqu'à ce qu'un batch vide signale la fin de la queue pending/in_progress.
EOF
)"
```

---

### Task 6: Parallelize + loop `steam_reviews_backfill_job`

**Files:**
- Modify: `orchestration/assets/steam_backfill.py`
- Modify: `tests/test_steam_backfill.py`

**Interfaces:**
- Consumes: `progress_stats` (Task 3), `_register_failure` (Task 4), `_drain_queue` (Task 5), `FakeConn`/`FakePostgres`/`FakeSteam`/`FakeContext` (Task 2).
- Produces: `BACKFILL_WORKERS` constant, updated `BackfillConfig` (`batch_size=40`, `max_consecutive_failures=3`), `_run_backfill(context, config, steam, postgres) -> None`, thin `backfill_reviews` op unchanged in signature/behavior from the job's perspective.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_steam_backfill.py`:

```python
import threading

from orchestration.assets.steam_backfill import (
    BackfillConfig,
    COUNT_QUEUE_SQL,
    _run_backfill,
)
from orchestration.resources import SteamReviewsPage
from tests._fakes import FakeConn, FakeContext


class _StateStore:
    def __init__(self, app_ids: list[int]) -> None:
        self.status = {app_id: "pending" for app_id in app_ids}
        self.retry_count = {app_id: 0 for app_id in app_ids}
        self.lock = threading.Lock()


class _IntegrationPostgres:
    """Simule raw.steam_fetch_state en mémoire pour tester _run_backfill de bout en bout."""

    def __init__(self, store: _StateStore) -> None:
        self.store = store

    def execute(self, sql, params=None):
        with self.store.lock:
            if "backfill_status = 'in_progress'" in sql:
                (app_id,) = params
                self.store.status[app_id] = "in_progress"
            elif "backfill_status = 'done'" in sql:
                (app_id,) = params
                self.store.status[app_id] = "done"
                self.store.retry_count[app_id] = 0
            elif "backfill_status = 'failed'" in sql:
                (app_id,) = params
                self.store.status[app_id] = "failed"

    def fetch_all(self, sql, params=None):
        with self.store.lock:
            if sql == COUNT_QUEUE_SQL:
                n = sum(
                    1 for s in self.store.status.values() if s in ("pending", "in_progress")
                )
                return [{"n": n}]
            if "RETURNING retry_count" in sql:
                _error, app_id = params
                self.store.retry_count[app_id] += 1
                return [{"retry_count": self.store.retry_count[app_id]}]
            (limit,) = params
            queue = [
                app_id
                for app_id, status in self.store.status.items()
                if status in ("pending", "in_progress")
            ]
            return [{"app_id": app_id} for app_id in queue[:limit]]

    def connect(self):
        return FakeConn()


class _RaisingSteam:
    def __init__(self, ok_pages: dict[int, list[SteamReviewsPage]], failing_app_id: int) -> None:
        self._ok_pages = ok_pages
        self._failing_app_id = failing_app_id

    def reviews_page(self, app_id, cursor="*", filter_="recent"):
        if app_id == self._failing_app_id:
            raise RuntimeError("boom")
        return self._ok_pages[app_id].pop(0)


def test_run_backfill_drains_queue_and_marks_failed_on_persistent_error():
    store = _StateStore(app_ids=[1, 2])
    postgres = _IntegrationPostgres(store)
    steam = _RaisingSteam(
        ok_pages={
            1: [
                SteamReviewsPage(
                    success=1,
                    query_summary={},
                    reviews=[
                        {
                            "recommendationid": "10",
                            "timestamp_created": 1,
                            "timestamp_updated": 1,
                        }
                    ],
                    cursor=None,
                )
            ]
        },
        failing_app_id=2,
    )
    context = FakeContext()
    config = BackfillConfig(batch_size=10, order="DESC", max_consecutive_failures=1)

    _run_backfill(context, config, steam, postgres)

    assert store.status[1] == "done"
    assert store.status[2] == "failed"
    assert any("Backfill terminé" in m for m in context.log.info_messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_steam_backfill.py -v -k run_backfill`
Expected: FAIL — `ImportError: cannot import name '_run_backfill'` (and `BackfillConfig` still has no `max_consecutive_failures` field).

- [ ] **Step 3: Update `_backfill_one_game`, `BackfillConfig`, and replace the op with `_run_backfill`**

In `orchestration/assets/steam_backfill.py`, add these imports at the top (alongside the existing `from dagster import ...` and `from collections.abc import Callable` from Task 5):

```python
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
```

And change:

```python
from orchestration.assets._common import insert_reviews_page
```

to:

```python
from orchestration.assets._common import insert_reviews_page, progress_stats
```

Add the workers constant near the top, after the imports (alongside other module-level constants):

```python
BACKFILL_WORKERS = 8
```

Replace `_backfill_one_game` with (adds start/end logs + page count):

```python
def _backfill_one_game(
    context: OpExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
    app_id: int,
) -> int:
    """Pagination complète d'un jeu (filter=recent) en append-only."""
    context.log.info(f"app_id={app_id} : démarrage backfill")
    cursor = "*"
    fetched = 0
    pages = 0
    while True:
        page = steam.reviews_page(app_id, cursor=cursor, filter_="recent")

        # success == 2 : pas de reviews / app invalide -> on considère terminé.
        if page.success == 2 or not page.reviews:
            break

        with postgres.connect() as conn:
            inserted, max_ts = insert_reviews_page(conn, app_id, page.reviews)
            conn.execute(CHECKPOINT_SQL, (page.cursor, max_ts, inserted, app_id))
        fetched += inserted
        pages += 1

        # Fin de pagination : le cursor cesse de changer.
        if not page.cursor or page.cursor == cursor:
            break
        cursor = page.cursor

    context.log.info(f"app_id={app_id} : terminé ({fetched} reviews, {pages} pages)")
    return fetched
```

Replace `class BackfillConfig(Config):` block with:

```python
class BackfillConfig(Config):
    # Nombre de jeux piochés par itération de _drain_queue (traités en
    # parallèle via BACKFILL_WORKERS avant de piocher le batch suivant).
    batch_size: int = 40
    # 'DESC' = gros jeux d'abord (recommandé), 'ASC' = petits jeux d'abord.
    order: str = "DESC"
    # Échecs consécutifs avant de passer un jeu en 'failed' (sort de la queue).
    max_consecutive_failures: int = 3
```

Replace the whole `@op def backfill_reviews(...)` block with:

```python
def _run_backfill(
    context: OpExecutionContext,
    config: BackfillConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> None:
    order = "ASC" if config.order.upper() == "ASC" else "DESC"
    total_pending = postgres.fetch_all(COUNT_QUEUE_SQL)[0]["n"]
    context.log.info(f"Backfill : {total_pending} jeux en attente (pending+in_progress)")

    start = time.monotonic()
    reviews_total = 0
    failed_total = 0
    lock = threading.Lock()

    def _process_one(app_id: int) -> None:
        nonlocal reviews_total, failed_total
        postgres.execute(MARK_IN_PROGRESS_SQL, (app_id,))
        try:
            fetched = _backfill_one_game(context, steam, postgres, app_id)
            postgres.execute(MARK_DONE_SQL, (app_id,))
            with lock:
                reviews_total += fetched
        except Exception as exc:  # noqa: BLE001 - on isole l'échec par jeu
            status = _register_failure(
                postgres, app_id, str(exc), config.max_consecutive_failures
            )
            context.log.error(f"app_id={app_id} : échec backfill ({exc}) -> {status}")
            if status == "failed":
                with lock:
                    failed_total += 1

    def fetch_batch() -> list[int]:
        rows = postgres.fetch_all(
            SELECT_QUEUE_SQL.format(order=order), (config.batch_size,)
        )
        return [row["app_id"] for row in rows]

    def process_batch(app_ids: list[int]) -> None:
        context.log.info(
            f"Backfill : nouveau batch de {len(app_ids)} jeux (order={order})"
        )
        with ThreadPoolExecutor(max_workers=BACKFILL_WORKERS) as pool:
            futures = [pool.submit(_process_one, app_id) for app_id in app_ids]
            for future in as_completed(futures):
                future.result()

        remaining = postgres.fetch_all(COUNT_QUEUE_SQL)[0]["n"]
        done_or_failed = total_pending - remaining
        elapsed = time.monotonic() - start
        pct, rate, eta_min = progress_stats(done_or_failed, total_pending, elapsed)
        context.log.info(
            f"Backfill : {done_or_failed}/{total_pending} traités ({pct:.0%}) "
            f"— {reviews_total} reviews cumulées — {rate:.2f} jeux/s — ETA ~{eta_min:.0f} min"
        )

    _drain_queue(fetch_batch, process_batch)

    elapsed_total = time.monotonic() - start
    context.log.info(
        f"Backfill terminé : {reviews_total} reviews, {failed_total} jeu(x) en échec "
        f"permanent, durée {elapsed_total / 60:.1f} min"
    )


@op
def backfill_reviews(
    context: OpExecutionContext,
    config: BackfillConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> None:
    _run_backfill(context, config, steam, postgres)
```

- [ ] **Step 4: Run all backfill tests to verify they pass**

Run: `pytest tests/test_steam_backfill.py -v`
Expected: 8 passed.

- [ ] **Step 5: Run the full test suite and lint**

Run: `pytest -v && ruff check .`
Expected: all tests pass, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add orchestration/assets/steam_backfill.py tests/test_steam_backfill.py
git commit -m "$(cat <<'EOF'
feat: paralléliser et boucler le backfill Steam jusqu'à queue vide

_run_backfill fan-out chaque batch sur BACKFILL_WORKERS=8 threads (au lieu
d'un jeu à la fois), boucle via _drain_queue jusqu'à épuisement de la queue
pending/in_progress (batch_size par défaut 40), et logue la progression
(pct/rate/ETA) après chaque batch grâce à progress_stats.
EOF
)"
```

---

### Task 7: Parallelize `steam_reviews_incremental_job`

**Files:**
- Modify: `orchestration/assets/steam_incremental.py`
- Create: `tests/test_steam_incremental.py`

**Interfaces:**
- Consumes: `progress_stats` (Task 3), `FakePostgres`/`FakeSteam`/`FakeContext` (Task 2).
- Produces: `INCREMENTAL_WORKERS` constant, `_run_incremental(context, config, steam, postgres) -> None`, thin `incremental_reviews` op unchanged in signature/behavior from the job's perspective.

- [ ] **Step 1: Write the failing test**

Create `tests/test_steam_incremental.py`:

```python
"""Tests de orchestration.assets.steam_incremental (fakes, sans DB/API réelles)."""

from orchestration.assets.steam_incremental import IncrementalConfig, _run_incremental
from orchestration.resources import SteamReviewsPage
from tests._fakes import FakeContext, FakePostgres, FakeSteam


def test_run_incremental_processes_all_rows_and_aggregates_reviews():
    rows = [
        {"app_id": 1, "max_ts": 100, "force_full": False},
        {"app_id": 2, "max_ts": 200, "force_full": False},
    ]
    postgres = FakePostgres(fetch_all_fn=lambda sql, params: rows)
    steam = FakeSteam(
        {
            1: [
                SteamReviewsPage(
                    success=1,
                    query_summary={},
                    reviews=[
                        {
                            "recommendationid": "11",
                            "timestamp_created": 150,
                            "timestamp_updated": 150,
                        }
                    ],
                    cursor=None,
                )
            ],
            2: [SteamReviewsPage(success=2, query_summary={}, reviews=[], cursor=None)],
        }
    )
    context = FakeContext()
    config = IncrementalConfig(full_check_interval_days=7)

    _run_incremental(context, config, steam, postgres)

    assert any(
        "2 jeux vérifiés, 1 reviews neuves/modifiées" in m
        for m in context.log.info_messages
    )


def test_run_incremental_noop_when_nothing_to_check():
    postgres = FakePostgres(fetch_all_fn=lambda sql, params: [])
    steam = FakeSteam({})
    context = FakeContext()
    config = IncrementalConfig(full_check_interval_days=7)

    _run_incremental(context, config, steam, postgres)

    assert any(
        "0 jeux vérifiés, 0 reviews neuves/modifiées" in m
        for m in context.log.info_messages
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_steam_incremental.py -v`
Expected: FAIL — `ImportError: cannot import name '_run_incremental'`.

- [ ] **Step 3: Update `_incremental_one_game` and replace the op with `_run_incremental`**

In `orchestration/assets/steam_incremental.py`, add these imports at the top:

```python
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
```

And change:

```python
from orchestration.assets._common import insert_reviews_page
```

to:

```python
from orchestration.assets._common import insert_reviews_page, progress_stats
```

Add the workers constant near the top, after the imports:

```python
INCREMENTAL_WORKERS = 8
```

Replace `_incremental_one_game` with (adds start/end logs):

```python
def _incremental_one_game(
    context: OpExecutionContext,
    steam: SteamResource,
    postgres: PostgresResource,
    app_id: int,
    high_water_mark: int,
    force_full: bool,
) -> int:
    """Passe `filter=updated`, stop dès qu'on repasse sous le high-water mark."""
    context.log.info(f"app_id={app_id} : démarrage vérification incrémentale")
    cursor = "*"
    fetched = 0
    stop = False
    while not stop:
        page = steam.reviews_page(app_id, cursor=cursor, filter_="updated")
        if page.success == 2 or not page.reviews:
            break

        new_reviews = []
        for r in page.reviews:
            ts_updated = r.get("timestamp_updated") or r.get("timestamp_created") or 0
            if not force_full and ts_updated <= high_water_mark:
                stop = True
                continue
            new_reviews.append(r)

        if new_reviews:
            with postgres.connect() as conn:
                inserted, max_ts = insert_reviews_page(conn, app_id, new_reviews)
                conn.execute(CHECKPOINT_SQL, (max_ts, inserted, force_full, app_id))
            fetched += inserted

        if stop or not page.cursor or page.cursor == cursor:
            break
        cursor = page.cursor

    context.log.info(f"app_id={app_id} : terminé ({fetched} reviews neuves/modifiées)")
    return fetched
```

Replace the whole `@op def incremental_reviews(...)` block with:

```python
def _run_incremental(
    context: OpExecutionContext,
    config: IncrementalConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> None:
    days = config.full_check_interval_days
    rows = postgres.fetch_all(SELECT_TO_CHECK_SQL, (days, days))
    total = len(rows)
    context.log.info(f"Incrémental : {total} jeux à vérifier")

    start = time.monotonic()
    reviews_total = 0
    lock = threading.Lock()

    def _process_one(row: dict) -> int:
        app_id = row["app_id"]
        try:
            return _incremental_one_game(
                context, steam, postgres, app_id, row["max_ts"], row["force_full"]
            )
        except Exception as exc:  # noqa: BLE001 - on isole l'échec par jeu
            postgres.execute(MARK_ERROR_SQL, (str(exc)[:500], app_id))
            context.log.error(f"app_id={app_id} : échec incrémental ({exc})")
            return 0

    if rows:
        with ThreadPoolExecutor(max_workers=INCREMENTAL_WORKERS) as pool:
            futures = [pool.submit(_process_one, row) for row in rows]
            for i, future in enumerate(as_completed(futures), start=1):
                fetched = future.result()
                with lock:
                    reviews_total += fetched
                elapsed = time.monotonic() - start
                pct, rate, _eta_minutes = progress_stats(i, total, elapsed)
                context.log.info(
                    f"Incrémental : {i}/{total} vérifiés ({pct:.0%}) "
                    f"— {reviews_total} reviews neuves/modifiées — {rate:.2f} jeux/s"
                )

    elapsed_total = time.monotonic() - start
    context.log.info(
        f"Incrémental terminé : {total} jeux vérifiés, {reviews_total} reviews "
        f"neuves/modifiées, durée {elapsed_total / 60:.1f} min"
    )


@op
def incremental_reviews(
    context: OpExecutionContext,
    config: IncrementalConfig,
    steam: SteamResource,
    postgres: PostgresResource,
) -> None:
    _run_incremental(context, config, steam, postgres)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_steam_incremental.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run the full test suite and lint**

Run: `pytest -v && ruff check . && ruff format --check .`
Expected: all tests pass, no lint/format errors.

- [ ] **Step 6: Commit**

```bash
git add orchestration/assets/steam_incremental.py tests/test_steam_incremental.py
git commit -m "$(cat <<'EOF'
feat: paralléliser l'incrémental Steam et logger sa progression

_run_incremental fan-out la vérification des jeux 'done' sur
INCREMENTAL_WORKERS=8 threads (au lieu d'un jeu à la fois), avec des logs
par jeu et un résumé de progression (pct/rate) via progress_stats.
EOF
)"
```

---

## Manual verification (not automated — needs real Steam API / Postgres)

Per CLAUDE.md's "pièges connus": these assets are scaffolds validated with fakes only. Before relying on this in a real backfill run:

1. `docker compose up -d postgres` then apply `db/init.sql` (or confirm the running DB already picked up `retry_count` via the `ALTER TABLE ... IF NOT EXISTS`).
2. Launch `steam_reviews_backfill_job` with a small `batch_size` (e.g. 5) against a handful of real `app_id`s and watch the Dagster run logs for the new per-game/per-batch/end-of-run lines.
3. Manually flip a game to a state that will keep failing (e.g. a deleted `app_id`) and confirm it reaches `backfill_status='failed'` after `max_consecutive_failures` and stops appearing in subsequent batches (no infinite loop).
4. Launch `steam_reviews_incremental_job` similarly and confirm the summary line reports the expected counts.
