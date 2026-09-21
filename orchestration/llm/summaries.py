"""Résumés LLM des reviews par jeu : générés en local par Ollama, lus et écrits en prod via ssh + psql.

Lancement : uv run python -m orchestration.llm.summaries --limit 20
"""

import argparse
import csv
import io
import itertools
import json
import logging
import re
import subprocess
import time
from collections import defaultdict
from collections.abc import Callable
from typing import NamedTuple

import httpx

log = logging.getLogger(__name__)

DEFAULT_HOST = "deploy@167.235.145.180"
DEFAULT_MODEL = "qwen3:8b"
OLLAMA_URL = "http://localhost:11434/api/generate"

REVIEWS_PER_SIDE = 20
MAX_REVIEW_CHARS = 800
MAX_POINTS = 5
# Un résumé est régénéré quand le jeu a pris 25 % de reviews depuis.
REGENERATE_GROWTH = 1.25

# Pas de port exposé ni de mot de passe prod en local : psql tourne dans le conteneur.
REMOTE_PSQL = (
    "cd ~/apps/steam-reviews-analysis && docker compose exec -T postgres "
    'sh -c \'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -qAt -v ON_ERROR_STOP=1\''
)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS raw.game_review_summaries (
    app_id                      BIGINT PRIMARY KEY,
    summary                     TEXT   NOT NULL,
    pros                        TEXT[] NOT NULL,
    cons                        TEXT[] NOT NULL,
    model                       TEXT   NOT NULL,
    reviews_used                INT    NOT NULL,
    total_reviews_at_generation BIGINT NOT NULL,
    generated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

PROMPT_TEMPLATE = """Steam reviews of one game ([+] recommended, [-] not recommended):
{reviews}

Summarize what players say, based only on these reviews. Answer in English, as JSON:
{{"summary": "<3-4 sentence paragraph>", "pros": ["<up to 5 short points>"], "cons": ["<up to 5 short points>"]}}"""

UPSERT_COLUMNS = (
    "app_id, summary, pros, cons, model, reviews_used, total_reviews_at_generation"
)

Review = tuple[bool, str]


class Summary(NamedTuple):
    summary: str
    pros: list[str]
    cons: list[str]


def select_games_sql(min_per_side: int, limit: int | None) -> str:
    return f"""
COPY (
    SELECT c.steam_app_id, c.total_reviews
    FROM staging.game_review_count AS c
    LEFT JOIN raw.game_review_summaries AS s ON s.app_id = c.steam_app_id
    WHERE
        c.total_positive >= {min_per_side}
        AND c.total_reviews - c.total_positive >= {min_per_side}
        AND (s.app_id IS NULL OR c.total_reviews > s.total_reviews_at_generation * {REGENERATE_GROWTH})
    ORDER BY c.total_reviews DESC
    {f"LIMIT {limit}" if limit else ""}
) TO STDOUT WITH (FORMAT csv);
"""


def select_reviews_sql(app_ids: list[int]) -> str:
    return f"""
COPY (
    SELECT app_id, voted_up, left(review_text, {MAX_REVIEW_CHARS * 2})
    FROM (
        SELECT
            app_id, voted_up, review_text,
            ROW_NUMBER() OVER (
                PARTITION BY app_id, voted_up
                ORDER BY weighted_vote_score DESC, votes_up DESC, recommendation_id
            ) AS rank_in_side
        FROM marts.review_highlight
        WHERE app_id IN ({", ".join(map(str, app_ids))})
    ) AS r
    WHERE rank_in_side <= {REVIEWS_PER_SIDE}
    ORDER BY app_id, voted_up DESC, rank_in_side
) TO STDOUT WITH (FORMAT csv);
"""


def build_prompt(reviews: list[Review]) -> str:
    lines = []
    for voted_up, text in reviews:
        text = re.sub(r"\s+", " ", text).strip()[:MAX_REVIEW_CHARS]
        lines.append(f"[{'+' if voted_up else '-'}] {text}")
    return PROMPT_TEMPLATE.format(reviews="\n".join(lines))


def _points(value) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"liste de points attendue, reçu {value!r}")
    if not all(isinstance(p, str) and p.strip() for p in value):
        raise ValueError(f"point vide ou non textuel dans {value!r}")
    return [p.strip() for p in value[:MAX_POINTS]]


