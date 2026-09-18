#!/usr/bin/env python3
"""Confronte le modèle réestimé aux 966 profils gelés de 2021.

Pour chaque topic de 2021 on ne dispose que de ses ~70 termes retenus par
pyLDAvis, avec log p(terme|topic). La comparaison se fait donc topic par topic,
restreinte à ce support, les deux distributions étant renormalisées dessus.

Trois mesures, plus un plancher : les mêmes mesures sur des appariements
aléatoires, qui disent ce que vaut un score « par hasard ».
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import tomotopy as tp
from scipy.optimize import linear_sum_assignment
from scipy.stats import spearmanr

FROZEN = Path(sys.argv[1])
MODEL = Path(sys.argv[2])
RNG = np.random.default_rng(1962)

LABELS = {
    1: "~Challenging", 2: "~Shooter", 3: "~Puzzle", 4: "~Strategy", 5: "~RPG",
    6: "~Simulation", 7: "écarté/technique", 8: "écarté/évaluatif",
    9: "écarté/consommation", 10: "écarté/Doom", 11: "~Multiplayer",
    12: "écarté/opposés", 13: "écarté/consommation", 14: "écarté/évaluatif",
}


def load_frozen(path: Path) -> dict[int, dict[str, float]]:
    d = json.loads(path.read_text())
    t = d["tinfo"]
    topics: dict[int, dict[str, float]] = defaultdict(dict)
    for term, cat, logprob in zip(t["Term"], t["Category"], t["logprob"]):
        if cat == "Default":  # pyLDAvis y range un rang, pas une log-probabilité
            continue
        topics[int(cat.removeprefix("Topic"))][term] = float(logprob)
    return dict(topics)


def hellinger(p: np.ndarray, q: np.ndarray) -> float:
    return float(np.sqrt(0.5 * np.sum((np.sqrt(p) - np.sqrt(q)) ** 2)))


def main() -> None:
    frozen = load_frozen(FROZEN)
    model = tp.LDAModel.load(str(MODEL))
    vocab = {w: i for i, w in enumerate(model.used_vocabs)}
    new_dists = [np.asarray(model.get_topic_word_dist(t)) for t in range(model.k)]

    all_terms = set().union(*(set(v) for v in frozen.values()))
    covered = all_terms & vocab.keys()
    print(f"termes gelés : {len(all_terms)} | présents dans le vocabulaire réestimé : "
          f"{len(covered)} ({len(covered) / len(all_terms):.1%})\n")

    n_old, n_new = len(frozen), model.k
    hell = np.ones((n_old, n_new))
    spear = np.zeros((n_old, n_new))
    jacc = np.zeros((n_old, n_new))

    for i, old in enumerate(sorted(frozen)):
        terms = [t for t in frozen[old] if t in vocab]
        if len(terms) < 10:
            continue
        idx = [vocab[t] for t in terms]
        p = np.exp([frozen[old][t] for t in terms])
        p /= p.sum()
        top_old = {t for t, _ in sorted(frozen[old].items(), key=lambda kv: -kv[1])[:20]}

        for j in range(n_new):
            q = new_dists[j][idx]
            q = q / q.sum() if q.sum() > 0 else np.full(len(idx), 1 / len(idx))
            hell[i, j] = hellinger(p, q)
            spear[i, j] = spearmanr(p, q).statistic
            top_new = {w for w, _ in model.get_topic_words(j, top_n=20)}
            jacc[i, j] = len(top_old & top_new) / len(top_old | top_new)

    rows, cols = linear_sum_assignment(hell)

    print(f"{'2021':>6} {'label mémoire':<22} {'→ réestimé':>10} {'Hellinger':>10} "
          f"{'Spearman':>9} {'Jaccard@20':>11}")
    print("-" * 74)
    matched_h, matched_s, matched_j = [], [], []
    for i, j in zip(rows, cols):
        old = sorted(frozen)[i]
        print(f"{old:>6} {LABELS.get(old, ''):<22} {j + 1:>10} {hell[i, j]:>10.3f} "
              f"{spear[i, j]:>9.3f} {jacc[i, j]:>11.3f}")
        matched_h.append(hell[i, j]); matched_s.append(spear[i, j]); matched_j.append(jacc[i, j])

    off = [(hell[i, j], spear[i, j], jacc[i, j])
           for i in range(n_old) for j in range(n_new) if (i, j) not in set(zip(rows, cols))]
    off = np.array(off)

    print("\n%-22s %10s %9s %11s" % ("", "Hellinger", "Spearman", "Jaccard@20"))
    print("%-22s %10.3f %9.3f %11.3f" % ("appariés (médiane)", np.median(matched_h),
                                         np.median(matched_s), np.median(matched_j)))
    print("%-22s %10.3f %9.3f %11.3f" % ("non appariés (méd.)", np.median(off[:, 0]),
                                         np.median(off[:, 1]), np.median(off[:, 2])))

    print("\nTop-15 du modèle réestimé")
    for t in range(model.k):
        print(f"  {t + 1:>2} : {', '.join(w for w, _ in model.get_topic_words(t, top_n=15))}")


if __name__ == "__main__":
    main()
