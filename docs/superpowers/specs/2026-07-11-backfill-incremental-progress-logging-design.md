# Design : logs de progression + parallélisation backfill/incrémental

Date : 2026-07-11

## Contexte

`daily_ingest_job` initialise `raw.steam_fetch_state` mais ne récupère aucune
review. La récupération se fait dans deux jobs séparés, non schedulés pour le
backfill (règle 4 de CLAUDE.md) :

- `steam_reviews_backfill_job` (`orchestration/assets/steam_backfill.py`) :
  traite un batch de jeux `pending`/`in_progress`, séquentiellement, un jeu à
  la fois, puis s'arrête.
- `steam_reviews_incremental_job` (`orchestration/assets/steam_incremental.py`) :
  traite en une passe tous les jeux `done` à vérifier, séquentiellement.

Aucun des deux ne logue de progression au-delà d'une ligne par jeu terminé. Le
backfill complet pouvant durer des jours (règle 3 : rate limit Steam ~1
req/s, budget réel du client `SteamResource` = 10 req/s partagés), il n'y a
aujourd'hui aucune visibilité sur l'avancement pendant un run.

`steam_review_counts` (`orchestration/assets/steam_census.py`) parallélise déjà
ses sondes avec un `ThreadPoolExecutor(max_workers=8)` et logue elapsed/rate/ETA
par batch — ce projet reprend ce pattern pour le backfill/incrémental.

## Objectif

1. Ajouter des logs de progression exploitables pendant un run long
   (backfill et incrémental).
2. Paralléliser le traitement des jeux dans les deux jobs (actuellement
   séquentiel), en réutilisant le pattern déjà en place dans
   `steam_review_counts`.
3. Faire boucler `steam_reviews_backfill_job` en interne jusqu'à épuisement de
   la queue `pending`/`in_progress`, au lieu de traiter un seul batch borné
   par run.
4. Empêcher la boucle ci-dessus de tourner indéfiniment sur un jeu qui échoue
   de façon permanente.

## Hors scope

- La reprise de pagination au dernier `last_cursor` connu en cas de crash
  mi-jeu (`_backfill_one_game` redémarre toujours à `cursor="*"`). Gap connu,
  traité séparément.
- Toute modification de `PostgresResource` ou de `SteamResource` (le throttle
  partagé et le pattern "une connexion par appel" restent thread-safe tels
  quels, aucun changement nécessaire).
- L'incrémental ne reçoit pas de logique `failed`/`retry_count` : il n'a pas
  de boucle interne à protéger (une seule passe sur la sélection déjà connue
  au démarrage du run), donc pas de risque de boucle infinie.

## 1. Schéma : `raw.steam_fetch_state`

Dans `db/init.sql`, après le `CREATE TABLE IF NOT EXISTS raw.steam_fetch_state`
existant, ajouter une migration idempotente (le fichier n'a pas de système de
migration séparé — cf. absence de dossier `migrations/`) :

```sql
ALTER TABLE raw.steam_fetch_state
    ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
```

Mettre à jour le commentaire de `backfill_status` :
`pending | in_progress | done | failed`. Pas de contrainte `CHECK` à ajouter
(aucune n'existe aujourd'hui sur cette colonne).

## 2. `steam_reviews_backfill_job`

### Config (`BackfillConfig`)

- `batch_size: int = 40` (était 5 — avec 8 workers, un batch de 5 sous-utilise
  le parallélisme).
- `max_consecutive_failures: int = 3` (nouveau).
- `order` inchangé.

### Boucle externe (jusqu'à queue vide)

```
while True:
    queue = SELECT_QUEUE_SQL (exclut désormais aussi backfill_status='failed')
    if queue is empty:
        break
    process queue via ThreadPoolExecutor(max_workers=BACKFILL_WORKERS)
```

`BACKFILL_WORKERS = 8`, constante de module (même style que `CENSUS_WORKERS`
dans `steam_census.py` — non exposée en config, cohérent avec la décision
utilisateur de garder cette valeur en dur).

### Gestion des échecs persistants

- Sur exception dans `_backfill_one_game` : incrémenter `retry_count` de ce
  jeu. Si `retry_count >= max_consecutive_failures` après incrémentation :
  passer `backfill_status='failed'` (sort de la queue définitivement, à
  reprendre manuellement plus tard en repassant le statut à `pending`).
  Sinon, le jeu reste `in_progress` et sera retenté au prochain passage de la
  boucle `while`.
- Sur succès (`MARK_DONE_SQL`) : `retry_count` remis à 0, pour ne pas polluer
  un futur re-backfill manuel du même jeu.

### Logs de progression

Compteurs partagés (jeux traités, reviews cumulées) protégés par un
`threading.Lock` (même pattern que `SteamResource._lock`).

- Démarrage du run : `Backfill : {N} jeux en attente (pending+in_progress)`
- Par jeu (existe déjà partiellement, à conserver/étendre) :
  - Début : `app_id={id} : démarrage backfill`
  - Fin : `app_id={id} : terminé ({reviews} reviews, {pages} pages)`
- Après chaque batch traité : `Backfill : {done}/{total} traités ({pct}%) — {reviews_total} reviews cumulées — {rate} jeux/s — ETA ~{eta} min` (même format que `steam_review_counts.review_summary`, avec `time.monotonic()` pour elapsed/rate/ETA).
- Fin du run : résumé (jeux traités, reviews totales, nombre de `failed`, durée totale).

## 3. `steam_reviews_incremental_job`

- Remplacer la boucle `for app_id in rows` par un `ThreadPoolExecutor(max_workers=INCREMENTAL_WORKERS)` (`INCREMENTAL_WORKERS = 8`, même constante de style que le backfill — pas de boucle externe nécessaire, `SELECT_TO_CHECK_SQL` ramène déjà tout en une passe).
- Logs par jeu identiques en esprit à ceux du backfill (début/fin avec compte de reviews neuves/modifiées), plus un résumé de fin de run (jeux vérifiés, reviews neuves/modifiées cumulées, durée). Pas de notion `failed`/`retry_count`.

## Data flow (inchangé)

`IGDB → Postgres (app_id) → recensement Steam → backfill/incrémental reviews → raw append-only → dbt → Metabase`

Ce travail ne touche que la mécanique interne des deux jobs de collecte
(parallélisme + logs + anti-boucle-infinie) ; ni le schéma `raw.steam_reviews`
(toujours append-only, règle 1), ni dbt, ne sont affectés.

## Error handling

- Chaque jeu reste isolé dans son propre `try/except` (déjà le cas) — une
  exception sur un jeu n'interrompt pas les autres threads du batch.
- `ThreadPoolExecutor` : on itère sur les `Future` avec `as_completed` pour
  logguer/committer au fur et à mesure, pas attendre la fin du batch entier
  pour tout traiter d'un coup.
- Le nouveau statut `failed` est un cul-de-sac volontaire : aucune tâche
  automatique ne le repasse à `pending`. Reprise = intervention manuelle
  (`UPDATE raw.steam_fetch_state SET backfill_status='pending', retry_count=0
  WHERE app_id=...`).

## Testing

- Tests unitaires sur la logique de comptage `retry_count` → `failed` (au
  seuil `max_consecutive_failures`, pas avant/après).
- Test que `SELECT_QUEUE_SQL` exclut bien `failed`.
- Test que le batch loop s'arrête bien quand la queue est vide (pas de run
  infini sur une base sans travail restant).
- Pas de test d'intégration réel contre l'API Steam (règle CLAUDE.md : décrit
  comme scaffold, à valider manuellement avant un run massif — hors scope de
  cette tâche).
