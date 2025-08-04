from sqlalchemy import *
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

engine = create_engine("postgresql://user:password@localhost:5434/steamreviews")
Base = declarative_base()
class GameTable(Base):
    __tablename__ = 'games'

    slug = Column(String(200), primary_key=True)
    title = Column(String(200), nullable=True)
    steam_app_id = Column(Integer, unique=True, nullable=False, index=True)
    summary = Column(String(5000), nullable=True)
    themes = Column(ARRAY(String), nullable=True)
    keywords = Column(ARRAY(String), nullable=True)
    player_perspectives = Column(ARRAY(String), nullable=True)
    

class GamesReviews(Base):
    __tablename__ = 'games_reviews'
    __table_args__ = (
        PrimaryKeyConstraint("appid", "recommendationid"),
    )
    # Identifiants
    appid = Column(Integer, nullable=False, index=True)
    recommendationid = Column(BigInteger, nullable=True, unique=True, index=True)
    author_steamid = Column(BigInteger, nullable=True, index=True)
    
    # Temps de jeu (en minutes)
    playtime_at_review_minutes = Column(Integer, default=0)
    playtime_forever_minutes = Column(Integer, default=0)
    playtime_last_two_weeks_minutes = Column(Integer, default=0)
    last_played = Column(Integer, nullable=True)  # Timestamp Unix
    
    # Contenu de la review
    review_text = Column(Text, nullable=True)
    checked_at = Column(DateTime, default=datetime.now, nullable=False)
    language = Column(String(10), nullable=True)
    
    # Votes et scores
    voted_up = Column(Boolean, default=False, nullable=False)
    votes_up = Column(Integer, default=0)
    votes_funny = Column(Integer, default=0)
    weighted_vote_score = Column(Float, default=0.0)
    
    # Flags d'achat et accès
    steam_purchase = Column(Boolean, default=True, nullable=False)
    received_for_free = Column(Boolean, default=False, nullable=False)
    written_during_early_access = Column(Boolean, default=False, nullable=False)

class GameReviewStats(Base):
    __tablename__ = 'games_reviews_stats'
    __table_args__ = (UniqueConstraint("appid"),)
    # Clé primaire
    appid = Column(Integer, primary_key=True, nullable=False)
    
    # Statistiques des reviews
    review_score = Column(Integer, default=0, nullable=False)
    total_positive = Column(Integer, default=0, nullable=False)
    total_negative = Column(Integer, default=0, nullable=False)
    total_reviews = Column(Integer, default=0, nullable=False)
    
    # Timestamp de mise à jour
    updated_at = Column(DateTime, default=datetime.now, nullable=False)
Base.metadata.create_all(engine)   