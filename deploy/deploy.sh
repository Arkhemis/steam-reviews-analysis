#!/usr/bin/env bash
# Lancé par /usr/local/bin/deploy (cf. cloud-init.yaml), après le pull de ce repo.
set -euo pipefail
git -C ~/apps/steam-reviews-website pull --ff-only
cd ~/apps/steam-reviews-analysis
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# Le build legacy empile une couche de cache par déploiement (39 Go le 2026-09-28).
docker builder prune -af >/dev/null || true
