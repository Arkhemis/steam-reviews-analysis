# Passer `steam_review` en incrémental

*24/09/2026. Quatre experts Data Eng, un par proposition. Chacun a challengé une proposition, puis critiqué celles des autres, puis tous ont amendé et signé un consensus. Les chiffres **mesurés** viennent de la prod (en lecture seule) ou de bancs Citus 14.1 locaux. Les chiffres **estimés** sont des extrapolations.*

## Recommandation

Arrêter de reconstruire les 183 M lignes chaque nuit.

- `staging.steam_review` devient une table **append-only versionnée**, alimentée chaque nuit par le seul delta de raw.
- Un petit **registre des versions périmées** complète cette table.
- Une **vue** assemble les deux pour donner la dernière version de chaque review.
- Une **compaction en place** a lieu environ tous les 10 mois (registre > 3 M lignes, voir la validation en prod).

Signé par les quatre experts, avec amendements (intégrés ci-dessous). Le changement de moteur (Timescale) est écarté à l'unanimité.

| | Aujourd'hui | Cible (estimé) |
| --- | --- | --- |
| `steam_review` + tests, chaque nuit | 2 h 09 + ~20 min | ~5 min (append) + 2-4 min (registre) + tests du delta |
| Surcoût pour les marts aval | 0 | +37 % par scan de la vue avec le registre actuel, +68 % à 5 M lignes (mesuré en prod) |
| Durée du daily (après le fix des steps) | ~4 h 40 | **~3 h 10**. La branche events (~3 h 10) devient le chemin critique. |
| Pic disque chaque nuit | +32 Go (copie `__dbt_tmp`) sur 42 Go libres | **0** |
| Marge disque dans 12 mois | négative avec le swap dbt | ~12 Go au rythme de septembre (à confirmer) |

## Constat

- **Volumes.** `raw.steam_reviews` : 184,2 M lignes, 41 Go en columnar (le payload fait 195 Go décompressé). `staging.steam_review` : 183,6 M lignes, 32,2 Go. Le ratio versions/reviews est de **1,003**.
- **Arrivées.** ~80 k lignes par nuit (entre 55 k et 100 k), dont ~23 k nouvelles versions. Environ 12 k finissent réellement périmées par nuit : 575 k accumulées en ~48 nuits. On retraite donc 100 % de la table pour 0,05 % de changements.
- **Où partent les 2 h 09** (banc local, mesuré) :

| Étape | Part |
| --- | --- |
| Extraction JSON | ~60 % |
| Écriture et compression columnar | ~25 % |
| Dédoublonnage | ~9 % |
| ANALYZE | +11 % |

  Le build ne tourne que sur un seul cœur, car ColumnarScan n'est jamais parallèle (mesuré).
- **Le columnar interdit DELETE, UPDATE et ON CONFLICT.** Les stratégies dbt `merge` et `delete+insert` sont donc exclues. Seuls restent l'append, `TRUNCATE` et `CREATE INDEX`.
- **Le filtre sur `loaded_at` est efficace sur raw.** Avec une valeur littérale, il saute 97 % des chunk groups (140 447 sur 144 997, mesuré). Il reste un surcoût fixe d'environ 28 s, dû aux 128 k stripes.

## Les quatre propositions challengées

| | Proposition | Verdict | Raison principale |
| --- | --- | --- | --- |
| **P0** | Garder le full rebuild en le rendant moins cher | ❌ comme solution, ✅ comme correctif rapide | Gain de 25 à 40 min au mieux. Plancher d'environ 1 h 30, car 85 % du coût (parsing + écriture) porte sur 183 M lignes. Pic de 30 Go inchangé. |
| **P1** | Base columnar reconstruite chaque semaine + delta heap chaque nuit + vue | ⚠️ sous conditions | Environ 2 h gagnées par nuit, mais le pic de 30 Go et le build de 2 h 09 restent une fois par semaine. Le delta en `table` fait supprimer la vue chaque nuit (`drop … cascade`). |
| **P2** | Staging append-only versionné + registre des versions périmées + vue | ✅ sous conditions, retenue | Environ 2 h gagnées, plus aucun pic. L'index btree prévu est contre-productif, et la clé du registre doit être corrigée. |
| **P3** | Passer à Timescale hypercore avec upserts et fusionner raw et staging | ❌ | Un upsert décompresse ~945 tuples par ligne modifiée, et la taille double sans VACUUM FULL (mesuré). Citus et Timescale ne cohabitent pas. La migration est impossible avec 42 Go libres, et le payload brut est perdu. |

