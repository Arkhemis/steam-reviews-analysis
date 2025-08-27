# Pre-processing part
import polars as pl
import pandas as pd

from datetime import datetime

# Utils packages
from airflow.decorators import dag, task
import sqlalchemy
import logging
from airflow.exceptions import AirflowException
from utils.models import ReviewProcessed
from utils.process_utils import clean_text, detect_lang
from tqdm import tqdm

tqdm.pandas()


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
engine = sqlalchemy.create_engine(
    "postgresql://user:password@postgres:5432/steamreviews"
)


@dag(
    dag_id="dag_process_reviews",
    start_date=datetime(year=2025, month=7, day=8, hour=9, minute=0),
    schedule="*/25 * * * *",
    catchup=False,
    max_active_runs=1,
)
def review_process_etl():
    @task()
    def extract_data(limit=100000):
        try:
            df = pd.read_sql(
                f"""
                        SELECT gr.recommendationid, gr.appid, gr.review_text 
            FROM games_reviews gr
            LEFT JOIN processed_reviews pr ON gr.recommendationid = pr.recommendationid
            WHERE gr.playtime_at_review_minutes > 120
            AND gr.language = 'english'
            AND pr.recommendationid IS NULL  -- Pas encore traité
            LIMIT  {limit}
            """,
                engine,
            )
            return df
        except Exception as e:
            logging.warning(
                f"Error {e}: The table processed_reviews does not exist. Creating it now."
            )
            try:
                ReviewProcessed.__table__.create(engine)
                df = pd.read_sql(
                    f"""
                select recommendationid, appid, review_text from games_reviews
                where regexp_count(trim(review_text), '\w+')>=5 and playtime_at_review_minutes>120
                and language = 'english'
                LIMIT {limit}
                """,
                    engine,
                )
                return df
            except Exception as e:
                raise AirflowException(
                    f"An error occured while fetching data! Caused by {e}. Stopping DAG now."
                )

    @task()
    def process_data(df):
        try:
            logging.info("Starting processing data.")
            df = pl.from_pandas(df)

            df = df.with_columns(
                [
                    pl.col("review_text")
                    .str.len_chars()
                    .alias("original_review_length"),
                    pl.col("review_text")
                    .map_elements(detect_lang, return_dtype=pl.String)
                    .alias("detected_language"),
                ]
            )

            df = df.filter(pl.col("detected_language") == "english")

            logging.info("Tokenizing text in batches...")
            texts = df.select("review_text").to_series().to_list()
            logging.info(f"Processing {len(texts)} texts")  # DEBUG

            tokens_batch = clean_text(texts)
            df = df.with_columns(
                [
                    pl.Series(
                        "tokens", tokens_batch, dtype=pl.List(pl.Utf8)
                    ),  # Spécifie le type
                ]
            )

            df = df.with_columns(
                [
                    pl.col("tokens").list.len().alias("token_count"),
                    pl.lit(datetime.now()).alias("processed_at"),
                ]
            )

            df_pandas = df.to_pandas().drop("review_text", axis=1)
            return df_pandas
        except Exception as e:
            logging.error(f"Detailed error: {str(e)}")  # Plus de détails
            raise AirflowException(
                f"An error occured while processing data! Caused by {e}. Stopping DAG now."
            )

    @task()
    def loading_processed_data(df):
        try:
            df["tokens"] = df["tokens"].apply(
                lambda x: list(x) if hasattr(x, "tolist") else x
            )
            df.to_sql("processed_reviews", engine, if_exists="append", index=False)
            return {"status": "load_complete", "count": len(df)}
        except Exception as e:
            logging.error(f"Error loading data: {e}")
            raise AirflowException(f"Loading failed: {e}")

    df_reviews = extract_data()
    df_games = process_data(df_reviews)
    loading_processed_data(df_games)


dag = review_process_etl()
