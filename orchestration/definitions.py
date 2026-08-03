from dagster import Definitions, EnvVar
from dagster_dbt import DbtCliResource

from orchestration.dbt import definitions as dbt_steam_reviews
from orchestration.igdb import definitions as igdb
from orchestration.igdb.resources import IGDBResource
from orchestration.postgres import PostgresResource
from orchestration.project import dbt_steam_reviews_project
from orchestration.steam import definitions as steam
from orchestration.steam.resources import SteamResource

# Toutes les resources vivent ici ; les domaines ne portent que assets/jobs/schedules.
defs = Definitions.merge(
    igdb.defs,
    steam.defs,
    dbt_steam_reviews.defs,
    Definitions(
        resources={
            "postgres": PostgresResource(
                host=EnvVar("POSTGRES_HOST").get_value(),
                port=EnvVar.int("POSTGRES_PORT").get_value(),
                user=EnvVar("POSTGRES_USER").get_value(),
                password=EnvVar("POSTGRES_PASSWORD").get_value(),
                database=EnvVar("POSTGRES_DB").get_value(),
            ),
            "steam": SteamResource(),
            "igdb": IGDBResource(
                client_id=EnvVar("IGDB_CLIENT_ID").get_value(),
                client_secret=EnvVar("IGDB_CLIENT_SECRET").get_value(),
            ),
            "dbt": DbtCliResource(project_dir=dbt_steam_reviews_project),
        },
    ),
)
