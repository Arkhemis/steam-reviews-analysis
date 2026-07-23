from dagster import ScheduleDefinition

from orchestration.jobs import (
    daily_ingest_job,
    steam_reviews_incremental_job,
)

daily_ingest_schedule = ScheduleDefinition(
    name="daily_ingest_schedule",
    job=daily_ingest_job,
    cron_schedule="0 2 * * *",
)

daily_incremental_schedule = ScheduleDefinition(
    name="daily_incremental_schedule",
    job=steam_reviews_incremental_job,
    cron_schedule="0 4 * * *",
)

schedules = [
    daily_ingest_schedule,
    daily_incremental_schedule,
]
