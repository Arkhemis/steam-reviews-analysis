with source as (

    select
        recommendation_id,
        app_id,
        payload,
        timestamp_created,
        timestamp_updated,
        loaded_at
    from {{ source('raw', 'steam_reviews') }}

),

renamed as (

    select
        recommendation_id,
        app_id,

        (payload -> 'author' ->> 'steamid')::bigint                    as author_steamid,
        payload -> 'author' ->> 'personaname'                          as author_personaname,
        payload -> 'author' ->> 'profile_url'                         as author_profile_url,
        payload -> 'author' ->> 'avatar'                               as author_avatar,
        payload -> 'author' ->> 'persona_status'                       as author_persona_status,
        (payload -> 'author' ->> 'num_games_owned')::int                as author_num_games_owned,
        (payload -> 'author' ->> 'num_reviews')::int                    as author_num_reviews,
        
        -- playtimes Steam sont exprimés en minutes
        (payload -> 'author' ->> 'playtime_forever')::int               as author_playtime_forever_minutes,
        (payload -> 'author' ->> 'playtime_at_review')::int             as author_playtime_at_review_minutes,
        (payload -> 'author' ->> 'playtime_last_two_weeks')::int        as author_playtime_last_two_weeks_minutes,
        to_timestamp((payload -> 'author' ->> 'last_played')::bigint)   as author_last_played_at,

        payload ->> 'review'                                            as review_text,
        payload ->> 'language'                                          as language,
        (payload ->> 'voted_up')::boolean                               as voted_up,
        (payload ->> 'votes_up')::int                                   as votes_up,
        
        -- l'API Steam sérialise parfois votes_funny comme un uint32 :
        -- une valeur négative comme -1 devient 4294967295, ce qui dépasse un int4 Postgres
        case
            when (payload ->> 'votes_funny')::bigint > 2147483647
                then (payload ->> 'votes_funny')::bigint - 4294967296
            else (payload ->> 'votes_funny')::bigint
        end::int                                                        as votes_funny,
        (payload ->> 'weighted_vote_score')::numeric                    as weighted_vote_score,
        (payload ->> 'comment_count')::int                              as comment_count,
        (payload ->> 'steam_purchase')::boolean                         as steam_purchase,
        (payload ->> 'received_for_free')::boolean                      as received_for_free,
        (payload ->> 'written_during_early_access')::boolean            as written_during_early_access,
        (payload ->> 'primarily_steam_deck')::boolean                   as primarily_steam_deck,
        (payload ->> 'refunded')::boolean                               as refunded,

        to_timestamp((payload ->> 'app_release_date')::double precision) as app_release_date,
        payload -> 'reactions'                                          as reactions,

        to_timestamp(timestamp_created)                                 as created_at,
        to_timestamp(timestamp_updated)                                 as updated_at,
        loaded_at

    from source

)

select * from renamed
