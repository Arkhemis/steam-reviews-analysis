from collections.abc import Iterator
from typing import Any

import psycopg
from dagster import ConfigurableResource
from psycopg.rows import dict_row


class PostgresResource(ConfigurableResource):
    """Fournit des connexions psycopg3 vers Postgres.
    """

    def setup_for_execution(self, context) -> None:  # noqa: ANN001
        self._dsn = (
            f"host={self.host} port={self.port} user={self.user} "
            f"password={self.password} dbname={self.database}"
        )

    def connect(self) -> Iterator[psycopg.Connection]:
        """Ouvre une connexion (commit auto en sortie, rollback sur exception)."""
        conn = psycopg.connect(self._dsn, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, query: str, params: tuple[Any, ...] | None = None) -> None:
        with self.connect() as conn:
            conn.execute(query, params)

    def fetch_all(
        self, query: str, params: tuple[Any, ...] | None = None
    ) -> list[dict[str, Any]]:
        with self.connect() as conn:
            cur = conn.execute(query, params)
            return cur.fetchall()