## Ce que le débat a fait changer

**Erreurs relevées d'un expert à l'autre**
- **Filtre incrémental standard de dbt.** `loaded_at > (SELECT max(...) FROM {{ this }})` est évalué comme une sous-requête. Citus ne saute alors **aucun** chunk group (0 contre 981 avec un littéral, mesuré) et le modèle relirait les 41 Go de raw. Le watermark doit être injecté comme **littéral** via `run_query`. Ce point concerne P1 comme P2.
- **Index btree sur columnar.** ~5,8 Go, et un lookup coûte 1 à 3 ms par clé, car il décompresse un chunk group. Pour 23 k éditions, c'est plus lent qu'une jointure de hachage sur un scan étroit (75 s contre ~31 s). Abandonné.
- **Identité d'une version.** `loaded_at` vaut `now()`, c'est-à-dire l'heure de début de la transaction. 29 lignes ont la même clé et le même `loaded_at` pour des `timestamp_updated` différents (mesuré). La clé d'une version est donc `(app_id, recommendation_id, timestamp_updated)`.
- **Watermark strict.** Une transaction de backfill longue, commitée tard, porte un `loaded_at` antérieur au watermark : ses lignes seraient perdues pour toujours. Il faut une **fenêtre de recouvrement**, rendue idempotente par le dédoublonnage.
- **Filtre `timestamp_created <> timestamp_updated`.** Il ne suffit pas à repérer les doublons : la seconde-frontière réinsère aussi des versions identiques de reviews jamais éditées.
- **TRUNCATE + INSERT dans une même transaction.** Le pic de 32 Go est conservé, car l'ancien fichier n'est supprimé qu'au commit. Et une compaction via la matérialisation incremental de dbt reconstruit aussi une `__dbt_tmp`.
- **Coût de la vue.** L'estimation de 30 à 90 s par scan était optimiste. La valeur retenue est **1,5 à 2 min par scan** (+76 % à +113 %, mesuré en local). La mesure en prod donne pire : **+4 min 34** (+70 %) sur `game_review_trend_daily`.

**Points tranchés**
- **Vue sans registre** : non viable (unanime). Un `NOT EXISTS` ou un `DISTINCT ON` recalculé à chaque lecture revient à un `GROUP BY` ou à une auto-jointure sur 183 M lignes, pour chacun des 6 consommateurs.
- **Risque merge join / `work_mem` à 4 Mo côté site** : il n'existe pas. Le site ne lit que des marts, de l'intermédiaire et quelques tables raw, jamais `staging.steam_review` (vérifié dans le code du site). Pas d'`ALTER ROLE`.
- **Compaction** : nécessaire, mais rare. Le coût n'est pas le stockage (~1,4 Go de lignes mortes par an), mais le hash de l'anti-join. Il déborde sur disque au-delà de `work_mem × 2` (~52 à 70 o par entrée, mesuré), et chaque consommateur écrirait alors plusieurs Go de fichiers temporaires.

## Solution retenue en détail

**0. Tout de suite, quelle que soit la suite (P0)**
- Supprimer le test d'unicité sur `raw.steam_reviews`. Raw contient des doublons par construction, donc il avertit chaque nuit : ~10 min.
- Passer le test d'unicité complet de `steam_review` en hebdomadaire : ~10 min.
- Limiter `ANALYZE` à une liste de colonnes, sans le supprimer, car le columnar échappe à l'autovacuum : 3 à 8 min.

