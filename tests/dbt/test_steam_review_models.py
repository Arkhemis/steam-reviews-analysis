"""Modèle staging.steam_review rendu par Jinja, joué dans chDB (ClickHouse embarqué).

Même moteur que la prod : ReplacingMergeTree, type JSON et regex RE2 sont
exercés tels quels, sans serveur ni run dbt.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from chdb import session
from jinja2 import Environment, StrictUndefined

from tests.conftest import raw_ddl

DBT = Path(__file__).resolve().parents[2] / "dbt"
MACROS = ["steam_review_parse.sql", "has_profanity.sql"]
ENV = Environment(undefined=StrictUndefined, extensions=["jinja2.ext.do"])


def render_model(*, incremental: bool) -> tuple[str, dict]:
    """SQL du modèle et sa config dbt."""
    config: dict = {}
    source = "".join((DBT / "macros" / m).read_text() for m in MACROS)
    source += (DBT / "models" / "staging" / "steam_review.sql").read_text()
    sql = ENV.from_string(source).render(
        config=lambda **kwargs: config.update(kwargs) or "",
        source=lambda schema, table: f"{schema}.{table}",
        this="staging.steam_review",
        is_incremental=lambda: incremental,
    )
    return sql, config


@pytest.fixture
def warehouse():
    sess = session.Session()
    for stmt in raw_ddl("raw"):
        sess.query(stmt)
    sess.query("CREATE DATABASE staging")
    try:
        yield sess
    finally:
        sess.close()


def add_raw_reviews(warehouse, *rows) -> None:
    """Lignes : jeu, review, jour de mise à jour, jour de chargement, payload."""
    values = [
        {
            "recommendation_id": recommendation_id,
            "app_id": app_id,
            "payload": payload,
            "timestamp_created": epoch(updated_on),
            "timestamp_updated": epoch(updated_on),
            "loaded_at": f"{loaded_on} 00:00:00",
        }
        for app_id, recommendation_id, updated_on, loaded_on, payload in rows
    ]
    warehouse.query(
        "INSERT INTO raw.steam_reviews FORMAT JSONEachRow\n"
        + "\n".join(json.dumps(v) for v in values)
    )


def epoch(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp())


def build(warehouse, *, incremental: bool) -> None:
    """Premier build (CREATE + INSERT) ou passage incrémental (INSERT), comme dbt."""
    sql, config = render_model(incremental=incremental)
    if not incremental:
        warehouse.query(
            f"CREATE TABLE staging.steam_review ENGINE = {config['engine']} "
            f"ORDER BY {config['order_by']} EMPTY AS {sql}"
        )
    warehouse.query(f"INSERT INTO staging.steam_review {sql} SETTINGS final = 0")


def reviews(warehouse, columns: str) -> list[dict]:
    result = warehouse.query(
        f"SELECT {columns} FROM staging.steam_review FINAL "
        "ORDER BY app_id, recommendation_id",
        "JSONEachRow",
    )
    return [json.loads(line) for line in result.data().splitlines()]


def review(**fields) -> dict:
    return {"review": "A useful review", "voted_up": True, **fields}


def test_first_build_keeps_latest_update_then_latest_capture(warehouse) -> None:
    add_raw_reviews(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-02", review(votes_up=1)),
        (1, 10, "2026-09-05", "2026-09-06", review(votes_up=2)),
        # Même version recapturée plus tard : la dernière capture gagne.
        (1, 10, "2026-09-05", "2026-09-07", review(votes_up=3)),
        (2, 10, "2026-09-01", "2026-09-03", review(votes_up=4, votes_funny=4294967295)),
    )

    build(warehouse, incremental=False)

    assert reviews(warehouse, "app_id, recommendation_id, votes_up, votes_funny") == [
        {"app_id": 1, "recommendation_id": 10, "votes_up": 3, "votes_funny": None},
        # uint32 de Steam ramené à sa valeur signée.
        {"app_id": 2, "recommendation_id": 10, "votes_up": 4, "votes_funny": -1},
    ]


def test_incremental_rereads_the_overlap_without_duplicates(warehouse) -> None:
    add_raw_reviews(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-20", review(votes_up=1)),
        (1, 20, "2026-09-01", "2026-09-21", review(votes_up=5)),
    )
    build(warehouse, incremental=False)
    add_raw_reviews(
        warehouse,
        (1, 10, "2026-09-05", "2026-09-22", review(votes_up=2)),
        (2, 10, "2026-09-01", "2026-09-22", review(votes_up=9)),
    )

    # Deux passages : le second relit la marge de 2 jours.
    build(warehouse, incremental=True)
    build(warehouse, incremental=True)

    assert reviews(warehouse, "app_id, recommendation_id, votes_up") == [
        {"app_id": 1, "recommendation_id": 10, "votes_up": 2},
        {"app_id": 1, "recommendation_id": 20, "votes_up": 5},
        {"app_id": 2, "recommendation_id": 10, "votes_up": 9},
    ]


def test_parses_payload_types_and_absent_keys(warehouse) -> None:
    add_raw_reviews(
        warehouse,
        (
            1,
            10,
            "2026-09-01",
            "2026-09-02",
            review(
                author={"steamid": "76561198000000001", "playtime_forever": 90},
                weighted_vote_score="0.523809552192687988",
                app_release_date=1700000000.5,
                review="☐ Graphics ✅ Good",
            ),
        ),
        # Clés absentes (le type JSON supprime aussi les null) : NULL.
        (1, 11, "2026-09-01", "2026-09-02", {"language": "english"}),
    )

    build(warehouse, incremental=False)

    assert reviews(
        warehouse,
        "recommendation_id, author_steamid, author_playtime_forever_minutes, "
        "weighted_vote_score, app_release_date, review_text_length, is_generic, voted_up",
    ) == [
        {
            "recommendation_id": 10,
            "author_steamid": 76561198000000001,
            "author_playtime_forever_minutes": 90,
            "weighted_vote_score": 0.523809552192687988,
            "app_release_date": "2023-11-14 22:13:20.500",
            "review_text_length": 17,
            "is_generic": True,
            "voted_up": True,
        },
        {
            "recommendation_id": 11,
            "author_steamid": None,
            "author_playtime_forever_minutes": None,
            "weighted_vote_score": None,
            "app_release_date": None,
            "review_text_length": None,
            "is_generic": False,
            "voted_up": None,
        },
    ]


@pytest.mark.parametrize(
    ("language", "text", "expected"),
    [
        ("english", "This game is shit.", True),
        ("english", "SHIT!", True),
        # Pluriel accepté, mot plus long refusé : frontières de mot.
        ("english", "total bastards", True),
        ("english", "a classic shitake recipe", False),
        ("english", "Scunthorpe", False),
        ("english", "♥♥♥♥ this", True),
        # Accents perdus en capitales.
        ("french", "ENCULES", True),
        # Turc : RE2 ne rapproche pas İ de i sans la classe dédiée.
        ("turkish", "ZENCİ", True),
        # Faux ami : « hell » est un mot ordinaire en allemand.
        ("german", "Das Spiel ist hell", False),
        ("german", "Scheiße", True),
        # Langue sans liste : les gros mots anglais servent de repli.
        ("unknownlang", "fuck", True),
        # Langue collée : pas de frontière de mot.
        ("schinese", "这游戏是垃圾啊", True),
        ("english", None, False),
    ],
)
def test_has_profanity(warehouse, language, text, expected) -> None:
    add_raw_reviews(
        warehouse,
        (1, 10, "2026-09-01", "2026-09-02", {"language": language, "review": text}),
    )

    build(warehouse, incremental=False)

    assert reviews(warehouse, "has_profanity") == [{"has_profanity": expected}]
