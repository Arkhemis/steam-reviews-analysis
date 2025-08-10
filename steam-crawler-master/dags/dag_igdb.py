from airflow.decorators import dag, task
from datetime import datetime
import pandas as pd
import os
import time
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
from utils.igdb_utils import * 
import sqlalchemy
from utils.models import GameTable
import logging
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from airflow.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.models import Variable



load_dotenv() # Charge les variables depuis le fichier .env

CLIENT_ID = Variable.get("IGDB_CLIENT_ID")
CLIENT_SECRET = Variable.get("IGDB_CLIENT_SECRET")
DATA_DUMP_DIR = Path('igdb_datadumps') 
TOKEN_URL = 'https://id.twitch.tv/oauth2/token'
API_BASE_URL = 'https://api.igdb.com/v4'
logger = logging.getLogger(__name__)

REQUIRED_ENDPOINTS = [
    'games',  'themes', 'keywords', 'player_perspectives', 'external_games'
    # 'genres', 'platforms', 'game_modes'
    #  'collections', 'franchises', 'game_types',
    # 'game_statuses', 'involved_companies', 'companies', ,
    # 'popularity_primitives', 'covers', 'artworks',
    # 'screenshots', 'alternative_names', 'external_game_sources',
    # 'websites', 'website_types',
    # # Ajouts pour les mappings nécessaires
    # 'game_localizations',
    # #'language_supports',
    # 'languages', 
    # 'multiplayer_modes',
    # 'age_ratings',
    # 'release_dates',
    # 'tags',
]

@dag(
    dag_id='dag_igdb',
    start_date=datetime(year=2025, month=7, day=8, hour=9, minute=0),
    schedule="@daily",
    catchup=False,
    max_active_runs=1
)
def igdb_etl():
    @task()
    def extract_from_igdb():
        DATA_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        api_headers = get_api_headers(CLIENT_ID, CLIENT_SECRET)
        logging.info('Got headers!')
        download_results = {}

        for endpoint in REQUIRED_ENDPOINTS:
            t0_endpoint = time.time()

            file_path = check_and_download_dump(endpoint, api_headers, DATA_DUMP_DIR)

            if file_path and file_path.exists() and file_path.stat().st_size > 0:
                download_results[endpoint] = True
                print(f"--- Fin {endpoint} (OK) ({(time.time() - t0_endpoint):.2f}s) ---")
            else:
                download_results[endpoint] = False
                print(f"*** ECHEC ou fichier invalide pour l'endpoint requis '{endpoint}' ***")
                print(f"--- Fin {endpoint} (ECHEC) ({(time.time() - t0_endpoint):.2f}s) ---")

    @task()
    def transform_igdb(text):
        games = pd.read_csv('igdb_datadumps/games.csv')

        games['themes'] = convert_ids_to_names(games, 'themes', 'slug')
        games['keywords'] = convert_ids_to_names(games, 'keywords', 'slug')
        games['player_perspectives'] = convert_ids_to_names(games, 'player_perspectives', 'slug')

        external_games = pd.read_csv('igdb_datadumps/external_games.csv')
        external_games = external_games[external_games['category'] == 1] #Only steam games
        external_games['appid'] = external_games['url'].str.extract(r'app/(\d+)')



        games_with_id = pd.merge(games, external_games, left_on='id', right_on='game')
        games_with_id = games_with_id[['slug', 'name_x', 'appid', 'summary', 'themes', 'keywords', 'player_perspectives', 'first_release_date', ]]
        games_clean = games_with_id.rename(columns={'name_x': 'title'})
        games_clean_sorted = games_clean.sort_values(by=['first_release_date'], ascending=False)
        games_clean_sorted_deduped = games_clean_sorted.drop_duplicates(subset=['appid'])
        return games_clean_sorted_deduped

    @task()
    def load_igdb_games(df_games):
        engine = sqlalchemy.create_engine("postgresql://user:password@postgres:5432/steamreviews")
        Session = sessionmaker(bind=engine)
        session = Session()
            
        GameTable.__table__.drop(engine, checkfirst=True)
        GameTable.__table__.create(engine)
        for _, row in df_games.iterrows():
            if pd.isna(row['appid']):
                continue
            release_date = None
            if pd.notna(row.get('first_release_date')):
                try:
                    # Si c'est une string, la parser
                    if isinstance(row['first_release_date'], str):
                        release_date = datetime.strptime(row['first_release_date'], '%Y-%m-%d %H:%M:%S').date()
                    # Si c'est déjà un datetime
                    elif hasattr(row['first_release_date'], 'date'):
                        release_date = row['first_release_date'].date()
                except (ValueError, AttributeError):
                    release_date = None
            try:
                game = GameTable(
                    slug=row['slug'],
                    title=row.get('title'),  
                    steam_app_id=int(row['appid']),
                    summary=row.get('summary'),
                    themes=row.get('themes', '').split(', ') if row.get('themes') else None,
                    keywords=row.get('keywords', '').split(', ') if row.get('keywords') else None,
                    player_perspectives=row.get('player_perspectives', '').split(', ') if row.get('player_perspectives') else None,
                    first_release_date=release_date,
                )
                session.add(game)
            except Exception as e:
                logging.error('An error occured while loading data {e}')

        session.commit()
        session.close()
        return {"status": "load_complete", "count": len(df_games)}

    trigger_steam_reviews = TriggerDagRunOperator(
        task_id='trigger_steam_reviews_dag',
        trigger_dag_id='dag_steam_reviews',  # ← ID de votre second DAG
        conf={
            'triggered_by': 'dag_igdb',
            'execution_date': '{{ ds }}',
            'games_loaded': True
        },
        wait_for_completion=False  # Le DAG IGDB se termine, Steam Reviews continue en parallèle
    )
        

    # Set dependencies using function calls
    allgood = extract_from_igdb()
    df_games = transform_igdb(allgood)
    load_result = load_igdb_games(df_games)
   
    
    load_result >> trigger_steam_reviews
# Allow the DAG to be run
dag = igdb_etl()

