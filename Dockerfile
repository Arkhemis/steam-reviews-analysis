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

# Code server gRPC : webserver + daemon s'y connectent (cf. workspace.yaml).
CMD ["dagster", "code-server", "start", \
     "-h", "0.0.0.0", "-p", "4000", \
     "-m", "orchestration.definitions"]
