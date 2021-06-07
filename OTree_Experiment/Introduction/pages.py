from otree.api import Currency as c, currency_range
from ._builtin import Page, WaitPage
from .models import Constants
import os
import subprocess
import sys
import random

class Introduction(Page):
    form_model = 'player'
class Intro2(Page):
    form_model = 'player'

page_sequence = [Introduction, Intro2]


