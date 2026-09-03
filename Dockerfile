# Image du code Dagster (user-code) + dbt. Sert le gRPC code server, et sert
# aussi d'image aux conteneurs de run lancés par DockerRunLauncher.
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

# Creds bidon : `dbt parse` rend le profile mais n'ouvre pas de connexion.
RUN dbt deps --project-dir dbt --profiles-dir dbt \
 && POSTGRES_USER=build POSTGRES_PASSWORD=build POSTGRES_DB=build \
    dbt parse --project-dir dbt --profiles-dir dbt

EXPOSE 4000

HEALTHCHECK --timeout=2s --start-period=5s --interval=3s --retries=20 \
    CMD ["dagster", "api", "grpc-health-check", "-p", "4000"]

CMD ["dagster", "code-server", "start", "-h", "0.0.0.0", "-p", "4000", \
     "-m", "orchestration.definitions"]
