#!/usr/bin/env python3
"""Réestimation du LDA à 14 topics, recette de 2021.

Hyperparamètres repris du wrapper gensim LdaMallet tel qu'appelé en 2021 :
LdaMallet(..., num_topics=14, random_seed=1962) avec les défauts du wrapper,
soit alpha=50 (somme sur les topics, donc 50/14 par topic), optimize_interval=0
et iterations=1000. MALLET prend beta=0.01 par défaut, que le wrapper n'exposait
pas. tomotopy reproduit le même échantillonneur de Gibbs effondré.

Étapes, chacune reprise si son artefact existe déjà.
"""

from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pyarrow.parquet as pq
import tomotopy as tp
from gensim.corpora import Dictionary
from gensim.models.phrases import Phrases

SRC = Path(sys.argv[1])
WORK = Path(sys.argv[2])
K = 14
SEED = 1962
ITERATIONS = 1000

WORK.mkdir(parents=True, exist_ok=True)


def stream(path: Path, column: str = "tokens"):
    f = pq.ParquetFile(path)
    for batch in f.iter_batches(batch_size=50_000, columns=[column]):
        yield from batch.column(column).to_pylist()


def build_phrases() -> tuple:
    bi_path, tri_path = WORK / "bigram.pkl", WORK / "trigram.pkl"
    if bi_path.exists() and tri_path.exists():
        return pickle.loads(bi_path.read_bytes()), pickle.loads(tri_path.read_bytes())

    print("passe 1/4 — bigrammes", flush=True)
    bigram = Phrases(stream(SRC), min_count=10)
    bi_path.write_bytes(pickle.dumps(bigram.freeze()))

    print("passe 2/4 — trigrammes", flush=True)
    frozen_bi = pickle.loads(bi_path.read_bytes())
    trigram = Phrases((frozen_bi[d] for d in stream(SRC)), min_count=10)
    tri_path.write_bytes(pickle.dumps(trigram.freeze()))

    return frozen_bi, pickle.loads(tri_path.read_bytes())


def with_ngrams(doc: list[str], bigram, trigram) -> list[str]:
    # Boucle de 2021 : les n-grammes s'ajoutent aux unigrammes, ils ne les remplacent pas.
    out = list(doc)
    out += [t for t in bigram[doc] if "_" in t]
    out += [t for t in trigram[bigram[doc]] if "_" in t]
    return out


def build_dictionary(bigram, trigram) -> Dictionary:
    path = WORK / "dictionary.pkl"
    if path.exists():
        return pickle.loads(path.read_bytes())

    print("passe 3/4 — dictionnaire", flush=True)
    d = Dictionary(with_ngrams(doc, bigram, trigram) for doc in stream(SRC))
    print(f"  vocabulaire brut : {len(d):,}", flush=True)
    d.filter_extremes(no_below=10, no_above=0.2)
    print(f"  après filter_extremes(10, 0.2) : {len(d):,}", flush=True)
    path.write_bytes(pickle.dumps(d))
    return d


def main() -> None:
    bigram, trigram = build_phrases()
    dictionary = build_dictionary(bigram, trigram)
    vocab = set(dictionary.token2id)

    print("passe 4/4 — chargement du corpus dans tomotopy", flush=True)
    model = tp.LDAModel(k=K, alpha=50 / K, eta=0.01, seed=SEED, tw=tp.TermWeight.ONE)

    n = skipped = 0
    for doc in stream(SRC):
        words = [t for t in with_ngrams(doc, bigram, trigram) if t in vocab]
        if words:
            model.add_doc(words)
            n += 1
        else:
            skipped += 1
        if (n + skipped) % 500_000 == 0:
            print(f"  {n + skipped:,} documents lus", flush=True)

    print(f"corpus : {n:,} documents, {skipped:,} vides après filtrage", flush=True)

    model.burn_in = 0
    model.train(0, workers=12)
    print(f"vocabulaire du modèle : {len(model.used_vocabs):,} | mots : {model.num_words:,}",
          flush=True)

    for i in range(0, ITERATIONS, 50):
        model.train(50, workers=12)
        print(f"  itération {i + 50:>5} / {ITERATIONS} | log-vraisemblance/mot {model.ll_per_word:.4f}",
              flush=True)

    model.save(str(WORK / "lda_k14.bin"), full=False)
    print("modèle enregistré")

    for t in range(K):
        top = ", ".join(w for w, _ in model.get_topic_words(t, top_n=15))
        print(f"topic {t + 1:>2} : {top}")


if __name__ == "__main__":
    main()
