from dagster import Definitions, load_assets_from_modules

from orchestration.steam import backfill, census

# Recensement et backfill sont deux concerns distincts : deux modules, un domaine.
defs = Definitions(
    assets=load_assets_from_modules([census, backfill]),
)
