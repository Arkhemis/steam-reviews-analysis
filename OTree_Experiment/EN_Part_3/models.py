import random
from otree.api import (
    models, widgets, BaseConstants, BaseSubsession, BaseGroup, BasePlayer,
    Currency as c, currency_range
)
from country_list import countries_for_language
doc = ''
countries = dict(countries_for_language('en'))

def make_countries():
    choices = []
    for c in countries:
        cho = []
        country = [(countries)[str(c)]]
        country = country[0]
        cho.append(country)
        cho.append(country)
        choices.append(cho)
    return choices

class Constants(BaseConstants):
    name_in_url = 'EN_Part_3'
    players_per_group = None
    num_rounds = 1
    WordsList_Souls_FR = ["level", "enemy", "fight", "combat", "boss", "weapon", "skill", "item", "attack", "upgrade"]
    WordsList_Shooter_FR = ["mission", "gun", "kill", "shoot", "enemy", "weapon", "car", "hit", "jump", "run"]
    WordsList_Horror_FR = ["experience", "puzzle", "design", "feel", "sound", "atmosphere", "horror", "visual", "find",
                        "environment", "mechanic"]
    WordsList_RTS_FR = ["war", "battle", "space", "strategy", "system", "artificial intelligence", "ship", "turn", "build", "base"]
    WordsList_RPG_FR = ["story", "character", "world", "feel", "main", "end", "interesting", "quest", "choice", "combat"]
    WordsList_Survival_FR = ["find", "build", "start", "survival", "thing", "world", "explore", "day", "craft", "building"]
    WordsList_Multiplayer_FR = ["player", "friend", "people", "mode", "map", "server", "team", "community", "single", "coop"]
    ### Version FR ###

class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass


def make_field_Time():
    return models.IntegerField(min = 0, max = 600, initial=0, label='')


