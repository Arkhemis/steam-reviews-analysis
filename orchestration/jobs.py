from dagster import AssetSelection, define_asset_job



daily_ingest_job = define_asset_job(
    name="daily_ingest_job",
    selection=AssetSelection.groups("ingest"),
    description="IGDB + recensement Steam + init de l'état de collecte.",
)


__all__ = [
    "daily_ingest_job",
    "steam_reviews_backfill_job",
    "steam_reviews_incremental_job",
]
