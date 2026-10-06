"""Liens IGDB → Steam lus depuis le dump external_games."""

from pathlib import Path

from orchestration.igdb.assets import _steam_app_ids_from_external_dump


def test_keeps_every_steam_edition_of_a_game(tmp_path: Path) -> None:
    dump = tmp_path / "external_games.csv"
    dump.write_text(
        "game,uid,category,external_game_source\n"
        "16,22380,,1\n"
        "16,22490,,1\n"
        "16,Fallout-NV,,5\n"
        "17,4000,1,\n"
    )

    assert _steam_app_ids_from_external_dump(dump) == {
        "16": [22380, 22490],
        "17": [4000],
    }
