# Migration de Postgres/Citus vers ClickHouse

Statut : migration faite en prod (PR A le 29 septembre 2026, PR B le 1er octobre). Rédigée le 28 septembre 2026 à partir des bancs du même jour (voir [changement_db.md](changement_db.md)).

## Décision

Toutes les données du projet passent dans ClickHouse : raw, staging, intermediate, marts, et aussi les tables de suivi de l'ingestion. Postgres ne garde qu'un rôle : le stockage d'instance de Dagster (runs, événements, plannings). dagster-postgres est le seul stockage de production que Dagster propose, ClickHouse ne peut pas le remplacer. Citus disparaît.

Ce que la migration supprime :

- le registre des versions dépassées (`steam_review_outdated`), l'anti-join de la vue `steam_review` et la table `steam_review_versions` : la staging devient une seule table qui ne garde que la dernière version de chaque review ;
- la compaction (`compact_steam_review`, `orchestration/dbt/compaction.py`), les `ANALYZE` manuels, le watermark littéral, les réglages `work_mem`, `enable_mergejoin` et le seuil de pushdown Citus ;
- les contournements pour l'absence de `UPDATE` et `DELETE` : ClickHouse les accepte.

Ce qu'elle ne règle pas : le disque. Le texte des reviews domine, et ClickHouse ne le compresse pas mieux que Citus.

## Mesures

Bancs locaux sur des échantillons de la prod, ClickHouse 26.9 limité à 3 Go de RAM et 4 CPU pour approcher le VPS.

| | Citus (prod) | ClickHouse | Écart |
|---|---|---|---|
| Raw, payload en type `JSON` | 239 o/ligne, 44 Go | 171 o/ligne, ~31,5 Go | −28 % |
| Staging (dernière version seulement) | 176 o/ligne, 32 Go | 160 o/ligne, ~29,5 Go | −9 % |
| `marts.review_highlight` | 7,7 Go | 613 o/ligne, ~5 Go | −35 % |
| 50 dernières reviews d'un jeu à 50 k reviews (`WHERE app_id = …`) | 32,4 s | 28–32 ms | ~1 000× |
| Lot de 3 000 nouvelles versions, raw → staging | registre + anti-join | 0,19 s | |
| Parse JSON + `has_profanity`, 614 k lignes | 9,4 s (Postgres heap) | 10,9 s | ≈ |
| Agrégats par jeu et par langue, 614 k lignes | 125–180 ms (heap) | 14–24 ms | ~8× |
| Insertion par lots de 5 000 (`clickhouse-connect`) | 57 k lignes/s (heap) | 62 k lignes/s | ≈ |
| 1 500 `UPDATE` unitaires, 3 threads | | 5 s (~3 ms chacun) | |

Les tailles viennent de l'échantillon de 10 % (17,8 M reviews, jeux `(app_id / 10) % 10 = 7`), après fusion des parts. Le premier échantillon, plus petit, donnait 189 et 181 o/ligne : ses parts n'avaient pas fusionné.

Durées et pics mémoire sur cet échantillon :

| Étape | Durée | Pic mémoire | Pleine échelle (×10) |
|---|---|---|---|
| Chargement de raw (CSV compressé → `JSON`) | 5 min 06 | 1,06 Go | ~50 min |
| Parse raw → staging, `has_profanity` compris | 9 min 08 | 1,50 Go | ~1 h 30 |
| Trois agrégats de staging, avec `FINAL` | 1,1–1,8 s | 265 Mo | ~15 s |
| `review_highlight_pick` (fenêtres `row_number`) | 22 s | 1,23 Go | ~4 min, mémoire à surveiller |
| `marts.review_highlight` (jointure avec la staging) | 22 s | 1,14 Go | ~4 min, mémoire à surveiller |
| `review_lexeme_count` (échantillonné) | 35 s | 1,17 Go | ~6 min |

Aucune requête n'a dépassé 1,5 Go sous le plafond de 3 Go. Le chargement et le parse avancent en flux : leur mémoire ne grandit pas avec le volume. Les fenêtres et la jointure de `review_highlight`, si. À pleine échelle, elles doivent pouvoir déborder sur disque, via `max_bytes_before_external_sort` et `join_algorithm = 'grace_hash'`, et c'est à vérifier au premier build.

