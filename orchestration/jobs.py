from dagster import AssetSelection, define_asset_job


daily_ingest_job = define_asset_job(
    name="daily_ingest_job",
    selection=AssetSelection.groups("ingest"),
    description="IGDB + recensement Steam.",
)


__all__ = [
    "daily_ingest_job",
]
