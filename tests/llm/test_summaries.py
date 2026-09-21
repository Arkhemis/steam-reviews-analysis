"""Résumés LLM : prompt, validation de la réponse et SQL envoyé à psql, sans réseau ni modèle."""

import csv
import io
import json

import pytest

from orchestration.llm import summaries
from orchestration.llm.summaries import (
    Summary,
    build_prompt,
    parse_summary,
    select_games_sql,
    to_pg_array,
    upsert_sql,
)


def valid_response(**overrides) -> str:
    payload = {"summary": "Players love it.", "pros": ["Fun"], "cons": ["Short"]}
    return json.dumps(payload | overrides)


def test_build_prompt_marks_polarity_and_truncates_normalized_text():
    prompt = build_prompt([(True, "Great\n\n  game"), (False, "x" * 2000)])

    assert "[+] Great game" in prompt
    assert f"[-] {'x' * summaries.MAX_REVIEW_CHARS}\n" in prompt + "\n"
    assert "x" * (summaries.MAX_REVIEW_CHARS + 1) not in prompt


def test_parse_summary_accepts_a_valid_response_and_caps_lists():
    summary = parse_summary(valid_response(pros=[f"p{i}" for i in range(8)]))

    assert summary == Summary(
        "Players love it.", [f"p{i}" for i in range(5)], ["Short"]
    )


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        json.dumps(["a list"]),
        valid_response(summary=""),
        valid_response(pros=[]),
        valid_response(cons="Short"),
        valid_response(cons=["ok", "  "]),
    ],
)
def test_parse_summary_rejects_malformed_responses(raw):
    with pytest.raises(ValueError):
        parse_summary(raw)


def test_to_pg_array_escapes_quotes_and_backslashes():
    assert (
        to_pg_array(['say "hi"', "a\\b", "x, {y}"]) == r'{"say \"hi\"","a\\b","x, {y}"}'
    )


def test_upsert_sql_embeds_csv_rows_readable_by_copy():
    sql = upsert_sql(
        [(730, Summary('A "quoted", summary', ["Fun, fast"], ["Bugs"]), 40, 1000)],
        "qwen3:8b",
    )

    data = sql.split("FROM STDIN WITH (FORMAT csv);\n")[1].split("\n\\.\n")[0]
    row = next(csv.reader(io.StringIO(data)))
    assert row == [
        "730",
        'A "quoted", summary',
        '{"Fun, fast"}',
        '{"Bugs"}',
        "qwen3:8b",
        "40",
        "1000",
    ]
    assert "ON CONFLICT (app_id) DO UPDATE" in sql


def test_select_games_sql_requires_both_sides_and_regenerates_after_growth():
    sql = select_games_sql(min_per_side=250, limit=10)

    assert "total_positive >= 250" in sql
    assert "total_reviews - c.total_positive >= 250" in sql
    assert f"* {summaries.REGENERATE_GROWTH}" in sql
    assert "LIMIT 10" in sql


def test_run_skips_failed_games_and_upserts_the_rest():
    scripts = []

    def fake_psql(sql: str) -> str:
        scripts.append(sql)
        if "FROM staging.game_review_count" in sql:
            return "1,500\n2,600\n3,700\n"
        if "FROM marts.review_highlight" in sql:
            # Le jeu 3 n'a aucune review éligible dans review_highlight.
            return '1,t,Good\n1,f,Bad\n2,t,"Nice, really"\n2,f,Meh\n'
        return ""

    responses = iter([valid_response(), "broken"])
    stats = summaries.run(
        min_per_side=250,
        limit=None,
        batch_size=10,
        model="m",
        run_psql=fake_psql,
        generate=lambda model, prompt: next(responses),
    )

    upserts = [s for s in scripts if "INSERT INTO raw.game_review_summaries" in s]
    assert len(upserts) == 1
    assert "\n1,Players love it." in upserts[0]
    assert stats == {"generated": 1, "failed": 1, "no_reviews": 1}
