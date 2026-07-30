from dagster import ScheduleDefinition

from orchestration.jobs import daily_ingest_job, igdb_ingest_job

daily_ingest_schedule = ScheduleDefinition(
    name="daily_ingest_schedule",
    job=daily_ingest_job,
    cron_schedule="0 2 * * *",
)


igdb_schedule = ScheduleDefinition(
    name="igdb_schedule",
    job=igdb_ingest_job,
    cron_schedule="0 3 * * *",
)

schedules = [
    daily_ingest_schedule,
    igdb_schedule,
]
