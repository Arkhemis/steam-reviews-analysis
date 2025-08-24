[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![Code style: Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Coverage](https://codecov.io/gh/Arkhemis/steam-reviews-analysis/branch/main/graph/badge.svg)](https://codecov.io/gh/Arkhemis/steam-reviews-analysis)
[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightgrey.svg)](https://creativecommons.org/licenses/by/4.0/)


I'm in the process of rewriting the whole code from scratch, so the below documentation will probably be obsolete. Stay tuned for fresh results on [steam.reviews](http://steam.reviews/)!










-----------------------------------------
## General info
This repository contains all repositories and codes used in Personality and Video games project, in order to reproduce the results obtained.

### Requirements
- Python 3.7
- See requirements.txt for Python packages used.

# Extracting reviews from Steam
For both experiments, we used the similar dataset, which regroups all English reviews for every game that have been scraped from Steam as of December 2020. In order to collect the reviews, either run all scripts in https://github.com/Arkhemis/steam-crawler, as instructed in its corresponding readme.md, or download directly the needed dataset here:

# First step
### Pre-processing the data

Run the pre_processing.py script, that will clean the reviews (removing stop-words, non-English reviews, non-alphabetics characters) and filter some of them out of the dataset (too short reviews, review left by an user with less than 2 hours of playtime, etc...).

### LDA Topic Modelling
Run the check_ntopic_lda.py to evaluate the optimal number of topics through the number that would get the highest coherence score. Note this step is computational heavy, so it can takes a long time to complete, depending on the computational power of your computer. The optimal number of topic according to the used dataset, following Ockham's Law, should be of 14. 

<img src="https://user-images.githubusercontent.com/80684272/115784577-9a228780-a3be-11eb-85d1-58b3b23f654c.png" width=50% height=50%>


Now, run the LDA_Model.py, preferably in a Jupyter Notebook (as to visualize the topics). The notebook can also be found here: https://colab.research.google.com/drive/1WRr_zDeYL5mpQDIWZqp6CDerUjye3eZx?usp=sharing

<img src="https://user-images.githubusercontent.com/80684272/121043539-031a5f00-c7b5-11eb-9ad1-28ca798cdcc1.png" width=50% height=50%>

### OTree Experiment
All codes used for my OTree experiment can be found in the corresponding directory.

### Statistical analysis

All codes for the statistical analysis can be found in the corresponding directory. Note that the dataset is not included, for privacy reasons.
