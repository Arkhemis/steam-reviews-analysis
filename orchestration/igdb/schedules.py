from dagster import ScheduleDefinition

from orchestration.igdb.jobs import igdb_ingest_job

igdb_schedule = ScheduleDefinition(
    name="igdb_schedule",
    job=igdb_ingest_job,
    cron_schedule="0 3 * * *",
)


__all__ = [
    "igdb_schedule",
]
