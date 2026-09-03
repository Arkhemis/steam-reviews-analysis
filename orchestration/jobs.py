"""Jobs transverses aux domaines (igdb + steam + dbt)."""

from dagster import AssetSelection, define_asset_job

daily_pipeline_job = define_asset_job(
    name="daily_pipeline",
    # Les 13 assets du projet forment une seule chaîne : la sélection globale
    # évite d'avoir à la réénumérer à chaque nouveau modèle dbt.
    selection=AssetSelection.all(),
    description=(
        "Chaîne complète : IGDB -> recensement Steam -> backfill -> incrémental "
        "-> projet dbt (staging, intermediate, marts)."
    ),
)


__all__ = [
    "daily_pipeline_job",
]
