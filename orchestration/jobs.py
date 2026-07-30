from dagster import AssetSelection, define_asset_job

igdb_ingest_job = define_asset_job(
    name="igdb_ingest_job",
    selection=AssetSelection.assets("igdb_games"),
    description="IGDB seul (test scheduling).",
)


__all__ = [
    "igdb_ingest_job",
]
