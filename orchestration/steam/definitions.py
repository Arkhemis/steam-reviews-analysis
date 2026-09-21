from dagster import Definitions, load_assets_from_modules

from orchestration.steam import backfill, census, events, game_details, incremental
from orchestration.steam.jobs import (
    steam_census_full_refresh_job,
    steam_events_full_refresh_job,
)

# Recensement, backfill, incrémental, annonces et fiches restent séparés dans le même domaine.
defs = Definitions(
    assets=load_assets_from_modules(
        [census, backfill, incremental, events, game_details]
    ),
    jobs=[steam_census_full_refresh_job, steam_events_full_refresh_job],
)