Lectures d'un jeu, avec `FINAL` :

| Requête | Jeu à 2,8 M reviews (Dota 2 dans l'échantillon) | Jeu à ~50 k reviews |
|---|---|---|
| 50 dernières reviews | 89–111 ms | 28–32 ms |
| Répartition mensuelle | 43–48 ms | 5–23 ms |

La même lecture des 50 dernières reviews prend 32,4 s en prod, sur un jeu à 50 k reviews. Citus doit décompresser 7 M lignes, car les reviews d'un jeu sont éparpillées dans la table, qui n'a aucun index. ClickHouse les range côte à côte, par `app_id`.

Vérifications d'exactitude sur 612 736 reviews :

- la déduplication de `ReplacingMergeTree` retient la même version que la macro Postgres (0 écart) ;
- toutes les colonnes parsées sont identiques, sauf :
  - `has_profanity` : 12 reviews sur 29 662 manquées, toutes en turc (`AMINA`) : RE2 ne fait pas correspondre `I` et `ı`. Correctif : ajouter `ı` et `İ` à la classe de la lettre `i` ;
  - `weighted_vote_score` : ClickHouse garde toutes les décimales en `Decimal(38,20)`, là où la référence importée en avait perdu une ;
- `review_lexeme_count`, où `stem()` remplace `to_tsvector` : 99,4 % des couples (jeu, lexème) sont communs et 93,5 % ont exactement les mêmes comptes. Les écarts viennent des mots composés (`co-op`), des URL et de l'apostrophe `’`.

## Architecture cible

| Service | Aujourd'hui | Après |
|---|---|---|
| Base de données | `citusdata/citus:14.1-pg16`, tout dedans | `clickhouse/clickhouse-server` (version LTS figée) pour les données ; `postgres:16.15` pour Dagster seul (~260 Mo) |
| Chargeurs Dagster | psycopg | `clickhouse-connect` |
| dbt | `dbt-postgres` | `dbt-clickhouse` (1.10.3, compatible avec dbt-core 1.11 verrouillé) |
| Site | driver `pg` | `@clickhouse/client` |
| dbgate | plugin postgres | plugin clickhouse, plus postgres pour Dagster si besoin |
| Volume `/mnt/pgdata` | `postgresql/` | `clickhouse/` et `postgresql-dagster/` (Dagster). Même point de montage : le drop-in systemd et `create_host_path: false` restent valables |

Budget mémoire sur le CX33 (8 Go) : ClickHouse plafonné à ~3,5 Go (`max_server_memory_usage`), le reste pour Dagster et ses runs, le site, dbgate et Postgres. Les réglages vont dans `deploy/clickhouse/config.d/` et `users.d/`, versionnés :

- plafond mémoire du serveur et par requête ;
- débordement sur disque des `GROUP BY` et des tris (`max_bytes_before_external_group_by`, `max_bytes_before_external_sort`) ;
- algorithme de jointure capable de déborder (`join_algorithm`) ;
- `max_threads = 4` ;
- caches réduits ;
- fuseau `UTC`.

Valeurs de départ, d'après le banc : `max_server_memory_usage` à 3,5 Go, `max_memory_usage` à 2,5 Go par requête, débordement des tris et `GROUP BY` à partir de 1 Go.

Utilisateurs : un compte d'écriture, comme aujourd'hui (`CLICKHOUSE_USER`), et en prod un compte `play` en lecture seule pour l'interface `/play` publiée sur `clickhouse.steam.reviews` (`users.d/play.xml`). Caddy force `user=play` et retire les autres identifiants : le compte d'écriture n'est pas joignable depuis internet. Variables d'environnement :

- `CLICKHOUSE_HOST`, `CLICKHOUSE_PORT`, `CLICKHOUSE_USER` et `CLICKHOUSE_PASSWORD` pour les chargeurs, dbt, le site et dbgate ;
- `CLICKHOUSE_PLAY_PASSWORD` pour le compte `play`, exigée par `docker-compose.prod.yml` ;
- `POSTGRES_*` pour Dagster seul (`deploy/dagster.yaml`).

## Schéma ClickHouse

Le DDL de raw remplace `db/init.sql` par `db/clickhouse/init.sql`. Comme aujourd'hui, ce script n'est exécuté qu'au premier démarrage sur un volume vide (`/docker-entrypoint-initdb.d`).

### Raw

| Table | Moteur et clé | Remarques |
|---|---|---|
| `raw.steam_reviews` | `ReplacingMergeTree(loaded_at)`, `ORDER BY (app_id, recommendation_id, timestamp_updated)`, `PARTITION BY toYYYYMM(loaded_at)` | Garde toutes les versions ; une même version capturée deux fois fusionne. La partition par mois de chargement limite la lecture incrémentale aux partitions récentes. `payload JSON`. |
| `raw.steam_review_counts` | `MergeTree ORDER BY app_id`, avec `enable_block_number_column` et `enable_block_offset_column` | Table d'état : `UPDATE` légers. Pas de contrainte d'unicité : le recensement n'insère que les `app_id` absents, un test dbt vérifie l'unicité. |
| `raw.steam_events` | `ReplacingMergeTree(loaded_at) ORDER BY (app_id, gid)` | `gid String`, `payload String` : le corps des annonces domine, `JSON` n'y gagnerait presque rien. `payload_hash UInt64`, calculé par le chargeur, repère les annonces modifiées. |
| `raw.steam_game_details` | `ReplacingMergeTree(loaded_at) ORDER BY app_id` | `payload String`, lu avec `JSONExtract`. |
| `raw.igdb_games` | `ReplacingMergeTree(loaded_at) ORDER BY igdb_id` | `genres`, `developers` et `publishers` en `Array(String)`. L'index GIN disparaît : rien ne filtre dessus. |
| `raw.game_review_summaries` | `ReplacingMergeTree(generated_at) ORDER BY app_id` | Branche `feat/game-review-summaries`, pas encore fusionnée : à porter avec elle. |

Le type `JSON` ne restitue pas le document à l'identique : il supprime les clés à `null` et les objets vides `{}`, et réécrit les nombres. Sur 200 000 payloads, seul `app_release_date` est concerné (`null` dans 4,6 % des cas) : un chemin absent se lit comme `NULL`, donc le parse ne change pas. Les flottants de `weighted_vote_score` sont tous exacts en `Float64`. La sauvegarde de l'étape 7 part de ClickHouse : elle garde ce document normalisé, pas le JSONB d'origine. Perte acceptée, puisque le parse n'en dépend pas. L'autre option est `payload String` : 248 o/ligne, soit ~11 Go de plus.

Les tables `ReplacingMergeTree` ne sont dédupliquées qu'à la fusion. Toute lecture qui compte ou joint doit donc passer par `FINAL`. Pour ne pas dépendre de la mémoire de chacun, dbt et le site activent le réglage de session `final = 1`, qui l'applique à toutes les tables qui le supportent. Son coût est à mesurer au banc à l'échelle.

### Staging

| Modèle | Aujourd'hui | Après |
|---|---|---|
| `steam_review` | vue anti-join sur `steam_review_versions` et `steam_review_outdated` | table incrémentale `append`, `ReplacingMergeTree(review_version) ORDER BY (app_id, recommendation_id)`, contrat dbt (types et `CODEC(ZSTD(3))` du texte) |
| `steam_review_versions`, `steam_review_outdated` | tables | supprimées |
| `game_detail`, `game_review_count`, `igdb_game`, `steam_event` | tables columnar | tables `MergeTree`, SQL réécrit |

Le modèle `steam_review` lit dans raw les lignes chargées depuis son dernier `loaded_at`, moins 2 jours de marge, parse et insère. `review_version` (`timestamp_updated` dans les 32 bits hauts, secondes de `loaded_at` dans les bas) reproduit le tri de la macro actuelle : version la plus récente, puis dernière capture. `ReplacingMergeTree(updated_at)` ne suffisait pas : raw ne déduplique qu'au sein d'une partition mensuelle, et au premier build l'ordre d'insertion est quelconque. Détail : [steam_review_incremental.md](steam_review_incremental.md).

Le parse (`steam_review_parse`) change de dialecte :

- chemins JSON typés au lieu de `->`/`->>` ;
- `toDateTime(x, 'UTC')` au lieu de `TO_TIMESTAMP` (`fromUnixTimestamp(x, 'UTC')` prend son second argument pour un format et renvoie la chaîne `UTC`) ;
- `COLLATE "C"` disparaît : ClickHouse compare déjà octet par octet ;
- `is_generic` passe par `match()`.

`has_profanity` utilise `multiIf(language = …, match(…))`. Un `CASE language WHEN` évalue les 31 regex sur chaque ligne : 30 s au lieu de 10,9 s. Les frontières de mots `\m`/`\M` deviennent `(?:^|[^\pL\pN_])` et `(?:[^\pL\pN_]|$)`, le drapeau `(?i)` remplace `~*`, et la classe de `i` gagne `ı` et `İ`.

Une correction de parse ne demande plus de compaction : un `UPDATE staging.steam_review SET … WHERE …` suffit. Testé à 10 % : 0,2 s pour les reviews turques d'un jeu. La table doit être créée avec `enable_block_number_column` et `enable_block_offset_column`, à mettre dans la config du modèle.

### Intermediate et marts

Même logique, en SQL ClickHouse. Les points à réécrire :

| Construction Postgres | Où | ClickHouse |
|---|---|---|
| `DISTINCT ON` | `review_lexeme_count`, test singulier, macro | `LIMIT 1 BY`, ou `max()` groupé pour le test singulier |
| `LATERAL UNNEST(TO_TSVECTOR(…))` | `review_lexeme_count`, analyse `distinctive_term_negative_control` | `ARRAY JOIN` sur `splitByNonAlpha`, filtre de mots vides, `stem(mot, 'en')` avec `allow_experimental_nlp_functions` ; traiter composés, URL et `’` |
| `MD5(x::text)` pour l'échantillonnage | `review_lexeme_count`, test singulier, analyse | `lower(hex(MD5(toString(x))))`, sinon l'ordre et donc l'échantillon changent |
| `PERCENTILE_CONT(0.5) WITHIN GROUP` | `steam_review_agg` | `quantileExactInclusive(0.5)` (même interpolation) |
| `REGEXP_MATCHES(…, 'g')` + `parts[1]` | `steam_event_categorized` | `extractAllGroups` ; les tableaux ClickHouse commencent aussi à 1 |
| `MAX(…) FILTER (WHERE …) OVER` | `game_distinctive_term` | `maxIf(…) OVER` |
| `AS MATERIALIZED` | `game_distinctive_term`, `review_window_highlight` | supprimé |
| `normal_two_sided_p` (approximation d'erf) | macro | `erf()`, natif |
| `INTERVAL 'n days'`, `DATE_TRUNC`, `DATE()`, `::numeric`, `::DATE` | plusieurs marts | `INTERVAL n DAY`, `toStartOfMonth`, `toDate`, `toDecimal`/`Float64` |
| `CROSS JOIN (VALUES …) AS c(category)` | `review_window_highlight` | `arrayJoin(['funny', 'helpful'])` |
| `EXCEPT ALL` | test singulier | à vérifier sur la version retenue |
| Configs `indexes` | intermediate, marts | supprimées : l'`ORDER BY` de chaque table suit ses filtres (par exemple `game_stats` par `steam_app_id`, `review_highlight` par `(app_id, rank_in_game)`) |
| Pre-hooks `SET work_mem`, `enable_mergejoin`, `hash_mem_multiplier`, `join_collapse_limit` ; post-hooks `ANALYZE` | `dbt_project.yml`, modèles | supprimés |

Configuration dbt :

- `profiles.yml` : `type: clickhouse`, `custom_settings` avec `final: 1`, `threads: 2` (pic de 1,5 Go par modèle, deux modèles tiennent sous le plafond) ;
- `sources.yml` : retirer `database:`, car un schéma est une base en ClickHouse ;
- `generate_schema_name` : garder, il donne les bases `staging`, `intermediate` et `marts` ;
- `where:` des tests en syntaxe ClickHouse (`now() - INTERVAL 3 DAY`) ;
- dbt_utils : `unique_combination_of_columns` et `accepted_range` sont du SQL générique, à vérifier au premier `dbt build`.

Constaté sur dbt-clickhouse 1.10.3 :

- un full refresh construit la table à côté puis l'échange : deux fois la taille le temps du build. `steam_review` garde donc `full_refresh=false` ;
- `on_schema_change: append_new_columns` ajoute les colonnes par `ALTER TABLE … ADD COLUMN` (avec le codec du contrat) ;
- `prefer_column_name_to_alias` casse les requêtes internes de l'adaptateur : il n'est pas activé, et les modèles qualifient les colonnes là où un alias `sum(x) AS x` masquerait `x` ;
- les colonnes d'une jointure `USING` sélectionnées qualifiées (`t.app_id`) gardent leur préfixe dans le nom de sortie : elles sont aliasées explicitement ;
- `join_use_nulls = 1` dans le profil : sans lui, un `LEFT JOIN` sans correspondance donne 0 ou `''` au lieu de NULL (`game_stats`).

## Code Python (Dagster)

Nouvelle ressource `ClickHouseResource` (`clickhouse-connect`), qui remplace `PostgresResource` (`orchestration/postgres.py`). Un client par thread, comme une connexion par jeu aujourd'hui. `definitions.py` la construit depuis `CLICKHOUSE_*`, et `deploy/dagster.yaml` ajoute ces variables à `DockerRunLauncher.env_vars`.

ClickHouse n'a pas de transactions. Chaque écriture doit rester juste si un run s'arrête au milieu, ce que la déduplication et l'ordre des écritures garantissent :

| Fichier | Aujourd'hui | Après |
|---|---|---|
| `igdb/assets.py` | upsert `ON CONFLICT (igdb_id)`, un seul commit | `client.insert` par lots de 1 000 ; `ReplacingMergeTree` rend la relance idempotente |
| `steam/census.py` | upsert `ON CONFLICT (app_id)` dont le `SET` lit la ligne existante | insertion des `app_id` absents, puis `UPDATE … SET col = coalesce(col, …)` sur les existants, en lot (`transform`) |
| `steam/backfill.py`, jeux légers | lot atomique : résumés, reviews, marquage | 1) insertion des reviews, 2) `UPDATE` des résumés et du marquage. Un arrêt entre les deux fait rejouer le lot, et raw déduplique |
| `steam/backfill.py`, jeux volumineux | insertions non commitées puis `rollback` si la pagination est incomplète | insertions au fil de l'eau ; pagination incomplète : on garde les reviews déjà insérées, seul le résumé est écrit et `last_backfill_at` reste NULL. **Changement de comportement** : les reviews d'un jeu partiellement chargé deviennent visibles avant la relance |
| `steam/incremental.py` | une transaction par jeu, `rollback` si le checkpoint n'est pas atteint | même principe : le checkpoint n'avance qu'après les insertions ; sinon les versions déjà insérées restent, sans conséquence car la relance repart du même checkpoint |
| `steam/incremental.py`, `RECOUNT_BACKFILLED_SQL` | `UPDATE … FROM … LEFT JOIN`, `rowcount` | `SELECT app_id, uniqExact(recommendation_id)` sur raw, comparaison en Python, puis un `UPDATE` groupé (`transform`) des seuls écarts ; la métrique est le nombre d'écarts |
| `steam/incremental.py`, `RELEVANT_APP_IDS` | `extract(dow FROM now())`, `IS DISTINCT FROM` | `toDayOfWeek(now()) % 7` (dimanche = 0, comme Postgres), comparaisons NULL-safe |
| `steam/events.py` | upsert `WHERE payload IS DISTINCT FROM`, `rowcount`, `gid = ANY(%s)` | lecture des `(app_id, gid, payload_hash)` connus (empreinte calculée en Python : le JSON stocké serait normalisé), insertion des seuls nouveaux ou modifiés, qui donnent la métrique ; `gid IN %(gids)s` |
| `steam/game_details.py` | upsert `ON CONFLICT (app_id)` | insertion (`ReplacingMergeTree`) |
| `dbt/compaction.py` | compaction avant chaque build | supprimé ; `dbt/assets.py` perd la ressource Postgres et l'étape de compaction |

