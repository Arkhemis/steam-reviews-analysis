library(mice)
library(car)
library(readr)
library(mvnmle)
library(psych)
library(dplyr)
library(pscl)
library(Hmisc)
library(MASS)
library(PMCMR) 

df <- read_csv("df_complet.csv")
set.seed(1962)
df$EXT_yes <- ifelse(df$EXT >= quantile(df$EXT, prob=c(.75)), 1, 0)
df$OPE_yes <- ifelse(df$OPE >= quantile(df$OPE, prob=c(.75)), 1, 0)
df$NEU_yes <- ifelse(df$NEU >= quantile(df$NEU, prob=c(.75)), 1, 0)
df$CON_yes <- ifelse(df$CON >= quantile(df$CON, prob=c(.75)), 1, 0)
df$AGR_yes <- ifelse(df$AGR >= quantile(df$AGR, prob=c(.75)), 1, 0)


df$WTP
df$Gender[df$Gender == "Homme"] <- 0
df$Gender[df$Gender == "Femme"] <- 1

### Normality test ###
## Souls = Challenging in the paper, Survival = Simulation ###
for (i in c("WTPlay_Souls", "WTPlay_Shooter", "WTPlay_Puzzle", "WTPlay_RTS", "WTPlay_RPG",
            "WTPlay_Survival", "WTPlay_Multiplayer","WTPTime_Souls", "WTPTime_Shooter", 
            "WTPTime_Puzzle", "WTPTime_RTS", "WTPTime_RPG","WTPTime_Survival", 
            "WTPTime_Multiplayer")){
  print(shapiro.test(df[[i]]))
}
shapiro.test(df$WTPlay_Souls)
### WTPLAY ###
df_OPE<-df[(df$OPE_yes==1),]
df_OPE = dplyr::select(df_OPE, -c(0:4, 12:45))
df_OPE<-as.matrix(df_OPE)
friedman.test(df_OPE)
posthoc.friedman.nemenyi.test(df_OPE)
psych::describe(df_OPE)



df_AGR<-df[(df$AGR_yes==1),]
df_AGR = dplyr::select(df_AGR, -c(0:4, 12:45))
psych::describe(df_AGR)
df_AGR<-as.matrix(df_AGR)
friedman.test(df_AGR)
posthoc.friedman.nemenyi.test(df_AGR)


df_CON<-df[(df$CON_yes==1),]
df_CON = dplyr::select(df_CON, -c(0:4, 12:45))
psych::describe(df_CON)
df_CON<-as.matrix(df_CON)
friedman.test(df_CON)
posthoc.friedman.nemenyi.test(df_CON)

df_NEU<-df[(df$NEU_yes==1),]
df_NEU = dplyr::select(df_NEU, -c(0:4, 12:45))
psych::describe(df_NEU)
df_NEU<-as.matrix(df_NEU)
friedman.test(df_NEU)
posthoc.friedman.nemenyi.test(df_NEU)

df_EXT<-df[(df$EXT_yes==1),]
df_EXT = dplyr::select(df_EXT, -c(0:4, 12:45))
psych::describe(df_EXT)
df_EXT<-as.matrix(df_EXT)
friedman.test(df_EXT)
posthoc.friedman.nemenyi.test(df_EXT)

## WTST ####

df_OPE<-df[(df$OPE_yes==1),]
df_OPE = dplyr::select(df_OPE, -c(0:11, 19:45))
df_OPE<-as.matrix(df_OPE)
friedman.test(df_OPE)
posthoc.friedman.nemenyi.test(df_OPE)
psych::describe(df_OPE)

df_AGR<-df[(df$AGR_yes==1),]
df_AGR = dplyr::select(df_AGR, -c(0:11, 19:45))
psych::describe(df_AGR)
df_AGR<-as.matrix(df_AGR)
friedman.test(df_AGR)
posthoc.friedman.nemenyi.test(df_AGR)


df_CON<-df[(df$CON_yes==1),]
df_CON = dplyr::select(df_CON, -c(0:11, 19:45))
psych::describe(df_CON)
df_CON<-as.matrix(df_CON)
friedman.test(df_CON)
posthoc.friedman.nemenyi.test(df_CON)

df_NEU<-df[(df$NEU_yes==1),]
df_NEU = dplyr::select(df_NEU, -c(0:11, 19:45))
psych::describe(df_NEU)
df_NEU<-as.matrix(df_NEU)
friedman.test(df_NEU)
posthoc.friedman.nemenyi.test(df_NEU)

df_EXT<-df[(df$EXT_yes==1),]
df_EXT = dplyr::select(df_EXT, -c(0:11, 19:45))
psych::describe(df_EXT)
df_EXT<-as.matrix(df_EXT)
friedman.test(df_EXT)
posthoc.friedman.nemenyi.test(df_EXT)



df <- read_csv("data_final_reversed.csv")

df$WTPlay_Souls[df$WTPlay_Souls != 1] <- 0
df$WTPlay_Shooter[df$WTPlay_Shooter != 1] <- 0
df$WTPlay_Puzzle[df$WTPlay_Puzzle != 1] <- 0
df$WTPlay_RTS[df$WTPlay_RTS != 1] <- 0
df$WTPlay_RPG[df$WTPlay_RPG != 1] <- 0
df$WTPlay_Survival[df$WTPlay_Survival != 1] <- 0
df$WTPlay_Multiplayer[df$WTPlay_Multiplayer != 1] <- 0


