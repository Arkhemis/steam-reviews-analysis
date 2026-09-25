"""Décision de compaction de steam_review_versions, sans base ni dbt."""

from types import SimpleNamespace

import dagster as dg
import pytest

from orchestration.dbt import compaction
from orchestration.dbt.compaction import (
    COMPACTION_THRESHOLD,
    OUTDATED_KEY,
    VERSIONS_KEY,
    compact_steam_review_if_needed,
)


class FakeDbt:
    def __init__(self):
        self.calls = []

    def cli(self, args):
        self.calls.append(args)
        return SimpleNamespace(wait=lambda: None)


def run(monkeypatch, outdated_rows, force=False, selected=(VERSIONS_KEY,)):
    monkeypatch.setattr(compaction, "count_outdated", lambda _postgres: outdated_rows)
    context = SimpleNamespace(
        selected_asset_keys=set(selected),
        log=SimpleNamespace(info=lambda _msg: None),
    )
    dbt = FakeDbt()
    events = list(compact_steam_review_if_needed(context, dbt, None, force))
    return dbt.calls, events


def test_below_threshold_only_reports_the_registry_size(monkeypatch):
    calls, events = run(monkeypatch, COMPACTION_THRESHOLD)

    assert calls == []
    [event] = events
    assert isinstance(event, dg.AssetObservation)
    assert event.asset_key == OUTDATED_KEY
    assert event.metadata["outdated_rows"].value == COMPACTION_THRESHOLD
    assert event.metadata["compaction_threshold"].value == COMPACTION_THRESHOLD
    assert event.metadata["compacted"].value is False


def test_above_threshold_compacts(monkeypatch):
    calls, events = run(monkeypatch, COMPACTION_THRESHOLD + 1)

    assert calls == [["run-operation", "compact_steam_review"]]
    assert events[0].metadata["compacted"].value is True


def test_full_refresh_forces_the_compaction(monkeypatch):
    calls, _ = run(monkeypatch, 0, force=True)

    assert calls == [["run-operation", "compact_steam_review"]]


def test_skipped_when_versions_is_not_in_the_step(monkeypatch):
    # Le step des marts ne doit pas compacter sous les pieds des consommateurs.
    calls, events = run(
        monkeypatch, COMPACTION_THRESHOLD + 1, selected=(dg.AssetKey("game_stats"),)
    )

    assert calls == []
    assert events == []


def test_skipped_before_the_first_build(monkeypatch):
    calls, events = run(monkeypatch, None, force=True)

    assert calls == []
    assert events == []


class FakePostgres:
    def __init__(self, exists, count=None, error=None):
        self.exists = exists
        self.count = count
        self.error = error
        self.queries = []

    def fetch_all(self, query):
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        if query == compaction.OUTDATED_EXISTS_SQL:
            return [{"exists": self.exists}]
        if query == compaction.COUNT_OUTDATED_SQL:
            return [{"n": self.count}]
        raise AssertionError(f"Unexpected query: {query}")


def test_count_outdated_does_not_query_a_missing_registry():
    postgres = FakePostgres(exists=False)

    assert compaction.count_outdated(postgres) is None
    assert postgres.queries == [compaction.OUTDATED_EXISTS_SQL]


def test_count_outdated_preserves_an_empty_registry_count():
    postgres = FakePostgres(exists=True, count=0)

    assert compaction.count_outdated(postgres) == 0
    assert postgres.queries == [
        compaction.OUTDATED_EXISTS_SQL,
        compaction.COUNT_OUTDATED_SQL,
    ]


def test_count_outdated_propagates_database_errors():
    error = RuntimeError("database unavailable")
    postgres = FakePostgres(exists=True, error=error)

    with pytest.raises(RuntimeError, match="database unavailable"):
        compaction.count_outdated(postgres)
    assert postgres.queries == [compaction.OUTDATED_EXISTS_SQL]


def test_non_selected_step_never_queries_the_registry():
    postgres = FakePostgres(exists=True, count=COMPACTION_THRESHOLD + 1)
    context = SimpleNamespace(selected_asset_keys=set())

    assert (
        list(compact_steam_review_if_needed(context, FakeDbt(), postgres, True)) == []
    )
    assert postgres.queries == []


def test_empty_registry_does_not_compact_without_force():
    postgres = FakePostgres(exists=True, count=0)
    context = SimpleNamespace(selected_asset_keys={VERSIONS_KEY})
    dbt = FakeDbt()

    [event] = compact_steam_review_if_needed(context, dbt, postgres, False)

    assert dbt.calls == []
    assert event.metadata["outdated_rows"].value == 0
    assert event.metadata["compacted"].value is False


def test_observation_is_yielded_only_after_compaction_finishes():
    steps = []

    class WaitingDbt:
        def cli(self, args):
            steps.append(("cli", args))
            return SimpleNamespace(wait=lambda: steps.append(("wait", None)))

    context = SimpleNamespace(
        selected_asset_keys={VERSIONS_KEY},
        log=SimpleNamespace(info=lambda message: steps.append(("log", message))),
    )
    postgres = FakePostgres(exists=True, count=COMPACTION_THRESHOLD + 1)

    [event] = compact_steam_review_if_needed(context, WaitingDbt(), postgres, False)

    assert [step[0] for step in steps] == ["log", "cli", "wait"]
    assert steps[1][1] == ["run-operation", "compact_steam_review"]
    assert event.asset_key == OUTDATED_KEY
    assert event.metadata["compacted"].value is True


def test_failed_compaction_does_not_report_success():
    class FailingDbt:
        def cli(self, _args):
            def fail():
                raise RuntimeError("dbt operation failed")

            return SimpleNamespace(wait=fail)

    context = SimpleNamespace(
        selected_asset_keys={VERSIONS_KEY},
        log=SimpleNamespace(info=lambda _message: None),
    )
    postgres = FakePostgres(exists=True, count=COMPACTION_THRESHOLD + 1)

    with pytest.raises(RuntimeError, match="dbt operation failed"):
        list(compact_steam_review_if_needed(context, FailingDbt(), postgres, False))
