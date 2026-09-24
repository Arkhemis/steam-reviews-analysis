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

from orchestration.dbt.compaction import compact_steam_review_if_needed
from orchestration.postgres import PostgresResource
from orchestration.project import dbt_steam_reviews_project


class DbtRunConfig(dg.Config):
    """Exposé dans le Launchpad : permet un full refresh sans job dédié."""

    full_refresh: bool = False


class LayerGroupedDbtTranslator(DagsterDbtTranslator):
    """Groupe les assets dbt par sous-dossier de models/ : staging, intermediate, marts.

    Pas de préfixe de clé d'asset (contrairement à BaseDbtTranslator côté picta) :
    le préfixe s'appliquerait aussi aux sources et casserait leur rattachement aux
    assets d'ingestion déclaré dans dbt/models/sources.yml.
    """

    def __init__(self) -> None:
        # Sans ce réglage, les tests déclarés sur les sources remontent en
        # observations plutôt qu'en asset checks.
        super().__init__(
            DagsterDbtTranslatorSettings(enable_source_tests_as_checks=True)
        )

    def get_group_name(self, dbt_resource_props: Mapping[str, Any]) -> str | None:
        return group_from_dbt_resource_props_fallback_to_directory(dbt_resource_props)


# Modèles qui joignent deux branches d'ingestion. Dagster découpe une définition
# en steps par profondeur d'ingestion amont : dans la définition principale, ils
# feraient attendre steam_events au step de steam_review (+1 h 30 par nuit).
BRIDGE_MODELS = "game_detail game_event_highlight"


def _dbt_build(
    context: dg.AssetExecutionContext, dbt: DbtCliResource, config: DbtRunConfig
):
    """`dbt build` (modèles + tests dans l'ordre du DAG) sur les assets sélectionnés.

    Passer `context` fait injecter --select par dagster-dbt à partir de la
    sélection Dagster : un modèle, une couche ou tout le projet selon le run.
    """
    args = ["build", "--full-refresh"] if config.full_refresh else ["build"]
    yield from dbt.cli(args, context=context).stream()


@dbt_assets(
    manifest=dbt_steam_reviews_project.manifest_path,
    dagster_dbt_translator=LayerGroupedDbtTranslator(),
    # Un nœud dbt ne peut être produit que par une AssetsDefinition, sinon les
    # clés se dupliquent : les deux sélections sont disjointes.
    select="fqn:*",
    exclude=f"resource_type:seed {BRIDGE_MODELS}",
)
def dbt_steam_reviews_models(
    context: dg.AssetExecutionContext,
    dbt: DbtCliResource,
    postgres: PostgresResource,
    config: DbtRunConfig,
):
    """Build selected dbt assets after checking whether review compaction is needed.

    A full refresh forces compaction when the versions asset is selected and the
    outdated table exists. Yield its registry observation, if any, before dbt
    build events. Database and dbt execution errors propagate.
    """
    yield from compact_steam_review_if_needed(
        context, dbt, postgres, force=config.full_refresh
    )
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
