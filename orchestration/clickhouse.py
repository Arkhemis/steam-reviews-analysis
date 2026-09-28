import threading
from collections.abc import Mapping, Sequence
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from dagster import ConfigurableResource
from pydantic import PrivateAttr

# Les tables ReplacingMergeTree ne dédupliquent qu'à la fusion : sans FINAL, un
# comptage ou une jointure verrait les doublons en attente.
SESSION_SETTINGS = {"final": 1}


class ClickHouseResource(ConfigurableResource):
    """Clients clickhouse-connect vers ClickHouse, un par thread.

    Les requêtes n'écrivent pas le nom de la base : `database` (raw par défaut)
    permet aux tests de jouer le même SQL dans une base jetable.
    """

    host: str
    port: int
    user: str
    password: str
    database: str = "raw"

    _local: threading.local = PrivateAttr(default_factory=threading.local)

    @property
    def client(self) -> Client:
        """Client du thread courant : un client ne supporte pas deux requêtes à la fois."""
        client = getattr(self._local, "client", None)
        if client is None:
            client = clickhouse_connect.get_client(
                host=self.host,
                port=self.port,
                username=self.user,
                password=self.password,
                database=self.database,
                settings=SESSION_SETTINGS,
                autogenerate_session_id=False,
            )
            self._local.client = client
        return client

    def query(
        self, sql: str, parameters: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Lignes du résultat, en dictionnaires."""
        result = self.client.query(sql, parameters=parameters)
        return list(result.named_results())

    def command(self, sql: str, parameters: Mapping[str, Any] | None = None) -> None:
        self.client.command(sql, parameters=parameters)

    def insert(
        self, table: str, rows: Sequence[Sequence[Any]], column_names: Sequence[str]
    ) -> None:
        if rows:
            self.client.insert(table, rows, column_names=list(column_names))
