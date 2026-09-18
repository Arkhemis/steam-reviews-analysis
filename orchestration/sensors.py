"""Sensors transverses aux domaines (alerting)."""

import os

import httpx
from dagster import DefaultSensorStatus, RunFailureSensorContext, run_failure_sensor

# Hôte servi par Caddy (cf. deploy/Caddyfile), pour lier le run dans l'alerte.
DAGSTER_BASE_URL = "https://dagster.steam.reviews"
# Discord tronque la description d'un embed à 4096 caractères.
MAX_DESCRIPTION_CHARS = 3500
WEBHOOK_TIMEOUT_SECONDS = 10.0


@run_failure_sensor(
    name="discord_run_failure_sensor",
    description="Poste une alerte Discord à chaque run en échec du code location.",
    # Actif dès le déploiement, comme daily_pipeline_schedule.
    default_status=DefaultSensorStatus.RUNNING,
)
def discord_run_failure_sensor(context: RunFailureSensorContext) -> None:
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        # Variable optionnelle : `dg dev` en local doit tourner sans webhook.
        context.log.warning("DISCORD_WEBHOOK_URL absent : alerte Discord ignorée.")
        return

    run = context.dagster_run
    failed_steps = [
        event.step_key for event in context.get_step_failure_events() if event.step_key
    ]

    lines = [f"[Voir le run]({DAGSTER_BASE_URL}/runs/{run.run_id})"]
    if failed_steps:
        lines.append("**Étapes en échec** : " + ", ".join(sorted(set(failed_steps))))
    lines.append(f"```\n{context.failure_event.message}\n```")

    mention_user_id = os.environ.get("DISCORD_MENTION_USER_ID")
    response = httpx.post(
        webhook_url,
        json={
            # Seul le `content` déclenche une notification Discord ; un embed seul
            # passe inaperçu, or un échec de nuit doit réveiller.
            "content": f"<@{mention_user_id}>" if mention_user_id else "",
            "embeds": [
                {
                    "title": f"❌ Run en échec : {run.job_name}",
                    "description": "\n".join(lines)[:MAX_DESCRIPTION_CHARS],
                    "color": 0xE01E5A,
                }
            ],
        },
        timeout=WEBHOOK_TIMEOUT_SECONDS,
    )
    # Échouer bruyamment : le tick apparaît en erreur dans l'UI et sera rejoué.
    response.raise_for_status()


__all__ = [
    "discord_run_failure_sensor",
]
