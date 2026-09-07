"""Jobs transverses aux domaines (igdb + steam + dbt)."""

from dagster import AssetSelection, define_asset_job

# Tag porté par les modèles dbt : dagster-dbt le remonte en clé de tag Dagster,
# valeur vide. Les modèles NLP à venir en héritent sans toucher à ce fichier.
nlp_assets = AssetSelection.tag("nlp", "")

daily_pipeline_job = define_asset_job(
    name="daily_pipeline",
    # Tout sauf le NLP : ces modèles pèsent des heures pour un résultat qui n'a
    # pas à être recalculé chaque nuit.
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
