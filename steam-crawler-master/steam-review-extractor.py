#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Copyright (C) 2018 Andrea Esuli (andrea@esuli.it)
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import datetime
import json
import os
import re
import sys
import pandas as pd
from pathlib import Path


def extract_reviews(basepath, outputfile_name):
    idre = re.compile(r'app-([0-9]+)$')
    with open(outputfile_name, mode="w", encoding="utf-8", newline="") as outputfile:
        for root, _, files in os.walk(basepath):
            m = idre.search(root)
            if m:
                id_ = m.group(1)
            else:
                print('skipping non-game path ', root, file=sys.stderr)
                continue
            if os.path.exists("H:/steam-crawler-master/data/pages/reviews-csv/"+id_+".csv"):
                print("The", id_,"file already exists. Skipping to the next one...")
                continue
            df = pd.DataFrame(columns=["game_id", "game_num_review", "game_review_positive", "game_review_negative", "game_review_score", "game_review_score_desc", "steam_ID", "user_num_review",
            "user_num_games", "user_postdate", "user_playtime", "user_review_text", "user_recommended", "user_review_helpful", "user_review_funny", "user_game_purchased",
            "user_review_score", "comments_for_this_review"])
            j = 1
            df1 = df2 = df3 = df4 = df5 = df6 = df7 = df8 = df9 = df
            next_split = 0
            check = 0
            for i in range(1, len(files)):
                file = "reviews-"+str(i)+".json"
                file = Path(root, file)
                print('processing', file, "number of pages:", len(files)-1, "next split at:", next_split)
                with open(file, encoding='utf8') as jsonfile:
                    try:
                        soup = json.load(jsonfile)
                    except ValueError:
                        print('error on ', file, file=sys.stderr)
                        break
                    game_id = id_
                    if "total_reviews" in soup["query_summary"]:
                        game_num_review = soup["query_summary"]["total_reviews"]
                        game_review_positive = soup["query_summary"]["total_positive"]
                        game_review_negative = soup["query_summary"]["total_negative"]
                        game_review_score = soup["query_summary"]["review_score"]
                        game_review_score_desc = soup["query_summary"]["review_score_desc"]
                    else:
                        print("No query_summary data")
                    for i in range(len(soup["reviews"])):
                        list = []
                        steam_ID = soup["reviews"][i]["author"]["steamid"]
                        user_num_review = soup["reviews"][i]["author"]["num_reviews"]
                        user_num_games = soup["reviews"][i]["author"]["num_games_owned"]
                        user_playtime = soup["reviews"][i]["author"]["playtime_forever"]
                        if user_playtime is None:
                            pass
                        else:
                            user_playtime = round(int(user_playtime)/60, 1) #converting minutes playtime into hour
                        user_postdate = soup["reviews"][i]["timestamp_created"]
                        if user_postdate is None:
                            pass
                        else:
                            user_postdate = datetime.datetime.fromtimestamp(float(user_postdate)).strftime('%Y-%m-%d %H:%M:%S')
                        user_review_text = soup["reviews"][i]["review"].replace('\n', '')
                        user_recommended = soup["reviews"][i]["voted_up"]
                        user_review_helpful = soup["reviews"][i]["votes_up"]
                        user_review_funny = soup["reviews"][i]["votes_funny"]
                        user_game_purchased = soup["reviews"][i]["steam_purchase"]
                        user_review_score = soup["reviews"][i]["weighted_vote_score"]
                        comments_for_this_review = soup["reviews"][i]["comment_count"]
                        list = [game_id, game_num_review, game_review_positive, game_review_negative, game_review_score, game_review_score_desc, steam_ID, user_num_review, user_num_games, user_postdate, user_playtime, user_review_text, user_recommended, user_review_helpful, user_review_funny, user_game_purchased, user_review_score, comments_for_this_review]
                        list = pd.Series(list, index = df.columns)
                        df.loc[len(df)] = list
                if len(files)>100:
                    split = round(len(files)/10)
                    if j == split:
                        print("Storing the first half")
                        df1 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*2
                    elif j == (split * 2):
                        print("Storing the second half")
                        df2 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*3
                    elif j == (split * 3):
                        print("Storing the third half")
                        df3 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*4
                    elif j == (split * 4):
                        print("Storing the fourth half")
                        df4 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*5
                    elif j == (split * 5):
                        print("Storing the fifth half")
                        df5 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*6
                    elif j == (split * 6):
                        print("Storing the sixth half")
                        df6 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*7
                    elif j == (split * 7):
                        print("Storing the seventh half")
                        df7 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*8
                    elif j == (split * 8):
                        print("Storing the eighth half")
                        df8 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*9
                    elif j == (split * 9):
                        print("Storing the nineth half")
                        df9 = df
                        df = df.drop(df.index[:len(df)])
                        next_split = split*10
                    j = j + 1
                    check = 1
            if check == 1:
                print("Concatening files...")
                df = pd.concat([df, df1, df2, df3, df4, df5, df6, df7, df8, df9])
            else:
                pass
            df.to_csv(path_or_buf="H:/steam-crawler-master/data/pages/reviews-csv/"+id_+".csv", index = False)




def main():
    parser = argparse.ArgumentParser(description='Extractor of Steam reviews')
    parser.add_argument(
        '-i', '--input', help='Input file or path (all files in subpath are processed)', default="./data/pages/reviews",
        required=False)
    parser.add_argument(
        '-o', '--output', help='Output file', default='./data/reviews.csv', required=False)
    args = parser.parse_args()

    extract_reviews(args.input, args.output)


if __name__ == '__main__':
    main()
