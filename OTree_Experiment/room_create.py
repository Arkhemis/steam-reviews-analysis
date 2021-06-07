import random
import string

rand_str = lambda n: ''.join([random.choice(string.ascii_lowercase) for i in range(n)])

with open("room.txt", "w", encoding="utf_8") as outfile:
    for i in range(1,1000):
        ra = rand_str(5)
        outfile.write(ra + "\n")
