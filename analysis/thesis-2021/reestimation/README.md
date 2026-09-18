# Réestimation du modèle de 2021

Objectif : refaire tourner la recette de 2021 sur le jeu de données archivé, et
mesurer si elle retrouve les 966 profils termes-topics gelés dans
`../ldavis_2021.json`. Si oui, la réestimation est fidèle et fournit un modèle
**scorable**, ce que l'artefact gelé n'est pas (pas de β complet, pas de θ).

## Source

`steamreview_dataset.csv`, 7 898 782 114 o, md5 `5f3a85f8ae5d121f12c1366f9bd7d688`,
déposé sur archive.org le **2021-05-31** par l'auteur
(<https://archive.org/details/steamreview_dataset>). Intégrité vérifiée octet à
octet et par md5 contre les métadonnées de l'item.

Cette date est la meilleure ancre d'antériorité disponible : antérieure au
commit du notebook (2022-07-12) et au dépôt du code (2021-06-07).

40 colonnes, dont `user_playtime` (en heures), `user_review_text`,
`user_recommended`, `game_id`, `steam_ID`, et **20 colonnes `tag_*`** — les tags
Steam par jeu, absents du mémoire, qui fournissent une source de labels de genre
contemporaine des données pour la validation externe.

Pas de colonne de langue : le filtrage linguistique passe par détection.

## Étapes

| Script | Rôle |
| --- | --- |
| `01_filter.py` | filtres de 2021 : ≥ 5 tokens, langue anglaise détectée, `user_playtime >= 2` |
| `02_tokenize.py` | `clean_text` du notebook + lemmatisation spaCy |
| `03_lda.py` | bigrammes/trigrammes, `filter_extremes(10, 0.2)`, LDA K=14 sous tomotopy |
| `04_validate.py` | appariement hongrois contre les profils gelés (Hellinger, Spearman, Jaccard@20) + plancher aléatoire |

## Fidélité : ce qui est repris à l'identique

- La chaîne de regex de `clean_text` (cellule 6 du notebook), y compris la
  substitution de tiret devenue inerte parce que la ponctuation tombe avant.
- `.lower()` **avant** spaCy — ce qui dégrade l'étiquetage morphosyntaxique donc
  la lemmatisation, mais c'est ce que faisait le code de 2021.
- L'ordre des filtres de tokens : mots vides, puis chiffres, puis longueur > 1.
- L'ajout des n-grammes aux unigrammes plutôt que leur substitution.
- `Phrases(min_count=10)` sans seuil explicite, `filter_extremes(no_below=10, no_above=0.2)`.
- Les hyperparamètres du wrapper gensim `LdaMallet` tel qu'appelé en 2021 :
  `num_topics=14`, `random_seed=1962`, et les défauts du wrapper — `alpha=50`
  (somme sur les topics, soit 50/14 par topic), `optimize_interval=0`,
  `iterations=1000` ; `beta=0.01` par défaut de MALLET, que le wrapper
  n'exposait pas.

## Écarts assumés

| Écart | Raison | Effet attendu |
| --- | --- | --- |
| tomotopy au lieu de MALLET | `gensim.models.wrappers` supprimé en gensim 4.0 | même échantillonneur (Gibbs effondré), mêmes hyperparamètres ; l'implémentation diffère |
| `en_core_web_sm` 3.8.0 au lieu de la 2.x | la 2.x n'est plus installable | lemmes majoritairement identiques, divergences sur les cas rares |
| `parser` et `ner` désactivés | le lemmatiseur ne dépend que du tagger et de l'`attribute_ruler` | aucun sur les lemmes, ~3× plus rapide |
| mots vides NLTK d'aujourd'hui | la liste a bougé depuis 2021 | quelques termes de bord |
| `custom_stopwords` reconstruit | **jamais défini** dans le notebook de 2021 ; définition reprise de `pre_processing.ipynb` (2025) : NLTK ∪ {game, videogame, video game, games, video games} | inconnu, à documenter comme hypothèse |
| détection de langue déplacée en fin de chaîne | coût, et une conjonction ne dépend pas de l'ordre | aucun |

`langdetect` est utilisé avec `DetectorFactory.seed = 0`, la bibliothèque étant
non déterministe par défaut — ce que le code de 2021 ne faisait pas.

## Limite connue du code d'origine

Le notebook de 2021 fait `import detect` puis appelle `detect(x)` dans un
`try/except` qui renvoie `False` sur exception. Un module n'étant pas appelable,
cette forme écarterait **toutes** les reviews. Le code exécuté à l'époque devait
donc différer de celui qui a été commité — comme pour les deux scripts
`Statistical analysis/*.py`, qui ne s'exécutent pas non plus. La reconstruction
suppose l'intention (`from langdetect import detect`).
