from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row


class PostgresResource:
    """Fournit des connexions psycopg3 vers Postgres."""

    def __init__(self, host: str, port: int, user: str, password: str, database: str):
        self.dsn = (
            f"host={host} port={port} user={user} password={password} dbname={database}"
        )

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection]:
        """Ouvre une connexion (commit auto en sortie, rollback sur exception)."""
        conn = psycopg.connect(self.dsn, row_factory=dict_row)
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
