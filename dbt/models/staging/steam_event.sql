{{ config(order_by='(app_id, gid)') }}

SELECT
    app_id,
    gid,

    -- announcement_body.gid est l'id du post, distinct du gid de l'événement
    JSONExtract(payload, 'announcement_body', 'gid', 'Nullable(String)') AS announcement_gid,

    -- 28 = actu, 12/13/14 = mise à jour, 20/21/35 = promo, 11 = stream, 10 = sortie
    JSONExtract(payload, 'event_type', 'Nullable(Int32)') AS event_type,
    JSONExtract(payload, 'comment_type', 'Nullable(String)') AS comment_type,

    nullIf(JSONExtract(payload, 'build_id', 'Nullable(Int64)'), 0) AS build_id,
    nullIf(JSONExtract(payload, 'build_branch', 'Nullable(String)'), '') AS build_branch,

    JSONExtract(payload, 'announcement_body', 'headline', 'Nullable(String)') AS headline,
    JSONExtract(payload, 'announcement_body', 'body', 'Nullable(String)') AS announcement_text,
    JSONExtract(payload, 'announcement_body', 'tags', 'Array(String)') AS tags,

    toDateTime(rtime32_start_time, 'UTC') AS started_at,  -- noqa: CP02
    toDateTime(JSONExtract(payload, 'announcement_body', 'posttime', 'Nullable(Int64)'), 'UTC') AS posted_at,
    toDateTime(JSONExtract(payload, 'announcement_body', 'updatetime', 'Nullable(Int64)'), 'UTC') AS updated_at,
    toDateTime(JSONExtract(payload, 'rtime32_last_modified', 'Nullable(Int64)'), 'UTC') AS last_modified_at,

    -- Steam met 0 pour « absent ».
    toDateTime(nullIf(JSONExtract(payload, 'rtime32_end_time', 'Nullable(Int64)'), 0), 'UTC') AS ended_at,
    toDateTime(nullIf(JSONExtract(payload, 'rtime32_visibility_start', 'Nullable(Int64)'), 0), 'UTC')
        AS visible_from,
    toDateTime(nullIf(JSONExtract(payload, 'rtime32_visibility_end', 'Nullable(Int64)'), 0), 'UTC')
        AS visible_until,
    toDateTime(nullIf(JSONExtract(payload, 'rtime_created', 'Nullable(Int64)'), 0), 'UTC') AS created_at,
    toDateTime(nullIf(JSONExtract(payload, 'rtime_mod_reviewed', 'Nullable(Int64)'), 0), 'UTC')
        AS mod_reviewed_at,

    JSONExtract(payload, 'announcement_body', 'voteupcount', 'Nullable(Int32)') AS votes_up,
    JSONExtract(payload, 'announcement_body', 'votedowncount', 'Nullable(Int32)') AS votes_down,
    JSONExtract(payload, 'announcement_body', 'commentcount', 'Nullable(Int32)') AS comment_count,

    loaded_at

FROM {{ source('raw', 'steam_events') }}
