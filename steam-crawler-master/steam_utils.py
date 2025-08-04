from datetime import datetime
import requests
import pandas as pd
import logging
import urllib3
import time

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logging.getLogger("urllib3").setLevel(logging.WARNING)

params = {
        'json':1,
        #'language': 'english',
        'cursor': '*',                                  
        'num_per_page': 100,
        'filter': 'recent'
    }

def process_games_review_data(review_stats, appid):
    """
    Process general game stats.
    """
    review_score = review_stats.get('review_score', 0)
    total_positive = review_stats.get('total_positive', 0)
    total_negative = review_stats.get('total_negative', 0)
    total_reviews = review_stats.get('total_reviews', 0)

    reviews_stats = {
    'appid': appid,
    'review_score': review_score,
    'total_positive': total_positive,
    'total_negative': total_negative,
    'total_reviews':total_reviews,
    'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    return reviews_stats

def get_game_reviews(appid, games_stats):
    
    """
    Process game reviews stats
    """


    params["cursor"] = '*'
    full_game_reviews = []
    while True:
        user_review_url = f'https://store.steampowered.com/appreviews/{appid}?json=1'
        user_reviews = requests.get(user_review_url, params=params, timeout=10).json()
        
        if user_reviews is None:
                    logging.warning(f"Failed to get reviews for appid {appid}") 
                    break

        if 'query_summary' not in user_reviews:
            logging.warning(f"Invalid response structure for appid {appid}")
            break

        if params["cursor"] == '*':
            query_summary = user_reviews["query_summary"]
            current_reviews = query_summary['total_reviews']
            if appid in games_stats and current_reviews == games_stats[appid]:
                logging.info(f"App {appid}: same review count ({current_reviews}), skipping")
                return [], []
            else:
                logging.info(f"App {appid}: reviews changed ({games_stats.get('appid', 0)} -> {current_reviews})")
                game_stat = process_games_review_data(query_summary, appid)

        page_review = []
        # extract each review in the response of the API call
        for review in user_reviews["reviews"]:
            recommendationid = review.get('recommendationid', None) #Shouldn't happen
            author_steamid = review.get('author', {}).get('steamid', None)
            playtime_forever = review.get('author', {}).get('playtime_forever', 0)
            playtime_last_two_weeks = review.get('author', {}).get('playtime_last_two_weeks', 0)
            playtime_at_review_minutes = review.get('author', {}).get('playtime_at_review', 0)
            last_played = review.get('author', {}).get('last_played', None)

            # Données review principales
            review_text = review.get('review', pd.NA)
            voted_up = review.get('voted_up', False)
            votes_up = review.get('votes_up', 0)
            votes_funny = review.get('votes_funny', 0)
            weighted_vote_score = review.get('weighted_vote_score', 0.0)
            steam_purchase = review.get('steam_purchase', True)  # Par défaut True
            received_for_free = review.get('received_for_free', False)
            written_during_early_access = review.get('written_during_early_access', False)
            language = review.get('language', pd.NA)

            reviews_dict = {
                'appid': appid, 
                'recommendationid': recommendationid,
                'author_steamid': author_steamid,
                'playtime_at_review_minutes': playtime_at_review_minutes,
                'playtime_forever_minutes': playtime_forever,
                'playtime_last_two_weeks_minutes': playtime_last_two_weeks,
                'last_played': last_played,

                'review_text': review_text,
                'checked_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),

                'voted_up': voted_up,
                'votes_up': votes_up,
                'votes_funny': votes_funny,
                'weighted_vote_score': weighted_vote_score,
                'steam_purchase': steam_purchase,
                'received_for_free': received_for_free,
                'written_during_early_access': written_during_early_access,
                'language': language
            }
            page_review.append(reviews_dict)
        full_game_reviews.extend(page_review)
        if ('cursor' in user_reviews and user_reviews["cursor"] != params["cursor"]):
            logging.debug('More than one cursor detected')
            params["cursor"] = user_reviews["cursor"]
        else:
            break

    time.sleep(0.5)
    return full_game_reviews, game_stat

def save_and_close(full_stats: pd.DataFrame, full_reviews: pd.DataFrame, engine):
    
    try: 
        existing_reviews = pd.read_sql('select * from games', engine)
        new_reviews_df = pd.DataFrame(full_reviews)
        combined = pd.concat([existing_reviews, new_reviews_df])
        combined.drop_duplicates(subset=['recommendationid'], keep='last', inplace=True)
        combined.to_sql('games', engine, if_exists='replace', index=False)
        logging.info('Games reviews updated and loaded')
    except Exception as e:
        logging.error('Something wrong happened while loading reviews %s', e)
    
    try: 
        new_stats_df = pd.DataFrame(full_stats)
        existing_stats = pd.read_sql('select * from games_stats', engine)
        combined_stats = pd.concat([existing_stats, new_stats_df], ignore_index=True)
        combined_stats.drop_duplicates(subset=['appid'], keep='last', inplace=True)
        combined_stats.to_sql('games_stats', engine, if_exists='replace', index=False)
        logging.info('Games review stats updated and loaded')
    except Exception as e:
        logging.error('Something wrong happened while loading reviews stats %s', e)