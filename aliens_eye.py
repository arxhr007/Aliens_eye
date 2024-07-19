#!/usr/bin/python3

import requests
import os
import threading
import itertools
import json
from argparse import ArgumentParser
r, g, y, b, p, w = "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[35m", "\033[37m"
parser = ArgumentParser()
parser.add_argument("username", nargs='*', help='- pass the username, example: $aliens_eye aaron123')
parser.add_argument("-r", "--read", help="- pass the JSON file path to read", type=str)
args = parser.parse_args()
banner = f"""{y}
"{b}New Multithreading        
  feature speeds up 
   the scan by 10x{y}"        "{b}Scans 550+ websites{y}"
       {r}★   {w}\\{y}  _.-'~~~~'-._  {w} /{y}
   {b}☾{y}      .-~ {g}\\__/{p}  \\__/{y} ~-.         .
        .-~  {g} ({r}oo{g}) {p} ({r}oo{p})    {y}~-.
       (_____{g}//~~\\\\{p}//~~\\\\{y}______)       {p}☆{y}
  _.-~`                         `~-._
 /{p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{y}\\     {w}✴
{y} \\___________________________________/
            \\x {w}x{y} x {w}x{y} x {w}x{y} x/    {b}✫{y}
    .  {w}*{y}     \\{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}/
                {r}INTERNET{g}
   ___   __   _________  ___  ____
  / _ | / /  /  _/ __/ |/ ( )/ __/
 / __ |/ /___/ // _//    /|/_\\ \\  
/_/ |_/____/___/___/_/|_/  /___/  
{b}
   ______  ______  {r}_   __ {w} ___ 
  {b}/ __/\\ \\/ / __/{r} | | / /{w} |_  |
 {b}/ _/   \\  / _/  {r} | |/ / {w}/ __/ 
{b}/___/   /_/___/   {r}|___(_){w}____/ 
                               
      
{g}by {y}arxhr007
"""
try:
    with open("/usr/bin/sites.json") as f:
        social = json.load(f)
except FileNotFoundError:
    try:
        with open("/data/data/com.termux/files/usr/bin/sites.json") as f:
            social = json.load(f)
    except FileNotFoundError:
        with open("sites.json") as f:
            social = json.load(f)
save_json = {}
def scanner(u, social):
    keywords = [
        "not found","doesn’t exist","didn't find", "does not exist","something went wrong", "no such user", 
        "user not found", "cannot find", "can't find", "not exist", "profile not found",
        "cannot be found", "can't be found", "page not found",
        "account does not exist", "account doesn't exist", "username not found", 
        "username doesn't exist", "no user found", "user does not exist", 
        "user doesn't exist", "no results found", "no such username","isn't available"
    ]
    for i, j in social.items():
        try:
            req = requests.get(j.format(u), timeout=10)
            code = req.status_code
            content = req.text.lower()  
        except requests.exceptions.RequestException:
            code=500
        print(f"{g}#" + f"{b}-" * 98 + f"{g}#")
        if code == 200 and any(keyword in content for keyword in keywords):
            user1 = f"{r}Not Found"
        else:
            user1 = f"{g}Found    " if code == 200 else f"{r}Not Found"
        user2 = "Not Found" if "Not" in user1 else "Found"
        save_json[i] = {"code": code, "user": user2, "url": j.format(u)}
        media = f"{g}# {y}{i[:15]}{' ' * (15 - len(i[:15]))}"
        url = f"{g}|{y} {j.format(u)}{' ' * (70 - len(j.format(u)))}"
        user1 ="|  "+user1+" "
        print(media + user1  + url)
def reader(filej):
    if os.path.isfile(filej):
        with open(filej, 'r') as file:
            data = json.load(file)
        print(f"{g}#" * 126)

        print(f"{g}# {r}SOCIAL MEDIA   {g}|     {r}USER {g}     | {r}STATUS CODE{g} | {r}                   URL   {g}      {' ' * 20}")
        for i,j in data.items():
            print(f"{g}#" + f"{b}-" * 124 + f"{g}#")
            user = j["user"]
            code=j["code"]
            url=j["url"]
            media = f"{g}# {y}{i[:15]}{' ' * (15 - len(i[:15]))}"
            code = f"{g}|     {y}{code}{' ' * (8 - len(str(code)))}"
            url = f"{g}|{y} {url}{' ' * (70 - len(url))}"
            user1 ="|   "+user+" "*(12-len(user))
            print(media + user1 + code + url)
        print(f"{g}#" * 126)
        
    else:
        print(f"{r}The file {filej} does not exist.{w}")
        return
def main(usernames):
    os.system("clear")
    print(banner)
    print(f"{r}NOTE: The data may not be completely accurate!\n")
    print(f"{r}NOTE: For educational purpose only!\n")
    if args.read:
        reader(args.read)
        print(f"{b}Thank you\n")
        return
    if not usernames:
        usernames = input(f"{y}Enter the username{r}:{g}").split()
        try:
            requests.get("https://www.google.com/")
        except requests.exceptions.RequestException:
            print(f"{r}! No internet, check connection")
            return
    for username in usernames:
        print(f"\n{y}Fetching details of {username}:\n")
        print(f"{g}#" * 100)
        print(f"{g}# {r}SOCIAL MEDIA   {g}|    {r}USER {g}   | {r}                   URL   {g}      {' ' * 20}")
        threads = []
        for start, end in [(i, i + 57) for i in range(0, len(social), 57)]:
            thread = threading.Thread(target=scanner, args=(username, dict(itertools.islice(social.items(), start, end))))
            threads.append(thread)
            thread.start()
        for thread in threads:
            thread.join()
        print(f"{g}#" * 100)
        with open(username + ".json", "w") as f:
            json.dump(save_json, f, indent=4)
        print(f"\n{y}Data has been saved in {username}.json")
    print(f"\n{r}Visit {g}https://en.wikipedia.org/wiki/List_of_HTTP_status_codes{r} to know more about status codes!\n")
    print(f"{b}Thank you\n")
if __name__ == "__main__":
    main(args.username)
