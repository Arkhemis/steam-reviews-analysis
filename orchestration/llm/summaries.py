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

# Par polarité : les plus utiles et les plus drôles, sans doublon.
USEFUL_PER_SIDE = 25
FUNNY_PER_SIDE = 5
MAX_REVIEW_CHARS = 800
NUM_CTX = 24576
# Marge pour le gabarit et la réponse ; au-delà, Ollama tronque le début du prompt sans erreur.
MAX_PROMPT_TOKENS = NUM_CTX - 2048
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

PROMPT_TEMPLATE = """Steam reviews of one game ([+] recommended, [-] not recommended), in several languages:
{reviews}

Summarize what players say, based only on these reviews. Reviews marked "joke" are humorous:
use them only to gauge the mood, never as a pro or a con. Pros and cons are specific
fragments naming concrete features or issues, not full sentences. Answer in English, as JSON:
{{"summary": "<3-4 sentence paragraph>", "pros": ["<up to 5 short points>"], "cons": ["<up to 5 short points>"]}}"""

UPSERT_COLUMNS = (
    "app_id, summary, pros, cons, model, reviews_used, total_reviews_at_generation"
)

# (recommandée, retenue seulement pour son humour, texte)
Review = tuple[bool, bool, str]


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
    SELECT
        app_id,
        voted_up,
        useful_rank > {USEFUL_PER_SIDE} AS is_joke,
        left(review_text, {MAX_REVIEW_CHARS * 2})
    FROM (
        -- Places réparties entre langues au prorata de leur volume (Sainte-Laguë) :
        -- aucune langue ne monopolise l'échantillon, les langues > ~2 % y figurent.
        SELECT
            *,
            ROW_NUMBER() OVER (
                PARTITION BY app_id, voted_up
                ORDER BY (useful_rank_in_language - 0.5) / language_reviews, language
            ) AS useful_rank,
            ROW_NUMBER() OVER (
                PARTITION BY app_id, voted_up
                ORDER BY (funny_rank_in_language - 0.5) / language_reviews, language
            ) AS funny_rank
        FROM (
            SELECT
                h.app_id, h.voted_up, h.review_text, h.language,
                GREATEST(
                    CASE WHEN h.voted_up THEN l.total_positive
                         ELSE l.total_reviews - l.total_positive END,
                    1
                ) AS language_reviews,
                ROW_NUMBER() OVER (
                    PARTITION BY h.app_id, h.voted_up, h.language
                    ORDER BY h.weighted_vote_score DESC, h.votes_up DESC, h.recommendation_id
                ) AS useful_rank_in_language,
                ROW_NUMBER() OVER (
                    PARTITION BY h.app_id, h.voted_up, h.language
                    ORDER BY h.votes_funny DESC, h.recommendation_id
                ) AS funny_rank_in_language
            FROM marts.review_highlight AS h
            LEFT JOIN intermediate.language_review_score AS l
                ON l.app_id = h.app_id AND l.language = h.language
            WHERE h.app_id IN ({", ".join(map(str, app_ids))})
        ) AS by_language
    ) AS r
    WHERE useful_rank <= {USEFUL_PER_SIDE} OR funny_rank <= {FUNNY_PER_SIDE}
    ORDER BY app_id, voted_up DESC, LEAST(useful_rank, funny_rank), useful_rank
) TO STDOUT WITH (FORMAT csv);
"""


def estimate_tokens(text: str) -> int:
    # Un idéogramme CJK coûte environ un token, le reste environ un token pour 4 caractères.
    cjk = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", text))
    return cjk + (len(text) - cjk) // 4


def build_prompt(reviews: list[Review]) -> tuple[str, int]:
    """Renvoie le prompt et le nombre de reviews gardées sous MAX_PROMPT_TOKENS."""
    sides = {True: [], False: []}
    for voted_up, is_joke, text in reviews:
        text = re.sub(r"\s+", " ", text).strip()[:MAX_REVIEW_CHARS]
        tag = ("+" if voted_up else "-") + (" joke" if is_joke else "")
        sides[voted_up].append(f"[{tag}] {text}")
    # Retire la review la moins bien classée du côté le plus fourni.
    while (
        sum(estimate_tokens(line) for side in sides.values() for line in side)
        > MAX_PROMPT_TOKENS
    ):
        max(sides.values(), key=len).pop()
    lines = sides[True] + sides[False]
    return PROMPT_TEMPLATE.format(reviews="\n".join(lines)), len(lines)


def _points(value) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"liste de points attendue, reçu {value!r}")
    if not all(isinstance(p, str) and p.strip() for p in value):
        raise ValueError(f"point vide ou non textuel dans {value!r}")
    return [p.strip().rstrip(".") for p in value[:MAX_POINTS]]


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
            "options": {"num_ctx": NUM_CTX, "temperature": 0.3},
        },
        timeout=300,
    )
    response.raise_for_status()
    body = response.json()
    if body["prompt_eval_count"] >= NUM_CTX - 1024:
        raise ValueError(f"prompt tronqué ({body['prompt_eval_count']} tokens)")
    return body["response"]


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
        for app_id, voted_up, is_joke, text in csv.reader(io.StringIO(output)):
            reviews[int(app_id)].append((voted_up == "t", is_joke == "t", text))

        rows = []
        for app_id, total in batch:
            if not reviews[app_id]:
                log.warning(f"app_id={app_id} : aucune review dans review_highlight")
                stats["no_reviews"] += 1
                continue
            prompt, reviews_used = build_prompt(reviews[app_id])
            try:
                summary = parse_summary(generate(model, prompt))
            except (ValueError, httpx.HTTPError) as exc:
                log.warning(f"app_id={app_id} : génération en échec ({exc})")
                stats["failed"] += 1
                continue
            rows.append((app_id, summary, reviews_used, total))

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
