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
        image_urls
    FROM {{ ref('steam_event_categorized') }}
    WHERE event_category IN ('news', 'update')

),


ranked AS (

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
        ROW_NUMBER() OVER (
            PARTITION BY app_id, EXTRACT(YEAR FROM started_on)
            ORDER BY votes_up DESC, comment_count DESC, gid ASC
        ) AS rank_in_year
    FROM eligible_events

)

SELECT
    app_id,
    gid,
    started_on,
    event_category,
    headline,
    votes_up,
    votes_down,
    comment_count,
    rank_in_year,

    -- Première image du corps de l'annonce, NULL quand il n'y en a pas (la
    -- moitié des cas) : c'est la vignette de l'infobulle, pas une galerie.
    image_urls[1] AS image_url,

    (votes_up >= votes_down) AS is_well_received

FROM ranked
WHERE rank_in_year <= {{ var('top_n_events_per_year', 3) }}
