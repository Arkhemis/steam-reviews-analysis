import pandas as pd
import logging
from datetime import datetime, time
from tqdm import tqdm
import sqlalchemy
from steam_utils import *
import sys
from tqdm.contrib.logging import logging_redirect_tqdm
import chime

chime.theme('pokemon')
engine = sqlalchemy.create_engine("postgresql://user:password@localhost:5434/steamreviews")


def init_games_df():
    try:
        games = pd.read_sql('select steam_app_id from games', engine)
        if len(games) == 0:
            games = pd.read_csv('games_rows.csv')
            games.to_sql('games', engine, if_exists='replace')
            logging.info('Games data loaded in db.')
    except:
        logging.error('Table games does not exist. Trying to parse it from the data')
        try:
            games = pd.read_csv('games_row.csv')
            games.to_sql('games', engine, if_exists='replace')
            logging.info('Games data loaded in db.')
        except FileNotFoundError as e:
            #Normally, it would be from a dataset from kaggle or else that will be automated
            logging.error('Games base data cannot be found. Stopping the script.')
            sys.exit()
            raise
    return games

def init_game_reviews_stats():
    try:
        games_stats = pd.read_sql('select appid, total_reviews, updated_at from games_reviews_stats', engine)
    except:
        GameReviewStats.__table__.create(engine, checkfirst=True)
        games_stats = pd.DataFrame()
    return games_stats

max_games = 100
processed_games = 0
full_stats, full_reviews = [], []


with logging_redirect_tqdm():
    games_df = init_games_df()
    games_reviews_stats_df = init_game_reviews_stats()

    for appid in tqdm(games_df['steam_app_id']):
        if processed_games >= max_games:
            try:
                save_and_close(full_stats, full_reviews, engine)
                processed_games = 0
                full_stats, full_reviews = [], []
                logging.info('%s games treated. Time to sleep a bit.', max_games)
                time.sleep(150)
            except Exception as e:
                logging.error('An error occured while saving the data: %s', e)
                chime.error()
                sys.exit()
        logging.debug(f"{processed_games=}")
        try:
            try:
                stats_row = games_reviews_stats_df[games_reviews_stats_df['appid'] == appid].iloc[0]
            except:
                stats_row = None
            reviews, stats = get_game_reviews(appid, stats_row)
            
            if reviews:
                full_stats.append(stats)
                full_reviews.extend(reviews)
                processed_games += 1
            else:
                continue
        except Exception as e:
            logging.error(f"Error processing appid {appid}: {e}")
            continue
