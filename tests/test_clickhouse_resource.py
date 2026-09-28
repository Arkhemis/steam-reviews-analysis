from concurrent.futures import ThreadPoolExecutor

from orchestration.clickhouse import ClickHouseResource


def test_reads_deduplicated_rows(clickhouse: ClickHouseResource) -> None:
    """Deux captures d'une même fiche : final = 1 n'en montre qu'une."""
    for payload in ('{"v": 1}', '{"v": 2}'):
        clickhouse.insert("steam_game_details", [(10, payload)], ["app_id", "payload"])

    rows = clickhouse.query("SELECT count() AS n FROM steam_game_details")

    assert rows == [{"n": 1}]


def test_one_client_per_thread(clickhouse: ClickHouseResource) -> None:
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda _: clickhouse.query("SELECT sleep(0.2) AS s"), range(8))
        )

    assert len(results) == 8
