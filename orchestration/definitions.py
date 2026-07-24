from dagster import Definitions, EnvVar, load_assets_from_modules

from orchestration.assets import igdb, steam_census
from orchestration.jobs import daily_ingest_job
from orchestration.resources import IGDBResource, PostgresResource, SteamResource
from orchestration.schedules import schedules

ingest_assets = load_assets_from_modules([igdb, steam_census])

postgres_resource = PostgresResource(
    host=EnvVar("POSTGRES_HOST").get_value(),
    port=EnvVar.int("POSTGRES_PORT").get_value(),
    user=EnvVar("POSTGRES_USER").get_value(),
    password=EnvVar("POSTGRES_PASSWORD").get_value(),
    database=EnvVar("POSTGRES_DB").get_value(),
)

steam_resource = SteamResource()

igdb_resource = IGDBResource(
    client_id=EnvVar("IGDB_CLIENT_ID").get_value(),
    client_secret=EnvVar("IGDB_CLIENT_SECRET").get_value(),
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