**1. `steam_review_versions`, modèle dbt `incremental`, stratégie `append`, columnar**
- Calcul du watermark à la compilation (`{% if execute and is_incremental() %}`) :
  - `max(loaded_at)` est lu par `run_query`, avec un filtre littéral `loaded_at > run_started_at − 30 j` pour que la lecture reste rapide ;
  - on retire 2 jours de recouvrement ;
  - la valeur est injectée en `'…'::timestamptz` ;
  - `raise_compiler_error` si elle est NULL (garde-fou « table vide »).
- Dédoublonnage du delta : `DISTINCT ON (app_id, recommendation_id, timestamp_updated)`, plus un anti-join contre les triplets déjà présents.
- **Un seul scan étroit de `versions` par nuit** : il sert à la fois à ce dédoublonnage et à l'alimentation du registre.
- Parsing JSON dans **une macro commune** au modèle, à la compaction et au full refresh.
- `on_schema_change='append_new_columns'`. Pour une nouvelle colonne, un seul run avec compaction forcée suffit : la compaction la crée depuis `steam_review_parse` puis remplit l'historique.
- L'append ne fait qu'un `INSERT` dans la table existante : pas de swap, donc la vue n'est pas supprimée.

**2. `steam_review_outdated`, heap incrémental**
- Contient `(app_id, recommendation_id, timestamp_updated)` des versions dépassées.
- Alimenté par une jointure de hachage entre le delta et `versions`, sur les colonnes de clé uniquement, sans index. Estimé : 2 à 4 min.
- **Reconstruit en entier une fois par mois** (`GROUP BY … HAVING count(*) > 1` sur `versions`) pour se corriger lui-même. La sortie est petite et il n'y a pas de pic.

**3. `steam_review`, vue**
- Définition : `versions` anti-join `outdated`.
- Les consommateurs ne changent pas.
- Pre-hook dans `intermediate` et `marts` : `SET work_mem = '128MB'; SET enable_mergejoin = off`.
- Avec `threads: 4`, cela fait au plus ~1 Go de hash simultané sur 7,6 Go de RAM.

**4. Compaction en place**
- Une macro `dbt run-operation compact_steam_review`, lancée par un op Dagster dans le run, après l'ingestion :
  1. `TRUNCATE` **commité à part** de `versions` et du registre ;
  2. un seul `INSERT INTO versions`, avec la macro de parsing et le dédoublonnage en une passe sur le payload.
- Pas de pic disque. La vue et le site ne sont pas touchés.
- Si la compaction échoue, le garde-fou « table vide » bloque le run suivant, et dbt ne lance pas les marts aval.
- **Déclenchement quand le registre dépasse 3 M lignes**, soit environ tous les 10 mois au rythme mesuré. Vers 3,5 M, le hash du registre dépasse la mémoire allouée (voir la validation en prod). C'est aussi le chemin du full refresh.

**5. Tests**
- Unicité et not_null sur les clés du delta, chaque nuit.
- Test complet hebdomadaire, plus une comparaison sur un échantillon de jeux entre un recalcul de la dernière version et la vue.

## DDL des nouvelles tables

Ces tables seront créées par dbt. Les DDL ci-dessous en montrent la forme exacte : types relevés dans le catalogue de prod de `staging.steam_review` le 24/09/2026.

### `staging.steam_review_versions`

Columnar, append-only. Elle contient **toutes** les versions de chaque review.

```sql
CREATE TABLE staging.steam_review_versions (
    recommendation_id                      bigint      NOT NULL,
    app_id                                 bigint      NOT NULL,

    author_steamid                         bigint,
    author_personaname                     text COLLATE "C",
    author_profile_url                     text COLLATE "C",
    author_avatar                          text COLLATE "C",
    author_persona_status                  text COLLATE "C",
    author_num_games_owned                 integer,
    author_num_reviews                     integer,
    author_playtime_forever_minutes        integer,
    author_playtime_at_review_minutes      integer,
    author_playtime_last_two_weeks_minutes integer,
    author_last_played_at                  timestamptz,

    review_text                            text COLLATE "C",
    language                               text,
    voted_up                               boolean,
    votes_up                               integer,
    votes_funny                            integer,
    weighted_vote_score                    numeric,
    comment_count                          integer,
    steam_purchase                         boolean,
    received_for_free                      boolean,
    written_during_early_access            boolean,
    primarily_steam_deck                   boolean,
    refunded                               boolean,
    app_release_date                       timestamptz,
    reactions                              jsonb,

    created_at                             timestamptz,
    updated_at                             timestamptz NOT NULL,  -- identifie la version
    loaded_at                              timestamptz NOT NULL,  -- sert au watermark, pas à l'identité

    review_text_length                     integer,
    is_generic                             boolean
) USING columnar;
```