def parse_summary(raw: str) -> Summary:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"réponse non JSON : {raw[:200]!r}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"objet JSON attendu, reçu {type(data).__name__}")
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("résumé vide")
    return Summary(
        summary.strip(), _points(data.get("pros")), _points(data.get("cons"))
    )


def to_pg_array(items: list[str]) -> str:
    quoted = (item.replace("\\", "\\\\").replace('"', '\\"') for item in items)
    return "{" + ",".join(f'"{item}"' for item in quoted) + "}"


def upsert_sql(rows: list[tuple[int, Summary, int, int]], model: str) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    for app_id, s, reviews_used, total_reviews in rows:
        writer.writerow(
            [
                app_id,
                s.summary,
                to_pg_array(s.pros),
                to_pg_array(s.cons),
                model,
                reviews_used,
                total_reviews,
            ]
        )
    return f"""
BEGIN;
CREATE TEMP TABLE incoming (LIKE raw.game_review_summaries INCLUDING DEFAULTS) ON COMMIT DROP;
COPY incoming ({UPSERT_COLUMNS}) FROM STDIN WITH (FORMAT csv);
{buffer.getvalue()}\\.
INSERT INTO raw.game_review_summaries ({UPSERT_COLUMNS})
SELECT {UPSERT_COLUMNS} FROM incoming
ON CONFLICT (app_id) DO UPDATE
SET summary                     = EXCLUDED.summary,
    pros                        = EXCLUDED.pros,
    cons                        = EXCLUDED.cons,
    model                       = EXCLUDED.model,
    reviews_used                = EXCLUDED.reviews_used,
    total_reviews_at_generation = EXCLUDED.total_reviews_at_generation,
    generated_at                = now();
COMMIT;
"""


def ssh_psql(host: str) -> Callable[[str], str]:
    def run_psql(sql: str) -> str:
        result = subprocess.run(
            ["ssh", host, REMOTE_PSQL],
            input=sql,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"psql distant en échec : {result.stderr.strip()}")
        return result.stdout

    return run_psql


def ollama_generate(model: str, prompt: str) -> str:
    response = httpx.post(
        OLLAMA_URL,
        json={
            "model": model,
            "prompt": prompt,
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"num_ctx": 8192, "temperature": 0.3},
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()["response"]


def run(
    min_per_side: int,
    limit: int | None,
    batch_size: int,
    model: str,
    run_psql: Callable[[str], str],
    generate: Callable[[str, str], str],
) -> dict[str, int]:
    run_psql(CREATE_TABLE_SQL)
    games = [
        (int(app_id), int(total))
        for app_id, total in csv.reader(
            io.StringIO(run_psql(select_games_sql(min_per_side, limit)))
        )
    ]
    log.info(f"{len(games)} jeux à résumer (≥ {min_per_side} reviews de chaque côté)")

    stats = {"generated": 0, "failed": 0, "no_reviews": 0}
    start = time.monotonic()
    for batch in itertools.batched(games, batch_size):
        reviews: dict[int, list[Review]] = defaultdict(list)
        output = run_psql(select_reviews_sql([app_id for app_id, _ in batch]))
        for app_id, voted_up, text in csv.reader(io.StringIO(output)):
            reviews[int(app_id)].append((voted_up == "t", text))

        rows = []
        for app_id, total in batch:
            if not reviews[app_id]:
                log.warning(f"app_id={app_id} : aucune review dans review_highlight")
                stats["no_reviews"] += 1
                continue
            try:
                summary = parse_summary(generate(model, build_prompt(reviews[app_id])))
            except (ValueError, httpx.HTTPError) as exc:
                log.warning(f"app_id={app_id} : génération en échec ({exc})")
                stats["failed"] += 1
                continue
            rows.append((app_id, summary, len(reviews[app_id]), total))

        if rows:
            run_psql(upsert_sql(rows, model))
        stats["generated"] += len(rows)
        done = sum(stats.values())
        log.info(
            f"{done}/{len(games)} — {done / (time.monotonic() - start):.2f} jeux/s — {stats}"
        )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--min-per-side", type=int, default=250)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--host", default=DEFAULT_HOST, help="cible ssh du VPS de prod")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run(
        min_per_side=args.min_per_side,
        limit=args.limit,
        batch_size=args.batch_size,
        model=args.model,
        run_psql=ssh_psql(args.host),
        generate=ollama_generate,
    )


if __name__ == "__main__":
    main()
