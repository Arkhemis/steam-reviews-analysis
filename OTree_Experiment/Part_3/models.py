import random
from otree.api import (
    models, widgets, BaseConstants, BaseSubsession, BaseGroup, BasePlayer,
    Currency as c, currency_range
)
from country_list import countries_for_language
countries = dict(countries_for_language('fr'))

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
doc = ''
class Constants(BaseConstants):
    name_in_url = 'Part_3'
    players_per_group = None
    num_rounds = 1
    WordsList_Souls = ["level", "enemy", "fight", "combat", "boss", "weapon", "skill", "item", "attack", "upgrade"]
    WordsList_Shooter = ["mission", "gun", "kill", "shoot", "enemy", "weapon", "car", "hit", "jump", "run"]
    WordsList_Horror = ["experience", "puzzle", "design", "feel", "sound", "atmosphere", "horror", "visual", "find",
                        "environment", "mechanic"]
    WordsList_RTS = ["war", "battle", "space", "strategy", "system", "ai", "ship", "turn", "build", "base"]
    WordsList_RPG = ["story", "character", "world", "feel", "main", "end", "interesting", "quest", "choice", "combat"]
    WordsList_Survival = ["find", "build", "start", "survival", "thing", "world", "explore", "day", "craft", "building"]
    WordsList_Multiplayer = ["player", "friend", "people", "mode", "map", "server", "team", "community", "single", "coop"]
    ### FR###
    WordsList_Souls_FR = ["niveau", "ennemi", "affronter", "combat", "boss", "arme", "compétence", "objet", "attaque",
                          "amélioration"]
    WordsList_Shooter_FR = ["mission", "arme à feu", "tuer", "tirer", "ennemi", "arme", "voiture", "coup", "sauter",
                            "courir"]
    WordsList_Horror_FR = ["expérience", "puzzle", "design", "ressentir", "son", "atmosphère", "horreur", "visuel",
                           "trouver",
                           "environnement", "mécanique"]
    WordsList_RTS_FR = ["guerre", "bataille", "espace", "stratégie", "système", "intelligence artificielle", "vaisseau",
                        "tour", "construire", "base"]
    WordsList_RPG_FR = ["histoire", "personnage", "monde", "ressentir", "principal", "fin", "intéressant", "quête",
                        "choix", "combat"]
    WordsList_Survival_FR = ["trouver", "construire", "commencer", "survie", "chose", "monde", "explorer", "jour",
                             "fabrication", "structure"]
    WordsList_Multiplayer_FR = ["joueur", "ami", "personnes", "mode", "carte", "serveur", "équipe", "communauté",
                                "seul", "coop"]

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
    Time_Justify = models.StringField(choices=[["Discover", 'Car je préfère consacrer mon temps à des genres de jeu que je connais peu/pas'],
                                               ['Classic', 'Car je préfère consacrer mon temps de jeu à des genres de jeux que j\'apprécie particulièrement'],
                                               ['Undecisive', 'J\'ai eu du mal à choisir et à attribuer mon temps de jeu'],
                                               ['other', 'Autre']],
                                                label="Pourquoi avez-vous réparti votre temps de jeu de cette façon ?",
                                                 widget=widgets.RadioSelectHorizontal)
    Autre_Justify = models.StringField(blank=True, label = "Si vous avez répondu autre à la question précédente, vous pouvez justifier votre choix ci-dessous :")
    Total = models.IntegerField(initial=0)
    ####

    Joueur = models.BooleanField(choices=[[True, 'Oui'], [False, 'Non']], label="Jouez-vous aux jeux vidéo?",
                                 widget=widgets.RadioSelectHorizontal)
    Platform_1 = models.StringField(blank = True, choices=[["pc", 'Ordinateur'], ["Playstation", 'Playstation'],["Xbox", 'Xbox'],
                                          ["portable", 'Consoles portables (DS, PSP)'],["Nintendo", 'Nintendo'],
                                             ["Telephone", 'Téléphone'], ["Old_school", 'Anciennes consoles (Nintendo 64, Dreamcast...)'],
                                             ["Other", 'Autres']], label = 'Sur quelle plate-forme jouez-vous principalement ? (cette question est optionelle si vous avez répondu "Non" à la question précédente)')
    Platform_2 = models.StringField(blank = True, choices=[["pc", 'Ordinateur'], ["Playstation", 'Playstation'], ["Xbox", 'Xbox'],
                                             ["portable", 'Consoles portables (DS, PSP)'], ["Nintendo", 'Nintendo'],
                                             ["Telephone", 'Téléphone'],
                                             ["Old_school", 'Anciennes consoles (Nintendo 64, Dreamcast...)'],
                                             ["Other", 'Autres']],
                                    label='Sur quelle plate-forme jouez-vous en deuxième ? (réponse optionelle)')
    Platform_3 = models.StringField(blank=True,
                                    choices=[["pc", 'Ordinateur'], ["Playstation", 'Playstation'], ["Xbox", 'Xbox'],
                                             ["portable", 'Consoles portables (DS, PSP)'], ["Nintendo", 'Nintendo'],
                                             ["Telephone", 'Téléphone'],
                                             ["Old_school", 'Anciennes consoles (Nintendo 64, Dreamcast...)'],
                                             ["Other", 'Autres']],
                                    label='Sur quelle plate-forme jouez-vous en troisième ? (réponse optionelle) ')
    Jeu_Favori = models.StringField(blank = True, label = 'Quel est votre jeu préféré (de tout temps) ? (réponse optionelle)')
    Jeu_Justification = models.LongStringField(blank = True, label = 'Si vous avez indiqué un jeu, vous pouvez expliquer la raison ci-dessous en 2-3 lignes.')

    Age = models.IntegerField(label='Quel âge avez-vous?', min=18, max=118)
    Genre = models.StringField(choices=[['Homme', 'Homme'], ['Femme', 'Femme'], ['None', 'Non-précisé']],
                                label='Quel est votre sexe?',
                                widget=widgets.RadioSelectHorizontal)
    Discipline = models.StringField(
        choices=[["math", 'Mathématiques'], ["sciences", 'Sciences (biologie/physique/chimie)'],
                 ["SciHumaines", 'Sciences Humaines'], ["Commercial", 'Commercial'],
                 ["eco", 'Économie'], ["info", 'Informatique'], ["droit", 'Droit'], ["langue", 'Langues étrangères'],
                 ["autre", "Autre"]],
        label='Quelle est votre discipline ?', widget=widgets.RadioSelectHorizontal)
    CSP = models.StringField(choices=[["Etudiant", 'Etudiant'], ["Enseignant", 'Enseignant'],
                 ["Agriculteur", 'Agriculteur'],["Ouvrier", 'Ouvrier'],
                 ["Commerçant", 'Commerçant'], ["Artisan", 'Artisan'], ["Cadre", 'Cadre'], ["Libéral", 'Libéral'],["Retraité", 'Retraité'],
                 ["autre", "Autre"]],
        label='Quelle est votre catégorie socio-professionnelle ?', widget=widgets.RadioSelectHorizontal)
    Education = models.StringField(choices=[["Secondary", 'Niveau Brevet/Baccalauréat'], ["Undergraduate", 'Licence'],
                                            ["Master", 'Master'], ["PhD", 'Doctorat'],
                                            ["Other", 'Autre']],
                                   label='Quel est votre niveau d\'éducation?', widget=widgets.RadioSelectHorizontal)
    Location = models.StringField(choices = make_countries(), label="Quel est votre pays de résidence ?")
    Tirage = models.BooleanField(choices=[[True, 'Oui'], [False, 'Non']], widget=widgets.RadioSelectHorizontal, label="Souhaitez-vous participer au tirage au sort (carte cadeau Amazon ou Steam d'une valeur de 60€) ?")
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

