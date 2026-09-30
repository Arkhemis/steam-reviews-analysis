"""Jobs transverses aux domaines (igdb + steam + dbt)."""

from dagster import AssetSelection, define_asset_job

# dagster-dbt remonte le tag dbt en clé de tag, valeur vide.
nlp_assets = AssetSelection.tag("nlp", "")

daily_pipeline_job = define_asset_job(
    name="daily_pipeline",
    # Le NLP prend des heures et n'a pas à tourner chaque nuit.
    selection=AssetSelection.all() - nlp_assets,
    description=(
        "Chaîne complète : IGDB -> recensement Steam -> backfill -> incrémental "
        "-> projet dbt (staging, intermediate, marts), hors modèles NLP."
    ),
)


__all__ = [
    "daily_pipeline_job",
    "nlp_assets",
]
