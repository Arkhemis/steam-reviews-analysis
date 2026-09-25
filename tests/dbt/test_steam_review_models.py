"""Exercise the review registry and view SQL with small, in-memory relations.

DuckDB runs the relevant PostgreSQL SQL dialect without a warehouse or dbt run.
Only dbt's relation names and compilation-time values are supplied by the test.
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pytest
from jinja2 import Environment, StrictUndefined


MODELS = Path(__file__).resolve().parents[2] / "dbt" / "models" / "staging"
MACROS = Path(__file__).resolve().parents[2] / "dbt" / "macros" / "steam_review.sql"
PARSE_MACRO = MACROS.with_name("steam_review_parse.sql")
ENV = Environment(undefined=StrictUndefined)


@pytest.fixture
def warehouse():
    with duckdb.connect(":memory:") as conn:
        conn.execute("CREATE SCHEMA raw")
        conn.execute("CREATE SCHEMA staging")
        conn.execute(
            "CREATE TABLE raw.steam_reviews ("
            "app_id INTEGER, recommendation_id INTEGER, loaded_at TIMESTAMPTZ, "
            "payload JSON, timestamp_created BIGINT, timestamp_updated BIGINT)"
        )
        conn.execute(
            "CREATE TABLE staging.steam_review_versions ("
            "app_id INTEGER, recommendation_id INTEGER, updated_at TIMESTAMPTZ, "
            "loaded_at TIMESTAMPTZ, votes_up INTEGER)"
        )
        conn.execute(
            "CREATE TABLE staging.steam_review_outdated ("
            "app_id INTEGER, recommendation_id INTEGER, updated_at TIMESTAMPTZ, "
            "detected_at TIMESTAMPTZ)"
        )
        yield conn


def add_versions(warehouse, *rows):
    warehouse.executemany(
        "INSERT INTO staging.steam_review_versions VALUES (?, ?, ?, ?, ?)", rows
    )


def add_raw_reviews(warehouse, *rows):
    """Rows: app, recommendation, updated epoch, loaded date, votes up."""
    warehouse.executemany(
        "INSERT INTO raw.steam_reviews VALUES (?, ?, ?, ?, ?, ?)",
        [
            (
                app_id,
                recommendation_id,
                loaded_at,
                json.dumps(
                    {
                        "review": "A useful review",
                        "voted_up": True,
                        "votes_up": votes_up,
                        "votes_funny": 4294967295,
                    }
                ),
                updated_at,
                updated_at,
            )
            for app_id, recommendation_id, updated_at, loaded_at, votes_up in rows
        ],
    )


def epoch(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def render_model(
    warehouse, name, *, incremental=False, full_rebuild=False, watermark=None
):
    def run_query(query):
        value = warehouse.execute(query).fetchone()[0]
        return SimpleNamespace(columns=[SimpleNamespace(values=lambda: [value])])

    context = {
        "config": lambda **_kwargs: "",
        "ref": lambda model: f"staging.{model}",
        "source": lambda schema, table: f"{schema}.{table}",
        "this": f"staging.{name}",
        "execute": True,
        "is_incremental": lambda: incremental,
        "steam_review_outdated_full_rebuild": lambda: full_rebuild,
        "steam_review_watermark": lambda _relation, _days: watermark,
        "run_query": run_query,
        # PostgreSQL-only regexes; covered by the dbt tests on the warehouse.
        "has_profanity": lambda _text, _language: "FALSE",
    }
    if name == "steam_review_versions":
        # These two dbt macros generate the actual parse and first-build SQL.
        macro_source = (
            PARSE_MACRO.read_text()
            + MACROS.read_text().split("{% macro steam_review_watermark", 1)[0]
        )
        macro_module = ENV.from_string(macro_source).make_module(context)
        context.update(
            {
                "steam_review_parse": macro_module.steam_review_parse,
                "steam_review_latest_versions": macro_module.steam_review_latest_versions,
                "steam_review_analyze_columns": lambda: [],
            }
        )
    return ENV.from_string((MODELS / f"{name}.sql").read_text()).render(context)


def outdated_keys(warehouse, query):
    return warehouse.execute(
        "SELECT app_id, recommendation_id, CAST(updated_at AS DATE) "
        f"FROM ({query}) AS result ORDER BY 1, 2, 3"
    ).fetchall()


def test_full_rebuild_marks_only_older_versions_per_game(warehouse):
    add_versions(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-02", 1),
        (1, 10, "2026-09-05", "2026-09-06", 2),
        (1, 10, "2026-09-10", "2026-09-11", 3),
        (1, 11, "2026-09-03", "2026-09-04", 4),
        (2, 10, "2026-09-01", "2026-09-02", 5),
        (2, 10, "2026-09-08", "2026-09-09", 6),
    )

    query = render_model(warehouse, "steam_review_outdated", full_rebuild=True)

    assert outdated_keys(warehouse, query) == [
        (1, 10, date(2026, 9, 1)),
        (1, 10, date(2026, 9, 5)),
        (2, 10, date(2026, 9, 1)),
    ]


def test_incremental_registry_adds_only_newly_outdated_touched_versions(warehouse):
    add_versions(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-02", 1),
        (1, 10, "2026-09-05", "2026-09-06", 2),
        (1, 10, "2026-09-10", "2026-09-23", 3),
        (1, 20, "2026-09-01", "2026-09-02", 4),
        (1, 20, "2026-09-10", "2026-09-11", 5),
    )
    warehouse.execute(
        "INSERT INTO staging.steam_review_outdated VALUES "
        "(1, 10, '2026-09-01', '2026-09-24')"
    )
    warehouse.executemany(
        "INSERT INTO raw.steam_reviews "
        "(app_id, recommendation_id, loaded_at) VALUES (?, ?, ?)",
        [(1, 10, "2026-09-22"), (1, 20, "2026-09-21")],
    )

    query = render_model(warehouse, "steam_review_outdated", incremental=True)

    assert outdated_keys(warehouse, query) == [(1, 10, date(2026, 9, 5))]


def test_incremental_registry_falls_back_to_versions_after_compaction(warehouse):
    add_versions(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-22", 1),
        (1, 10, "2026-09-10", "2026-09-23", 2),
        (1, 20, "2026-09-01", "2026-09-22", 3),
        (1, 20, "2026-09-10", "2026-09-23", 4),
    )
    warehouse.executemany(
        "INSERT INTO raw.steam_reviews "
        "(app_id, recommendation_id, loaded_at) VALUES (?, ?, ?)",
        [(1, 10, "2026-09-22"), (1, 20, "2026-09-21")],
    )

    query = render_model(
        warehouse,
        "steam_review_outdated",
        incremental=True,
        watermark="'2026-09-21'::timestamptz",
    )

    assert outdated_keys(warehouse, query) == [(1, 10, date(2026, 9, 1))]


def test_review_view_retains_the_latest_version_for_each_game(warehouse):
    add_versions(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-02", 1),
        (1, 10, "2026-09-05", "2026-09-06", 8),
        (2, 10, "2026-09-01", "2026-09-02", 4),
        (1, 11, "2026-09-01", "2026-09-02", 6),
    )
    warehouse.execute(
        "INSERT INTO staging.steam_review_outdated VALUES "
        "(1, 10, '2026-09-01', '2026-09-24')"
    )

    query = render_model(warehouse, "steam_review")
    rows = warehouse.execute(
        "SELECT app_id, recommendation_id, votes_up "
        f"FROM ({query}) AS result ORDER BY 1, 2"
    ).fetchall()

    assert rows == [(1, 10, 8), (1, 11, 6), (2, 10, 4)]


def test_first_build_uses_latest_update_and_latest_capture_on_ties(warehouse):
    add_raw_reviews(
        warehouse,
        (1, 10, epoch("2026-09-01"), "2026-09-02", 1),
        (1, 10, epoch("2026-09-05"), "2026-09-06", 2),
        (1, 10, epoch("2026-09-05"), "2026-09-07", 3),
        (2, 10, epoch("2026-09-01"), "2026-09-03", 4),
    )

    query = render_model(warehouse, "steam_review_versions")
    rows = warehouse.execute(
        "SELECT app_id, recommendation_id, CAST(updated_at AS DATE), "
        f"votes_up, votes_funny FROM ({query}) AS result ORDER BY 1, 2"
    ).fetchall()

    assert rows == [
        (1, 10, date(2026, 9, 5), 3, -1),
        (2, 10, date(2026, 9, 1), 4, -1),
    ]


def test_append_keeps_one_capture_per_new_version_and_ignores_overlap(warehouse):
    add_versions(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-22", 1),
    )
    add_raw_reviews(
        warehouse,
        (1, 10, epoch("2026-09-01"), "2026-09-23", 5),
        (1, 10, epoch("2026-09-05"), "2026-09-22", 6),
        (1, 10, epoch("2026-09-05"), "2026-09-24", 7),
        (1, 20, epoch("2026-09-04"), "2026-09-21", 8),
        (2, 10, epoch("2026-09-01"), "2026-09-23", 9),
    )

    query = render_model(
        warehouse,
        "steam_review_versions",
        incremental=True,
        watermark="'2026-09-21'::timestamptz",
    )
    rows = warehouse.execute(
        "SELECT app_id, recommendation_id, CAST(updated_at AS DATE), "
        f"votes_up FROM ({query}) AS result ORDER BY 1, 2"
    ).fetchall()

    assert rows == [
        (1, 10, date(2026, 9, 5), 7),
        (2, 10, date(2026, 9, 1), 9),
    ]
