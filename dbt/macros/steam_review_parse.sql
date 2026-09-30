{#- `source_relation` : table ou sous-requête entre parenthèses. -#}
{% macro steam_review_parse(source_relation) %}
SELECT
    *,

    -- Calculés ici pour ne pas relire le texte en aval.
    toNullable(toUInt32(lengthUTF8(review_text))) AS review_text_length,
    toBool(ifNull(match(review_text, '[✅☐]'), false)) AS is_generic,
    toBool({{ has_profanity('review_text', 'language') }}) AS has_profanity

FROM (

    SELECT
        recommendation_id,
        app_id,

        toUInt64OrNull(payload.author.steamid::String) AS author_steamid,
        payload.author.personaname::Nullable(String) AS author_personaname,
        payload.author.profile_url::Nullable(String) AS author_profile_url,
        payload.author.avatar::Nullable(String) AS author_avatar,
        payload.author.persona_status::Nullable(String) AS author_persona_status,
        payload.author.num_games_owned::Nullable(Int32) AS author_num_games_owned,
        payload.author.num_reviews::Nullable(Int32) AS author_num_reviews,

        payload.author.playtime_forever::Nullable(Int32) AS author_playtime_forever_minutes,
        payload.author.playtime_at_review::Nullable(Int32) AS author_playtime_at_review_minutes,
        payload.author.playtime_last_two_weeks::Nullable(Int32) AS author_playtime_last_two_weeks_minutes,
        toDateTime(payload.author.last_played::Nullable(Int64), 'UTC') AS author_last_played_at,

        payload.review::Nullable(String) AS review_text,
        toLowCardinality(payload.language::Nullable(String)) AS language,
        payload.voted_up::Nullable(Bool) AS voted_up,
        payload.votes_up::Nullable(Int32) AS votes_up,

        -- Steam sérialise parfois votes_funny en uint32 : -1 devient 4294967295.
        toInt32(
            payload.votes_funny::Nullable(Int64)
            - if(payload.votes_funny::Nullable(Int64) > 2147483647, 4294967296, 0)
        ) AS votes_funny,
        toDecimal128OrNull(payload.weighted_vote_score::String, 20) AS weighted_vote_score,
        payload.comment_count::Nullable(Int32) AS comment_count,
        payload.steam_purchase::Nullable(Bool) AS steam_purchase,
        payload.received_for_free::Nullable(Bool) AS received_for_free,
        payload.written_during_early_access::Nullable(Bool) AS written_during_early_access,
        payload.primarily_steam_deck::Nullable(Bool) AS primarily_steam_deck,
        payload.refunded::Nullable(Bool) AS refunded,

        fromUnixTimestamp64Milli(
            toInt64(payload.app_release_date::Nullable(Float64) * 1000), 'UTC'
        ) AS app_release_date,
        toJSONString(payload.reactions) AS reactions,

        toDateTime(timestamp_created, 'UTC') AS created_at,
        toDateTime(timestamp_updated, 'UTC') AS updated_at,
        loaded_at,

        -- La plus récente, puis la dernière capture (loaded_at dans les 32 bits bas).
        bitShiftLeft(toUInt64(timestamp_updated), 32)
        + toUInt32(toUnixTimestamp(loaded_at)) AS review_version

    FROM {{ source_relation }}

)
{% endmacro %}
