from dagster import Definitions, EnvVar, load_assets_from_modules

from orchestration.assets import igdb, steam_census
from orchestration.jobs import daily_ingest_job
from orchestration.resources import IGDBResource, PostgresResource, SteamResource
from orchestration.schedules import schedules

ingest_assets = load_assets_from_modules([igdb, steam_census])

postgres_resource = PostgresResource(
    host=EnvVar("POSTGRES_HOST"),
    port=EnvVar.int("POSTGRES_PORT"),
    user=EnvVar("POSTGRES_USER"),
    password=EnvVar("POSTGRES_PASSWORD"),
    database=EnvVar("POSTGRES_DB"),
)

steam_resource = SteamResource()

igdb_resource = IGDBResource(
    client_id=EnvVar("IGDB_CLIENT_ID"),
    client_secret=EnvVar("IGDB_CLIENT_SECRET"),
)

defs = Definitions(
    assets=[*ingest_assets],
    jobs=[daily_ingest_job],
    schedules=schedules,
    resources={
        "postgres": postgres_resource,
        "steam": steam_resource,
        "igdb": igdb_resource,
    },
)
