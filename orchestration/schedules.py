"""Schedules transverses aux domaines (igdb + steam + dbt)."""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from orchestration.jobs import daily_pipeline_job

daily_pipeline_schedule = ScheduleDefinition(
    name="daily_pipeline_schedule",
    job=daily_pipeline_job,
    cron_schedule="0 0 * * *",
    # Actif dès le déploiement : la chaîne complète doit tourner sans passer
    # par une activation manuelle dans l'UI.
    default_status=DefaultScheduleStatus.RUNNING,
)


__all__ = [
    "daily_pipeline_schedule",
]
