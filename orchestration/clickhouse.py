import threading
from collections.abc import Mapping, Sequence
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from dagster import ConfigurableResource
from pydantic import PrivateAttr

# ReplacingMergeTree ne déduplique qu'à la fusion.
SESSION_SETTINGS = {"final": 1}

# Un paramètre lié est borné à 128 Kio (http_max_field_value_size) : 5000 entiers tiennent, pas 5000 chaînes.
PARAM_BATCH_SIZE = 5000


class ClickHouseResource(ConfigurableResource):
    """Un client par thread ; le SQL ne nomme pas la base, pour que les tests en changent."""

    host: str
    port: int
    user: str
    password: str
    database: str = "raw"

    _local: threading.local = PrivateAttr(default_factory=threading.local)

    @property
    def client(self) -> Client:
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
        result = self.client.query(sql, parameters=parameters)
        return list(result.named_results())

    def command(self, sql: str, parameters: Mapping[str, Any] | None = None) -> None:
        self.client.command(sql, parameters=parameters)

    def insert(
        self, table: str, rows: Sequence[Sequence[Any]], column_names: Sequence[str]
    ) -> None:
        if rows:
            self.client.insert(table, rows, column_names=list(column_names))
