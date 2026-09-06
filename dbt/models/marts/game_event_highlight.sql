{{
    config(
        indexes=[
            {'columns': ['app_id', 'started_on'], 'type': 'btree'},
        ]
    )
}}

WITH eligible_events AS (

    SELECT
        app_id,
        gid,
        started_on,
        event_category,
        headline,
        votes_up,
        votes_down,
        comment_count,
        image_urls,
        votes_up + votes_down AS total_votes,

        COALESCE(
            votes_down::numeric / NULLIF(votes_up + votes_down, 0),
            0
        ) AS pct_negative

    FROM {{ ref('steam_event_categorized') }}
    WHERE event_category IN ('news', 'update')

),

most_discussed AS (

    SELECT
        app_id,
        gid
    FROM (
        SELECT
            app_id,
            gid,
            ROW_NUMBER() OVER (
                PARTITION BY app_id, EXTRACT(YEAR FROM started_on)
                ORDER BY total_votes DESC, comment_count DESC, gid ASC
            ) AS rk
        FROM eligible_events
    ) AS ranked
    WHERE rk <= {{ var('top_n_events_per_year', 3) }}

),

controversial AS (

    SELECT
        app_id,
        gid
    FROM (
        SELECT
            app_id,
            gid,
            ROW_NUMBER() OVER (
                PARTITION BY app_id, EXTRACT(YEAR FROM started_on)
                ORDER BY total_votes DESC, gid ASC
            ) AS rk
        FROM eligible_events
        WHERE
            pct_negative > {{ var('controversy_pct_negative', 0.25) }}

            -- Plancher de volume : à trois votes contre un, le ratio ne dit
            -- rien du jeu, seulement que quatre personnes sont passées par là.
            AND total_votes >= {{ var('controversy_min_votes', 100) }}
    ) AS ranked
    WHERE rk <= {{ var('top_n_controversial_per_year', 2) }}

),

selected AS (

    SELECT
        app_id,
        gid
    FROM most_discussed

    UNION

    SELECT
        app_id,
        gid
    FROM controversial

)

SELECT
    e.app_id,
    e.gid,
    e.started_on,
    e.event_category,
    e.headline,
    e.votes_up,
    e.votes_down,
    e.comment_count,

    ROW_NUMBER() OVER (
        PARTITION BY e.app_id, EXTRACT(YEAR FROM e.started_on)
        ORDER BY e.total_votes DESC, e.comment_count DESC, e.gid ASC
    ) AS rank_in_year,

    -- Première image du corps de l'annonce, NULL quand il n'y en a pas (la
    -- moitié des cas) : c'est la vignette de l'infobulle, pas une galerie.
    e.image_urls[1] AS image_url,

    ROUND(e.pct_negative, 4) AS pct_negative,

    -- Même seuil et même plancher que le repêchage ci-dessus, pour que le
    -- contour rouge de l'infobulle désigne exactement ce que le modèle
    -- appelle une controverse.
    (
        e.pct_negative <= {{ var('controversy_pct_negative', 0.25) }}
        OR e.total_votes < {{ var('controversy_min_votes', 100) }}
    ) AS is_well_received

FROM eligible_events AS e
INNER JOIN selected AS s
    ON
        e.app_id = s.app_id
        AND e.gid = s.gid
