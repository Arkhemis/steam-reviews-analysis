#!/usr/bin/env bash
# Lancé par /usr/local/bin/deploy (cf. cloud-init.yaml), après le pull de ce repo.
set -euo pipefail
git -C ~/apps/steam-reviews-website pull --ff-only
cd ~/apps/steam-reviews-analysis
# Les conteneurs de run Dagster (auto_remove: false, cf. dagster.yaml) retiennent
# chacun l'image du déploiement qui les a lancés : 1,8 Go par image, disque plein
# le 2026-11-24. Purgés avant le build pour lui laisser la place.
docker container prune -f --filter label=dagster/run_id --filter until=336h >/dev/null || true
docker image prune -af >/dev/null || true
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# Le build legacy empile une couche de cache par déploiement (39 Go le 2026-09-28).
docker builder prune -af >/dev/null || true
