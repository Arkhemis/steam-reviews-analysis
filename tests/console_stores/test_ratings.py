"""Lecture des notes du PS Store et du Microsoft Store, sans réseau."""

import json

import httpx

from orchestration.console_stores.resources import (
    ConsoleStoreResource,
    playstation_rating_from_page,
    xbox_ratings_from_catalog,
)


def widget(cache: dict) -> str:
    return (
        '<script id="env:1" type="application/json">'
        + json.dumps({"args": {"conceptId": "10000333"}, "cache": cache})
        + "</script>"
    )


def test_playstation_rating_is_the_default_product_one() -> None:
    page = widget({"ROOT_QUERY": {}}) + widget(
        {
            "Concept:10000333": {"defaultProduct": {"__ref": "Product:ER"}},
            "Product:ER": {
                "starRating": {"averageRating": 4.71, "totalRatingsCount": 186865}
            },
            "Product:DLC": {
                "starRating": {"averageRating": 2.0, "totalRatingsCount": 10}
            },
        }
    )

    assert playstation_rating_from_page(page, "10000333") == (4.71, 186865)


def test_playstation_concept_without_ratings() -> None:
    page = widget(
        {
            "Concept:10000333": {"defaultProduct": {"__ref": "Product:ER"}},
            "Product:ER": {"starRating": {"averageRating": 0, "totalRatingsCount": 0}},
        }
    )

    assert playstation_rating_from_page(page, "10000333") is None


def test_removed_playstation_concept_has_no_rating() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/en-us/error"})

    stores = ConsoleStoreResource(playstation_min_interval_seconds=0)
    stores.setup_for_execution(None)
    stores._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert stores.get_playstation_rating("99999999") is None


def test_xbox_ratings_keep_the_all_time_window_of_rated_products() -> None:
    def usage(span: str, average: float, count: int) -> dict:
        return {
            "AggregateTimeSpan": span,
            "AverageRating": average,
            "RatingCount": count,
        }

    payload = {
        "Products": [
            {
                "ProductId": "9P3J32CTXLRZ",
                "MarketProperties": [
                    {
                        "UsageData": [
                            usage("7Days", 4.9, 35),
                            usage("AllTime", 4.5, 55511),
                        ]
                    }
                ],
            },
            {
                "ProductId": "9NOTRATED000",
                "MarketProperties": [{"UsageData": [usage("AllTime", 0, 0)]}],
            },
        ]
    }

    assert xbox_ratings_from_catalog(payload) == {"9P3J32CTXLRZ": (4.5, 55511)}
