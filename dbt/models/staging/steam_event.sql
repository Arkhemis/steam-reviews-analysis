SELECT
    app_id,
    gid COLLATE "C" AS gid,

    -- announcement_body.gid est l'id du post, distinct du gid de l'événement
    (payload -> 'announcement_body' ->> 'gid') COLLATE "C" AS announcement_gid,

    -- 28 = actu, 12/13/14 = mise à jour, 20/21/35 = promo, 11 = stream, 10 = sortie
    (payload ->> 'event_type')::int AS event_type,
    (payload ->> 'comment_type') COLLATE "C" AS comment_type,

    NULLIF((payload ->> 'build_id')::bigint, 0) AS build_id,
    NULLIF(payload ->> 'build_branch', '') COLLATE "C" AS build_branch,

    (payload -> 'announcement_body' ->> 'headline') COLLATE "C" AS headline,
    (payload -> 'announcement_body' ->> 'body') COLLATE "C" AS announcement_text,
    payload -> 'announcement_body' -> 'tags' AS tags,

    TO_TIMESTAMP(rtime32_start_time) AS started_at,  -- noqa: CP02
    TO_TIMESTAMP((payload -> 'announcement_body' ->> 'posttime')::bigint) AS posted_at,
    TO_TIMESTAMP((payload -> 'announcement_body' ->> 'updatetime')::bigint) AS updated_at,
    TO_TIMESTAMP((payload ->> 'rtime32_last_modified')::bigint) AS last_modified_at,

    (payload -> 'announcement_body' ->> 'voteupcount')::int AS votes_up,
    (payload -> 'announcement_body' ->> 'votedowncount')::int AS votes_down,
    (payload -> 'announcement_body' ->> 'commentcount')::int AS comment_count,

    loaded_at

FROM {{ source('raw', 'steam_events') }}
