from otree.api import Currency as c, currency_range
from ._builtin import Page, WaitPage
from .models import Constants
import os
import subprocess
import sys
import random

"""

@staticmethod
def live_method(player, data):
    player.WTP_WordsList_Souls = int(data)

def before_next_page(self):
    self.participant.vars['Envie_WordsList_Souls'] = self.player.Envie_WordsList_Souls
    self.participant.vars['WTP_WordsList_Souls'] = self.player.WTP_WordsList_Souls

def page_creation(TaskNumber, name_type):
    def is_displayed(self):
        return self.round_number == self.participant.vars['task_rounds'][1]
    def vars_for_template(player):
        type_name = [Constants.WordsList_%s % name_type].copy()
        random.shuffle(type_name)
        return dict({
            "WordsList_"+str(name_type) : type_name
        })
    Task = type(f"Task{TaskNumber}", (Page,), {'form_model' : 'player',
    "form_fields": [f"Envie_WordsList_{name_type}"],
    "is_displayed": is_displayed,
    "vars_for_template": vars_for_template

    })
    return Task
Task1 = page_creation(1,"Souls")

hello = "o"
world = "k"
ok = "result"

print ("%s%s" % (hello, world))
"""

class xopo(Page):
    form_model = 'player'
    form_fields = ['Envie_WordsList_Souls']

    def is_displayed(self):
        global code
        code = self.participant.code
        return self.round_number == self.participant.vars['task_rounds'][1]

    def vars_for_template(player):
        WordsList_Souls_FR = Constants.WordsList_Souls_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_Souls_FR)
        return dict(
            WordsList_Souls_FR=WordsList_Souls_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_Souls'] = self.player.Envie_WordsList_Souls


class cjxq(Page):
    form_model = 'player'
    form_fields = ['Envie_WordsList_Shooter']

    def is_displayed(self):
        global code
        code = self.participant.code
        return self.round_number == self.participant.vars['task_rounds'][2]
    def vars_for_template(player):

        WordsList_Shooter_FR = Constants.WordsList_Shooter_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_Shooter_FR)
        return dict(
            WordsList_Shooter_FR=WordsList_Shooter_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_Shooter'] = self.player.Envie_WordsList_Shooter

class fxjk(Page):
    form_model = 'player'
    form_fields = ['Envie_WordsList_Horror']
    def is_displayed(self):
        global code
        code = self.participant.code
        return self.round_number == self.participant.vars['task_rounds'][3]
    def vars_for_template(player):
        WordsList_Horror_FR = Constants.WordsList_Horror_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_Horror_FR)
        return dict(
            WordsList_Horror_FR=WordsList_Horror_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_Horror'] = self.player.Envie_WordsList_Horror

class cxwz(Page):
    form_model = 'player'
    form_fields = ['Envie_WordsList_RTS']
    def is_displayed(self):
        global code
        code = self.participant.code
        return self.round_number == self.participant.vars['task_rounds'][4]
    def vars_for_template(player):
        WordsList_RTS_FR = Constants.WordsList_RTS_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_RTS_FR)
        return dict(
            WordsList_RTS_FR=WordsList_RTS_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_RTS'] = self.player.Envie_WordsList_RTS

class djza(Page):
    form_model = 'player'
    form_fields = ['Envie_WordsList_RPG']
    def is_displayed(self):
        global code
        code = self.participant.code
        return self.round_number == self.participant.vars['task_rounds'][5]
    def vars_for_template(player):
        WordsList_RPG_FR = Constants.WordsList_RPG_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_RPG_FR)
        return dict(
            WordsList_RPG_FR=WordsList_RPG_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_RPG'] = self.player.Envie_WordsList_RPG


class auxw(Page): #survival
    form_model = 'player'
    form_fields = ['Envie_WordsList_Survival']
    def is_displayed(self):
        global code
        code = self.participant.code
        return self.round_number == self.participant.vars['task_rounds'][6]
    def vars_for_template(player):
        WordsList_Survival_FR = Constants.WordsList_Survival_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_Survival_FR)
        return dict(
            WordsList_Survival_FR=WordsList_Survival_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_Survival'] = self.player.Envie_WordsList_Survival

class llka(Page):
    form_model = 'player'
    form_fields = ['Envie_WordsList_Multiplayer']
    def is_displayed(self):
        return self.round_number == self.participant.vars['task_rounds'][7]
    def vars_for_template(player):
        WordsList_Multiplayer_FR = Constants.WordsList_Multiplayer_FR.copy()
        #random.Random(str(code)).shuffle(WordsList_Multiplayer_FR)
        return dict(
            WordsList_Multiplayer_FR=WordsList_Multiplayer_FR
        )
    def before_next_page(self):
        self.participant.vars['Envie_WordsList_Multiplayer'] = self.player.Envie_WordsList_Multiplayer


page_sequence = [xopo,
    cjxq,
    fxjk,
    cxwz,
    djza,
    auxw,
    llka
    ]
