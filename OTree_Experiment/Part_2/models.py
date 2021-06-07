import random
from otree.api import (
    models, widgets, BaseConstants, BaseSubsession, BaseGroup, BasePlayer,
    Currency as c, currency_range
)
#from otreeutils.surveys import generate_likert_field, generate_likert_table, create_player_model_for_survey
from collections import OrderedDict
doc = ''
class Constants(BaseConstants):
    name_in_url = 'Part_2'
    players_per_group = None
    num_rounds = 1
    with open(name_in_url + "/bffquestions.txt", encoding='utf-8') as f:
        questions_bff = f.readlines()
    with open(name_in_url + "/svssquestions.txt", encoding='utf-8') as f:
        questions_svss = f.readlines()
    choices_map = OrderedDict(
        (
            (1, "Désapprouve fortement"),
            (2, "Désapprouve un peu"),
            (3, "Ni en désaccord, ni d\'accord"),
            (4, "Approuve un peu"),
            (5, "Approuve fortement"),
        )
    )
    choices_map_ssvs = OrderedDict(
        (
            (-1, "-1"),
            (0, "0"),
            (1, "1"),
            (2, "2"),
            (3, "3"),
            (4, "4"),
            (5, "5"),
            (6, "6"),
            (7, "7"),
            (8, "8")
        )
    )
class Subsession(BaseSubsession):
    pass


class Group(BaseGroup):
    pass

def make_fieldsBFF(questions):
    res = []
    for q in questions:
        res.append(
            models.IntegerField(
                choices=[(i, Constants.choices_map[i]) for i in range(1,6)],
                label=q,
                widget=widgets.RadioSelect,
            )
        )
    return res

def make_fieldsSSVS(questions):
    res = []
    for q in questions:
        res.append(
            models.IntegerField(
                choices=[(i, Constants.choices_map_ssvs[i]) for i in range(-1,9)],
                label=q,
                widget=widgets.RadioSelect,
            )
        )
    return res
class Player(BasePlayer):
    (
        bff_1,
        bff_2,
        bff_3,
        bff_4,
        bff_5,
        bff_6,
        bff_7,
        bff_8,
        bff_9,
        bff_10,
        bff_11,
        bff_12,
        bff_13,
        bff_14,
        bff_15,
        bff_16,
        bff_17,
        bff_18,
        bff_19,
        bff_20,
        bff_21,
        bff_22,
        bff_23,
        bff_24,
        bff_25,
        bff_26,
        bff_27,
        bff_28,
        bff_29,
        bff_30,
        bff_31,
        bff_32,
        bff_33,
        bff_34,
        bff_35,
        bff_36,
        bff_37,
        bff_38,
        bff_39,
        bff_40,
        bff_41,
        bff_42,
        bff_43,
        bff_44
    ) = make_fieldsBFF(Constants.questions_bff)
    """
    (
        ssvs_power,
        ssvs_achievement,
        ssvs_hedonism,
        ssvs_stimulation,
        ssvs_selfdirection,
        ssvs_universalism,
        ssvs_benevolence,
        ssvs_tradition,
        ssvs_conformity,
        ssvs_security,
    ) = make_fieldsSSVS(Constants.questions_svss)





                                          ('ssvs_power', 'POUVOIR (pouvoir social, autorité, richesse)'),
                                          ('',
                                           'ACCOMPLISSEMENT (succès, compétence, ambition, influence sur les gens et sur les événements)'),
                                          ('',
                                           'HÉDONISME (satisfaction des désirs, amour de la vie, se faire plaisir)'),
                                          ('',
                                           'STIMULATION (être audacieux, avoir une vie variée et stimulante, avoir une vie excitante)'),
                                          ('',
                                           'AUTONOMIE (créativité, liberté, curiosité, indépendance, choix de ses propres objectifs)'),
                                          ('',
                                           'UNIVERSALISME (ouverture d\'esprit, amour de la beauté de la nature et des arts, justice sociale, monde en paix, égalité, sagesse, unité avec la nature, protection de l\'environnement)'),
                                          ('',
                                           'BIENVEILLANCE (secourabilité, honnêteté, pardon, loyauté, responsabilité)'),
                                          ('',
                                           'TRADITION (respect de la tradition, humilité, acceptation des circonstances de la vie, dévotion, modération)'),
                                          ('',
                                           'CONFORMITÉ (obéissance, respect des parents et des aînés, autodiscipline, politesse)'),
                                          ('',
                                           'SÉCURITÉ (sécurité nationale, sécurité familiale, ordre social, propreté, réciprocité des services rendus)'),
                                      ],
                                      table_rows_equal_height=True,
                                      form_help_initial=''
                                      #  table_row_header_width_pct=5,                          # width of row header (first column) in percent. default: 253,
                )
            ]
        }
}
Player = create_player_model_for_survey('Psycog.models', SURVEY_DEFINITIONS)
"""