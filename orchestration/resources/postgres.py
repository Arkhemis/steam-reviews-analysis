from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from dagster import ConfigurableResource
from psycopg.rows import dict_row


class PostgresResource(ConfigurableResource):
    """Fournit des connexions psycopg3 vers Postgres."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Ouvre une connexion (commit auto en sortie, rollback sur exception)."""
        conn = psycopg.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            dbname=self.database,
            row_factory=dict_row,
        )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def fetch_all(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(query, params)
            return cur.fetchall()
