from dagster import AssetSelection, define_asset_job



igdb_ingest_job = define_asset_job(
    name="igdb_ingest_job",
    selection=AssetSelection.assets("igdb_games"),
    description="IGDB seul (test scheduling).",
)


__all__ = [
    "daily_ingest_job",
    "igdb_ingest_job",
]
