import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import scikit_posthocs as sp
import warnings
import seaborn as sns
import statsmodels.api as sm
from bevel.linear_ordinal_regression import OrderedLogit
import scipy.stats as stats
warnings.filterwarnings("ignore")
from statsmodels.miscmodels.ordinal_model import OrderedModel
from scipy.stats import pearsonr, spearmanr
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.tools.tools import add_constant






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



def make_dfinal(df):
    df_trick = df.copy() #A CHANGER
    cat_vars=["Age_Range", "Personality","Discipline",	"Joueur",	"Gender",	"CSP",	"Education",	"Location"]
    for var in cat_vars:
        cat_list='var'+'_'+var
        cat_list = pd.get_dummies(df_trick[var], prefix=var)
        data1=df_trick.join(cat_list)
        df_trick=data1
    data_vars=df_trick.columns.values.tolist()
    to_keep=[i for i in data_vars if i not in cat_vars]
    data_final=df_trick[to_keep]
    return data_final

def appen_TimeWTP(li):
    li.append(df['WTPTime_Souls'][ind])
    li.append(df['WTPTime_Shooter'][ind])
    li.append(df['WTPTime_Puzzle'][ind])
    li.append(df['WTPTime_RPG'][ind])
    li.append(df['WTPTime_RTS'][ind])
    li.append(df['WTPTime_Survival'][ind])
    li.append(df['WTPTime_Multiplayer'][ind])

def appen_WTPlay(li):
    li.append(df['WTPlay_Souls'][ind])
    li.append(df['WTPlay_Shooter'][ind])
    li.append(df['WTPlay_Puzzle'][ind])
    li.append(df['WTPlay_RPG'][ind])
    li.append(df['WTPlay_RTS'][ind])
    li.append(df['WTPlay_Survival'][ind])
    li.append(df['WTPlay_Multiplayer'][ind])


df = pd.read_csv("df_complet.csv")



WTPTime = {"WTPTime_Souls":df['WTPTime_Souls'], "WTPTime_Shooter":df['WTPTime_Shooter'], "WTPTime_Puzzle":df['WTPTime_Puzzle'],
  "WTPTime_RTS":df['WTPTime_RTS'], "WTPTime_RPG":df['WTPTime_RPG'], "WTPTime_Survival":df['WTPTime_Survival'], "WTPTime_Multiplayer":df['WTPTime_Multiplayer']}

WTPlay = {"WTPlay_Souls":df['WTPlay_Souls'], "WTPlay_Shooter":df['WTPlay_Shooter'], "WTPlay_Puzzle":df['WTPlay_Puzzle'],"WTPlay_RTS":df['WTPlay_RTS'],
 "WTPlay_RPG":df['WTPlay_RPG'],  "WTPlay_Survival":df['WTPlay_Survival'], "WTPlay_Multiplayer":df['WTPlay_Multiplayer']}


#### Descriptive analysis ######
col_demo = ["Age_Range", "Gender", "Personality", "Joueur", "Discipline", 'CSP', 'Location']


df_demo = df[col_demo]

cat_cols = df_demo.select_dtypes(include=object).columns.tolist()

(pd.DataFrame(
    df_demo[cat_cols]
    .melt(var_name='column', value_name='Demographic')
    .value_counts())
.rename(columns={0: 'counts'})
.sort_values(by=['column'])
)


for type_game in WTPTime:
    k2, p = stats.normaltest(WTPTime[type_game])
    if p> 0.05:
     print("Normal distribution for")
    else:
     print("Not Normal distribution for", k2, p, type_game)

for type_game in WTPlay:
    k2, p = stats.normaltest(WTPlay[type_game])
    if p> 0.05:
     print("Normal distribution for")
    else:
     print("Not Normal distribution for",type_game)


#### FOR THE WTPTIME RANKING ####



EXT = []
OPE = []
CON = []
AGR = []
NEU = []
for ind in df.index:
    li = []
    if df['Personality'][ind] == "EXT":
         appen_TimeWTP(li)
         EXT.append(li)
    elif df['Personality'][ind] == "OPE":
         appen_TimeWTP(li)
         OPE.append(li)
    elif df['Personality'][ind] == "CON":
         appen_TimeWTP(li)
         CON.append(li)
    elif df['Personality'][ind] == "AGR":
         appen_TimeWTP(li)
         AGR.append(li)
    elif df['Personality'][ind] == "NEU":
         appen_TimeWTP(li)
         NEU.append(li)
OPE = np.array(OPE)
AGR = np.array(AGR)
EXT = np.array(EXT)
CON = np.array(CON)
NEU = np.array(NEU)
NEU
Perso_Time= {"OPE":OPE, "AGR":AGR, "CON":CON, "EXT":EXT, "NEU":NEU}

