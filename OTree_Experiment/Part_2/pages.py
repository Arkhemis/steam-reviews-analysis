from otree.api import Currency as c, currency_range
from ._builtin import Page, WaitPage
from .models import Constants
import os
import subprocess
import sys
import random
from . import models
bff = []
for i in range(1,46):
    bff.append(str(i))

ssvs = ["power", "achievement", "hedonism", "stimulation", "selfdirection", "universalism", "benevolence", "tradition", "conformity", "security"]

def reverse(nombre):
    if nombre == 5:
        nombre = 1
    elif nombre == 4:
        nombre = 2
    elif nombre == 2:
        nombre = 4
    elif nombre == 1:
        nombre = 5
    return nombre

class psly(Page):
    form_model = "player"

    def get_form_fields(self):
        res = ["bff_{}".format(str(bff[i + 1])) for i in range(-1,25)]
        return res

class lysp(Page):
    form_model = "player"
    debug_fill_forms_randomly = True

    def get_form_fields(self):
        res = ["bff_{}".format(str(bff[i + 1])) for i in range(25,43)]
        return res
"""
class SVSS(Page):
    form_model = "player"

    def get_form_fields(self):
        res = ["ssvs_{}".format(str(ssvs[i + 1])) for i in range(-1,9)]
        return res
    def before_next_page(self):
        EXT = self.player.bff_1 + reverse(self.player.bff_6) + self.player.bff_11 + self.player.bff_16 + reverse(self.player.bff_21)
        + self.player.bff_26 + reverse(self.player.bff_31) + self.player.bff_36
        AGR = reverse(self.player.bff_2) + self.player.bff_7 + reverse(self.player.bff_12) + self.player.bff_17 + self.player.bff_22
        + reverse(self.player.bff_27) + self.player.bff_32 + reverse(self.player.bff_37) + self.player.bff_42 + reverse(self.player.bff_45)
        CON = self.player.bff_3 + reverse(self.player.bff_8) + self.player.bff_13 + reverse(self.player.bff_18) + reverse(self.player.bff_23)
        + self.player.bff_28 + self.player.bff_33 + self.player.bff_38 + reverse(self.player.bff_43)
        NEU = self.player.bff_4 + reverse(self.player.bff_9) + self.player.bff_14 + self.player.bff_19 + reverse(self.player.bff_24)
        + self.player.bff_29 + reverse(self.player.bff_34) + self.player.bff_39
        OPE = self.player.bff_5 + self.player.bff_10 + self.player.bff_15 + self.player.bff_20 + self.player.bff_25 + self.player.bff_30
        + reverse(self.player.bff_35) + self.player.bff_40 + reverse(self.player.bff_41) + self.player.bff_44
        Types = {'EXT': EXT, 'AGR': AGR, 'CON': CON, 'NEU': NEU, 'OPE': OPE}
        Max_Type = max(Types, key=Types.get)
        print(Max_Type)
        print(EXT, AGR, CON, NEU, OPE)
        self.participant.vars['Personality'] = Max_Type
"""
class svtt(Page):
    def before_next_page(self):
        EXT = self.player.bff_1 + reverse(self.player.bff_6) + self.player.bff_11 + self.player.bff_16 + reverse(self.player.bff_21)
        + self.player.bff_26 + reverse(self.player.bff_31) + self.player.bff_36
        AGR = reverse(self.player.bff_2) + self.player.bff_7 + reverse(self.player.bff_12) + self.player.bff_17 + self.player.bff_22
        + reverse(self.player.bff_27) + self.player.bff_32 + reverse(self.player.bff_37) + self.player.bff_42
        CON = self.player.bff_3 + reverse(self.player.bff_8) + self.player.bff_13 + reverse(self.player.bff_18) + reverse(self.player.bff_23)
        + self.player.bff_28 + self.player.bff_33 + self.player.bff_38 + reverse(self.player.bff_43)
        NEU = self.player.bff_4 + reverse(self.player.bff_9) + self.player.bff_14 + self.player.bff_19 + reverse(self.player.bff_24)
        + self.player.bff_29 + reverse(self.player.bff_34) + self.player.bff_39
        OPE = self.player.bff_5 + self.player.bff_10 + self.player.bff_15 + self.player.bff_20 + self.player.bff_25 + self.player.bff_30
        + reverse(self.player.bff_35) + self.player.bff_40 + reverse(self.player.bff_41) + self.player.bff_44
        Types = {'EXT': EXT, 'AGR': AGR, 'CON': CON, 'NEU': NEU, 'OPE': OPE}
        Max_Type = max(Types, key=Types.get)
        print(Max_Type)
        print(EXT, AGR, CON, NEU, OPE)
        self.participant.vars['Personality'] = Max_Type
page_sequence = [psly, lysp, svtt]

