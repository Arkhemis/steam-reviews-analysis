{{ config(order_by='(app_id, started_on)') }}

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

        coalesce(
            votes_down / nullIf(votes_up + votes_down, 0),
            0
        ) AS pct_negative

    FROM {{ ref('steam_event_categorized') }}
    WHERE event_category IN ('news', 'update')

),

monthly_score AS (

    SELECT
        app_id,
        toStartOfMonth(review_date) AS period_month,
        sum(total_reviews) AS reviews,
        sum(total_positive) AS positive_reviews
    FROM {{ ref('game_review_trend_daily') }}
    GROUP BY 1, 2

),

monthly_baseline AS (

    SELECT
        app_id,
        period_month,
        reviews,
        positive_reviews / nullIf(reviews, 0) AS pct_positive,

        -- Premier mois : fenêtre vide, somme à 0, baseline NULL comme en Postgres.
        sum(positive_reviews) OVER w
        / nullIf(sum(reviews) OVER w, 0) AS baseline_positive

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
        AND abs(pct_positive - baseline_positive) >= {{ var('shock_delta', 0.15) }}

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
            row_number() OVER (
                PARTITION BY app_id, toYear(started_on)
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
            row_number() OVER (
                PARTITION BY app_id, toStartOfMonth(started_on)
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
            e.app_id AS app_id,
            e.gid AS gid,
            row_number() OVER (
                PARTITION BY e.app_id, toStartOfMonth(e.started_on)
                ORDER BY
                    CASE WHEN s.delta < 0 THEN e.pct_negative ELSE -e.pct_negative END DESC,
                    e.total_votes DESC,
                    e.gid ASC
            ) AS rk
        FROM eligible_events AS e
        INNER JOIN shock_months AS s
            ON
                e.app_id = s.app_id
                AND toStartOfMonth(e.started_on) = s.period_month
        WHERE e.total_votes >= {{ var('controversy_min_votes', 100) }}
    ) AS ranked
    WHERE rk <= 1

),

selected AS (

    SELECT
        app_id,
        gid
    FROM most_discussed

    UNION DISTINCT

    SELECT
        app_id,
        gid
    FROM controversial

    UNION DISTINCT

    SELECT
        app_id,
        gid
    FROM shock_rescue

)

SELECT
    e.app_id AS app_id,
    e.gid AS gid,
    e.started_on,
    e.event_category,
    e.headline,
    e.votes_up,
    e.votes_down,
    e.comment_count,

    row_number() OVER (
        PARTITION BY e.app_id, toYear(e.started_on)
        ORDER BY e.total_votes DESC, e.comment_count DESC, e.gid ASC
    ) AS rank_in_year,

    -- Un tableau vide renvoie '' en ClickHouse : NULL, comme Postgres.
    if(empty(e.image_urls), NULL, e.image_urls[1]) AS image_url,

    round(e.pct_negative, 4) AS pct_negative,

    CAST(
        e.pct_negative <= {{ var('controversy_pct_negative', 0.25) }}
        OR e.total_votes < {{ var('controversy_min_votes', 100) }},
        'Nullable(Bool)'
    ) AS is_well_received

FROM eligible_events AS e
INNER JOIN selected
    USING (app_id, gid)
