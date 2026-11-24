import itertools

from dagster import AssetExecutionContext, MaterializeResult, MetadataValue, asset

from orchestration.clickhouse import ClickHouseResource
from orchestration.console_stores.resources import ConsoleStoreResource

COLUMNS = ["average_rating", "rating_count", "platforms"]


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description=(
        "Notes des joueurs du PS Store (US) des jeux liés à Steam par IGDB, avec "
        "les plateformes du concept, un septième des concepts chaque jour -> raw.playstation_store_ratings."
    ),
)
def playstation_store_ratings(
    context: AssetExecutionContext,
    console_stores: ConsoleStoreResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    # Une page par concept : chacun n'est relu qu'une fois par semaine.
    concept_ids = [
        row["concept_id"]
        for row in clickhouse.query(
            """
            SELECT DISTINCT arrayJoin(playstation_concept_ids) AS concept_id
            FROM igdb_games
            WHERE cityHash64(concept_id) % 7 = toDayOfWeek(today()) - 1
            ORDER BY concept_id
            """
        )
    ]
    context.log.info(f"PS Store : {len(concept_ids)} concepts à lire")

    rows = []
    failed = 0
    for scanned, concept_id in enumerate(concept_ids, start=1):
        try:
            rating = console_stores.get_playstation_rating(concept_id)
        except Exception:
            context.log.exception(f"PS Store : concept {concept_id} en échec")
            failed += 1
            continue
        if rating:
            rows.append((concept_id, *rating))
        if len(rows) >= 500:
            clickhouse.insert(
                "playstation_store_ratings", rows, ["concept_id", *COLUMNS]
            )
            context.log.info(f"PS Store : {scanned}/{len(concept_ids)} concepts lus")
            rows = []
    clickhouse.insert("playstation_store_ratings", rows, ["concept_id", *COLUMNS])

    return MaterializeResult(
        metadata={
            "concepts_scanned": MetadataValue.int(len(concept_ids)),
            "concepts_failed": MetadataValue.int(failed),
        }
    )


@asset(
    group_name="ingest",
    deps=["igdb_games"],
    description=(
        "Notes des joueurs du Microsoft Store (US) des jeux liés à Steam par "
        "IGDB, avec les plateformes du produit -> raw.xbox_store_ratings."
    ),
)
def xbox_store_ratings(
    context: AssetExecutionContext,
    console_stores: ConsoleStoreResource,
    clickhouse: ClickHouseResource,
) -> MaterializeResult:
    product_ids = [
        row["product_id"]
        for row in clickhouse.query(
            """
            SELECT DISTINCT arrayJoin(xbox_product_ids) AS product_id
            FROM igdb_games
            ORDER BY product_id
            """
        )
    ]
    context.log.info(f"Microsoft Store : {len(product_ids)} produits à lire")

    rated = 0
    for batch in itertools.batched(product_ids, 100):
        ratings = console_stores.get_xbox_ratings(list(batch))
        clickhouse.insert(
            "xbox_store_ratings",
            [(product_id, *rating) for product_id, rating in ratings.items()],
            ["product_id", *COLUMNS],
        )
        rated += len(ratings)

    return MaterializeResult(
        metadata={
            "products_scanned": MetadataValue.int(len(product_ids)),
            "products_rated": MetadataValue.int(rated),
        }
    )
