import pytest
from datetime import datetime
from steam_utils import *
import pandas as pd

@pytest.fixture
def get_sample_game_data():
    appid = 30 #Day of Defeat 
    reviews_stats = {
    'appid': appid,
    'review_score': 30,
    'total_positive': 10,
    'total_negative': 20,
    'total_reviews':30,
    'updated_at': datetime.now()
    }
    reviews_stats = pd.DataFrame([reviews_stats])
    return appid, reviews_stats

def test_processing_data(get_sample_game_data):
    appid, reviews_stats = get_sample_game_data

    # Appel de la fonction à tester
    full_reviews, full_game_stat_reviews = get_game_reviews(appid, reviews_stats.iloc[0])
    assert len(full_reviews) > 0
    assert len(full_game_stat_reviews) > 0
    
