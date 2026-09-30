"""Assets dbt du projet steam-reviews."""

from collections.abc import Mapping
from typing import Any

import dagster as dg
from dagster_dbt import (
    DagsterDbtTranslator,
    DagsterDbtTranslatorSettings,
    DbtCliResource,
    dbt_assets,
)
from dagster_dbt.asset_utils import group_from_dbt_resource_props_fallback_to_directory

from orchestration.project import dbt_steam_reviews_project


class DbtRunConfig(dg.Config):
    full_refresh: bool = False


class LayerGroupedDbtTranslator(DagsterDbtTranslator):
    """Sans préfixe de clé : il casserait le rattachement des sources aux assets d'ingestion."""

    def __init__(self) -> None:
        # Sinon les tests de sources remontent en observations, pas en asset checks.
        super().__init__(
            DagsterDbtTranslatorSettings(enable_source_tests_as_checks=True)
        )

    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
        return group_from_dbt_resource_props_fallback_to_directory(dbt_resource_props)


# Joignent deux branches d'ingestion : dans la définition principale, tout leur step les attendrait.
BRIDGE_MODELS = "game_detail game_event_highlight"


def _dbt_build(
    context: dg.AssetExecutionContext, dbt: DbtCliResource, config: DbtRunConfig
):
    args = ["build", "--full-refresh"] if config.full_refresh else ["build"]
    yield from dbt.cli(args, context=context).stream()


@dbt_assets(
    manifest=dbt_steam_reviews_project.manifest_path,
    dagster_dbt_translator=LayerGroupedDbtTranslator(),
    # Sélections disjointes : un nœud dbt ne peut appartenir qu'à une définition.
    select="fqn:*",
    exclude=f"resource_type:seed {BRIDGE_MODELS}",
)
def dbt_steam_reviews_models(
    context: dg.AssetExecutionContext,
    dbt: DbtCliResource,
    config: DbtRunConfig,
):
    yield from _dbt_build(context, dbt, config)


@dbt_assets(
    manifest=dbt_steam_reviews_project.manifest_path,
    dagster_dbt_translator=LayerGroupedDbtTranslator(),
    select=BRIDGE_MODELS,
)
def dbt_steam_reviews_bridge_models(
    context: dg.AssetExecutionContext,
    dbt: DbtCliResource,
    config: DbtRunConfig,
):
    yield from _dbt_build(context, dbt, config)
