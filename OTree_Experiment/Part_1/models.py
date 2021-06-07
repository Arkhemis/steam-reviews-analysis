import random
from otree.api import (
    models, widgets, BaseConstants, BaseSubsession, BaseGroup, BasePlayer,
    Currency as c, currency_range
)

doc = ''
class Constants(BaseConstants):
    name_in_url = 'Part_1'
    players_per_group = None
    num_rounds = 1
    Points = c(1500)
    tasks = [x for x in range(1,8)]
    num_rounds = len(tasks)
    WordsList_Souls = ["level", "enemy", "fight", "combat", "boss", "weapon", "skill", "item", "attack", "upgrade"]
    WordsList_Shooter = ["mission", "gun", "kill", "shoot", "enemy", "weapon", "car", "hit", "jump", "run"]
    WordsList_Horror = ["experience", "puzzle", "design", "feel", "sound", "atmosphere", "horror", "visual", "find",
                        "environment", "mechanic"]
    WordsList_RTS = ["war", "battle", "space", "strategy", "system", "artificial intelligence", "ship", "turn", "build", "base"]
    WordsList_RPG = ["story", "character", "world", "feel", "main", "end", "interesting", "quest", "choice", "combat"]
    WordsList_Survival = ["find", "build", "start", "survival", "thing", "world", "explore", "day", "craft", "building"]
    WordsList_Multiplayer = ["player", "friend", "people", "mode", "map", "server", "team", "community", "single", "coop"]
    ### Version FR ###
    WordsList_Souls_FR = ["niveau", "ennemi", "affronter", "combat", "boss", "arme", "compétence", "objet", "attaque", "amélioration"]
    WordsList_Shooter_FR = ["mission", "arme à feu", "tuer", "tirer", "ennemi", "arme", "voiture", "coup", "sauter", "courir"]
    WordsList_Horror_FR = ["expérience", "puzzle", "design", "ressentir", "son", "atmosphère", "horreur", "visuel", "trouver",
                        "environnement", "mécanique"]
    WordsList_RTS_FR = ["guerre", "bataille", "espace", "stratégie", "système", "intelligence artificielle", "vaisseau", "tour", "construire", "base"]
    WordsList_RPG_FR = ["histoire", "personnage", "monde", "ressentir", "principal", "fin", "intéressant", "quête", "choix", "combat"]
    WordsList_Survival_FR = ["trouver", "construire", "commencer", "survie", "chose", "monde", "explorer", "jour", "fabrication", "structure"]
    WordsList_Multiplayer_FR = ["joueur", "ami", "personnes", "mode", "carte", "serveur", "équipe", "communauté", "seul", "coop"]


class Subsession(BaseSubsession):
    def creating_session(self):
        import itertools
        import random
        if self.round_number == 1:
            for p in self.get_players():
                round_numbers = list(range(1, Constants.num_rounds + 1))
                random.shuffle(round_numbers)
                p.participant.vars['task_rounds'] = dict(zip(Constants.tasks, round_numbers))


class Group(BaseGroup):
    pass



class Player(BasePlayer): #Ici sont codées les variables qui seront soumises au participant
    def make_field_Envie():
        return models.IntegerField(
            choices=[[1, 'Pas du tout'], [2, 'Un petit peu'], [3, 'Un peu'], [4, 'Moyennement'], [5, 'Probablement'],
                     [6, 'Très probablement'], [7, 'Totalement']],
            label='Voudriez-vous jouer à un jeu possédant ces caractéristiques ?',
            widget=widgets.RadioSelectHorizontal,
        )
    def make_field_WTP():
        return models.IntegerField()

    Envie_WordsList_Souls = make_field_Envie()
    Envie_WordsList_Shooter = make_field_Envie()
    Envie_WordsList_Horror = make_field_Envie()
    Envie_WordsList_RTS = make_field_Envie()
    Envie_WordsList_RPG = make_field_Envie()
    Envie_WordsList_Survival = make_field_Envie()
    Envie_WordsList_Multiplayer = make_field_Envie()





    """
    Achat_WordsList_Souls = models.
    Achat_WordsList_Shooter
    Achat_WordsList_Horror
    Achat_WordsList_RTS
    Achat_WordsList_RPG
    Achat_WordsList_Survival
    Achat_WordsList_Multiplayer"""