- **Aucune contrainte ni index.** Une clé unique poserait un btree de ~5,8 Go, plus lent qu'une jointure de hachage (voir le débat).
- **Invariant garanti par le modèle et vérifié par les tests** : `(app_id, recommendation_id, updated_at)` est unique.
- Les colonnes sont celles de `staging.steam_review` aujourd'hui : les consommateurs ne voient aucune différence.

### `staging.steam_review_outdated`

Heap, petite table (< 3 M lignes avant compaction).

```sql
CREATE TABLE staging.steam_review_outdated (
    app_id            bigint      NOT NULL,
    recommendation_id bigint      NOT NULL,
    updated_at        timestamptz NOT NULL,  -- version périmée
    outdated_at       timestamptz NOT NULL DEFAULT now(),  -- nuit de détection, pour le suivi
    PRIMARY KEY (app_id, recommendation_id, updated_at)
);
```

- Heap : `default_table_access_method = 'columnar'` du dossier staging est surchargé dans la config du modèle.
- La PK coûte ~150 Mo à 3 M lignes. Elle rend l'alimentation idempotente (relance Dagster, fenêtre de recouvrement).
- `ANALYZE` en post-hook : le planner doit la voir petite pour la prendre comme côté hash.

### `staging.steam_review`

Vue qui remplace la table actuelle, sous le même nom.

```sql
CREATE VIEW staging.steam_review AS
SELECT v.*
FROM staging.steam_review_versions AS v
WHERE NOT EXISTS (
    SELECT 1
    FROM staging.steam_review_outdated AS s
    WHERE s.app_id = v.app_id
      AND s.recommendation_id = v.recommendation_id
      AND s.updated_at = v.updated_at
);
```

- `NOT EXISTS` produit un hash anti-join, avec le registre comme côté haché. Le pre-hook `enable_mergejoin = off` des consommateurs empêche le tri des 183 M lignes.
- `ref('steam_review')` ne change pas dans les 6 consommateurs.

## Exemple de données, sur trois nuits

*Données fictives : identifiants, pseudo et texte sont inventés. Seules les colonnes utiles à l'exemple sont montrées.*

Le cas : une review de `app_id = 1086940` est publiée le 20/09, éditée le 23/09, puis réinsérée à l'identique le 24/09 (la seconde-frontière du loader).

### Nuit du 21/09 : première version

`raw.steam_reviews` reçoit une ligne. L'append l'ajoute à `versions`, et le registre ne change pas.

`steam_review_versions`

| app_id | recommendation_id | updated_at | loaded_at | voted_up | votes_up | review_text | review_text_length |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1086940 | 201934577 | 2026-09-20 18:02:11+00 | 2026-09-20 22:14:03+00 | false | 3 | "Crash au chapitre 2, injouable." | 32 |

`steam_review_outdated` : vide pour cette clé.

`steam_review` (vue) : 1 ligne, `voted_up = false`.

### Nuit du 24/09 : l'auteur édite sa review

Raw reçoit une **nouvelle ligne** pour la même clé, avec un `updated_at` plus récent. L'append l'ajoute. La jointure de hachage entre le delta et `versions` trouve l'ancienne version et l'inscrit au registre.

`steam_review_versions`

| app_id | recommendation_id | updated_at | loaded_at | voted_up | votes_up | review_text | review_text_length |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1086940 | 201934577 | 2026-09-20 18:02:11+00 | 2026-09-20 22:14:03+00 | false | 3 | "Crash au chapitre 2, injouable." | 32 |
| 1086940 | 201934577 | 2026-09-23 09:47:55+00 | 2026-09-23 22:31:40+00 | true | 5 | "EDIT : corrigé par le patch 3, excellent jeu." | 45 |

