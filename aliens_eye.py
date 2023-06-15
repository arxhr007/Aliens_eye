#! /usr/bin/python3
from requests import get,exceptions
from os import system
from argparse import ArgumentParser
import threading
import itertools
from json import dump,load
parser = ArgumentParser()
parser.add_argument("username",nargs='*',help='- pass the username , example:  $aliens_eye aaron123')
args = parser.parse_args()
r = "\033[31m"
g = "\033[32m"
y = "\033[33m"
b='\33[36m'
p = "\033[35m"
banner=f"""{y}
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
{g}insta:{r}@_arxhr007_
"""
with open("sites.json") as f:
 social=load(f)
spece=" "*20
save_json={}
def scanner(u,social):
 for i,j in social.items():
  try:
   req = get(j.format(u),timeout=10)
   code=req.status_code
  except (exceptions.ConnectionError,exceptions.Timeout,exceptions.TooManyRedirects): 
   continue
  print(f"{g}#"+f"{p}-"*124+f"{g}#")
  if code==200:
   user1="Found"
   user=f"{g}|{y}        Found        "
  elif code==404:
   user1="Not Found"
   user=f"{g}|{r}      Not Found      "
  else:
   user1="undefined status code"
   user=f"{g}|{b}      undefined      "
  j=j.format(u)
  save_json[i]={"code:":code,"user:":user1,"url:":j}
  media=f"{g}# {y}"+i[:15]+" "*(15-len(i[:15]))
  code=f"{g}|     {y}"+str(code)+" "*5
  url=f"{g}|{y} "+j+" "*(70-len(j))+f"{g}#"
  print(media+user+code+url)
def main(usernames):
 system("clear")
 print(banner)
 print(f"{r}NOTE:The data may not be completely accurate!\n")
 print(f"{r}NOTE: for educational purpose only!\n")
 if usernames == []:
  usernames=input(f"{y}Enter the username{r}:{g}").split()
  try:
   get("https://www.google.com/")
  except exceptions.ConnectionError:
   print(f"{r}!no internet, check connection")
   exit()
 for username in usernames:
    print(f"\n{y}Fetching details of {username}:\n")
    print(f"{g}#"*126)
    print(f"{g}# {r}SOCIAL MEDIA   {g}|        {r}USER {g}        | {r}STATUS CODE{g} | {r}                   URL   {g}      {spece}                   #")
    thread1 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 40))))
    thread2 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 40,80))))
    thread3 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 80,120))))
    thread4 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 120,160))))
    thread5 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 160,200))))
    thread6 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(),200,240))))
    thread7 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 240,280))))
    thread8 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 280,320))))
    thread9 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 320,360))))
    thread10 = threading.Thread(target=scanner,args=(username,dict(itertools.islice(social.items(), 360,435))))
    thread1.start()
    thread2.start()
    thread3.start()
    thread4.start()
    thread5.start()
    thread6.start()
    thread7.start()
    thread8.start()
    thread9.start()
    thread10.start()
    thread1.join()
    thread2.join()
    thread3.join()
    thread4.join()
    thread5.join()
    thread6.join()
    thread7.join()
    thread8.join()
    thread9.join()
    thread10.join()
    print("#"*126)
    with open(username+".json","w") as f:
        dump(save_json,f,indent=4)
    print(f"\n{y}Data has been saved in {username}.json")
 print(f"\n{r}vist {g}https://en.wikipedia.org/wiki/List_of_HTTP_status_codes{r} to know more about status codes!\n")
 print(f"{b}Thank you\n")
if __name__ == "__main__":
 main(args.username)
