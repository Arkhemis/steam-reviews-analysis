-- Le corps de l'annonce reste en BBCode brut : son nettoyage viendra plus tard.
-- Seuls les médias qu'il contient sont extraits ici.
SELECT
    e.*,
    DATE(e.started_at) AS started_on,

    -- Les 27 codes event_type de Steam, regroupés d'après un sondage des
    -- titres en prod. 28 et 12/13/14 pèsent 86 % à eux seuls.
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

    -- Steam substitue {STEAM_CLAN_IMAGE} par la racine du CDN des groupes ;
    -- le chemin qui suit porte déjà le clanid.
    ARRAY(
        SELECT
            REPLACE(
                img.parts[1],
                '{STEAM_CLAN_IMAGE}',
                'https://clan.cloudflare.steamstatic.com/images'
            )
        FROM REGEXP_MATCHES(e.announcement_text, '\[img\]([^\[]+?)\[/img\]', 'g') AS img (parts)
    ) AS image_urls,

    -- Les [url=...] sont tantôt nus, tantôt entre guillemets.
    ARRAY(
        SELECT link.parts[1]
        FROM REGEXP_MATCHES(e.announcement_text, '\[url="?([^"\]]+?)"?\]', 'g') AS link (parts)
    ) AS link_urls,

    ARRAY(
        SELECT video.parts[1]
        FROM REGEXP_MATCHES(e.announcement_text, '\[previewyoutube=([^;\]]+)', 'g') AS video (parts)
    ) AS youtube_ids

FROM {{ ref('steam_event') }} AS e
