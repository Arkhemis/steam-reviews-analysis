# Modèle LDA du mémoire (2021)

Ce dossier fige le seul état survivant du modèle de topics estimé pour le
mémoire de M2 *Segmenting video game consumers according to their personality*.
Il sert d'instrument de référence : toute réestimation ultérieure se compare à
lui, et sa date d'existence est vérifiable.

## Provenance

Le modèle MALLET n'a jamais été sérialisé. Ce qui subsiste est la structure
`PreparedData` que pyLDAvis a inscrite dans la sortie de la cellule 13 du
notebook `Games_Personality_Project.ipynb`, transportée depuis dans le dépôt.

| Quoi | Référence |
| --- | --- |
| Blob du notebook | `c446b377d0921c9f19e1d22aba30c97b6f2ece3a` (559 305 o) |
| Commit d'ajout du notebook | `cbc62f4`, 2022-07-12 19:32 +0200 |
| Commit de suppression | `62cd86d`, 2025-08-27 (« Removed stats analysis ») |
| Code LDA | `lda_model.py` / `lda_check_topic.py`, ajoutés en `9d2b6e5` le 2021-06-07, inchangés jusqu'à leur suppression |
| Sortie des logits (même notebook) | horodatée par statsmodels au 2021-09-24 10:51 |
| Fenêtre des données d'estimation | 2010-10-16 → 2021-01-05 (mémoire, §4.1.1) |
| Corpus d'estimation | 4 892 472 reviews, 2 793 097 utilisateurs, 1 095 jeux |

Le blob sert d'ancre plutôt qu'un commit : le notebook a changé de chemin au fil
des réorganisations, son contenu non.

Chaîne de dates utile pour un argument d'antériorité : le modèle porte sur des
données qui s'arrêtent au **2021-01-05**, et son artefact est publiquement
commité depuis le **2022-07-12**. Tout ce qui suit ces bornes lui est postérieur.

## Contenu

