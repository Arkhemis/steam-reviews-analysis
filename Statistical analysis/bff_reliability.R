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
df <- read_csv("df_bff.csv")
df <- dplyr::select(df, -c(0:113,158:203))
### Reliability ####
cols = c("Part_2.1.player.bff_6","Part_2.1.player.bff_21","Part_2.1.player.bff_31",
         "Part_2.1.player.bff_2", "Part_2.1.player.bff_12", "Part_2.1.player.bff_27",
         "Part_2.1.player.bff_37", "Part_2.1.player.bff_8", "Part_2.1.player.bff_18",
         "Part_2.1.player.bff_23","Part_2.1.player.bff_43", "Part_2.1.player.bff_9",
         "Part_2.1.player.bff_24","Part_2.1.player.bff_34","Part_2.1.player.bff_35",
         "Part_2.1.player.bff_41")
df[ ,cols] = 8 - df[ ,cols]


df_OPE= df[, c("Part_2.1.player.bff_5", "Part_2.1.player.bff_10","Part_2.1.player.bff_15",
               "Part_2.1.player.bff_20","Part_2.1.player.bff_25","Part_2.1.player.bff_30",
                "Part_2.1.player.bff_35","Part_2.1.player.bff_40", 
                "Part_2.1.player.bff_41","Part_2.1.player.bff_44")]
psych::alpha(df_OPE)

df_AGR= df[, c("Part_2.1.player.bff_2", "Part_2.1.player.bff_7",
                     "Part_2.1.player.bff_12", "Part_2.1.player.bff_17",
                    "Part_2.1.player.bff_22", "Part_2.1.player.bff_27", 
                     "Part_2.1.player.bff_32", "Part_2.1.player.bff_37", 
                     "Part_2.1.player.bff_42")]
psych::alpha(df_AGR)

df_CON= df[, c("Part_2.1.player.bff_3","Part_2.1.player.bff_8", 
              "Part_2.1.player.bff_13","Part_2.1.player.bff_18", "Part_2.1.player.bff_23",
              "Part_2.1.player.bff_28","Part_2.1.player.bff_33","Part_2.1.player.bff_38",
              "Part_2.1.player.bff_43")]
psych::alpha(df_CON)

df_NEU= df[, c("Part_2.1.player.bff_4","Part_2.1.player.bff_9","Part_2.1.player.bff_14",
               "Part_2.1.player.bff_19","Part_2.1.player.bff_24","Part_2.1.player.bff_29",
               "Part_2.1.player.bff_34","Part_2.1.player.bff_39")]
psych::alpha(df_CON)

df_EXT= df[, c("Part_2.1.player.bff_1", "Part_2.1.player.bff_6",
              "Part_2.1.player.bff_11", "Part_2.1.player.bff_16",
              "Part_2.1.player.bff_21", "Part_2.1.player.bff_26",
              "Part_2.1.player.bff_31", "Part_2.1.player.bff_36")]
psych::alpha(df_EXT)



