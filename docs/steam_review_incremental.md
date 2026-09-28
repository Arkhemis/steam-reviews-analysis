# `staging.steam_review` en incrémental

*Conception ClickHouse, 28/09/2026. Elle remplace celle du 24/09 pour Citus (table de versions, registre des versions périmées, vue anti-join, compaction), consultable dans l'historique git de ce fichier. Contexte et mesures : [migration_clickhouse.md](migration_clickhouse.md).*

## Principe

`staging.steam_review` est une table `ReplacingMergeTree(review_version) ORDER BY (app_id, recommendation_id)`, alimentée en `append` par dbt.

- Chaque nuit, le modèle relit dans `raw.steam_reviews` les lignes chargées depuis le dernier `loaded_at` de la table, moins 2 jours de marge, les parse et les insère.
- Les fusions de parts ne gardent, pour chaque review, que la ligne de plus grande `review_version`. Avant fusion, les lectures passent par `FINAL` (réglage de session `final = 1` de dbt et du site), qui applique la même règle à la lecture.
- Il n'y a plus ni registre, ni vue, ni compaction.

## Version retenue

`review_version = timestamp_updated << 32 + secondes de loaded_at`.

- La version la plus récente de la review gagne.
- À version égale (la même version capturée deux fois), la dernière capture gagne, comme le tri `loaded_at DESC` de l'ancienne macro.

`ReplacingMergeTree(updated_at)` seul ne suffisait pas : à `updated_at` égal, il garde la dernière ligne insérée, et le premier build insère raw dans un ordre quelconque.

## Marge de relecture

La marge de 2 jours rattrape les lignes arrivées dans raw pendant ou après le dernier build avec un `loaded_at` antérieur (runs longs, relances). Les versions déjà présentes reviennent avec la même `review_version` et fusionnent : la relecture ne crée aucun doublon visible.

Le filtre `loaded_at > (SELECT max(loaded_at) FROM staging.steam_review) - INTERVAL 2 DAY` est évalué avant la lecture, et raw est partitionné par mois de chargement (`toYYYYMM(loaded_at)`) : seules les partitions récentes sont lues.

## Pourquoi raw n'est pas relu avec `FINAL`

raw est aussi un `ReplacingMergeTree`, mais ne déduplique qu'au sein d'une partition. Une même version capturée deux mois différents y reste en double. La staging la déduplique de toute façon, et `FINAL` sur raw coûterait une fusion à la lecture : le modèle pose `final = 0` (`query_settings`).

## Full refresh

Désactivé (`full_refresh=false`). dbt-clickhouse reconstruit une table à côté puis l'échange : le disque doublerait le temps du build (~30 Go). Pour tout reconstruire, supprimer la table puis lancer le modèle.

## Corriger le parse

Une correction du parse ne demande plus de compaction :

```sql
UPDATE staging.steam_review
SET has_profanity = ...
WHERE language = 'turkish'
```

La table est créée avec `enable_block_number_column` et `enable_block_offset_column`, qu'exigent les `UPDATE` légers.

## Tests

- Chaque nuit : `not_null` sur les colonnes clés, limité aux 3 derniers jours de `loaded_at`.
- Le dimanche, ou avec `--vars '{full_tests: true}'` : unicité de `(recommendation_id, app_id)` sur toute la table, et `steam_review_matches_raw_sample`, qui recalcule depuis raw la dernière version des reviews de 20 jeux tirés au sort.
- `tests/dbt/test_steam_review_models.py` joue le modèle rendu dans chDB : choix de version, relecture de la marge, parse, `has_profanity`.