Syntaxe : les paramètres psycopg (`%s`) deviennent des paramètres nommés `clickhouse-connect`, et `executemany` devient `client.insert(table, rows, column_names=…)`.

Le script LLM de la branche `feat/game-review-summaries` passe de `psql` à `clickhouse-client` via SSH. L'upsert par table temporaire devient une simple insertion, et `to_pg_array()` n'a plus de raison d'être. Le notebook de `feat/stop-words` fait un `ATTACH` DuckDB vers Postgres : il passe par `clickhouse-connect`.

## Site (`steam-reviews-website`)

Toutes ses requêtes sont en lecture. `src/lib/db.ts` passe de `pg` à `@clickhouse/client`, avec le réglage `final = 1`. Les ~30 requêtes de `src/lib/data/gameData.ts` et `src/lib/sitemap.ts` sont à réécrire :

- paramètres `$n` → `{nom:Type}` ;
- `= ANY($1::bigint[])` → `IN {ids:Array(UInt64)}` ;
- `$2::text IS NULL OR …` → paramètre `Nullable(String)` ;
- `TO_CHAR(DATE_TRUNC(…))` → `formatDateTime(toStartOfMonth(…), …)` ;
- `ORDER BY RANDOM()` → `rand()` ;
- **`JOIN LATERAL`** (`reviewDuelQuery`) → réécriture avec `LIMIT 1 BY` ou une fonction de fenêtre, car ClickHouse n'a pas `LATERAL`.

