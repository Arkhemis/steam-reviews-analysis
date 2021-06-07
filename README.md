# M2 Eco-Psycho Thesis
A repository containing all codes used in my M2 Thesis

## Table of contents
* [General info](#general-info)
* [Technologies](#technologies)
* [Setup](#setup)

## General info
This repository contains all repositories and codes used in my M2 Economy and Psychology Thesis project, in order to reproduce the results obtained.

### Requirements
- Python 3.7
- See requirements.txt for Python packages used.

# Extracting reviews from Steam
For both experiments, we used the similar dataset, which regroups all English reviews for every game that have been scraped from Steam as of December 2020. In order to collect the reviews, either run all scripts in https://github.com/Arkhemis/steam-crawler, as instructed in its corresponding readme.md, or download directly the needed dataset here:

# First experiment
### Pre-processing the data

Run the pre_processing.py script, that will clean the reviews (removing stop-words, remove non-English reviews, non-alphabetics characters) and filter some of them out of the dataset (too short reviews, review left by an user with less than 2 hours of playtime, etc...).

### LDA Topic Modelling
Run the check_ntopic_lda.py to evaluate the optimal number of topics through the number that would get the highest coherence score. Note this step is computational heavy, so it can takes a long time to complete, depending on the computational power of your computer. The optimal number of topic according to the used dataset, following Ockham's Law, should be of 14. 

<img src="https://user-images.githubusercontent.com/80684272/115784577-9a228780-a3be-11eb-85d1-58b3b23f654c.png" width=50% height=50%>


Now, run the LDA_Model.py, preferably in a Jupyter Notebook (as to visualize the topics). The notebook can also be found here: https://colab.research.google.com/drive/1WRr_zDeYL5mpQDIWZqp6CDerUjye3eZx?usp=sharing

### OTree Experiment
All codes used for my OTree experiment can be found in the corresponding directory.

# Second experiment
