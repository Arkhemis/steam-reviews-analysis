"""Unit tests for compilation-time review watermark and scheduling decisions."""

import datetime as datetime_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, StrictUndefined


MACROS = Path(__file__).resolve().parents[2] / "dbt" / "macros" / "steam_review.sql"
# dbt's custom `test` tag is unrelated to the macros exercised here.
MACRO_SOURCE = MACROS.read_text().split("{% test", 1)[0]
ENV = Environment(undefined=StrictUndefined, extensions=["jinja2.ext.do"])


class MacroReturn(Exception):
    def __init__(self, value):
        self.value = value


def dbt_return(value):
    raise MacroReturn(value)


def returned(call):
    try:
        call()
    except MacroReturn as result:
        return result.value
    raise AssertionError("The macro did not call return()")


def macro_module(*, started_at, incremental=True, variables=None, **overrides):
    variables = variables or {}
    context = {
        "return": dbt_return,
        "run_started_at": started_at,
        "is_incremental": lambda: incremental,
        "var": lambda name, default: variables.get(name, default),
        "modules": SimpleNamespace(datetime=datetime_module),
        **overrides,
    }
    return ENV.from_string(MACRO_SOURCE).make_module(context)


def test_watermark_uses_a_literal_and_scans_recent_data_first():
    queries = []
    watermark = datetime_module.datetime(2026, 9, 22, tzinfo=datetime_module.UTC)

    def run_query(query):
        queries.append(query)
        return SimpleNamespace(columns=[SimpleNamespace(values=lambda: [watermark])])

    module = macro_module(
        started_at=datetime_module.datetime(2026, 9, 24, tzinfo=datetime_module.UTC),
        execute=True,
        run_query=run_query,
    )

    assert (
        returned(
            lambda: module.steam_review_watermark("staging.steam_review_versions", 2)
        )
        == "'2026-09-22T00:00:00+00:00'::timestamptz"
    )
    [query] = queries
    assert "MAX(loaded_at) FROM staging.steam_review_versions" in query
    assert "loaded_at > '2026-08-25T00:00:00+00:00'::timestamptz" in query
    assert "(SELECT MAX(loaded_at) FROM staging.steam_review_versions)" in query
    assert "- INTERVAL '2 days'" in query


def test_watermark_compilation_without_execution_does_not_query_database():
    def unexpected_query(_query):
        raise AssertionError("run_query must not be called while compiling")

    module = macro_module(
        started_at=datetime_module.datetime(2026, 9, 24, tzinfo=datetime_module.UTC),
        execute=False,
        run_query=unexpected_query,
    )

    assert (
        returned(
            lambda: module.steam_review_watermark("staging.steam_review_versions", 2)
        )
        == "'1970-01-01'::timestamptz"
    )


def test_watermark_rejects_an_empty_versions_table():
    def run_query(_query):
        return SimpleNamespace(columns=[SimpleNamespace(values=lambda: [None])])

    def fail(message):
        raise RuntimeError(message)

    module = macro_module(
        started_at=datetime_module.datetime(2026, 9, 24, tzinfo=datetime_module.UTC),
        execute=True,
        run_query=run_query,
        exceptions=SimpleNamespace(raise_compiler_error=fail),
    )

    with pytest.raises(RuntimeError, match="staging.steam_review_versions est vide"):
        module.steam_review_watermark("staging.steam_review_versions", 2)


@pytest.mark.parametrize(
    ("day", "incremental", "variables", "expected"),
    [
        (2, False, {}, True),
        (1, True, {}, True),
        (2, True, {}, False),
        (2, True, {"rebuild_steam_review_outdated": True}, True),
        (1, True, {"rebuild_steam_review_outdated": False}, False),
    ],
)
def test_registry_full_rebuild_schedule(day, incremental, variables, expected):
    module = macro_module(
        started_at=datetime_module.datetime(2026, 9, day),
        incremental=incremental,
        variables=variables,
    )

    assert returned(module.steam_review_outdated_full_rebuild) is expected


@pytest.mark.parametrize(
    ("day", "variables", "expected"),
    [
        (20, {}, True),  # Sunday
        (21, {}, False),
        (21, {"full_tests": True}, True),
    ],
)
def test_full_review_checks_run_weekly_or_on_request(day, variables, expected):
    module = macro_module(
        started_at=datetime_module.datetime(2026, 9, day),
        variables=variables,
    )

    assert returned(module.is_weekly_test_run) is expected