Le site ne lit que les marts et `intermediate.language_review_score`. Chaque requête filtre par `app_id`, ou lit en entier un mart de quelques dizaines de Mo, sauf deux lectures de `review_highlight` sur tous les jeux (`rank_in_game = 1 AND voted_up`). Elles ne lisent que ces deux petites colonnes. Aucune ne cherche une review par son seul `recommendation_id`, le cas où ClickHouse est lent faute d'index B-tree.

Types renvoyés : le code appelle `.toISOString()` sur des dates que `pg` renvoie en objets `Date` (`created_at`, `author_last_played_at`, `first_release_date`). ClickHouse les renvoie en chaînes : les convertir dans `db.ts` ou au point d'usage. Les entiers 64 bits restent des chaînes et `Number()` continue de marcher. Les tableaux restent des tableaux. Le code d'erreur `42P01` devient `UNKNOWN_TABLE` (60).

Tests :

- `queryPlan.test.ts` vérifie les plans Postgres (`EXPLAIN (FORMAT JSON)`) : à réécrire sur `EXPLAIN indexes = 1` ou à supprimer ;
- `gameData.test.ts` contient du SQL Postgres brut.

Docs du site à mettre à jour : `CLAUDE.md`, `README.md`, `docs/home-data.md`.

## Outillage et infrastructure

