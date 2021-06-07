from os import environ
import os
import os.path
import sys

SESSION_CONFIG_DEFAULTS = dict(real_world_currency_per_point=0.10, participation_fee=10)
SESSION_CONFIGS = [dict(name='SessionFr', num_demo_participants=20, app_sequence=["Introduction",'Part_1', 'Part_2', 'Part_3']),
                   dict(name='SessionEn', num_demo_participants=20, app_sequence=["EN_Introduction",'EN_Part_1', 'EN_Part_2', 'EN_Part_3'])]
LANGUAGE_CODE = 'en'
REAL_WORLD_CURRENCY_CODE = 'USD'
USE_POINTS = True
DEMO_PAGE_INTRO_HTML = ''
ROOMS = [
    dict(
        name='Experiment_FR',
        display_name='Experiment_FR',
        use_secure_urls=False
    ), dict(
        name='Experiment_EN',
        display_name='Experiment_EN',
        use_secure_urls=False)
    ]

ADMIN_USERNAME = 'admin'
PARTICIPANT_FIELDS = ['Envie_WordsList_Souls', "Envie_WordsList_Shooter", "Envie_WordsList_Horror", "Envie_WordsList_RTS",
                      "Envie_WordsList_RPG", "Envie_WordsList_Survival", "Envie_WordsList_Multiplayer"]

# for security, best to set admin password in an environment variable
ADMIN_PASSWORD = environ.get('OTREE_ADMIN_PASSWORD')
ADMIN_PASSWORD = "passwordtropcomplexe"


SECRET_KEY = 'blahblah'

###Set la database
#os.environ['DATABASE_URL'] = 'postgres://postgres@localhost/django_db'

# if an app is included in SESSION_CONFIGS, you don't need to list it here
INSTALLED_APPS = ['otree']
os.environ['OTREE_AUTH_LEVEL'] = "STUDY"
OTREE_PRODUCTION = environ.get('OTREE_PRODUCTION')
if environ.get('OTREE_PRODUCTION') not in {None, '', '0'}: #Alterner pour changer en debug
    DEBUG = True #False en debug
else:
    DEBUG = False #True en debug
