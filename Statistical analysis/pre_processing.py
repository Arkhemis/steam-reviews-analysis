import os
import random
import re
import string
import pandas as pd
from string import punctuation
from nltk import word_tokenize
import numpy as np
import nltk
import spacy
import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)


nlp_model = spacy.load('en_core_web_sm')
nlp_model.max_length = 1000000000
SEED = 1962
random.seed(SEED)
os.environ["PYTHONHASHSEED"] = str(SEED)
np.random.seed(SEED)

def clean_text(text, tokenizer, stopwords):
    text = str(text).lower()  # Lowercase words
    text = re.sub(r"\[(.*?)\]", "", text)  # Remove [+XYZ chars] in content
    text = re.sub(r"\s+", " ", text)  # Remove multiple spaces in content
    text = re.sub(r"\w+…|…", "", text)  # Remove ellipsis (and last word)
    text = re.sub(r"<a[^>]*>(.*?)</a>", r"\1", text) #Remove html tags
    text = re.sub(f"[{re.escape(punctuation)}]", "", text)
    text = re.sub(r"(?<=\w)-(?=\w)", " ", text)  # Replace dash between words
    text = re.sub(
        f"[{re.escape(string.punctuation)}]", "", text
    )  # Remove punctuation
    doc = nlp_model(text)
    tokens = [token.lemma_ for token in doc]
    #tokens = tokenizer(text)  # Get tokens from text
    tokens = [t for t in tokens if not t in stopwords]  # Remove stopwords
    tokens = ["" if t.isdigit() else t for t in tokens]  # Remove digits
    tokens = [t for t in tokens if len(t) > 1]  # Remove short tokens
    return tokens #Clean the Text

def custom_detect(x):
    try:
        return detect(x)=='en'
    except:
        return False
########### IMPORT DATAFRAMES ######
df = pd.read_csv("./full_review_dataset.csv")

df["user_review_text"].replace(to_replace=r'[^a-zA-Z\s]', value='',inplace=True,regex=True) #Remove non-alphabetic character and numbers
m1 = df['user_review_text'].str.isspace() #Check spaces in user_review_text
df = df.loc[m1 == False].reset_index(drop=True) #Keep only values of m1 and values of m2 in which there is anything but only spaces
df = df[df['user_review_text'].apply(lambda x: (len(x.split(' ')) >= 5) and custom_detect(x))]
df = df_filtered.df("index", axis=1).reset_index(drop = True)

df = df[(df.user_playtime >= 2)] #Remove users with less than 2 hours of playtime

df = df.drop_duplicates(subset = "user_review_text", keep =  "first").reset_index(drop = True)
df["user_review_text"] = df["user_review_text"].fillna("")

df1["tokens"] = df1["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df1.to_csv('df_tokenised_part1.csv', index = False)
df2["tokens"] = df2["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df2.to_csv('df_tokenised_part2.csv', index = False)
df3["tokens"] = df3["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df3.to_csv('df_tokenised_part3.csv', index = False)
df4["tokens"] = df4["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df4.to_csv('df_tokenised_part4.csv', index = False)
df5["tokens"] = df5["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df5.to_csv('df_tokenised_part5.csv', index = False)
df6["tokens"] = df6["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df6.to_csv('df_tokenised_part6.csv', index = False)
df7["tokens"] = df7["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df7.to_csv('df_tokenised_part7.csv', index = False)
df8["tokens"] = df8["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df8.to_csv('df_tokenised_part8.csv', index = False)
df9["tokens"] = df9["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df9.to_csv('df_tokenised_part9.csv', index = False)
df10["tokens"] = df10["user_review_text"].map(lambda x: clean_text(x, word_tokenize, custom_stopwords))
df10.to_csv('df_tokenised_part10.csv', index = False)


df1 = pd.read_csv("./df_tokenised_part1.csv")
df2 = pd.read_csv("./df_tokenised_part2.csv")
df3 = pd.read_csv("./df_tokenised_part3.csv")
df4 = pd.read_csv("./df_tokenised_part4.csv")
df5 = pd.read_csv("./df_tokenised_part5.csv")
df6 = pd.read_csv("./df_tokenised_part6.csv")
df7 = pd.read_csv("./df_tokenised_part7.csv")
df = pd.concat([df1, df2, df3, df4, df5, df6, df7]).reset_index(drop = True)


df['tokens'] = df['tokens'].str[1:-1]
df['tokens'] = df['tokens'].str.replace(r'\'', '')
df['tokens'] = df['tokens'].str.replace(r'\,', '')
_, idx = np.unique(df["tokens"], return_index=True)
df = df.iloc[idx, :]
df.tokens = df.tokens.apply(lambda x: " ".join(w for w in nltk.wordpunct_tokenize(x) if w.lower() in words or not w.isalpha()))
unique = set(df1['tokens'].str.replace('[^a-zA-Z ]', '').str.lower().str.split(' ').sum()) #Retrieve unique words
truc = set(unique.intersection(vocab_model))  #Keep only words of unique that appears in the vocab of the first model
truc = set(truc.intersection(set(model2.wv.vocab))) #Same thing for the second model
df.tokens = df.tokens.apply(lambda x: " ".join(w for w in nltk.wordpunct_tokenize(x) if w.lower() in words or not w.isalpha()))
df.tokens = df.tokens.apply(lambda x: " ".join(w for w in nltk.wordpunct_tokenize(x) if w in truc)) #Keep only words of the vocab of the two previous model
df = df[(df["tokens"].str.count(" ") >= 5)]
df.to_csv('df_review_complete.csv', index = False)
