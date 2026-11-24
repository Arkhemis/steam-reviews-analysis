"""Liens IGDB → stores lus depuis le dump external_games."""

from pathlib import Path

from orchestration.igdb.assets import _external_ids_from_dump


def test_keeps_every_store_id_of_a_game(tmp_path: Path) -> None:
    dump = tmp_path / "external_games.csv"
    dump.write_text(
        "game,uid,category,external_game_source\n"
        "16,22380,,1\n"
        "16,22490,,1\n"
        "16,Fallout-NV,,5\n"
        "16,10000333,,36\n"
        "16,9P3J32CTXLRZ,,11\n"
        "17,4000,1,\n"
        "17,not-a-concept,,36\n"
    )

    assert _external_ids_from_dump(dump) == {
        1: {"16": ["22380", "22490"], "17": ["4000"]},
        11: {"16": ["9P3J32CTXLRZ"]},
        36: {"16": ["10000333"]},
    }
