from contextlib import contextmanager

from orchestration.steam.incremental import (
    NewReviewPages,
    insert_new_versions,
    iter_review_batches,
    sync_app_reviews,
)


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


class FakeCursor:
    def __init__(self, conn: "FakeConn") -> None:
        self.conn = conn
        self.rows: list[dict] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, sql: str, params: tuple) -> None:
        if sql.lstrip().startswith("SELECT"):
            _, recommendation_ids = params
            self.rows = [
                {"recommendation_id": recommendation_id, "timestamp_updated": ts}
                for recommendation_id, ts in self.conn.existing
                if recommendation_id in recommendation_ids
            ]
        else:
            self.conn.updates.append(params)

    def fetchall(self) -> list[dict]:
        return self.rows

    def executemany(self, sql: str, rows: list[tuple]) -> None:
        self.conn.inserted.extend(rows)


class FakeConn:
    def __init__(self, existing: set[tuple[int, int]] | None = None) -> None:
        self.existing = existing or set()
        self.inserted: list[tuple] = []
        self.updates: list[tuple] = []
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakePostgres:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    @contextmanager
    def connect(self):
        yield self.conn


def review(recommendation_id: int, timestamp_updated: int) -> dict:
    # Steam sérialise recommendationid en texte.
    return {
        "recommendationid": str(recommendation_id),
        "timestamp_created": timestamp_updated,
        "timestamp_updated": timestamp_updated,
    }


def ids(pages: list[list[dict]]) -> list[list[int]]:
    return [[int(item["recommendationid"]) for item in page] for page in pages]


def test_pages_stop_at_review_older_than_checkpoint() -> None:
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
    pages = NewReviewPages(steam, 10, 100)

    assert ids(list(pages)) == [[1, 2], [3]]
    assert pages.reached_checkpoint is True


def test_pages_accept_last_page_when_checkpoint_timestamp_was_seen() -> None:
    steam = FakeSteam(
        {
            "*": {
                "reviews": [review(1, 101), review(2, 100)],
                "cursor": None,
            }
        }
    )
    pages = NewReviewPages(steam, 10, 100)

    assert ids(list(pages)) == [[1, 2]]
    assert pages.reached_checkpoint is True


def test_pages_flag_incomplete_pagination() -> None:
    steam = FakeSteam(
        {
            "*": {
                "reviews": [review(1, 110)],
                "cursor": None,
            }
        }
    )
    pages = NewReviewPages(steam, 10, 100)

    assert ids(list(pages)) == [[1]]
    assert pages.reached_checkpoint is False


def test_batches_group_pages_without_holding_everything() -> None:
    pages = [[review(1, 110), review(2, 109)], [review(3, 108)], [review(4, 107)]]

    assert ids(list(iter_review_batches(pages, 2))) == [[1, 2], [3, 4]]


def test_insert_skips_known_versions_and_intra_batch_duplicates() -> None:
    conn = FakeConn(existing={(1, 100)})

    inserted, new_reviews = insert_new_versions(
        conn,
        10,
        [review(1, 100), review(2, 110), review(2, 110)],
    )

    assert inserted == 1
    assert new_reviews == 1
    assert [row[0] for row in conn.inserted] == [2]


def test_insert_keeps_a_new_version_of_a_known_review() -> None:
    conn = FakeConn(existing={(1, 100)})

    inserted, new_reviews = insert_new_versions(conn, 10, [review(1, 120)])

    assert inserted == 1
    # La review existe déjà : nouvelle version, mais pas une nouvelle review.
    assert new_reviews == 0


def test_sync_commits_and_advances_the_checkpoint() -> None:
    steam = FakeSteam(
        {"*": {"reviews": [review(1, 120), review(2, 100)], "cursor": None}}
    )
    conn = FakeConn()

    result = sync_app_reviews(steam, FakePostgres(conn), 10, 100)

    assert result.reached_checkpoint is True
    assert result.versions_inserted == 2
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.updates == [(2, 120, 10)]


def test_sync_rolls_back_when_the_checkpoint_is_not_reached() -> None:
    steam = FakeSteam({"*": {"reviews": [review(1, 120)], "cursor": None}})
    conn = FakeConn()

    result = sync_app_reviews(steam, FakePostgres(conn), 10, 100)

    assert result.reached_checkpoint is False
    assert result.versions_inserted == 0
    assert conn.rollbacks == 1
    assert conn.commits == 0
    # Le compteur du jeu n'est pas touché : il repartira du même checkpoint.
    assert conn.updates == []
