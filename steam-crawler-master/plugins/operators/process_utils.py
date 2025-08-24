import re
import spacy
import os
import nltk
import numpy as np
from lingua import LanguageDetectorBuilder
from nltk.corpus import stopwords
import string
import logging

logger = logging.getLogger(__name__)
nlp_model = spacy.load("en_core_web_sm")
nlp_model.max_length = 1000000000
SEED = 1962
np.random.seed(SEED)
os.environ["PYTHONHASHSEED"] = str(SEED)
detector = LanguageDetectorBuilder.from_all_languages().build()
nltk.download("stopwords")

# Récupère les stopwords anglais

stopwords = set(stopwords.words("english")).union(
    ["game", "videogame", "video game", "games", "video games"]
)


def clean_text(texts, stopwords):
    # 1. Pre-processing en batch (vectorisé)
    cleaned_texts = []
    for text in texts:
        text = str(text).lower()
        text = re.sub(r"\[(.*?)\]", "", text)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\w+…|…", "", text)
        text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text)
        text = re.sub(r"(?<=\w)-(?=\w)", " ", text)
        text = re.sub(f"[{re.escape(string.punctuation)}]", "", text)
        cleaned_texts.append(text)
    docs = nlp_model.pipe(cleaned_texts, batch_size=10000)

    # 3. Tokenization
    results = []
    for doc in docs:
        tokens = [token.lemma_ for token in doc]
        tokens = [
            t for t in tokens if t not in stopwords and not t.isdigit() and len(t) > 1
        ]
        results.append(tokens)

    return results


def detect_lang(text):
    try:
        language = detector.detect_language_of(text)
        return str(language.name).lower() if language else None
    except Exception as e:
        logging.error(f"Failed to identify the language used: {e}")
        return None