| Élément | Changement |
|---|---|
| `docker-compose.yml` | service `clickhouse` (image figée, `ulimits nofile`, `config.d` et `users.d` montés, healthcheck `SELECT 1`, ports sur `127.0.0.1`) ; service `postgres` en `postgres:16` sans `init.sql` ni `shared_preload_libraries=citus` ; `depends_on` de user-code, webserver et daemon sur les deux |
| `docker-compose.prod.yml` | bind `/mnt/pgdata/clickhouse` et `/mnt/pgdata/postgresql-dagster` avec `create_host_path: false` ; variables `CLICKHOUSE_*` pour le site et dbgate ; dbgate en `dbgate-plugin-clickhouse` |
| `deploy/dagster.yaml` | stockage inchangé (`POSTGRES_*`) ; `CLICKHOUSE_*` ajoutées à `env_vars` |
| `Dockerfile`, `.github/workflows/deploy.yml` | fausses variables `CLICKHOUSE_*` pour `dbt parse` |
| `pyproject.toml` | retirer `dbt-postgres`, `psycopg`, `duckdb` ; ajouter `dbt-clickhouse`, `clickhouse-connect`, `chdb` (tests) ; garder `dagster-postgres` |
| `.sqlfluff`, `.pre-commit-config.yaml` | `dialect = clickhouse`, `additional_dependencies: dbt-clickhouse` |
| `.github/workflows/ci.yml` | le job `sql-lint` démarre `clickhouse/clickhouse-server` au lieu de `postgres:16` |
| `tests/dbt/test_steam_review_models.py` | exécute les modèles rendus dans chDB (ClickHouse embarqué) au lieu de DuckDB ; ne plus simuler `has_profanity` |
| `tests/steam/test_incremental_selection.py` | base réelle ClickHouse au lieu de Postgres |
| `tests/steam/test_incremental_pagination.py`, `tests/dbt/test_compaction.py` | fausse connexion ClickHouse ; `test_compaction.py` supprimé |
| `tools/infra_map/build.py` | lit `db/clickhouse/init.sql` (moteurs au lieu de columnar/heap), nœud `clickhouse` |
| Docs | `README.md`, `docs/steam_review_incremental.md` (conception entièrement bâtie sur les limites de columnar : à réécrire), `docs/changement_db.md` |

