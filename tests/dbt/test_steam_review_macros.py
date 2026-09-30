"""Planification des tests lourds, décidée à la compilation."""

import datetime as datetime_module
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, StrictUndefined


MACROS = Path(__file__).resolve().parents[2] / "dbt" / "macros" / "steam_review.sql"
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
