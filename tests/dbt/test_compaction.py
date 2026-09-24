"""Décision de compaction de steam_review_versions, sans base ni dbt."""

from types import SimpleNamespace

import dagster as dg

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
