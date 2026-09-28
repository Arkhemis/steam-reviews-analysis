{{ config(order_by='steam_app_id') }}

SELECT
    app_id AS steam_app_id,
    nullIf(JSONExtractString(payload, 'name'), '') AS name,

    multiIf(
        type = 0, 'game',
        type = 1, 'demo',
        type = 2, 'mod',
        type = 4, 'dlc',
        type = 11, 'music',
        'other'
    ) AS app_type,
    JSONExtract(payload, 'related_items', 'parent_appid', 'Nullable(UInt32)') AS parent_steam_app_id,

    -- success = 15 : app retirée du store, fiche vide
    CAST(JSONExtract(payload, 'success', 'Nullable(Int64)') = 1, 'Nullable(Bool)') AS is_available,
    JSONExtract(payload, 'visible', 'Nullable(Bool)') AS is_visible,
    ifNull(JSONExtract(payload, 'unlisted', 'Nullable(Bool)'), false) AS is_unlisted,
    ifNull(JSONExtract(payload, 'is_free', 'Nullable(Bool)'), false) AS is_free,
    -- Steam n'envoie ces clés que lorsqu'elles valent true
    ifNull(JSONExtract(payload, 'is_early_access', 'Nullable(Bool)'), false) AS is_early_access,
    ifNull(JSONExtract(payload, 'is_coming_soon', 'Nullable(Bool)'), false) AS is_coming_soon,

    -- GetItems sérialise les prix en chaînes : JSONExtract les lit quand même.
    toDecimal64(
        coalesce(
            JSONExtract(payload, 'best_purchase_option', 'original_price_in_cents', 'Nullable(Int64)'),
            JSONExtract(payload, 'best_purchase_option', 'final_price_in_cents', 'Nullable(Int64)')
        ),
        2
    ) / 100 AS price_usd,

    -- Date prévue, et non effective, quand is_coming_soon
    toDateTime(nullIf(JSONExtract(payload, 'release', 'steam_release_date', 'Nullable(Int64)'), 0), 'UTC')
        AS steam_release_date,
    toDateTime(nullIf(JSONExtract(payload, 'release', 'original_release_date', 'Nullable(Int64)'), 0), 'UTC')
        AS original_release_date,
    toDateTime(
        nullIf(JSONExtract(payload, 'release', 'release_from_early_access_date', 'Nullable(Int64)'), 0), 'UTC'
    ) AS release_from_early_access_date

FROM (
    SELECT
        app_id,
        payload,
        JSONExtract(payload, 'type', 'Nullable(Int64)') AS type
    FROM {{ source('raw', 'steam_game_details') }}
)
