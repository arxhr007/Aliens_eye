#!/usr/bin/env python3
import aiohttp
import asyncio
import os
import json
from argparse import ArgumentParser

r, g, y, b, p, w = "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[35m", "\033[37m"

parser = ArgumentParser()
parser.add_argument("username", nargs='*', help='Usernames to scan (e.g., $ python3 script.py user1 user2)')
parser.add_argument("-r", "--read", help='Path to JSON file to read and display', type=str)
args = parser.parse_args()

banner = f"""{y}
"{b}New asyncio        
  feature speeds up 
   the scan by 10x{y}"        "{b}Scans 570 websites{y}"
       {r}★   {w}\\{y}  _.-'~~~~'-._  {w} /{y}
   {b}☾{y}      .-~ {g}\\__/{p}  \\__/{y} ~-.         .
        .-~  {g} ({r}oo{g}) {p} ({r}oo{p})    {y}~-.
       (_____{g}
  _.-~`                         `~-._
 /{p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{y}\\     {w}✴
{y} \\___________________________________/
            \\x {w}x{y} x {w}x{y} x {w}x{y} x/    {b}✫{y}
    .  {w}*{y}     \\{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}/
                {r}INTERNET{g}
   ___   __   _________  ___  ____
  / _ | / /  /  _/ __/ |/ ( )/ __/
 / __ |/ /___/ // _//    /|/_\\ \\  
/_/ |_/____/___/___/_/|_/  /___/  
{b}
    ________  ________        {w}______
   {b}/ ____/\\ \\/ / ____/ {r} _   _{w}|__   /
  {b}/ __/    \\  / __/    {r}| | / /{w}/_ _< 
 {b}/ /___    / / /___    {r}| |/ /{w}__/  / 
{b}/_____/   /_/_____/    {r}|___/{w}/____/  

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

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

keywords = [
    "not found","doesn’t exist","didn't find","does not exist","something went wrong","no such user",
    "user not found","cannot find","can't find","not exist","profile not found","account does not exist",
    "username not found","no user found","no results found","no such username","isn't available","that content is unavailable"
]

safewords = ["follow","subscribe","like","share","following","followers"]

def reader(filej):
    if os.path.isfile(filej):
        with open(filej, 'r') as f:
            data = json.load(f)
        print(f"{g}#" * 80)
        print(f"{b}# {y}{'SITE':20}{b}| {y}{'STATUS':9}{b}| {y}{'HTTP CODE':9}{b}| {y}URL{w}")
        print(f"{g}#" * 80)
        for site, info in data.items():
            code = info.get("code")
            user = info.get("user")
            url = info.get("url")

            color_code = g + str(code) if code == 200 else r + str(code)

            color_status = g + user if user.lower() == 'found' else r + user

            color_url = g + url if user.lower() == 'found' else r + url
            print(f"{g}# {y}{site:20}{w}| {color_status:14}{w}| {color_code:^14}{w}| {color_url}{w}")
        print(f"{g}#" * 80)
    else:
        print(f"{r}File not found: {filej}{w}")

async def async_scanner(site_name, url_template, username, session):
    url = url_template.format(username)
    try:
        async with session.get(url, timeout=10) as resp:
            content = await resp.text()
            code = resp.status
    except Exception:
        content = ""
        code = 500

    content_lower = content.lower()

    if code == 200 and not any(k in content_lower for k in keywords):
        status_text = 'Found'
    else:
        status_text = 'Not Found'
    color_status = g + status_text if status_text == 'Found' else r + status_text

    color_code = g + str(code) if code == 200 else r + str(code)

    color_url = g + url if status_text == 'Found' else r + url

    save_json[site_name] = {"code": code, "user": status_text, "url": url}
    print(f"{g}# {y}{site_name:20}{w}| {color_status:14}{w}| {color_code:^14}{w}| {color_url}{w}")

async def check_internet():
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get("https://www.google.com/", timeout=5):
                return True
    except:
        return False

async def run_username(username):
    async with aiohttp.ClientSession(headers=headers) as session:
        tasks = [async_scanner(site, tmpl, username, session) for site, tmpl in social.items()]
        await asyncio.gather(*tasks)

def main():
    os.system("clear")
    print(banner)
    print(f"{r}NOTE: For educational purposes only!{w}\n")

    if args.read:
        reader(args.read)
        return

    usernames = args.username or input(f"{y}Enter username(s): {w}").split()

    if not asyncio.run(check_internet()):
        print(f"{r}! No internet connection{w}")
        return

    for username in usernames:
        global save_json
        save_json = {}
        print(f"\n{p}Scanning '{y}{username}{p}' across {len(social)} sites...{w}\n")
        print(f"{b}# {y}{'SITE':20}{b}| {y}{'STATUS':9}{b}| {y}{'HTTP CODE':9}{b}| {y}URL{w}")
        print(f"{g}#" * 80)

        asyncio.run(run_username(username))

        with open(f"{username}.json", 'w') as f:
            json.dump(save_json, f, indent=4)
        print(f"\n{g}Results saved to {y}{username}.json{w}\n")

if __name__ == "__main__":
    main()
