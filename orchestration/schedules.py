"""Schedules transverses aux domaines (igdb + steam + dbt)."""

from dagster import DefaultScheduleStatus, ScheduleDefinition

from orchestration.jobs import daily_pipeline_job

daily_pipeline_schedule = ScheduleDefinition(
    name="daily_pipeline_schedule",
    job=daily_pipeline_job,
    cron_schedule="0 0 * * *",
    execution_timezone="Europe/Paris",
    default_status=DefaultScheduleStatus.RUNNING,
)


__all__ = [
    "daily_pipeline_schedule",
]
