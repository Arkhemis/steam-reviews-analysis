# Lenteur des filtres par app_id et alternatives à Citus columnar

État au 28 septembre 2026, avant la décision de migrer vers ClickHouse.

> Analyse antérieure à la migration. Le banc suivant ([migration_clickhouse.md](migration_clickhouse.md)) a montré que ClickHouse tient sous 3,5 Go de RAM sur le VPS, avec un disque proche de Citus, des agrégats ~8× plus rapides et un DML natif : la recommandation « rester sur Citus » ci-dessous est caduque.

## Diagnostic

`SELECT * FROM staging.steam_review WHERE app_id = 730 LIMIT 100` tournait plus de 13 minutes.

La table n'a pas besoin d'être réorganisée : `staging.steam_review_versions` est **déjà regroupée par app_id**.
- Elle compte 18 378 chunk groups.
- Dans la moitié d'entre eux, l'écart entre le min et le max d'app_id vaut 0 : un seul jeu par chunk group.

Ce regroupement n'était pourtant pas utilisé, parce que Citus ne pousse un filtre dans le scan que si la corrélation de la colonne dans `pg_stats` dépasse `columnar.qual_pushdown_correlation_threshold`, qui vaut 0,9 par défaut.
- app_id est regroupé mais pas trié : sa corrélation vaut -0,35.
- Aucun chunk group n'était donc sauté, et 164 M lignes étaient filtrées une à une.
- `loaded_at`, à 0,999, passe le seuil : c'est pour ça que le filtre littéral fonctionne sur raw.

À vérifier en premier devant un filtre lent sur une table columnar : la ligne `Columnar Chunk Groups Removed by Filter` de l'`EXPLAIN ANALYZE`. Si elle est absente, le filtre n'a pas été poussé dans le scan.

## Correctif appliqué

J'ai posé `ALTER DATABASE steam_reviews SET columnar.qual_pushdown_correlation_threshold = 0` en prod. Il n'est pas versionné : Citus disparaît avec la migration.

| Requête | Avant | Après |
| --- | --- | --- |
| `SELECT app_id FROM staging.steam_review_versions WHERE app_id = 730 LIMIT 100` | 27 s | 1 s |
| `SELECT * FROM staging.steam_review WHERE app_id = 730 LIMIT 100` | > 13 min | 3,3 s |

Le réglage ne s'applique qu'aux nouvelles sessions : une connexion déjà ouverte, dans DbGate par exemple, doit être rouverte. Son coût est négligeable : sur une colonne mal corrélée, le filtre poussé revient à lire des min/max déjà en mémoire.

## Alternatives à Citus columnar

Contraintes : gratuit et self-hosted. Préférence forte pour Postgres et pour des projets éprouvés. Pour cette étude, j'ai aussi regardé des projets jeunes et des moteurs hors Postgres.

Les tailles du tableau ci-dessous viennent du benchmark du 8 septembre, le reste d'une recherche documentaire. Citus, Timescale et pg_ducklake ont depuis été mesurés sur nos données : voir le banc du 28 septembre.

### Candidats sérieux

| Option | Licence | Maturité | DML | Saut par app_id | Taille / mémoire | Effort |
| --- | --- | --- | --- | --- | --- | --- |
| **Citus columnar** (en place, 14.1 ; 14.2 disponible) | AGPL | Stable, mais columnar ne reçoit plus que de la maintenance | Non | Min/max par chunk group, avec seuil à 0 | 93 o/ligne typé, 142 o JSONB | Nul |
| **TimescaleDB hypercore** (2.30.1) | TSL (gratuite en self-hosted, interdit la revente « as a service ») | Mûr, releases mensuelles | UPDATE, DELETE et `ON CONFLICT` sur les données compressées | Index sparse min/max et bloom, `orderby app_id` sans segmentby | 215 o/ligne typé, 357 o JSONB : ~105 Go contre ~71 Go aujourd'hui | Moyen |
| **pg_ducklake** (1.0.2) | MIT | Jeune, un seul mainteneur principal | Oui, et les petits lots sont tamponnés avant écriture en Parquet | Partitionnement et tri | Parquet zstd, non mesuré ; un moteur DuckDB par connexion, à plafonner | Moyen |
| **pgColumnar** (1.0-alpha4, Command Prompt) | MIT | Alpha créée en juillet 2026 ; format sur disque non stable | UPDATE et DELETE, autovacuum optionnel | Zone maps et filtre de Bloom par chunk | Non documentée | Moyen |

