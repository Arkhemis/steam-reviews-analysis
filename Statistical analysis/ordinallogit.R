library(readr)
library(dplyr)
library(pscl)
library(Hmisc)
library(MASS)
library(PMCMR) 
library(rms) 
library(brant)
library(poliscidata)
df <- read_csv("df_not_reversed.csv")
set.seed(1962)

df$WTPlay_Souls <- factor(df$WTPlay_Souls, 
                          levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                          , ordered=TRUE)

df$WTPlay_Shooter <- factor(df$WTPlay_Shooter, 
                            levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                          , ordered=TRUE)

df$WTPlay_Puzzle <- factor(df$WTPlay_Puzzle, 
                           levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                          , ordered=TRUE)

df$WTPlay_RTS <- factor(df$WTPlay_RTS, 
                        levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                            , ordered=TRUE)

df$WTPlay_RPG <- factor(df$WTPlay_RPG, 
                        levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                           , ordered=TRUE)

df$WTPlay_Survival <- factor(df$WTPlay_Survival, 
                             levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                        , ordered=TRUE)

df$WTPlay_Multiplayer <- factor(df$WTPlay_Multiplayer, 
                                levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                             , ordered=TRUE)




df$WTPTime_Souls <- factor(df$WTPTime_Souls, 
                          levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                          , ordered=TRUE)

df$WTPTime_Shooter <- factor(df$WTPTime_Shooter, 
                            levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                            , ordered=TRUE)

df$WTPTime_Puzzle <- factor(df$WTPTime_Puzzle, 
                           levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                           , ordered=TRUE)

df$WTPTime_RTS <- factor(df$WTPTime_RTS, 
                        levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                        , ordered=TRUE)

df$WTPTime_RPG <- factor(df$WTPTime_RPG, 
                        levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                        , ordered=TRUE)

df$WTPTime_Survival <- factor(df$WTPTime_Survival, 
                             levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                             , ordered=TRUE)

df$WTPTime_Multiplayer <- factor(df$WTPTime_Multiplayer, 
                              levels=c(1,2,3,4,5,6,7), labels=c("7","6","5","4","3","2","1")
                              , ordered=TRUE)

df$Joueur_1.0 <- factor(df$Joueur_1.0, 
                                levels=c(0,1), labels=c("No","Yes")
                                , ordered=TRUE)

df$Gender_Femme <- factor(df$Gender_Femme, 
                        levels=c(0,1), labels=c("Man","Woman")
                        , ordered=TRUE)

for (i in c("WTPlay_Souls","WTPlay_Shooter", 'WTPlay_Puzzle','WTPlay_RTS', 'WTPlay_RPG', 'WTPlay_Survival',
            'WTPlay_Multiplayer')) {
  print(i)
  polrMod <-  polr(formula = paste(i[[1]], "~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme")
, data = df, Hess=TRUE)
  brant(polrMod)
  print(exp(coef(polrMod)))
  (ctable <- coef(summary(polrMod)))
  p <- pnorm(abs(ctable[, "t value"]), lower.tail = FALSE) * 2
  print((ctable <- cbind(ctable, "p value" = p)))
}



for (i in c("WTPTime_Souls", "WTPTime_Shooter", 'WTPTime_Puzzle','WTPTime_RTS', 'WTPTime_RPG', 'WTPTime_Survival',
            'WTPTime_Multiplayer')) {
  print(i)
  polrMod <-  polr(formula = paste(i[[1]], "~ Age + OPE + AGR  + CON + NEU + EXT + Joueur_1.0 + Gender_Femme")
                   , data = df, Hess=TRUE)
  #brant(polrMod)
  print(exp(coef(polrMod)))
  print(exp(polrMod$zeta))
  (ctable <- coef(summary(polrMod)))
  p <- pnorm(abs(ctable[, "t value"]), lower.tail = FALSE) * 2
  print((ctable <- cbind(ctable, "p value" = p)))
}