wtplay_souls = glm(formula = WTPlay_Souls ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_shooter = glm(formula = WTPlay_Shooter ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_puzzle = glm(formula = WTPlay_Puzzle ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_rts = glm(formula = WTPlay_RTS ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_rpg = glm(formula = WTPlay_RPG ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_survival = glm(formula = WTPlay_Survival ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_multiplayer = glm(formula = WTPlay_Multiplayer ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)



round(exp(coef(wtplay_souls)),3)
round(exp(coef(wtplay_shooter)),3)
round(exp(coef(wtplay_puzzle)),3)

round(exp(coef(wtplay_rts)),3)
round(exp(coef(wtplay_rpg)),3)
round(exp(coef(wtplay_survival)),3)
round(exp(coef(wtplay_multiplayer)),3)

pR2(wtplay_souls)
pR2(wtplay_shooter)
pR2(wtplay_puzzle)
pR2(wtplay_rts)
pR2(wtplay_rpg)
pR2(wtplay_survival)
pR2(wtplay_multiplayer)

print(summary(wtplay_souls))
print(summary(wtplay_shooter))
print(summary(wtplay_puzzle))
print(summary(wtplay_rts))
print(summary(wtplay_rpg))
print(summary(wtplay_survival))
print(summary(wtplay_multiplayer))


####
wtplay_souls_2 = glm(formula = WTPlay_Souls ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                       Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                     ,family = binomial, data = df)
wtplay_shooter_2 = glm(formula = WTPlay_Shooter ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                         Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                       ,family = binomial, data = df)
wtplay_puzzle_2 = glm(formula = WTPlay_Puzzle ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                        Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                      ,family = binomial, data = df)
wtplay_rts_2 = glm(formula = WTPlay_RTS ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                     Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                   ,family = binomial, data = df)
wtplay_rpg_2 = glm(formula = WTPlay_RPG ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                     Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                   ,family = binomial, data = df)
wtplay_survival_2 = glm(formula = WTPlay_Survival ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                          Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                        ,family = binomial, data = df)
wtplay_multiplayer_2 = glm(formula = WTPlay_Multiplayer ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme + 
                             Joueur_1.0*OPE + Joueur_1.0*AGR + Joueur_1.0*CON + Joueur_1.0*NEU + Joueur_1.0*EXT 
                           ,family = binomial, data = df)



round(exp(coef(wtplay_souls)),3)
round(exp(coef(wtplay_shooter)),3)
round(exp(coef(wtplay_puzzle)),3)

round(exp(coef(wtplay_rts)),3)
round(exp(coef(wtplay_rpg)),3)
round(exp(coef(wtplay_survival)),3)
round(exp(coef(wtplay_multiplayer)),3)

pR2(wtplay_souls)
pR2(wtplay_shooter)
pR2(wtplay_puzzle)
pR2(wtplay_rts)
pR2(wtplay_rpg)
pR2(wtplay_survival)
pR2(wtplay_multiplayer)

print(summary(wtplay_souls))
print(summary(wtplay_puzzle))
print(summary(wtplay_rts))
print(summary(wtplay_rpg))
print(summary(wtplay_survival))
print(summary(wtplay_multiplayer))

### TIME ###

df$WTPTime_Souls[df$WTPTime_Souls != 1] <- 0
df$WTPTime_Shooter[df$WTPTime_Shooter != 1] <- 0
df$WTPTime_Puzzle[df$WTPTime_Puzzle != 1] <- 0
df$WTPTime_RTS[df$WTPTime_RTS != 1] <- 0
df$WTPTime_RPG[df$WTPTime_RPG != 1] <- 0
df$WTPTime_Survival[df$WTPTime_Survival != 1] <- 0
df$WTPTime_Multiplayer[df$WTPTime_Multiplayer != 1] <- 0


wtptime_souls = glm(formula = WTPTime_Souls ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtptime_shooter = glm(formula = WTPTime_Shooter ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtptime_puzzle = glm(formula = WTPTime_Puzzle ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_rts = glm(formula = WTPTime_RTS ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_rpg = glm(formula = WTPTime_RPG ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_survival = glm(formula = WTPTime_Survival ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)
wtplay_multiplayer = glm(formula = WTPTime_Multiplayer ~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme, family = binomial, data = df)



round(exp(coef(wtptime_souls)),3)
round(exp(coef(wtptime_shooter)),3)
round(exp(coef(wtptime_puzzle)),3)

round(exp(coef(wtplay_rts)),3)
round(exp(coef(wtplay_rpg)),3)
round(exp(coef(wtplay_survival)),3)
round(exp(coef(wtplay_multiplayer)),3)

pR2(wtptime_souls)
pR2(wtptime_shooter)
pR2(wtptime_puzzle)
pR2(wtplay_rts)
pR2(wtplay_rpg)
pR2(wtplay_survival)
pR2(wtplay_multiplayer)

print(summary(wtptime_souls))
print(summary(wtptime_shooter))
print(summary(wtptime_puzzle))
print(summary(wtplay_rts))
print(summary(wtplay_rpg))
print(summary(wtplay_survival))
print(summary(wtplay_multiplayer))