`ldavis_2021.json` — charge pyLDAvis re-sérialisée (clés triées, indentée ;
contenu identique à l'original, qui tenait sur une ligne).

- `mdsDat` — 14 topics : coordonnées 2D et part du corpus (`Freq`, en %, somme 100)
- `tinfo` — par topic, ses termes retenus avec `logprob` = log p(terme|topic) et `loglift` = log p(terme|topic)/p(terme)
- `token.table` — 2 051 lignes, p(topic|terme)
- `R` = 30, `lambda.step` = 0.01

`extract_ldavis.py` — réextraction depuis le blob. `--check` échoue si le JSON
versionné diverge de la source.

```bash
python analysis/thesis-2021/extract_ldavis.py --check
```

sha256 attendu : `66d2c0ee50cd8097f878a5dd8c3d3b15a48ed3388a0bb0d0907d9243e7350339`

## Ce que l'artefact ne contient pas

À dire explicitement dans toute publication qui s'appuie dessus :

- **966 termes distincts seulement**, l'union des top-30 par pertinence sur les
  pas de λ. Ce n'est pas la matrice β complète sur le dictionnaire d'origine
  (qui, après `filter_extremes(no_below=10, no_above=0.2)` sur 4,9 M de
  documents, en comptait plusieurs milliers).
- **Pas de matrice document-topic** (θ), pas de α, pas d'état MALLET, pas de
  dictionnaire gensim.

Conséquence directe : **on ne peut pas scorer de nouveaux documents avec ce
modèle.** Une validation hors-échantillon par perplexité tenue est hors de
portée. Deux voies restent ouvertes :

1. Aligner un modèle réestimé sur ces profils termes-topics (recouvrement des
   top-mots, corrélation de rangs, Hellinger sur les 966 termes communs).
2. Réestimer sur le jeu de données de 2021 archivé
   (<https://archive.org/details/steamreview_dataset>) pour récupérer un modèle
   complet, en se servant de ces profils comme cible de validation : si la
   réestimation les retrouve, elle est fidèle, et elle devient scorable.

## Les 14 topics

`topic.order` = `[11, 5, 7, 10, 3, 9, 14, 12, 1, 13, 2, 8, 4, 6]`.

**Piège :** pyLDAvis renumérote les topics par fréquence décroissante. Les
« Topic n°5 », « n°7 » du mémoire sont des indices d'**affichage**, pas les
indices du modèle MALLET. La colonne « modèle » ci-dessous donne la
correspondance (1-indexée).

| Affiché | Modèle | Part % | Termes saillants (top 12 par p(terme\|topic)) | Mémoire |
| --- | --- | --- | --- | --- |
| 1 | 11 | 8.37 | level, enemy, fight, combat, boss, weapon, skill, system, item, attack, soul, ability | ~Challenging |
| 2 | 5 | 7.90 | mission, gun, kill, shoot, enemy, weapon, car, hit, move, jump, run, drive | ~Shooter |
| 3 | 7 | 7.76 | experience, puzzle, design, feel, sound, atmosphere, horror, visual, find, environment, mechanic, element | ~Puzzle |
| 4 | 10 | 7.64 | war, battle, space, strategy, system, ai, ship, turn, build, base, total, city | ~Strategy |
| 5 | 3 | 7.48 | story, character, world, feel, main, end, interesting, quest, choice, combat, side, voice | ~RPG |
| 6 | 9 | 7.42 | find, build, start, survival, thing, world, explore, day, craft, back, place, die | ~Simulation |
| 7 | 14 | 7.12 | bug, run, issue, fix, work, problem, ca, crash, save, setting, bad, break | écarté (technique) |
| 8 | 12 | 7.03 | thing, lot, feel, pretty, bit, bad, give, cool, start, stuff, kind, big | écarté (évaluatif) |
| 9 | 1 | 6.98 | update, review, add, content, early, release, hope, developer, access, work, change, year | écarté (consommation) |
| 10 | 13 | 6.85 | life, back, guy, hell, man, doom, die, cry, watch, kill, half, god | écarté (« Doom® ») |
| 11 | 2 | 6.65 | player, friend, people, mode, map, server, team, community, single, zombie, coop, match | ~Multiplayer |
| 12 | 8 | 6.53 | hard, easy, long, learn, challenge, hour, music, short, beautiful, enjoy, nice, bit | écarté (termes opposés) |
| 13 | 4 | 6.34 | buy, hour, worth, money, price, wait, sale, spend, year, steam, full, ca | écarté (consommation) |
| 14 | 6 | 5.95 | love, recommend, amazing, graphic, awesome, enjoy, fan, highly, original, series, absolutely, favorite | écarté (évaluatif) |

Les parts sont proches de 1/14 ≈ 7,1 % : cohérent avec des priors symétriques,
le wrapper gensim utilisé n'activant pas l'optimisation des hyperparamètres
(`optimize_interval=0`). Une réestimation sous tomotopy doit poser
`optim_interval=0` pour rester comparable.

Ce tableau documente l'artefact ; il ne fige pas les labels publiables (top-50
et libellés arrêtés), qui restent à faire.

## Reproductibilité du code d'origine

Deux tags annotés marquent les états à archiver :

| Tag | Commit | Ce qu'il contient |
| --- | --- | --- |
| `thesis-2021` | `9d2b6e5`, 2021-06-07 | le code LDA d'origine ; ancre d'antériorité |
| `thesis-2021-artifacts` | `8eec94b`, 2025-08-27 | dernier état complet avant suppression : notebook avec la sortie pyLDAvis, scripts Python et R, expérience OTree |

Le notebook n'existe qu'à partir de `cbc62f4` (2022-07-12) : `thesis-2021` seul
ne suffit pas à retrouver l'artefact, d'où le second tag.

Le code ne tourne plus en l'état :

- `gensim.models.wrappers` (donc `LdaMallet`) a été supprimé en gensim 4.0 ;
  `pyLDAvis.gensim` est devenu `pyLDAvis.gensim_models`.
- `lda_model.py` et `lda_check_topic.py` ne s'exécutent pas : `dropna(...,
  inplace=True)` renvoie `None`, et le `split()` des tokens intervient après la
  boucle `Phrases`, qui reçoit donc des chaînes. Le notebook, lui, est correct.
- Le balayage commité porte sur K ∈ {50…95}, pas sur la plage qui a produit le
  K = 14 du mémoire. La courbe de cohérence de la figure 2 n'est pas
  reproductible depuis le dépôt.
