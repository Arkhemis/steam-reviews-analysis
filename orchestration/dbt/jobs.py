import dagster as dg
from dagster_dbt import build_dbt_asset_selection

from orchestration.dbt.assets import (
    DbtRunConfig,
    dbt_steam_reviews_bridge_models,
    dbt_steam_reviews_models,
)


def _dbt_selection(dbt_select: str) -> dg.AssetSelection:
    # build_dbt_asset_selection n'accepte qu'une définition à la fois.
    return build_dbt_asset_selection(
        [dbt_steam_reviews_models], dbt_select=dbt_select
    ) | build_dbt_asset_selection(
        [dbt_steam_reviews_bridge_models], dbt_select=dbt_select
    )


# Les couches sont déjà taguées par dossier dans dbt/dbt_project.yml.
dbt_all = _dbt_selection("fqn:*")


def _layer_selection(layer: str) -> dg.AssetSelection:
    return _dbt_selection(f"tag:{layer}")


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
        ops={
            op: DbtRunConfig(full_refresh=True)
            for op in ("dbt_steam_reviews_models", "dbt_steam_reviews_bridge_models")
        },
    ),
)


__all__ = [
    "dbt_build_job",
    "dbt_full_refresh_job",
    "dbt_intermediate_job",
    "dbt_marts_job",
    "dbt_staging_job",
]
