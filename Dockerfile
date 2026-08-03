# Image du code Dagster (user-code) + dbt. Sert le gRPC code server que
# webserver et daemon interrogent. dbt s'exécute dans ce même conteneur via
# dagster-dbt (pas de service séparé, cf. PLAN §8).
FROM python:3.13-slim

# uv pour installer les dépendances (cf. CI).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

# Couche de dépendances (cache tant que le lock ne change pas).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Code applicatif.
COPY orchestration ./orchestration
COPY dbt ./dbt
RUN uv sync --frozen --no-dev

EXPOSE 4000

# dbt/target/manifest.json doit exister AVANT l'import de orchestration.definitions :
# @dbt_assets lit le manifest pour savoir quels assets créer. En local
# project.prepare_if_dev() s'en charge, mais il ne fait rien hors `dagster dev`
# (il teste la variable DAGSTER_IS_DEV_CLI). On ne peut pas non plus le cuire au
# build de l'image : docker-compose monte ./dbt par-dessus /app/dbt, ce qui
# masquerait le manifest, et dbt/target/ est gitignoré donc absent du VPS.
# D'où ce parse au démarrage : il ne se connecte pas à la base, il ne fait que
# résoudre profiles.yml et écrire le manifest.
CMD ["sh", "-c", "dbt parse --project-dir dbt --profiles-dir dbt && \
     exec dagster code-server start -h 0.0.0.0 -p 4000 -m orchestration.definitions"]
