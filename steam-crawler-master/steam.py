import pandas as pd
import logging
from datetime import datetime
from tqdm import tqdm
import sqlalchemy
from steam_utils import *

engine = sqlalchemy.create_engine("postgresql://user:password@localhost:5434/steamreviews")

games = pd.read_sql('select steam_app_id from games', engine)
games_stats = pd.read_sql('select appid, total_reviews from games_stats', engine)
games_stats_dict = dict(zip(games_stats['appid'], games_stats['total_reviews']))
max_games = 10
processed_games = 0
full_stats = []
full_reviews = []



for appid in tqdm(games['steam_app_id']):
    if processed_games >= max_games:
        save_and_close(full_stats, full_reviews, engine)
        break
        
    try:
        reviews, stats = get_game_reviews(appid, games_stats_dict)
        
        if stats is not None:
            full_stats.append(stats)
        else:
            continue
        
        if reviews:
            full_reviews.extend(reviews)
            print('Cool')
            processed_games += 1
        else:
            continue
    except Exception as e:
        logging.error(f"Error processing appid {appid}: {e}")
        continue
