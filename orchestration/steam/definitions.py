from dagster import Definitions, load_assets_from_modules

from orchestration.steam import backfill, census, incremental

# Recensement, backfill et incrémental restent séparés dans le même domaine.
defs = Definitions(
    assets=load_assets_from_modules([census, backfill, incremental]),
)
