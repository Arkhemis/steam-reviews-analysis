# Pre-processing part
import re 
import pandas as pd 
import numpy as np
import string

from datetime import datetime

# Utils packages
from airflow.decorators import dag, task
import os
import sqlalchemy
import logging
from airflow.exceptions import AirflowException
from utils.models import ReviewProcessed
from utils.process_utils import *
from tqdm import tqdm

tqdm.pandas()


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
engine = sqlalchemy.create_engine("postgresql://user:password@postgres:5432/steamreviews")


@dag(
    dag_id='dag_process_reviews',
    start_date=datetime(year=2025, month=7, day=8, hour=9, minute=0),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1
)
def review_process_etl():
    @task()
    def extract_data(limit=100000):
        try:
            df = pd.read_sql(f"""
            with eligibile_reviews as (
            select recommendationid, appid, review_text from games_reviews
                        where regexp_count(trim(review_text), '\w+')>=5 and playtime_at_review_minutes>120
                        and language = 'english'
            )
            select * from eligibile_reviews where recommendationid 
            not in (select distinct recommendationid from processed_reviews)
            LIMIT {limit}
            """, engine)
            return df
        except Exception as e:
            logging.warning('The table processed_reviews does not exist. Creating it now.')
            try:
                
                ReviewProcessed.__table__.create(engine)
                df = pd.read_sql(f"""
                select recommendationid, appid, review_text from games_reviews
                where regexp_count(trim(review_text), '\w+')>=5 and playtime_at_review_minutes>120
                and language = 'english'
                LIMIT {limit}
                """, engine)
                return df
            except Exception as e:
                raise AirflowException(f'An error occured while fetching data! Caused by {e}. Stopping DAG now.')
    @task()    
    def process_data(df):
        try:
            logging.info('Starting processing data.')
            logging.info('Identifying length of text.')
            df['original_review_length'] = df['review_text'].progress_apply(lambda x: len(x))
            logging.info('Detecting language.')
            df['detected_language'] = df['review_text'].progress_apply(lambda x: detect_lang(x))
            df = df[df['detected_language'] == 'english']  #Keep only english reviews
            logging.info('Tokenizing text.')
            df["tokens"] = df["review_text"].progress_apply(lambda x: clean_text(x, stopwords)).astype('object')
            logging.info('Counting tokens.')
            df["token_count"] = df['tokens'].progress_apply(lambda x: len(x))
            df['processed_at'] = datetime.now()

            df = df.drop('review_text', axis=1) #Don't need that anymore
            logging.info('Data processed.')

            return df
        except Exception as e:
            raise AirflowException(f'An error occured while processing data! Caused by {e}. Stopping DAG now.')
    @task()
    def loading_processed_data(df):
        try:
            df['tokens'] = df['tokens'].apply(lambda x: list(x) if hasattr(x, 'tolist') else x)
            df.to_sql('processed_reviews', engine, if_exists='append', index=False)
            return {"status": "load_complete", "count": len(df)}
        except Exception as e:
            logging.error(f'Error loading data: {e}')
            raise AirflowException(f'Loading failed: {e}')

    df_reviews = extract_data()
    df_games = process_data(df_reviews)
    load_result = loading_processed_data(df_games)

dag = review_process_etl()