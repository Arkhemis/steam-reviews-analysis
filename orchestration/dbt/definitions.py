from dagster import Definitions

from orchestration.dbt.assets import dbt_steam_reviews_models
from orchestration.dbt.jobs import (
    dbt_build_job,
    dbt_full_refresh_job,
    dbt_intermediate_job,
    dbt_marts_job,
    dbt_staging_job,
)

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
