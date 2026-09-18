#!/usr/bin/env python3
"""Nettoyage + lemmatisation spaCy, à l'identique du notebook de 2021 (cellule 6).

Deux écarts assumés, tous deux sans effet sur les lemmes :
  - parser et ner désactivés : le lemmatiseur de en_core_web_sm ne dépend que
    du tagger et de l'attribute_ruler.
  - en_core_web_sm 3.8.0 au lieu de la 2.x de l'époque.

`custom_stopwords` n'est défini nulle part dans le notebook de 2021 ; la
définition reprise ici est celle de pre_processing.ipynb (2025).
"""

from __future__ import annotations

import re
import string
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import spacy
from nltk.corpus import stopwords

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
BATCH = 20_000
PROCS = 10

STOPWORDS = set(stopwords.words("english")).union(
    ["game", "videogame", "video game", "games", "video games"]
)
PUNCT = f"[{re.escape(string.punctuation)}]"


def clean(text: str) -> str:
    text = str(text).lower()
    text = re.sub(r"\[(.*?)\]", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\w+…|…", "", text)
    text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text)
    text = re.sub(PUNCT, "", text)
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)  # inerte : le tiret est déjà tombé
    return re.sub(PUNCT, "", text)


def keep(tokens: list[str]) -> list[str]:
    tokens = [t for t in tokens if t not in STOPWORDS]
    tokens = ["" if t.isdigit() else t for t in tokens]
    return [t for t in tokens if len(t) > 1]


def texts(src: pq.ParquetFile):
    for batch in src.iter_batches(batch_size=BATCH, columns=["user_review_text"]):
        for text in batch.column("user_review_text").to_pylist():
            yield clean(text)


def main() -> None:
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    nlp.max_length = 10_000_000

    src = pq.ParquetFile(SRC)
    schema = pa.schema([("tokens", pa.list_(pa.string()))])
    writer = pq.ParquetWriter(OUT, schema, compression="zstd")

    # Un seul appel à nlp.pipe : chaque appel avec n_process>1 relance les
    # processus, ce qui dominait le coût quand la boucle appelait pipe par lot.
    done = empty = 0
    buf: list[list[str]] = []
    for doc in nlp.pipe(texts(src), batch_size=1000, n_process=PROCS):
        toks = keep([t.lemma_ for t in doc])
        empty += not toks
        buf.append(toks)
        if len(buf) >= 100_000:
            writer.write_table(pa.table({"tokens": buf}, schema=schema))
            done += len(buf)
            buf = []
            print(f"{done:>10,} documents lemmatisés ({empty:,} vides)", flush=True)
    if buf:
        writer.write_table(pa.table({"tokens": buf}, schema=schema))
        done += len(buf)

    writer.close()
    print(f"\nTOTAL {done:,} documents, dont {empty:,} vides après filtrage")


if __name__ == "__main__":
    main()