### CORRELATION TABLE #####
for p in Perso_Time: #it's just the name, not the element inside
    df_corr = df.copy()
    df_corr = df_corr[df_corr["Personality"] == p].reset_index(drop=True)
    df_corr = make_dfinal(df)
    cols=['WTPlay_Souls', 'WTPlay_Shooter',
           'WTPlay_Puzzle', 'WTPlay_RTS', 'WTPlay_RPG', 'WTPlay_Survival',
           'WTPlay_Multiplayer', 'WTPTime_Souls', 'WTPTime_Shooter',
           'WTPTime_Puzzle', 'WTPTime_RPG', 'WTPTime_RTS', 'WTPTime_Survival',
           'WTPTime_Multiplayer']
    df_corr = df_corr[cols]
    correlation = round(df_corr.corr(), 2)
    mask = np.zeros_like(correlation, dtype=np.bool)
    mask[np.triu_indices_from(mask)] = True
    f, ax = plt.subplots(figsize=(20, 10))
    cmap = sns.diverging_palette(180, 20, as_cmap=True)
    sns.heatmap(correlation, mask=mask, cmap=cmap, vmax=1, vmin =-1, center=0,
                square=True, linewidths=.5, cbar_kws={"shrink": .5}, annot=True)
    plt.title("Personality:"+p)
    plt.show()



cols=['Age', 'Joueur_1.0', 'Gender_Femme', 'OPE', 'AGR',
       'CON', 'NEU', 'EXT']
data_final = make_dfinal(df)
data_final = data_final[cols]
print(round(data_final.corr(), 2))
pvals = pd.DataFrame([[pearsonr(data_final[c], data_final[y])[1] for y in
data_final.columns] for c in data_final.columns], columns=data_final.columns, index=data_final.columns)
print(pvals)



cols=['WTPlay_Souls', 'WTPlay_Shooter',
       'WTPlay_Puzzle', 'WTPlay_RTS', 'WTPlay_RPG', 'WTPlay_Survival',
       'WTPlay_Multiplayer', 'WTPTime_Souls', 'WTPTime_Shooter',
       'WTPTime_Puzzle', 'WTPTime_RTS', 'WTPTime_RPG', 'WTPTime_Survival',
       'WTPTime_Multiplayer']
data_final = make_dfinal(df)
data_final = data_final[cols]
round(data_final.corr(), 2)
pvals = pd.DataFrame([[pearsonr(data_final[c], data_final[y])[1] for y in
data_final.columns] for c in data_final.columns], columns=data_final.columns, index=data_final.columns)
round(pvals,3)
data_final.WTPTime_Multiplayer.mean()
data_final.WTPTime_Multiplayer.std()

data_final = make_dfinal(df)
data_final = data_final[cols]
round(data_final.corr("spearman"), 2)
pvals = pd.DataFrame([[spearmanr(data_final[c], data_final[y])[1] for y in
data_final.columns] for c in data_final.columns], columns=data_final.columns, index=data_final.columns)
round(pvals,3)


for type_game in WTPTime:
    print("Mean:", type_game, round(WTPTime[type_game].mean(),1))
    print("SD",type_game,round(WTPTime[type_game].std(),1))

for type_game in WTPlay:
    print("Mean:", type_game, round(WTPlay[type_game].mean(),1))
    print("SD",type_game,round(WTPlay[type_game].std(),1))
# VOIR CORRELATION SIGNIFICATIVE

####



for p in Perso_Time:
    print("For",p,", the friedmanchisquare is:",stats.friedmanchisquare(*Perso_Time[p].T))
    print("For",p,", the posthoc is:\n",sp.posthoc_nemenyi_friedman(Perso_Time[p]))
    #print("The rank aggregation for the",p,"personality is",mc4_aggregator(
    #pd.DataFrame(Perso_Time[p].T,index=["souls",'shooter','puzzle','rts','rpg','survie', 'multi']), index_col = 0),"\n") #https://github.com/kalyaniuniversity/MC4

EXT = []
OPE = []
CON = []
AGR = []
NEU = []
for ind in df.index:
    li = []
    if df['Personality'][ind] == "EXT":
         appen_WTPlay(li)
         EXT.append(li)
    elif df['Personality'][ind] == "OPE":
         appen_WTPlay(li)
         OPE.append(li)
    elif df['Personality'][ind] == "CON":
         appen_WTPlay(li)
         CON.append(li)
    elif df['Personality'][ind] == "AGR":
         appen_WTPlay(li)
         AGR.append(li)
    elif df['Personality'][ind] == "NEU":
         appen_WTPlay(li)
         NEU.append(li)
OPE = np.array(OPE)
AGR = np.array(AGR)
EXT = np.array(EXT)
CON = np.array(CON)
NEU = np.array(NEU)
Perso_WTPlay= {"OPE":OPE, "AGR":AGR, "CON":CON, "EXT":EXT, "NEU":NEU}
for p in Perso_WTPlay:
    print("For",p,", the friedmanchisquare is:",stats.friedmanchisquare(*Perso_WTPlay[p].T))
    print("For",p,", the posthoc is:\n",sp.posthoc_nemenyi_friedman(Perso_WTPlay[p]))



### LOGIT #####


for type_game in WTPTime:
    for i in range(len(df)):
        df[str(type_game)][i] = reverse(df[str(type_game)][i])
