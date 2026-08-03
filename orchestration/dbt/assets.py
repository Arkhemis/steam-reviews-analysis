import dagster as dg
from dagster_dbt import DbtCliResource, dbt_assets

from orchestration.dbt import DbtRunConfig, LayerGroupedDbtTranslator, stream_dbt_build
from orchestration.project import dbt_steam_reviews_project


@dbt_assets(
    manifest=dbt_steam_reviews_project.manifest_path,
    dagster_dbt_translator=LayerGroupedDbtTranslator(),
    # Une seule définition couvre tout le projet : un nœud dbt ne peut être
    # produit que par une AssetsDefinition, sinon les clés se dupliquent.
    select="fqn:*",
    exclude="resource_type:seed",
)
def dbt_steam_reviews_models(
    context: dg.AssetExecutionContext,
    dbt: DbtCliResource,
    config: DbtRunConfig,
):
    yield from stream_dbt_build(context, dbt, config)
