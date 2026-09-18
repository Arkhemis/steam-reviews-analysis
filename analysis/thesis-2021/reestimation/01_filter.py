#!/usr/bin/env python3
"""Rejoue les filtres de 2021 sur le dataset archivé.

Chaîne d'origine (notebook, cellule 6) :
    df[df.user_review_text.apply(lambda x: len(x.split(' ')) >= 5 and detect(x)=='en')]
    df[df.user_playtime >= 2]

La détection de langue est déplacée en dernier : elle coûte mille fois les
autres filtres et le résultat d'une conjonction ne dépend pas de l'ordre.
"""

from __future__ import annotations

import sys
from multiprocessing import Pool
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from langdetect import DetectorFactory, detect

DetectorFactory.seed = 0  # langdetect est non déterministe par défaut

DATA = Path(sys.argv[1])
OUT = Path(sys.argv[2])
CHUNK = 200_000
WORKERS = 10

KEEP = [
    "game_id", "game_Name", "steam_ID", "user_playtime",
    "user_recommended", "user_postdate", "user_review_text",
]
TAGS = [f"tag_{i}" for i in range(1, 21)]


def is_english(text: str) -> bool:
    try:
        return detect(text) == "en"
    except Exception:
        return False


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    writer = None
    games: dict[int, tuple] = {}
    seen = kept = 0

    reader = pd.read_csv(
        DATA, chunksize=CHUNK, usecols=KEEP + TAGS,
        dtype={"game_id": "int64", "steam_ID": "str", "user_review_text": "str"},
        on_bad_lines="warn", low_memory=False,
    )

    with Pool(WORKERS) as pool:
        for n, chunk in enumerate(reader):
            seen += len(chunk)

            for row in chunk[["game_id", "game_Name"] + TAGS].itertuples(index=False):
                if row[0] not in games:
                    games[row[0]] = row

            df = chunk.dropna(subset=["user_review_text"])
            df = df[df["user_review_text"].str.count(" ") >= 4]  # len(split(' ')) >= 5
            df = df[pd.to_numeric(df["user_playtime"], errors="coerce") >= 2]

            if len(df):
                mask = pool.map(is_english, df["user_review_text"].tolist(), chunksize=200)
                df = df[pd.Series(mask, index=df.index)]

            if len(df):
                table = pa.Table.from_pandas(df[KEEP], preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(OUT / "filtered.parquet", table.schema,
                                              compression="zstd")
                writer.write_table(table)
                kept += len(df)

            print(f"chunk {n:>3} | lues {seen:>10,} | gardées {kept:>10,}", flush=True)

    if writer:
        writer.close()

    pd.DataFrame(games.values(), columns=["game_id", "game_Name"] + TAGS).to_parquet(
        OUT / "games.parquet", index=False
    )
    print(f"\nTOTAL lues {seen:,} | gardées {kept:,} ({kept / seen:.1%}) | jeux {len(games):,}")


if __name__ == "__main__":
    main()