`steam_review_outdated`

| app_id | recommendation_id | updated_at | outdated_at |
| --- | --- | --- | --- |
| 1086940 | 201934577 | 2026-09-20 18:02:11+00 | 2026-09-23 23:12:08+00 |

`steam_review` (vue) : 1 ligne, la version du 23/09 (`voted_up = true`).

### Nuit du 25/09 : réinsertion identique, dans la fenêtre de recouvrement

Deux choses arrivent en même temps :
- le loader réinsère la même version dans raw (même `updated_at`, nouveau `loaded_at`) ;
- la fenêtre de recouvrement (watermark − 2 j) relit aussi la ligne du 23/09.

Le triplet `(1086940, 201934577, 2026-09-23 09:47:55)` existe déjà dans `versions`. L'anti-join de l'append l'écarte. Rien n'est ajouté à `versions` ni au registre, et la vue ne bouge pas. C'est ce qui rend le recouvrement idempotent.

### Compaction (registre > 3 M lignes)

Deux étapes :
1. `TRUNCATE` commité des deux tables ;
2. `INSERT` de la seule dernière version de chaque clé depuis raw.

Après compaction, `versions` ne contient plus que la ligne du 23/09, et le registre est vide. La vue renvoie exactement la même chose qu'avant.

## Validation en prod (24/09)

Mesures faites en prod le soir du 24/09, serveur au repos, en trois passes : témoin sans registre, puis avec registre, puis de nouveau témoin. On a utilisé `staging.steam_review` actuel et un registre simulé en table temporaire, avec les pre-hooks prévus (`work_mem = 128MB`, `enable_mergejoin = off`). Une première série, faite l'après-midi, était faussée : le site chargeait le serveur, et une limite de test de 10 Go sur les fichiers temporaires était plus basse que celle de la prod (30 Go).

**1. Coût de l'anti-join, sur `game_review_trend_daily`**

