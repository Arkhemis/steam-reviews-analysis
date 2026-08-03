from dagster import Definitions, load_assets_from_modules

from orchestration.igdb import assets
from orchestration.igdb.jobs import igdb_ingest_job
from orchestration.igdb.schedules import igdb_schedule

defs = Definitions(
    assets=load_assets_from_modules([assets]),
    jobs=[igdb_ingest_job],
    schedules=[igdb_schedule],
)
