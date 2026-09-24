"""Compaction de staging.steam_review_versions (macro dbt `compact_steam_review`).

Lancée juste avant le `dbt build` qui append le delta : versions et registre repartent
de la dernière version de chaque review, sans pic disque.
"""

from collections.abc import Iterator

import dagster as dg
from dagster_dbt import DbtCliResource

from orchestration.postgres import PostgresResource

# Vers 3,5 M lignes (~70 o par entrée), le hash de l'anti-join de la vue déborde
# de work_mem × hash_mem_multiplier (256 Mo) : environ une compaction tous les 10 mois.
COMPACTION_THRESHOLD = 3_000_000

VERSIONS_KEY = dg.AssetKey("steam_review_versions")
OUTDATED_KEY = dg.AssetKey("steam_review_outdated")

OUTDATED_EXISTS_SQL = (
    "SELECT to_regclass('staging.steam_review_outdated') IS NOT NULL AS exists"
)
COUNT_OUTDATED_SQL = "SELECT count(*) AS n FROM staging.steam_review_outdated"


def count_outdated(postgres: PostgresResource) -> int | None:
    """Return the outdated review row count, or ``None`` if the table is absent.

    Database query errors propagate to the caller.
    """
    if not postgres.fetch_all(OUTDATED_EXISTS_SQL)[0]["exists"]:
        return None
    return postgres.fetch_all(COUNT_OUTDATED_SQL)[0]["n"]


def compact_steam_review_if_needed(
    context: dg.AssetExecutionContext,
    dbt: DbtCliResource,
    postgres: PostgresResource,
    force: bool,
) -> Iterator[dg.AssetObservation]:
    """Compact review versions when the outdated row count exceeds the threshold.

    ``force`` requests compaction at any row count, but only when the versions
    asset is selected and the outdated table exists. The threshold is exclusive.
    Yield an observation with the pre-compaction count and decision in that case;
    otherwise yield nothing. Registry query and dbt operation errors propagate.
    """
    if VERSIONS_KEY not in context.selected_asset_keys:
        return

    outdated_rows = count_outdated(postgres)
    if outdated_rows is None:
        return

    compacted = force or outdated_rows > COMPACTION_THRESHOLD
    if compacted:
        context.log.info(
            f"Compaction de steam_review_versions : {outdated_rows} versions périmées "
            f"(seuil {COMPACTION_THRESHOLD}, forcée={force})"
        )
        dbt.cli(["run-operation", "compact_steam_review"]).wait()

    yield dg.AssetObservation(
        asset_key=OUTDATED_KEY,
        metadata={
            "outdated_rows": outdated_rows,
            "compaction_threshold": COMPACTION_THRESHOLD,
            "compacted": compacted,
        },
    )
