"""Chargé isolément par `dagster-dbt project prepare-and-package`."""

from pathlib import Path

from dagster_dbt import DbtProject

REPO_ROOT = Path(__file__).resolve().parent.parent

dbt_steam_reviews_project = DbtProject(
    project_dir=REPO_ROOT / "dbt",
    profiles_dir=REPO_ROOT / "dbt",
)

# En prod, le manifest est construit au démarrage du code server.
dbt_steam_reviews_project.prepare_if_dev()

__all__ = ["dbt_steam_reviews_project"]
