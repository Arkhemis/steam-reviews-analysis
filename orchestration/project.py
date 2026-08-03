"""Projet dbt exposé au scope module.

`dagster-dbt project prepare-and-package` charge ce fichier isolément et prépare
chaque `DbtProject` trouvé au scope du module (génération de dbt/target/manifest.json).
Ce fichier n'est PAS la code location : celle-ci reste `orchestration.definitions`.
"""

from pathlib import Path

from dagster_dbt import DbtProject

REPO_ROOT = Path(__file__).resolve().parent.parent

# profiles_dir explicite : le profiles.yml du repo vit dans dbt/, pas dans ~/.dbt.
dbt_steam_reviews_project = DbtProject(
    project_dir=REPO_ROOT / "dbt",
    profiles_dir=REPO_ROOT / "dbt",
)

# Régénère le manifest sous `dagster dev` / `dg dev`. En prod le manifest doit
# déjà exister : il est construit au démarrage du code server (cf. Dockerfile).
dbt_steam_reviews_project.prepare_if_dev()

__all__ = ["dbt_steam_reviews_project"]
