import random
from otree.api import (
    models, widgets, BaseConstants, BaseSubsession, BaseGroup, BasePlayer,
    Currency as c, currency_range
)

doc = ''
class Constants(BaseConstants):
    name_in_url = 'EN_Part_1'
    players_per_group = None
    num_rounds = 1
    Points = c(1500)
    tasks = [x for x in range(1,8)]
    num_rounds = len(tasks)
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
            choices=[[1, 'Not at all'], [2, 'A little bit'], [3, 'A bit'], [4, 'Maybe'], [5, 'Likely'],
                     [6, 'Very likely'], [7, 'Definitely']],
            label='Would you like to play a game with these characteristics?',
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

