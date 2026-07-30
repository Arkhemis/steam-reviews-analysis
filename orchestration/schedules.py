from dagster import ScheduleDefinition

from orchestration.jobs import daily_ingest_job, igdb_ingest_job


igdb_schedule = ScheduleDefinition(
    name="igdb_schedule",
    job=igdb_ingest_job,
    cron_schedule="0 3 * * *",
)

schedules = [
    daily_ingest_schedule,
    igdb_schedule,
]