for type_game in WTPlay:
    for i in range(len(df)):
        df[str(type_game)][i] = reverse(df[str(type_game)][i])

WTPTime = {"WTPTime_Souls":df['WTPTime_Souls'], "WTPTime_Shooter":df['WTPTime_Shooter'], "WTPTime_Puzzle":df['WTPTime_Puzzle'],
  "WTPTime_RTS":df['WTPTime_RTS'], "WTPTime_RPG":df['WTPTime_RPG'], "WTPTime_Survival":df['WTPTime_Survival'], "WTPTime_Multiplayer":df['WTPTime_Multiplayer']}

WTPlay = {"WTPlay_Souls":df['WTPlay_Souls'], "WTPlay_Shooter":df['WTPlay_Shooter'], "WTPlay_Puzzle":df['WTPlay_Puzzle'],"WTPlay_RTS":df['WTPlay_RTS'],
 "WTPlay_RPG":df['WTPlay_RPG'],  "WTPlay_Survival":df['WTPlay_Survival'], "WTPlay_Multiplayer":df['WTPlay_Multiplayer']}

cols=['Age', 'OPE', 'AGR', 'CON', 'NEU', 'EXT',
       'Gender_Femme', 'Joueur_1.0']

data_final = make_dfinal(df)
ok = []
for type_game in WTPlay:
    X=data_final[cols]
    y=data_final[str(type_game)]
    mod_prob = OrderedModel(data_final[str(type_game)],data_final[cols],
                        distr='logit')
    res_prob = mod_prob.fit(method='bfgs')
    #y=data_final[str(type_g)]
    ol = OrderedLogit()
    ol.fit(X, y)
    print(type_game)
    ol.print_summary()
    ok.append(res_prob.summary())
    #print(type_game,clf.score(X, y))

data_final = make_dfinal(df)
ok = []
for type_game in WTPTime:
    X=data_final[cols]
    y=data_final[str(type_game)]
    mod_prob = OrderedModel(data_final[str(type_game)],data_final[cols],
                        distr='probit')
    res_prob = mod_prob.fit(method='bfgs')
    #y=data_final[str(type_g)]
    ol = OrderedLogit()
    ol.fit(X, y)
    print(type_game)
    ol.print_summary()
    ok.append(res_prob.summary())

## CHECK Multicollinearity #####
cols=['Age', 'OPE', 'AGR', 'CON', 'NEU', 'EXT',
       'Gender_Femme', 'Joueur_1.0']
data_final = make_dfinal(df)
data_final = data_final[cols]
X = add_constant(data_final)
vif = pd.Series([variance_inflation_factor(X.values, i)
               for i in range(X.shape[1])],
              index=X.columns)
round(vif,2)


#LOGIT
data_final = make_dfinal(df)
for type_game in WTPlay:
    data_final[str(type_game)] = np.where(data_final[str(type_game)]==1, 1, 0)
    X=data_final[cols]
    #X["constant"] = 1
    y=data_final[str(type_game)]
    logit_model=sm.Logit(y,X)
    result=logit_model.fit(maxiter=10000, method='bfgs')
    print(result.summary2())

data_final = make_dfinal(df)
for type_game in WTPTime:
    data_final[str(type_game)] = np.where(data_final[str(type_game)]==1, 1, 0)
    X=data_final[cols]
    X["constant"] = 1
    y=data_final[str(type_game)]
    logit_model=sm.Logit(y,X)
    result=logit_model.fit(maxiter=10000, method='bfgs')
    print(result.summary2())



cols_gamer=['Age', 'OPE', 'AGR', 'CON', 'NEU', 'EXT',
       'Gender_Femme']


data_final = make_dfinal(df)
X=data_final[cols_gamer]
X["constant"] = 1
y=data_final['Joueur_1.0']
logit_model=sm.Logit(y,X)
result=logit_model.fit(maxiter=1000000, method='bfgs')
print(result.summary2())

EXT = []
OPE = []
CON = []
AGR = []
NEU = []
for ind in df.index:
    li = []
    if df['Personality'][ind] == "EXT":
         appen_WTPlay(li)
         EXT.append(li)
    elif df['Personality'][ind] == "OPE":
         appen_WTPlay(li)
         OPE.append(li)
    elif df['Personality'][ind] == "CON":
         appen_WTPlay(li)
         CON.append(li)
    elif df['Personality'][ind] == "AGR":
         appen_WTPlay(li)
         AGR.append(li)
    elif df['Personality'][ind] == "NEU":
         appen_WTPlay(li)
         NEU.append(li)
OPE = np.array(OPE)
AGR = np.array(AGR)
EXT = np.array(EXT)
CON = np.array(CON)
NEU = np.array(NEU)
Perso_WTPlay= {"OPE":OPE, "AGR":AGR, "CON":CON, "EXT":EXT, "NEU":NEU}
for p in Perso_WTPlay:
    print("For",p,", the friedmanchisquare is:",stats.friedmanchisquare(*Perso_WTPlay[p].T))
    print("For",p,", the posthoc is:\n",sp.posthoc_nemenyi_friedman(Perso_WTPlay[p]))
