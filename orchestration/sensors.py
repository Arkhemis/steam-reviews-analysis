"""Sensors transverses aux domaines (alerting)."""

import os
import time

import httpx
from dagster import DefaultSensorStatus, RunFailureSensorContext, run_failure_sensor

DEFAULT_DAGSTER_BASE_URL = "https://dagster.steam.reviews"
# Discord tronque la description d'un embed à 4096 caractères.
MAX_DESCRIPTION_CHARS = 3500
WEBHOOK_TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 3
BACKOFF_BASE_SECONDS = 2.0


def _post_alert(context: RunFailureSensorContext, url: str, payload: dict) -> None:
    """Poste sur Discord en retentant 429, 5xx et erreurs réseau."""
    for attempt in range(1, MAX_RETRIES + 1):
        delay = BACKOFF_BASE_SECONDS**attempt
        try:
            response = httpx.post(url, json=payload, timeout=WEBHOOK_TIMEOUT_SECONDS)
            if response.status_code != 429 and response.status_code < 500:
                response.raise_for_status()
                return
            delay = float(response.headers.get("retry-after", delay))
            reason = f"HTTP {response.status_code}"
        except httpx.TransportError as exc:
            reason = str(exc)

        if attempt == MAX_RETRIES:
            raise RuntimeError(
                f"Discord injoignable après {MAX_RETRIES} essais : {reason}"
            )
        context.log.warning(
            f"Discord : {reason} ; retry {attempt}/{MAX_RETRIES} dans {delay:.0f}s"
        )
        time.sleep(delay)


@run_failure_sensor(
    name="discord_run_failure_sensor",
    description="Poste une alerte Discord à chaque run en échec du code location.",
    default_status=DefaultSensorStatus.RUNNING,
)
def discord_run_failure_sensor(context: RunFailureSensorContext) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        context.log.warning("DISCORD_WEBHOOK_URL absent : alerte Discord ignorée.")
        return

    run = context.dagster_run
    base_url = os.environ.get("DAGSTER_BASE_URL") or DEFAULT_DAGSTER_BASE_URL
    failed_steps = [
        event.step_key for event in context.get_step_failure_events() if event.step_key
    ]

    lines = [f"[Voir le run]({base_url}/runs/{run.run_id})"]
    if failed_steps:
        lines.append("**Étapes en échec** : " + ", ".join(sorted(set(failed_steps))))
    lines.append(f"```\n{context.failure_event.message}\n```")

    mention_user_id = os.environ.get("DISCORD_MENTION_USER_ID")
    # Le curseur avance même si le tick échoue : sans retries, l'alerte est perdue.
    _post_alert(
        context,
        webhook_url,
        {
            # Un embed seul ne notifie pas.
            "content": f"<@{mention_user_id}>" if mention_user_id else "",
            "embeds": [
                {
                    "title": f"❌ Run en échec : {run.job_name}",
                    "description": "\n".join(lines)[:MAX_DESCRIPTION_CHARS],
                    "color": 0xE01E5A,
                }
            ],
        },
    )


__all__ = [
    "discord_run_failure_sensor",
]
