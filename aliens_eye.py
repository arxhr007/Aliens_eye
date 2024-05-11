#!/usr/bin/python3

import requests
import os
import threading
import itertools
import json
from argparse import ArgumentParser

r, g, y, b = "\033[31m", "\033[32m", "\033[33m", "\033[36m"

parser = ArgumentParser()
parser.add_argument("username", nargs='*', help='- pass the username, example: $aliens_eye aaron123')
args = parser.parse_args()

banner = f"""{y}
   ___   __   _________  ___  ____
  / _ | / /  /  _/ __/ |/ ( )/ __/
 / __ |/ /___/ // _//    /|/_\ \  
/_/ |_/____/___/___/_/|_/  /___/  
{r}
   ______  ______
  / __/\ \/ / __/                 
 / _/   \  / _/                   
/___/   /_/___/                   
      
{g}by {y}arxhr007
"""

try:
    with open("/usr/bin/sites.json") as f:
        social = json.load(f)
except FileNotFoundError:
    with open("/data/data/com.termux/files/usr/bin/sites.json") as f:
        social = json.load(f)

save_json = {}

def scanner(u, social):
    for i, j in social.items():
        try:
            req = requests.get(j.format(u), timeout=10)
            code = req.status_code
        except requests.exceptions.RequestException:
            continue
        print(f"{g}#" + f"{b}-" * 124 + f"{g}#")
        user1 = "Found" if code == 200 else "Not Found" if code == 404 else "Undefined Status Code"
        user = f"{g}|{y}{' ' * 20}{user1}{' ' * (20 - len(user1))}"
        save_json[i] = {"code": code, "user": user1, "url": j.format(u)}
        media = f"{g}# {y}{i[:15]}{' ' * (15 - len(i[:15]))}"
        code = f"{g}|     {y}{code}{' ' * (5 - len(str(code)))}"
        url = f"{g}|{y} {j.format(u)}{' ' * (70 - len(j.format(u)))}{g}#"
        print(media + user + code + url)

def main(usernames):
    os.system("clear")
    print(banner)
    print(f"{r}NOTE: The data may not be completely accurate!\n")
    print(f"{r}NOTE: For educational purpose only!\n")
    if not usernames:
        usernames = input(f"{y}Enter the username{r}:{g}").split()
        try:
            requests.get("https://www.google.com/")
        except requests.exceptions.RequestException:
            print(f"{r}! No internet, check connection")
            return
    for username in usernames:
        print(f"\n{y}Fetching details of {username}:\n")
        print(f"{g}#" * 126)
        print(f"{g}# {r}SOCIAL MEDIA   {g}|        {r}USER {g}        | {r}STATUS CODE{g} | {r}                   URL   {g}      {' ' * 20}#")
        threads = []
        for start, end in [(i, i + 40) for i in range(0, len(social), 40)]:
            thread = threading.Thread(target=scanner, args=(username, dict(itertools.islice(social.items(), start, end))))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        print("#" * 126)
        with open(username + ".json", "w") as f:
            json.dump(save_json, f, indent=4)
        print(f"\n{y}Data has been saved in {username}.json")
    print(f"\n{r}Visit {g}https://en.wikipedia.org/wiki/List_of_HTTP_status_codes{r} to know more about status codes!\n")
    print(f"{b}Thank you\n")

if __name__ == "__main__":
    main(args.username)
