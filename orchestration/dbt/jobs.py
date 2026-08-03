import dagster as dg
from dagster_dbt import build_dbt_asset_selection

from orchestration.dbt import DbtRunConfig
from orchestration.dbt.assets import dbt_steam_reviews_models

# Les couches sont déjà taguées par dossier dans dbt/dbt_project.yml.
dbt_all = build_dbt_asset_selection([dbt_steam_reviews_models], dbt_select="fqn:*")


def _layer_selection(layer: str) -> dg.AssetSelection:
    return build_dbt_asset_selection(
        [dbt_steam_reviews_models], dbt_select=f"tag:{layer}"
    )


dbt_build_job = dg.define_asset_job(
    name="dbt_build",
    selection=dbt_all,
    description="Matérialise tout le projet dbt (modèles + tests).",
)

dbt_staging_job = dg.define_asset_job(
    name="dbt_staging",
    selection=_layer_selection("staging"),
    description="Matérialise la couche staging seule.",
)

dbt_intermediate_job = dg.define_asset_job(
    name="dbt_intermediate",
    selection=_layer_selection("intermediate"),
    description="Matérialise la couche intermediate seule.",
)

dbt_marts_job = dg.define_asset_job(
    name="dbt_marts",
    selection=_layer_selection("marts"),
    description="Matérialise la couche marts seule.",
)

dbt_full_refresh_job = dg.define_asset_job(
    name="dbt_full_refresh",
    selection=dbt_all,
    description="Matérialise tout le projet dbt en full refresh.",
    config=dg.RunConfig(
        ops={"dbt_steam_reviews_models": DbtRunConfig(full_refresh=True)},
    ),
)


__all__ = [
    "dbt_build_job",
    "dbt_full_refresh_job",
    "dbt_intermediate_job",
    "dbt_marts_job",
    "dbt_staging_job",
]
