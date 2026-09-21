SELECT
    app_id AS steam_app_id,
    NULLIF(payload ->> 'name', '') COLLATE "C" AS name,

    CASE (payload ->> 'type')::int
        WHEN 0 THEN 'game'
        WHEN 1 THEN 'demo'
        WHEN 2 THEN 'mod'
        WHEN 4 THEN 'dlc'
        WHEN 11 THEN 'music'
        ELSE 'other'
    END AS app_type,
    (payload -> 'related_items' ->> 'parent_appid')::int AS parent_steam_app_id,

    -- success = 15 : app retirée du store, fiche vide
    (payload ->> 'success')::int = 1 AS is_available,
    (payload ->> 'visible')::boolean AS is_visible,
    COALESCE((payload ->> 'unlisted')::boolean, FALSE) AS is_unlisted,
    COALESCE((payload ->> 'is_free')::boolean, FALSE) AS is_free,
    -- Steam n'envoie ces clés que lorsqu'elles valent true
    COALESCE((payload ->> 'is_early_access')::boolean, FALSE) AS is_early_access,
    COALESCE((payload ->> 'is_coming_soon')::boolean, FALSE) AS is_coming_soon,

    ROUND(
        COALESCE(
            payload -> 'best_purchase_option' ->> 'original_price_in_cents',
            payload -> 'best_purchase_option' ->> 'final_price_in_cents'
        )::numeric / 100,
        2
    ) AS price_usd,

    -- Date prévue, et non effective, quand is_coming_soon
    TO_TIMESTAMP(NULLIF((payload -> 'release' ->> 'steam_release_date')::bigint, 0)) AS steam_release_date,
    TO_TIMESTAMP(NULLIF((payload -> 'release' ->> 'original_release_date')::bigint, 0)) AS original_release_date,
    TO_TIMESTAMP(NULLIF((payload -> 'release' ->> 'release_from_early_access_date')::bigint, 0))
        AS release_from_early_access_date

FROM {{ source('raw', 'steam_game_details') }}
