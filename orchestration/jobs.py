from dagster import AssetSelection, define_asset_job


daily_ingest_job = define_asset_job(
    name="daily_ingest_job",
    selection=AssetSelection.groups("ingest"),
    description="IGDB + recensement Steam.",
)

igdb_ingest_job = define_asset_job(
    name="igdb_ingest_job",
    selection=AssetSelection.assets("igdb_games"),
    description="IGDB seul (test scheduling).",
)


__all__ = [
    "daily_ingest_job",
    "igdb_ingest_job",
]
