import pandas as pd
import logging
from datetime import datetime, time, timedelta
from tqdm import tqdm
import sqlalchemy
from utils.steam_utils import *
from utils.models import *
import sys
from tqdm.contrib.logging import logging_redirect_tqdm
from airflow.decorators import dag, task

engine = sqlalchemy.create_engine("postgresql://user:password@postgres:5432/steamreviews")

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

@dag(
    dag_id='dag_steam_reviews',
    start_date=datetime(year=2025, month=7, day=8, hour=9, minute=0),
    schedule="@daily",
    catchup=False,
    max_active_runs=1
)
def steam_reviews_etl():
    @task()
    def init_games_df():

        
        try:
            print('alchemy', sqlalchemy.__version__)
            print('pandas', pd.__version__)
            #Sorting by newest releases first
            games = pd.read_sql('select steam_app_id, first_release_date from games order by first_release_date desc', engine) 
            
        except Exception as e:
            logging.error('An error occured %s', e)
            try:
                games = pd.read_csv('games_row.csv')
                games.to_sql('games', engine, if_exists='replace')
                logging.info('Games data loaded in db.')
            except FileNotFoundError as e:
                #Normally, it would be from a dataset from kaggle or else that will be automated
                logging.error('Games base data cannot be found. Stopping the script.')
                sys.exit()
                raise
        total_games_in_db = len(games)
        #Excluding games releasing today because they don't have reviews for the most part
        games = games[games['first_release_date'] <= datetime.today().date() - timedelta(days=1)] 
        total_games_in_db_filtered = len(games)
        logging.info(f"""
                     Total games in db: {total_games_in_db}. 
                     Total games after filtering out unreleased games: {total_games_in_db_filtered} ({total_games_in_db_filtered/total_games_in_db}%)"""
                     )
        return games
    @task()
    def init_game_reviews_stats():
        try:
            games_stats = pd.read_sql('select appid, total_reviews, updated_at from games_reviews_stats', engine)
        except:
            GameReviewStats.__table__.create(engine, checkfirst=True)
            games_stats = pd.DataFrame()
        return games_stats

    @task()
    def process_reviews(games_df, games_reviews_stats_df):
        max_games = 500
        processed_games = 0
        full_stats, full_reviews = [], []


        with logging_redirect_tqdm(loggers=[logging.Logger("airflow.task")]):
            for appid in tqdm(games_df['steam_app_id']):
                if processed_games >= max_games or len(full_reviews) >= 500000:
                    try:
                        save_and_close(full_stats, full_reviews, engine)
                        processed_games = 0
                        full_stats, full_reviews = [], []
                        logging.info('%s games treated. Time to sleep a bit.', max_games)
                        time.sleep(150)
                    except Exception as e:
                        logging.error('An error occured while saving the data: %s', e)
                        # sys.exit()
                try:
                    try:
                        stats_row = games_reviews_stats_df[games_reviews_stats_df['appid'] == appid].iloc[0].to_dict()  # ✅
                    except:
                        stats_row = None
                    reviews, stats, should_skip = get_game_reviews(appid, stats_row)
                    
                    if should_skip:
                        full_stats.append(stats)
                        continue

                    if reviews or stats: 
                        full_stats.append(stats)
                        if reviews:  # Seulement ajouter les reviews s'il y en a
                            full_reviews.extend(reviews)
                        processed_games += 1
                    else:
                        continue  # Ce cas ne devrait plus arriver
                except Exception as e:
                    logging.error(f"Error processing appid {appid}: {e}")
                    continue

    games_df = init_games_df()
    games_stats = init_game_reviews_stats()
    process_reviews(games_df, games_stats)

dag_steam_reviews = steam_reviews_etl()