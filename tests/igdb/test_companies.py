"""Sociétés IGDB : groupe de tête et pays."""

from orchestration.igdb.assets import _country_alpha_2, _top_parent


def test_top_parent_walks_up_to_the_group() -> None:
    parents = {"studio": "label", "label": "group"}

    assert _top_parent("studio", parents) == "group"
    assert _top_parent("group", parents) == "group"


def test_top_parent_stops_on_a_cycle() -> None:
    assert _top_parent("a", {"a": "b", "b": "a"}) == "b"


def test_country_from_iso_numeric() -> None:
    assert _country_alpha_2("76") == "BR"
    assert _country_alpha_2("") is None
    assert _country_alpha_2("999") is None
