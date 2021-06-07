import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")


def reverse_personality(nombre):
    if nombre == 5:
        nombre = 1
    elif nombre == 4:
        nombre = 2
    elif nombre == 2:
        nombre = 4
    elif nombre == 1:
        nombre = 5
    return nombre

def reverse(nombre):
    if nombre == 7:
        nombre = 1
    elif nombre == 6:
        nombre = 2
    elif nombre == 5:
        nombre = 4
    elif nombre == 4:
        nombre = 3
    elif nombre == 3:
        nombre = 4
    elif nombre == 2:
        nombre = 6
    elif nombre == 1:
        nombre = 7
    return nombre



df_fr = pd.read_csv("./data_fr.csv")
df_en = pd.read_csv("./data_en.csv")
df_fr_old_db = pd.read_csv("./data_fr_old_db.csv")
df_en_old_db = pd.read_csv("./data_en_old_db.csv")
df_en.columns = df_fr_old_db.columns
df_en_old_db.columns = df_fr_old_db.columns
df = pd.concat([df_fr_old_db, df_fr, df_en, df_en_old_db])
#print([(i,j) for i,j in enumerate(df.columns)])

len_df = len(df.dropna(subset=["participant._current_page_name"]).reset_index(drop=True)) #Number of people that clicked
df = df[df["participant._current_page_name"] == 'fin'].reset_index(drop=True)


df.rename(columns = {
                             'Part_3.1.player.Envie_WordsList_Souls':'WTPlay_Souls', #Souls are action-hard game
                             'Part_3.1.player.Envie_WordsList_Shooter':'WTPlay_Shooter',
                             'Part_3.1.player.Envie_WordsList_Horror':'WTPlay_Puzzle',
                             'Part_3.1.player.Envie_WordsList_RTS':'WTPlay_RTS',
                             'Part_3.1.player.Envie_WordsList_RPG':'WTPlay_RPG',
                             'Part_3.1.player.Envie_WordsList_Survival':'WTPlay_Survival',
                             'Part_3.1.player.Envie_WordsList_Multiplayer':'WTPlay_Multiplayer',
                             ####
                              'Part_3.1.player.Time_Souls':'WTPTime_Souls_T',
                              'Part_3.1.player.Time_Shooter':"WTPTime_Shooter_T",
                              'Part_3.1.player.Time_Horror':"WTPTime_Puzzle_T",
                              'Part_3.1.player.Time_RPG':"WTPTime_RPG_T",
                              'Part_3.1.player.Time_RTS':"WTPTime_RTS_T",
                              'Part_3.1.player.Time_Survival':"WTPTime_Survival_T",
                              'Part_3.1.player.Time_Multiplayer':"WTPTime_Multiplayer_T",
                              ###
                             "Part_3.1.player.Joueur":"Joueur",
                              'Part_3.1.player.Age':'Age',
                              'Part_3.1.player.Genre':'Gender',
                              'Part_3.1.player.Personality':'Personality',
                              'Part_3.1.player.Discipline': 'Discipline',
                             'Part_3.1.player.CSP': "CSP",
                             'Part_3.1.player.Education': "Education",
                             'Part_3.1.player.Location': "Location"
                              }, inplace = True)

