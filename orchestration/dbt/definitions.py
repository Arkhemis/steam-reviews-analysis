from dagster import Definitions

from orchestration.dbt_steam_reviews.assets import dbt_steam_reviews_models
from orchestration.dbt_steam_reviews.jobs import (
    dbt_build_job,
    dbt_full_refresh_job,
    dbt_intermediate_job,
    dbt_marts_job,
    dbt_staging_job,
)

# Pas de schedule ici : la cadence de rafraîchissement des marts reste à décider.
defs = Definitions(
    assets=[dbt_steam_reviews_models],
    jobs=[
        dbt_build_job,
        dbt_staging_job,
        dbt_intermediate_job,
        dbt_marts_job,
        dbt_full_refresh_job,
    ],
)
