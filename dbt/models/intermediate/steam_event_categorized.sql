{{ config(order_by='(app_id, gid)') }}

SELECT

    e.app_id,
    e.gid,
    toDate(e.started_at) AS started_on,
    CASE
        WHEN e.event_type IN (28, 1) THEN 'news'
        WHEN e.event_type IN (12, 13, 14) THEN 'update'
        WHEN e.event_type IN (20, 21, 35, 31) THEN 'promotion'
        WHEN e.event_type IN (22, 23, 24, 30, 32) THEN 'in_game_event'
        WHEN e.event_type IN (9, 11, 18, 19) THEN 'stream'
        WHEN e.event_type = 34 THEN 'cross_promo'
        WHEN e.event_type IN (10, 15, 16) THEN 'release'
        WHEN e.event_type IN (17, 25, 26) THEN 'contest'
        WHEN e.event_type = 29 THEN 'beta'
        WHEN e.event_type = 27 THEN 'expo'
        ELSE 'other'
    END AS event_category,
    e.headline,
    e.announcement_text,
    e.votes_up,
    e.votes_down,
    e.comment_count,

    -- Steam substitue {STEAM_CLAN_IMAGE} par la racine du CDN de ses groupes.
    arrayMap(
        img -> replaceAll(img[1], '{STEAM_CLAN_IMAGE}', 'https://clan.cloudflare.steamstatic.com/images'),  -- noqa: RF03
        extractAllGroups(ifNull(e.announcement_text, ''), '\\[img\\]([^\\[]+?)\\[/img\\]')
    ) AS image_urls

FROM {{ ref('steam_event') }} AS e
