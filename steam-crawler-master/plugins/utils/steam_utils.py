from datetime import datetime, timedelta
import requests
import pandas as pd
import logging
import urllib3
import time
from utils.models import Base, GamesReviews, GameReviewStats  # Import de vos modèles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import insert
import json

logging.basicConfig(format='%(levelname)s:%(message)s', level=logging.INFO)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

#TODO: Technically, the reviews are filtered by recency so we could only fetch the most recent up to the last review checked?
#Need to see how to implement that.

params = {
        'json':1,
        'language': 'all', #fetch all languages
        'cursor': '*',                                  
        'num_per_page': 100,
        'filter': 'recent',
        'filter_offtopic_activity': 0 #Add review bombing.
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
    # Stats par défaut pour tous les cas
    default_game_stat = {
        'appid': appid,
        'review_score': 0,
        'total_positive': 0,
        'total_negative': 0,
        'total_reviews': 0,
        'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    max_retries = 3
    full_game_reviews = []
    params["cursor"] = '*'
    should_skip = False
    review_count = 0
    while True:
        if games_stats is not None and 'updated_at' in games_stats:
            updated_at = games_stats['updated_at']
            if updated_at is not None and updated_at > datetime.now() - timedelta(days=7):
                logging.debug(f'Already checked {appid} recently ({updated_at}), skipping...') #Clutters the log otherwise 
                # Retourner les stats existantes
                should_skip = True
                games_stats['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                return [], games_stats, should_skip

        retry_count = 0
        while retry_count < max_retries:
            try:
                user_review_url = f'https://store.steampowered.com/appreviews/{appid}?json=1'
                user_reviews = requests.get(user_review_url, params=params, timeout=10).json()
                break
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
                logging.warning(f"Error for appid {appid} (attempt {retry_count}/{max_retries}): {e}")

                if retry_count >= max_retries:
                    logging.error(f"Max retries reached for appid {appid}")
                    return [], default_game_stat, True

        if user_reviews['success'] == 2:
            logging.warning(f"No reviews for appid {appid}")    
            return [], default_game_stat, should_skip
        
        if user_reviews is None:
            logging.warning(f"Failed to get reviews for appid {appid}") 
            return [], default_game_stat, should_skip
        
        if 'query_summary' not in user_reviews:
            logging.warning(f"Invalid response structure for appid {appid}")
            return [], default_game_stat, should_skip

        if params["cursor"] == '*':
            query_summary = user_reviews["query_summary"]
            total_current_reviews = query_summary['total_reviews']
            
            if total_current_reviews == 0:
                logging.info(f"0 reviews found for {appid}")
                return [], default_game_stat, should_skip
            elif total_current_reviews > 100000:
                logging.info(f"Oof. What a big game. Containing {total_current_reviews} reviews!")

                
            if games_stats is not None and total_current_reviews <= games_stats.get('total_reviews', 0):
                logging.info(f"App {appid}: same review count ({total_current_reviews}), last checked at {games_stats['updated_at']} skipping, ")
                should_skip = True
                games_stats['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                return [], games_stats.to_dict() if hasattr(games_stats, 'to_dict') else games_stats, should_skip
            else:
                if games_stats is not None:
                    logging.info(f"App {appid}: reviews missing or changed ({games_stats.get('total_reviews', 'N/A')} -> {total_current_reviews})")
                else:
                    logging.info(f"App {appid}: reviews are missing")
                    
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
            review_text = review.get('review', None) #Shouldn't happen either
            voted_up = review.get('voted_up', False)
            votes_up = review.get("votes_up", 0)
            if votes_up > 100000: #highly unlikely
                votes_up = 0
            votes_funny = review.get("votes_funny", 0)
            if votes_funny > 100000: #highly unlikely
                votes_funny = 0
            weighted_vote_score = review.get('weighted_vote_score', 0.0)
            steam_purchase = review.get('steam_purchase', True)  # Par défaut True
            received_for_free = review.get('received_for_free', False)
            written_during_early_access = review.get('written_during_early_access', False)
            language = review.get('language', None)
            primarily_steam_deck = review.get('primarily_steam_deck', False)

            timestamp_created = review.get('timestamp_created', None)
            if timestamp_created is not None:
                timestamp_created = datetime.fromtimestamp(timestamp_created).date()

            timestamp_updated = review.get('timestamp_updated', None)
            if timestamp_updated is not None:
                timestamp_updated = datetime.fromtimestamp(timestamp_updated).date()

            developer_response = review.get('developer_response', None)
            timestamp_dev_responded = review.get('timestamp_dev_responded', None)
            if timestamp_dev_responded is not None:
                timestamp_dev_responded = datetime.fromtimestamp(timestamp_dev_responded).date()
            
            


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
                'primarily_steam_deck': primarily_steam_deck,

                'language': language,

                'timestamp_created': timestamp_created,
                'timestamp_updated' : timestamp_updated,

                'developer_response': developer_response,
                'timestamp_dev_responded': timestamp_dev_responded
            }
            page_review.append(reviews_dict)
        full_game_reviews.extend(page_review)

        review_count += 1  
        

        if review_count > 0 and review_count % 1000 == 0:  
            logging.info(f"Big game {appid}: processed {review_count * 100} reviews so far, sleeping...")
            time.sleep(120)
            logging.info(f"Wake up mate!")

        if ('cursor' in user_reviews and user_reviews["cursor"] != params["cursor"]):
            logging.debug('More than one cursor detected')
            params["cursor"] = user_reviews["cursor"]
        else:
            break

        
    return full_game_reviews, game_stat, should_skip

def save_and_close(full_stats: list, full_reviews: list, engine):
    """
    Performs a bulk upsert in chunks for very large datasets.
    """
    chunk_size: int = 10000
    if not full_reviews and not full_stats:
        logging.info("No new data to save.")
        return

    logging.info("Starting data bulk upsert to db in chunks...")
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # UPSERT en masse pour les reviews
        if full_reviews:
            logging.info(f"Processing {len(full_reviews)} reviews in chunks of {chunk_size}...")
            # Pas besoin de DataFrame ici, on peut travailler directement sur la liste
            for i in range(0, len(full_reviews), chunk_size):
                chunk = full_reviews[i:i + chunk_size]
                
                stmt_reviews = insert(GamesReviews).values(chunk)
                update_columns_reviews = {
                    key: stmt_reviews.excluded[key] 
                    for key in chunk[0].keys() if key not in ['appid', 'recommendationid']
                }
                stmt_reviews = stmt_reviews.on_conflict_do_update(
                    index_elements=['appid', 'recommendationid'],
                    set_=update_columns_reviews
                )
                session.execute(stmt_reviews)
                logging.info(f"  Upserted chunk {i//chunk_size + 1}/{(len(full_reviews)-1)//chunk_size + 1}")

            logging.info(f'Finished upserting {len(full_reviews)} reviews.')


        if full_stats:
            logging.info(f"Processing {len(full_stats)} stats in chunks of {chunk_size}...")
            for i in range(0, len(full_stats), chunk_size):
                chunk = full_stats[i:i + chunk_size]
                stmt_stats = insert(GameReviewStats).values(chunk)
                update_columns_stats = {
                    key: stmt_stats.excluded[key] 
                    for key in chunk[0].keys() if key != 'appid'
                }
                stmt_stats = stmt_stats.on_conflict_do_update(
                    index_elements=['appid'],
                    set_=update_columns_stats
                )
                session.execute(stmt_stats)

            logging.info(f'Finished upserting {len(full_stats)} stats.')

        session.commit()
        logging.info("Database transaction committed successfully.")

    except Exception as e:
        logging.error(f"An error occurred during database upsert: {e}")
        session.rollback() # Annule toute la transaction en cas d'erreur
        raise
    finally:
        session.close()