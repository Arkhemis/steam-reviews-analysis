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

monthly_score AS (

    SELECT
        app_id,
        DATE_TRUNC('month', review_date)::date AS period_month,
        SUM(total_reviews) AS reviews,
        SUM(total_positive) AS positive_reviews
    FROM {{ ref('game_review_trend_daily') }}
    GROUP BY 1, 2

),

monthly_baseline AS (

    SELECT
        app_id,
        period_month,
        reviews,
        positive_reviews::numeric / NULLIF(reviews, 0) AS pct_positive,

        SUM(positive_reviews) OVER w
        / NULLIF(SUM(reviews) OVER w, 0) AS baseline_positive

    FROM monthly_score
    WINDOW w AS (
        PARTITION BY app_id
        ORDER BY period_month
        ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
    )

),

-- Les mois où la courbe décroche, dans un sens ou dans l'autre. Le plancher de
-- volume écarte les mois trop maigres pour qu'un écart de score veuille dire
-- quelque chose.
shock_months AS (

    SELECT
        app_id,
        period_month,
        pct_positive - baseline_positive AS delta
    FROM monthly_baseline
    WHERE
        reviews >= {{ var('shock_min_reviews', 200) }}
        AND ABS(pct_positive - baseline_positive) >= {{ var('shock_delta', 0.15) }}

),

-- Les annonces qui ont le plus fait réagir dans l'année, quel qu'en soit le
-- sens : ce sont les jalons du jeu (une sortie, un crossover, une refonte), et
-- l'année est la bonne maille pour eux — on veut les trois qui comptent, pas
-- un par mois.
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
                PARTITION BY app_id, DATE_TRUNC('month', started_on)
                ORDER BY votes_down DESC, gid ASC
            ) AS rk
        FROM eligible_events
        WHERE
            pct_negative > {{ var('controversy_pct_negative', 0.25) }}

            AND total_votes >= {{ var('controversy_min_votes', 100) }}
    ) AS ranked
    WHERE rk <= {{ var('top_n_controversial_per_month', 1) }}

),

-- On retient donc, pour chaque mois qui décroche, l'annonce dont l'accueil va
-- dans le sens du décrochage : la plus rejetée quand le score tombe, la mieux
-- reçue quand il remonte.
shock_rescue AS (

    SELECT
        app_id,
        gid
    FROM (
        SELECT
            e.app_id,
            e.gid,
            ROW_NUMBER() OVER (
                PARTITION BY e.app_id, DATE_TRUNC('month', e.started_on)
                ORDER BY
                    CASE WHEN s.delta < 0 THEN e.pct_negative ELSE -e.pct_negative END DESC,
                    e.total_votes DESC,
                    e.gid ASC
            ) AS rk
        FROM eligible_events AS e
        INNER JOIN shock_months AS s
            ON
                e.app_id = s.app_id
                AND DATE_TRUNC('month', e.started_on) = s.period_month
        WHERE e.total_votes >= {{ var('controversy_min_votes', 100) }}
    ) AS ranked
    WHERE rk <= 1

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

    UNION

    SELECT
        app_id,
        gid
    FROM shock_rescue

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


    e.image_urls[1] AS image_url,

    ROUND(e.pct_negative, 4) AS pct_negative,

    (
        e.pct_negative <= {{ var('controversy_pct_negative', 0.25) }}
        OR e.total_votes < {{ var('controversy_min_votes', 100) }}
    ) AS is_well_received

FROM eligible_events AS e
INNER JOIN selected
    USING (app_id, gid)