Les restes de la prod ne sont pas migrés, sauf avis contraire :

- `marts.game_language_distribution` : orpheline, plus rien ne l'écrit ;
- schémas `scratch` (`highlight_rank` et `review_highlight`, ~1 Go) et `audit` (`rev_per_app`, 8 Mo) : tables créées à la main ;
- réglage de base `columnar.qual_pushdown_correlation_threshold` : il disparaît avec Citus.

### Sauvegardes

Aujourd'hui, aucune. Seules les tables raw sont irremplaçables, tout le reste se reconstruit avec dbt. Deux niveaux :

- **Obligatoire, pendant la migration** : `BACKUP DATABASE raw TO File(…)` depuis ClickHouse vers le disque local du VPS, une fois la parité vérifiée et avant de supprimer raw de Citus (étape 7). Le disque local (75 Go, 60 libres) est distinct du volume (`/mnt/pgdata`, 40 libres) : la sauvegarde (~37 Go, déjà compressée) n'entre pas en concurrence avec la copie. Il est couvert par les sauvegardes Hetzner du serveur, contrairement au volume. Un export depuis Citus aurait demandé ~3 h 30 de relecture de columnar et ~50 Go.
- **Ensuite, chaque semaine** : le même `BACKUP` en incrémental (`base_backup`). Le disque local ne garde qu'une chaîne ; une copie hors du serveur (Object Storage) reste recommandée, avec un bucket que l'utilisateur crée.

