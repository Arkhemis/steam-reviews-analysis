# Code server gRPC et image des conteneurs de run.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY orchestration ./orchestration
COPY dbt ./dbt
RUN uv sync --frozen --no-dev

# Creds bidon : `dbt parse` rend le profile mais n'ouvre pas de connexion.
RUN dbt deps --project-dir dbt --profiles-dir dbt \
 && CLICKHOUSE_USER=build CLICKHOUSE_PASSWORD=build \
    dbt parse --project-dir dbt --profiles-dir dbt

EXPOSE 4000

# La sonde met ~3 s à démarrer Python : sous 10 s, elle expire dès que la machine charge.
HEALTHCHECK --timeout=10s --start-period=30s --interval=10s --retries=12 \
    CMD ["dagster", "api", "grpc-health-check", "-p", "4000"]

CMD ["dagster", "code-server", "start", "-h", "0.0.0.0", "-p", "4000", \
     "-m", "orchestration.definitions"]
