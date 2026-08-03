"""Helpers dbt partagés par les domaines adossés à un projet dbt.

Pendant du `data_dagster/dbt.py` de data-dagster, allégé : pas de partitions
(aucun modèle incrémental ici) et pas de préfixe de clé d'asset, cf. le
translator ci-dessous.
"""

from collections.abc import Iterator, Mapping
from typing import Any

import dagster as dg
from dagster_dbt import (
    DagsterDbtTranslator,
    DagsterDbtTranslatorSettings,
    DbtCliResource,
)
from dagster_dbt.asset_utils import group_from_dbt_resource_props_fallback_to_directory


class DbtRunConfig(dg.Config):
    """Exposé dans le Launchpad : permet un full refresh sans job dédié."""

    full_refresh: bool = False


def stream_dbt_build(
    context: dg.AssetExecutionContext, dbt: DbtCliResource, config: DbtRunConfig
) -> Iterator:
    """`dbt build` (modèles + tests dans l'ordre du DAG) sur les assets sélectionnés.

    Passer `context` fait injecter --select par dagster-dbt à partir de la
    sélection Dagster : un modèle, une couche ou tout le projet selon le run.
    """
    args = ["build", "--full-refresh"] if config.full_refresh else ["build"]
    yield from dbt.cli(args, context=context).stream()


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