df = df[df["Gender"] != 'None'].reset_index(drop=True)
df.loc[df['Part_3.1.player.Platform_1'] == "Telephone", 'Joueur'] = 0
df["EXT"] = 0
df["AGR"] = 0
df["CON"] = 0
df["OPE"] = 0
df["NEU"] = 0
for i in range(len(df)):
    df["EXT"][i] = df["Part_2.1.player.bff_1"][i] + reverse_personality(df["Part_2.1.player.bff_6"][i]) + df["Part_2.1.player.bff_11"][i] + df["Part_2.1.player.bff_16"][i] + reverse_personality(df["Part_2.1.player.bff_21"][i]) + df["Part_2.1.player.bff_26"][i] + reverse_personality(df["Part_2.1.player.bff_31"][i]) + df["Part_2.1.player.bff_36"][i]

    df["AGR"][i] = reverse_personality(df["Part_2.1.player.bff_2"][i]) + df["Part_2.1.player.bff_7"][i]+ reverse_personality(df["Part_2.1.player.bff_12"][i]) + df["Part_2.1.player.bff_17"][i] + df["Part_2.1.player.bff_22"][i]  + reverse_personality(df["Part_2.1.player.bff_27"][i]) + df["Part_2.1.player.bff_32"][i] + reverse_personality(df["Part_2.1.player.bff_37"][i]) + df["Part_2.1.player.bff_42"][i]

    df["CON"][i] = df["Part_2.1.player.bff_3"][i] + reverse_personality(df["Part_2.1.player.bff_8"][i]) + df["Part_2.1.player.bff_13"][i] +  reverse_personality(df["Part_2.1.player.bff_18"][i])    + reverse_personality(df["Part_2.1.player.bff_23"][i])  + df["Part_2.1.player.bff_28"][i] + df["Part_2.1.player.bff_33"][i]   + df["Part_2.1.player.bff_38"][i] + reverse_personality(df["Part_2.1.player.bff_43"][i])

    df["NEU"][i] = df["Part_2.1.player.bff_4"][i] + reverse_personality(df["Part_2.1.player.bff_9"][i])  + df["Part_2.1.player.bff_14"][i] + df["Part_2.1.player.bff_19"][i] + reverse_personality(df["Part_2.1.player.bff_24"][i]) + df["Part_2.1.player.bff_29"][i] + reverse_personality(df["Part_2.1.player.bff_34"][i]) + df["Part_2.1.player.bff_39"][i]

    df["OPE"][i] = df["Part_2.1.player.bff_5"][i] + df["Part_2.1.player.bff_10"][i] + df["Part_2.1.player.bff_15"][i] + df["Part_2.1.player.bff_20"][i] + df["Part_2.1.player.bff_25"][i] + df["Part_2.1.player.bff_30"][i]  + reverse_personality(df["Part_2.1.player.bff_35"][i]) + df["Part_2.1.player.bff_40"][i] + reverse_personality(df["Part_2.1.player.bff_41"][i]) + df["Part_2.1.player.bff_44"][i]


df.loc[(18 <= df.Age) & (df.Age <= 24), 'Age_Range'] = "18-24"
df.loc[(25 <= df.Age) & (df.Age <= 34), 'Age_Range'] = "25-34"
df.loc[(35 <= df.Age) & (df.Age <= 44), 'Age_Range'] = "35-44"
df.loc[(45 <= df.Age) & (df.Age <= 54), 'Age_Range'] = "45-54"
df.loc[(55 <= df.Age), 'Age_Range'] = "55 & over"



cols = ['WTPTime_Souls', 'WTPTime_Shooter',"WTPTime_Puzzle","WTPTime_RPG","WTPTime_RTS","WTPTime_Survival","WTPTime_Multiplayer"]
cols_2 = ['WTPTime_Souls_T', 'WTPTime_Shooter_T',"WTPTime_Puzzle_T","WTPTime_RPG_T","WTPTime_RTS_T","WTPTime_Survival_T","WTPTime_Multiplayer_T"]
df[cols] = df.loc[:, cols_2]
df[cols] = df[cols].rank(axis=1).astype(int)

WTPTime = {"WTPTime_Souls":df['WTPTime_Souls'], "WTPTime_Shooter":df['WTPTime_Shooter'], "WTPTime_Puzzle":df['WTPTime_Puzzle'],
  "WTPTime_RTS":df['WTPTime_RTS'], "WTPTime_RPG":df['WTPTime_RPG'], "WTPTime_Survival":df['WTPTime_Survival'], "WTPTime_Multiplayer":df['WTPTime_Multiplayer']}

WTPlay = {"WTPlay_Souls":df['WTPlay_Souls'], "WTPlay_Shooter":df['WTPlay_Shooter'], "WTPlay_Puzzle":df['WTPlay_Puzzle'],"WTPlay_RTS":df['WTPlay_RTS'],
 "WTPlay_RPG":df['WTPlay_RPG'],  "WTPlay_Survival":df['WTPlay_Survival'], "WTPlay_Multiplayer":df['WTPlay_Multiplayer']}

for type_game in WTPTime:
    for i in range(len(df)):
        df[str(type_game)][i] = reverse(df[str(type_game)][i])
for type_game in WTPlay:
    for i in range(len(df)):
        df[str(type_game)][i] = reverse(df[str(type_game)][i])



df["Part_3.1.player.Jeu_Favori"] = df["Part_3.1.player.Jeu_Favori"].str.lower()

df.to_csv("df_bff.csv", index =0)
todrop_1 = np.r_[0,2:7,8:162,163,195:197]
df.drop(df.columns[todrop_1], axis=1, inplace=True)
df1.drop(df.columns[todrop_1], axis=1, inplace=True)

df.to_csv("df_complet.csv", index =0)
