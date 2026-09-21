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
    prompt, kept = build_prompt(
        [(True, False, "Great\n\n  game"), (False, False, "x" * 2000)]
    )

    assert "[+] Great game" in prompt
    assert f"[-] {'x' * summaries.MAX_REVIEW_CHARS}\n" in prompt + "\n"
    assert "x" * (summaries.MAX_REVIEW_CHARS + 1) not in prompt
    assert kept == 2


def test_build_prompt_drops_lowest_ranked_reviews_of_the_larger_side_over_budget(
    monkeypatch,
):
    monkeypatch.setattr(summaries, "MAX_PROMPT_TOKENS", 4)
    # Chaque ligne, préfixe "[±] " compris, est estimée à 2 tokens.
    reviews = [
        (True, False, "good"),
        (True, False, "fine"),
        (True, False, "late"),
        (False, False, "差"),
        (False, False, "bad!"),
    ]

    prompt, kept = build_prompt(reviews)

    assert kept == 2
    assert "[+] good" in prompt and "[-] 差" in prompt
    assert "late" not in prompt and "bad!" not in prompt


def test_build_prompt_tags_reviews_kept_only_for_their_humor():
    prompt, _ = build_prompt(
        [(True, True, "10/10 would crash again"), (False, False, "Bugs")]
    )

    assert "[+ joke] 10/10 would crash again" in prompt
    assert "[-] Bugs" in prompt


def test_select_reviews_sql_apportions_useful_and_funniest_by_language_volume():
    sql = summaries.select_reviews_sql([730, 570])

    assert "WHERE h.app_id IN (730, 570)" in sql
    assert "(useful_rank_in_language - 0.5) / language_reviews" in sql
    assert f"useful_rank > {summaries.USEFUL_PER_SIDE} AS is_joke" in sql
    assert f"useful_rank <= {summaries.USEFUL_PER_SIDE}" in sql
    assert f"OR funny_rank <= {summaries.FUNNY_PER_SIDE}" in sql


def test_ollama_generate_rejects_a_prompt_that_filled_the_context(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "prompt_eval_count": summaries.NUM_CTX,
                "response": valid_response(),
            }

    monkeypatch.setattr(summaries.httpx, "post", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(ValueError, match="tronqué"):
        summaries.ollama_generate("m", "prompt")


def test_parse_summary_accepts_a_valid_response_and_caps_lists():
    summary = parse_summary(valid_response(pros=[f"p{i}" for i in range(8)]))

    assert summary == Summary(
        "Players love it.", [f"p{i}" for i in range(5)], ["Short"]
    )


def test_parse_summary_strips_trailing_periods_from_points():
    summary = parse_summary(valid_response(pros=["Great story."], cons=["Bugs"]))

    assert summary.pros == ["Great story"]


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
            return '1,t,f,Good\n1,f,f,Bad\n2,t,t,"Nice, really"\n2,f,f,Meh\n'
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