Ce que Timescale ou pg_ducklake supprimeraient par rapport à Citus : le registre des versions périmées, la vue anti-join et l'ANALYZE manuel. dbt pourrait de nouveau utiliser `merge` ou `delete+insert`.

### Banc du 28 septembre : Citus, Timescale et pg_ducklake mesurés

Échantillon : un jeu sur 30 de `staging.steam_review_versions`, avec `(app_id / 10) % 30 = 7` (les app_id sont des multiples de 10). On garde la dernière version de chaque review : 5 005 499 lignes et 4 426 jeux, soit 2,7 % de la prod. Les trois moteurs tournent en local dans des conteneurs PG16 limités à 4 CPU et 8 Go, avec les réglages mémoire de la prod (`shared_buffers` 160 Mo, `work_mem` 4 Mo).

Configurations :
- **Citus 14.1** : zstd 3, 10 k lignes par chunk group, seuil de pushdown à 0.
- **Timescale 2.30.1** : chunks d'un an sur `created_at`, `orderby app_id, recommendation_id, updated_at`, sans segmentby, avec un index unique pour `ON CONFLICT`.
- **pg_ducklake 1.0.2** : Parquet zstd 3, trié sur `(app_id, recommendation_id)`.

**Taille**

| | o/ligne | Extrapolé à 184 M lignes |
| --- | --- | --- |
| Citus | 174,5 | 32,1 Go (32,4 Go mesurés en prod) |
| Timescale | 282,5 | 51,9 Go (+62 %) |
| pg_ducklake | 164,3 | 30,2 Go (−6 %) |

**Lectures** (médiane sur 5 passes, connexion neuve à chaque passe, cache chaud)

| Requête | Citus | Timescale | pg_ducklake |
| --- | --- | --- | --- |
| `WHERE app_id = X LIMIT 100` (gros, moyen, petit jeu) | 0,02 / 0,04 / 0,03 s | 0,01 / 0,01 / 0,03 s | 0,10 / 0,13 / 0,09 s |
| `count` + `avg` sur un jeu (1,07 M / 37 k / 200 lignes) | 0,12 / 0,01 / 0,01 s | 0,07 / 0,05 / 0,05 s | 0,04 / 0,03 / 0,03 s |
| `GROUP BY app_id` sur toute la table | 0,72 s | 0,14 s | 0,09 s |
| `review_text ILIKE '%…%'` sur toute la table | 5,8 s | 2,3 s | 9,0 s |
| Pic RSS d'un backend, toutes requêtes | 271 Mo | 191 Mo | 165 Mo |

pg_ducklake coûte environ 0,1 s fixe par requête, le démarrage du moteur DuckDB de la connexion. Les durées absolues ne sont pas celles du VPS : seuls les écarts entre moteurs comptent.

**DML** : lot quotidien réaliste ramené à l'échelle, 3 000 lignes (2 300 reviews récentes mises à jour, 300 de plus d'un an, 400 nouvelles), profil relevé en prod sur les derniers jours.

| | Citus | Timescale | pg_ducklake |
| --- | --- | --- | --- |
| `MERGE` (stratégie dbt `merge`) | impossible | refusé sur hypertable compressée | 3,6 s |
| `DELETE … USING` + `INSERT` (dbt `delete+insert`) | impossible | 54 à 97 s : décompresse 95 % de la table, qui passe de 1,4 à 4,4 Go | 0,2 s |
| `INSERT … ON CONFLICT` | impossible | 2,5 s, +165 Mo non compressés jusqu'à la recompression | non testé |
| `UPDATE` d'un jeu (37 k lignes) / `DELETE` d'un jeu | impossible | 0,5 s / 0,02 s | 0,3 s / 0,05 s |
| Pic RSS | 35 Mo (append) | 224 Mo | 383 Mo |