Le dossier de sauvegarde, `/var/backups/clickhouse` sur l'hôte, est monté dans le conteneur et déclaré dans `config.d` (`backups.allowed_path`). Le monter sous `/mnt/pgdata` le mettrait sur le volume, ce qu'on veut éviter.

## Déroulé de la migration

Disque : 148 Go, dont 40 libres. Citus occupe ~101 Go, dont 41 Go pour raw, 30 Go pour la staging des reviews, 9,5 Go pour les événements et 7,7 Go pour `review_highlight`. Cible ClickHouse : environ 31,5 Go de raw des reviews, 29,5 Go de staging et ~15 Go pour le reste. Les deux copies ne tiennent pas ensemble : d'où l'ordre ci-dessous.

Le code part en deux PR, parce que le service `postgres` du compose sert à la fois de source à la copie et de stockage à Dagster :

- **PR A** : tout le code ClickHouse, service `clickhouse` ajouté, service `postgres` encore en image Citus. Dagster garde son stockage dans Citus.
- **PR B** : service `postgres` en `postgres:16` sur `/mnt/pgdata/postgresql-dagster`, retrait de `init.sql` et de Citus.

Un push sur `main` déclenche `deploy.yml`, dont le job `dbt-modified-models` lance un run dbt de tous les modèles modifiés, c'est-à-dire tous. Pendant la migration, ce run tournerait sur un ClickHouse vide. Les deux PR se fusionnent donc avec `[skip ci]` dans le message du commit de merge. Le déploiement se lance ensuite à la main par `workflow_dispatch`, qui saute ce job.

0. **Avant le jour J.**
   - Les deux PR prêtes : analyse, site, et branche LLM si elle est fusionnée d'ici là.
   - Validation complète en local sur l'échantillon de 10 % : chargeurs contre les API réelles, `dbt build`, pages du site.
   - Image ClickHouse figée.
   - Sur le VPS : créer `/mnt/pgdata/clickhouse` et `/var/backups/clickhouse` au nom de l'uid 101 (celui de ClickHouse dans l'image), sinon Docker crée le second au nom de root et `BACKUP` échoue ; ajouter `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD` et `CLICKHOUSE_PLAY_PASSWORD` au `.env`.
   - `BACKUP` d'essai d'une petite table vers `/var/backups/clickhouse`, puis `RESTORE` dans une base de test.