class Player(BasePlayer): #Ici sont codées les variables qui seront soumises au participant
    choice = models.StringField(label="",widget=widgets.RadioSelect)
    treatment = models.StringField()
    Personality = models.StringField()
    Envie_WordsList_Souls = models.IntegerField(initial=0)
    Envie_WordsList_Shooter = models.IntegerField(initial=0)
    Envie_WordsList_Horror = models.IntegerField(initial=0)
    Envie_WordsList_RTS = models.IntegerField(initial=0)
    Envie_WordsList_RPG = models.IntegerField(initial=0)
    Envie_WordsList_Survival = models.IntegerField(initial=0)
    Envie_WordsList_Multiplayer = models.IntegerField(initial=0)
    Time_Souls = make_field_Time()
    Time_Shooter = make_field_Time()
    Time_Horror = make_field_Time()
    Time_RPG = make_field_Time()
    Time_RTS = make_field_Time()
    Time_Survival = make_field_Time()
    Time_Multiplayer = make_field_Time()
    Time_Justify = models.StringField(choices=[["Discover", 'Because I prefer to devote my time to games that I know little/no about'],
                                               ['Classic', 'Because I prefer to devote my time playing games that I particularly enjoy'],
                                               ['Undecisive', 'I had a hard time choosing and allocating my playing time'],
                                               ['other', 'Other']],
                                                label="Why did you choose to devote your playing time this way?",
                                                 widget=widgets.RadioSelectHorizontal)
    Autre_Justify = models.StringField(blank=True, label = "If you answered Other to the previous question, please justify your choice below:")
    Total = models.IntegerField(initial=0)
    ####

    Joueur = models.BooleanField(choices=[[True, 'Yes'], [False, 'No']], label="Do you play videogames?",
                                 widget=widgets.RadioSelectHorizontal)
    Platform_1 = models.StringField(blank = True, choices=[["pc", 'Computer'], ["Playstation", 'Playstation'],["Xbox", 'Xbox'],
                                          ["portable", 'Handheld game consoles (DS, PSP)'],["Nintendo", 'Nintendo'],
                                             ["Telephone", 'Phone'], ["Old_school", 'Retro/Old consoles (Nintendo 64, Dreamcast...)'],
                                             ["Other", 'Other']], label = 'On which platform do you play mostly? (this question is optional if you answered "No" to the previous question)')
    Platform_2 = models.StringField(blank = True, choices=[["pc", 'Computer'], ["Playstation", 'Playstation'], ["Xbox", 'Xbox'],
                                             ["portable", 'Handheld game consoles (DS, PSP)'], ["Nintendo", 'Nintendo'],
                                             ["Telephone", 'Phone'],
                                             ["Old_school", 'Retro/Old consoles (Nintendo 64, Dreamcast...)'],
                                             ["Other", 'Other']],
                                    label='On which platform do you play second most? (optional answer)')
    Platform_3 = models.StringField(blank=True,
                                    choices=[["pc", 'Computer'], ["Playstation", 'Playstation'], ["Xbox", 'Xbox'],
                                             ["portable", 'Handheld game consoles (DS, PSP)'], ["Nintendo", 'Nintendo'],
                                             ["Telephone", 'Phone'],
                                             ["Old_school", 'Retro/Old consoles (Nintendo 64, Dreamcast...)'],
                                             ["Other", 'Other']],
                                    label='On which platform do you play third most? (optional answer)')
    Jeu_Favori = models.StringField(blank = True, label = 'What is your favorite game (of all time)? (optional answer)')
    Jeu_Justification = models.LongStringField(blank = True, label = 'If you have indicated a favorite game, you can explain the reason below in 2-3 lines (or more).')

    Age = models.IntegerField(label='How old are you?', min=18, max=118)
    Genre = models.StringField(choices=[['Homme', 'Man'], ['Femme', 'Woman'], ['None', 'Other']],
                                label='What is your gender?',
                                widget=widgets.RadioSelectHorizontal)
    Discipline = models.StringField(
        choices=[["math", 'Mathematics'], ["sciences", 'Sciences (biology/physics/chemistry)'],
                 ["SciHumaines", 'Social Sciences'], ["Commercial", 'Sales representative'],
                 ["eco", 'Economy'], ["info", 'I.T'], ["droit", 'Law'], ["langue", 'Foreign languages'],
                 ["autre", "Other"]],
        label='What is your field of study?', widget=widgets.RadioSelectHorizontal)
    CSP = models.StringField(choices=[["Etudiant", 'Student'], ["Enseignant", 'Teacher'],
                 ["Agriculteur", 'Farmer'],["Ouvrier", 'Blue collar'],
                 ["Commerçant", 'Retail worker'], ["Artisan", 'Artisan'], ["Cadre", 'Executive'], ["Libéral", 'Free-Lance'],["Unemployed","Unemployed"],["Retraité", 'Retired'],
                 ["autre", "Other"]],
        label='What is your socio-professional category?', widget=widgets.RadioSelectHorizontal)
    Education = models.StringField(choices=[["Secondary", 'Up to secondary'], ["Undergraduate", 'Undergraduate'],
                 ["Master", 'Master level'],["PhD", 'PhD Level'],
                 ["Other", 'Other']],
        label='What is your educational attainment?', widget=widgets.RadioSelectHorizontal)
    Location = models.StringField(choices = make_countries() ,label="In which country do you live?")




    Tirage = models.BooleanField(choices=[[True, 'Yes'], [False, 'No']], widget=widgets.RadioSelectHorizontal, label="Would you like to participate in the prize draw (to win either a Amazon or Steam gift card worth 60€)?")
    def live_Time(self, data):
        t = data['type']
        if t == 'Time_Souls':
            self.Time_Souls = data["value"]
        elif t == 'Time_Shooter':
            self.Time_Shooter = data["value2"]
        elif t == 'Time_Horror':
            self.Time_Horror = data["value3"]
        elif t == 'Time_RTS':
            self.Time_RTS = data["value4"]
        elif t == 'Time_RPG':
            self.Time_RPG = data["value5"]
        elif t == 'Time_Survival':
            self.Time_Survival = data["value6"]
        elif t == 'Time_Multiplayer':
            self.Time_Multiplayer = data["value7"]
        self.Total = self.Time_Souls + self.Time_Shooter + self.Time_Horror + self.Time_RTS + self.Time_RPG + \
                     self.Time_Survival + self.Time_Multiplayer
        if t == 'Total_Reset':
            self.Total = 0
            self.Time_Souls = 0
            self.Time_Shooter = 0
            self.Time_Horror = 0
            self.Time_RTS = 0
            self.Time_RPG = 0
            self.Time_Survival = 0
            self.Time_Multiplayer = 0
        return {self.id_in_group: self.Total}

