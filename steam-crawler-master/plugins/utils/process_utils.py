import re
import spacy
import os
import nltk
import numpy as np
from lingua import LanguageDetectorBuilder
from nltk.corpus import stopwords
import string
import logging
import pandas as pd

logger = logging.getLogger(__name__)
nlp_model = spacy.load('en_core_web_sm')
nlp_model.max_length = 1000000000
SEED = 1962
np.random.seed(SEED)
os.environ["PYTHONHASHSEED"] = str(SEED)
detector = LanguageDetectorBuilder.from_all_languages().build()
nltk.download('stopwords')

# Récupère les stopwords anglais
stopwords = set(stopwords.words('english')).union(['game', 'videogame', 'video game', 'games', 'video games'])


def clean_text(text, stopwords):
    text = str(text).lower()  # Lowercase words
    text = re.sub(r"\[(.*?)\]", "", text)  # Remove [+XYZ chars] in content
    text = re.sub(r"\s+", " ", text)  # Remove multiple spaces in content
    text = re.sub(r"\w+…|…", "", text)  # Remove ellipsis (and last word)
    text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text) #Remove html tags
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)  # Replace dash between words
    text = re.sub(
        f"[{re.escape(string.punctuation)}]", "", text
    )  # Remove punctuation
    doc = nlp_model(text)
    tokens = [token.lemma_ for token in doc]
    tokens = [t for t in tokens if not t in stopwords and not t.isdigit() and len(t) > 1] #remove short tokens, stopwords and digits
    return tokens #Clean the Text


def detect_lang(text):
    try:
        language = detector.detect_language_of(text)
        return str(language.name).lower() if language else None
    except:
        logging.error('Failed to identify the language used')
        return None