1. **Gel.** Mettre en pause plannings et sensors Dagster, attendre la fin des runs. Le site continue de lire les marts Citus.
2. *(supprimée : la sauvegarde de raw part de ClickHouse, à l'étape 7.)*
3. **Fusionner la PR A et déployer.** ClickHouse démarre à côté de Citus, sur `/mnt/pgdata/clickhouse`, avec le DDL de raw. Les plannings restent en pause.
4. **Supprimer la staging Citus.** D'abord la vue `staging.steam_review`, qui est le seul objet dépendant, puis `steam_review_versions`, `steam_review_outdated` et les autres tables de staging, qui se reconstruisent. On libère ~32 Go, soit ~72 Go libres. Les marts restent, le site ne voit rien.
5. **Copier raw** de Citus vers ClickHouse, table par table, avec `INSERT INTO raw.… SELECT … FROM postgresql(…)`.
   - Les identifiants Postgres passent par une *named collection* dans `config.d`, que l'utilisateur écrit. Autrement, le mot de passe apparaîtrait en clair dans `system.query_log`.
   - Environ 37 Go écrits, soit ~35 Go libres. Durée : ~1 h, selon le débit de lecture de Citus.
   - Les fusions de parts ont besoin d'espace temporaire. La partition par mois borne la taille des parts, et ClickHouse reporte une fusion plutôt que de remplir le disque.
6. **Vérifier la parité de raw** : nombre de lignes, `uniqExact(app_id, recommendation_id)` par jeu, sommes de contrôle sur un échantillon de jeux. Jusqu'ici, revenir en arrière ne coûte qu'une reconstruction de la staging Citus.
7. **Sauvegarder raw, puis le supprimer de Citus.**
   - `BACKUP DATABASE raw TO File('raw_<date>')` depuis ClickHouse, puis vérifier que la sauvegarde se relit : `RESTORE` de `raw.steam_game_details` dans une base de test, et comparaison des comptes. ~37 Go sur le disque local, ~23 Go libres ensuite.
   - Supprimer raw et les événements Citus. On libère ~50 Go, soit ~85 Go libres. Revenir en arrière demande désormais un `RESTORE` depuis cette sauvegarde.
8. **Premier `dbt build`** dans ClickHouse, lancé depuis Dagster : staging (~29,5 Go, ~1 h 30 de parse), intermediate, marts (~20 min). Environ 45 Go libres ensuite, ~60 Go une fois Citus supprimé.
9. **Basculer le site** sur ClickHouse et vérifier les pages principales : accueil, fiche jeu, classements, sitemap. Les marts Citus existent encore : revenir en arrière ne demande qu'un redéploiement du site.
10. **Basculer Dagster.**
    - Arrêter webserver, daemon et user-code.
    - `pg_dump -n public` depuis Citus (~260 Mo), maintenant et pas plus tôt : les runs des étapes 3 à 8 doivent y figurer.
    - Fusionner et déployer la PR B, restaurer le dump dans le `postgres:16` neuf, redémarrer Dagster.
    - Garder le répertoire de données Citus (~20 Go restants) une semaine sans incident, puis le supprimer.
11. **Reprise.** Réactiver les plannings. Surveiller le premier incrémental et le premier build nocturne : durées, pic mémoire, reviews/s.

Les étapes 3 à 10 se font dans la même session, Dagster en pause. Durée estimée : 3 à 4 h, dont ~1 h de copie, la sauvegarde sur le disque local (durée à mesurer) et ~2 h de `dbt build`.

## Questions ouvertes

- Coût de `final = 1` sur les lectures nocturnes à pleine échelle.
- Mémoire des fenêtres et de la jointure de `review_highlight` à pleine échelle (premier build).
- Migration ou abandon de `scratch` et `audit`.
- Durée du `BACKUP` sur le disque local.
- Bucket Object Storage pour une copie hors du serveur.