| Registre | Écart avec le témoin |
| --- | --- |
| 637 k clés (taille actuelle) | **+37 %** |
| 5,1 M clés (plus d'un an sans compaction) | **+68 %**, ~11 Go de fichiers temporaires au pic, sous la limite de 30 Go |

- Vers 3,5 M lignes (256 Mo à ~70 o par entrée), le hash du registre ne tient plus dans la mémoire allouée. La jointure passe alors en lots et écrit sur disque, sans échouer.
- Conséquence : **seuil de compaction à 3 M lignes**, sous ce point.

**2. Croissance, mesurée sur les derniers jours (hors backfills du début septembre)**
- raw reçoit ~77 k lignes par jour, et ~10 k versions deviennent périmées chaque jour.
- Cela fait **~3,7 M versions périmées par an**, soit une compaction environ tous les 10 mois.
- Construire le registre a pris 3 min 52 pour 5 M clés : l'estimation de 2 à 4 min tient.

**3. Marge disque**
- ~11 Go par an (raw et `versions`), pour 41 Go libres le 24/09.
- À suivre chaque trimestre.

**Filet de sécurité non retenu par défaut.** PGDATA est sur un volume Hetzner Cloud agrandissable à chaud (`resize2fs`, sans coupure), pour environ 5 € par mois pour 100 Go (tarif non vérifié). L'expert P3 le préférait à la compaction en place. La majorité l'a jugé inutile avec une compaction qui ne fait pas de pic, mais c'est la sortie la plus simple si la marge fond plus vite que prévu.

## Implémentation (PR #48)

Trois écarts au design, et la procédure de mise en production.

**Écarts**
- **Deux scans étroits de `versions` par nuit, au lieu d'un.** L'anti-join de l'append et l'alimentation du registre sont deux modèles dbt. Le registre part des reviews touchées dans raw et garde, pour chacune, les versions qui ne sont pas la plus récente. Son watermark est sa propre dernière nuit réussie (`max(outdated_at)` − 3 jours), avec repli sur `versions` quand la compaction l'a vidé. Le déduire de `versions`, qui a déjà rattrapé son retard dans le même build, oublierait les reviews éditées au début d'une panne de plus de 3 jours.
- **La compaction est lancée par l'op dbt de Dagster, juste avant le `dbt build`** (`orchestration/dbt/compaction.py`), et non par un op séparé. Ainsi, rien ne peut s'intercaler entre la compaction et l'append. La taille du registre est publiée en observation Dagster de `steam_review_outdated` à chaque run.
- **Les compteurs d'une version sont figés à sa première capture.** Aujourd'hui, une review re-scrapée avec le même `timestamp_updated` (seconde-frontière, re-backfill d'un jeu) prend les `votes_up` et temps de jeu les plus récents. Désormais, seule la compaction les rafraîchit.

**Réglages**
- Les tests complets (unicité sur la vue, comparaison à raw sur 20 jeux tirés au sort) ne tournent que le dimanche, ou avec `--vars '{full_tests: true}'`. Les autres jours, ils passent à vide.
- Le registre est recalculé en entier le 1er du mois, ou avec `--vars '{rebuild_steam_review_outdated: true}'`.
- `versions` et le registre ont `full_refresh=false`. Un full refresh depuis Dagster passe par la compaction. À la main : `dbt run-operation compact_steam_review`.

**Mise en production**

La table actuelle contient déjà la dernière version de chaque review, c'est-à-dire l'état après compaction. On la renomme donc au lieu de la reconstruire : on évite ainsi 2 h de build et un pic de 30 Go.

1. Merger dans la journée, et loin de 22:00 UTC : la CD reconstruit ensuite tout l'aval de `steam_review`, soit plusieurs heures.
2. Juste avant le merge, sans run dbt en cours :
   ```sql
   BEGIN;
   ALTER TABLE staging.steam_review RENAME TO steam_review_versions;
   CREATE VIEW staging.steam_review AS SELECT * FROM staging.steam_review_versions;
   COMMIT;
   ```
3. La CD append le delta, construit le registre en entier, puis remplace la vue temporaire par la vraie et reconstruit l'aval.
4. Si le run CD n'est pas fini avant 22:00 UTC, mettre en pause le daily de ce soir-là.

Sans l'étape 2, dbt reconstruit `versions` depuis raw, avec 2 h de build et +30 Go pendant que l'ancienne table existe encore.

## Chantiers annexes repérés

- **`RECOUNT_BACKFILLED_SQL`** (`orchestration/steam/incremental.py`). À chaque run, il fait un `count(DISTINCT recommendation_id) … GROUP BY app_id` sur les 184 M lignes de raw. Ce calcul est dans `steam_reviews_incremental`, donc sur le chemin critique du gros step dbt. Prioritaire selon l'expert P2.
- **Stripes minuscules dans raw.** 122 k stripes de moins de 100 lignes, et ~4 500 de plus chaque nuit : les loaders committent souvent. Le gaspillage disque est inférieur à 0,5 Go, mais le surcoût de métadonnées (~28 s par lecture filtrée) croît d'environ 1,6 M stripes par an.
  - Correctif proposé : **regrouper les commits** dans les loaders (par exemple tous les 50 k lignes, avec le checkpoint dans la même transaction). Environ 20 lignes, sans nouvel état.
  - La table tampon heap a été écartée : DDL manuel en prod, et risque de perte si le checkpoint avance sans le tampon.
  - Deux experts veulent le faire maintenant, deux dans 3 à 6 mois.
- **Compacter raw a posteriori** : exclu. `SET ACCESS METHOD` ferait un aller-retour en heap de 203 Go, et une réécriture columnar un pic de 41 Go, pour récupérer moins de 0,5 Go.
- **Requête lente du site steam.reviews** (vue pendant les mesures). `SELECT MAX(review_date) FROM marts.game_review_trend_daily WHERE app_id = $1` parcourt à rebours l'index sur `review_date` jusqu'à trouver le jeu, au lieu de passer par l'index sur `app_id`. Cela prend 0,85 s pour le jeu 730, et plusieurs minutes pour un petit jeu sans review récente : 10 à 11 requêtes concurrentes saturaient les 4 cœurs. Correctif probable : un index composite `(app_id, review_date)` à la place de `(review_date)`.
