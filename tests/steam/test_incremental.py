from orchestration.steam.incremental import fetch_steam_reviews


class FakeSteam:
    def __init__(self, pages: dict[str, dict]) -> None:
        self.pages = pages

    def get_all_reviews(
        self,
        app_id: int,
        *,
        cursor: str,
        language: str,
    ) -> dict:
        return self.pages[cursor]


def review(recommendation_id: int, timestamp_updated: int) -> dict:
    return {
        "recommendationid": recommendation_id,
        "timestamp_updated": timestamp_updated,
    }


def test_fetch_stops_at_review_older_than_checkpoint() -> None:
    steam = FakeSteam(
        {
            "*": {
                "reviews": [review(1, 110), review(2, 100)],
                "cursor": "next",
            },
            "next": {
                "reviews": [review(3, 100), review(4, 99)],
                "cursor": "end",
            },
        }
    )

    reviews, reached_checkpoint = fetch_steam_reviews(steam, 10, 100)

    assert [item["recommendationid"] for item in reviews] == [1, 2, 3]
    assert reached_checkpoint is True


def test_fetch_accepts_last_page_when_checkpoint_timestamp_was_seen() -> None:
    steam = FakeSteam(
        {
            "*": {
                "reviews": [review(1, 101), review(2, 100)],
                "cursor": None,
            }
        }
    )

    reviews, reached_checkpoint = fetch_steam_reviews(steam, 10, 100)

    assert len(reviews) == 2
    assert reached_checkpoint is True


def test_fetch_rejects_incomplete_pagination() -> None:
    steam = FakeSteam(
        {
            "*": {
                "reviews": [review(1, 110)],
                "cursor": None,
            }
        }
    )

    reviews, reached_checkpoint = fetch_steam_reviews(steam, 10, 100)

    assert len(reviews) == 1
    assert reached_checkpoint is False