Timescale limite par défaut une transaction DML à 100 000 tuples décompressés (`timescaledb.max_tuples_decompressed_per_dml_transaction`) : il faut monter ce plafond ou le désactiver. Après le delete+insert, il faut compter 2 min de VACUUM, 2 min 20 de recompression et 3 min 40 de VACUUM pour revenir à 1,8 Go, dont 374 Mo d'index gonflé qu'un VACUUM ne rend pas. À l'échelle de la prod, ce pic tournerait autour de 160 Go, plus que le volume.

pg_ducklake impose deux changements de types : il ne connaît pas `jsonb` (`reactions` passe en `json`), et il tronque `numeric` en `decimal(18,3)` (`weighted_vote_score` passe en `double precision`).

**Verdict**
- **Timescale est écarté** : +62 % de disque, et les deux stratégies incrémentales de dbt échouent, l'une refusée, l'autre ruineuse. Seul `ON CONFLICT` passe, ce qui demanderait une stratégie dbt maison.
- **pg_ducklake passe le seuil fixé plus bas** : il ne gagne que 6 % de disque, mais `delete+insert` fonctionne en 0,2 s avec moins de 400 Mo par requête. Le registre des versions et l'anti-join pourraient donc disparaître. Ses limites restent un seul mainteneur, 0,1 s de latence fixe et un scan texte plus lent.

### Écartés

| Option | Raison |
| --- | --- |
| Hydra columnar | Abandonné en 2025 |
| storage_engine (fork de Hydra) | Un seul auteur, inactif depuis juin 2026 |
| pg_mooncake | Racheté par Databricks en octobre 2025, dépôt gelé |
| ParadeDB pg_analytics | Archivé en mars 2025 |
| ParadeDB pg_search | Index de recherche plein texte posé sur du heap (486 o/ligne) |
| pg_duckdb | Pas de stockage columnar persistant dans Postgres |
| pg_parquet | Import/export via COPY, pas un stockage ; inactif depuis novembre 2025 |
| pg_lake (Snowflake) | Demande un stockage objet ; son process prend 80 % de la RAM par défaut |
| OrioleDB | Stockage en lignes, en bêta |
| Apache Cloudberry | Fork complet de Postgres ; le mode mono-nœud est prévu pour le dev et les tests |
| CedarDB Community | Binaire fermé, passe en lecture seule au-delà de 64 GiB |
| ClickHouse, StarRocks, Doris | Trop lourds à côté de Postgres sur 7,6 Go (StarRocks recommande 32 Go) |
| DuckLake + dbt-duckdb | Mûr (1.0), mais c'est une seconde pile, et il faudrait recopier les marts dans Postgres pour le site |
| chDB, Databend, GlareDB | Pas de lien avec Postgres, builds nightly seulement, ou projet en sommeil |
| QuestDB, GreptimeDB, InfluxDB 3 | Moteurs de séries temporelles, mal adaptés au texte et au JSONB |

## Recommandation

1. **Rester sur Citus columnar**, avec le seuil à 0 et les contournements actuels. C'est la seule option mesurée et la plus compacte.
2. **Réduire le nombre de stripes de raw** : écrire les petits lots de l'ingestion dans une table heap tampon, puis les verser dans `raw.steam_reviews` en un seul `INSERT … SELECT` par nuit. On aurait un stripe par nuit au lieu d'un par transaction : raw en compte 128 k aujourd'hui, et ils coûtent environ 28 s de métadonnées par lecture filtrée. Le gain est estimé, pas mesuré.
3. **Monter Citus de 14.1 à 14.2** au passage.
4. **Si le DML redevient une douleur**, faire un essai borné sur la staging seulement, jamais sur raw ni sur la prod :
   - pg_ducklake en premier ;
   - pgColumnar une fois sa version 1.0 stable sortie ;
   - Timescale si le disque le permet.

   Mesures à relever : octets par ligne, latence de `WHERE app_id = X`, mémoire par requête.

   Seuil pour migrer : au moins 20 % de disque en moins ou la disparition du registre des versions et de l'anti-join, avec une mémoire sous 1 Go par requête.

La réécriture de la table triée par app_id n'est pas nécessaire : les données sont déjà regroupées par jeu, et le seuil à 0 suffit à en profiter.

