#! /usr/bin/python3
from requests import get,exceptions
from os import system
from argparse import ArgumentParser
from json import dump
parser = ArgumentParser()
parser.add_argument("username",type=str,nargs='?')
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
      
{g}by {y}BLINKING-IDIOT
{p}insta:{r}@_arxhr007_
"""
save_json={}
def scanner(u):
 social={
 "facebook":f"https://facebook.com/{u}",
 "youtube":f"https://youtube.com/{u}",
 "instagram":f"https://instagram.com/{u}",
 "vimeo":f"https://vimeo.com/{u}",
 "github":f"https://github.com/{u}",
 "plus":f"https://plus.google.com/{u}",
 "pinterest":f"https://pinterest.com/{u}",
 "flickr":f"https://flickr.com/people/{u}",
 "vk":f"https://vk.com/{u}",
 "about":f"https://about.me/{u}",
 "disqus":f"https://disqus.com/{u}",
 "bitbucket":f"https://bitbucket.org/{u}",
 "flipboard":f"https://flipboard.com/@{u}",
 "twitter":f"https://twitter.com/{u}",
 "medium":f"https://medium.com/@{u}",
 "hackerone":f"https://hackerone.com/{u}",
 "keybase":f"https://keybase.io/{u}"
 }
 print(f"\n{p}starting:\n")
 spece=" "*20
 print(f"{g}#"*126)
 print(f"{g}# {r}SOCIAL MEDIA   {g}|        {r}USER {g}        | {r}STATUS CODE{g} | {r}                   URL   {g}      {spece}                   #")
 for i,j in social.items():
  try:
   req = get(j)
   code=req.status_code
  except exceptions.TooManyRedirects:
   print("TooManyRedirects")
   break
  except exceptions.ConnectionError:
   print("\n\nConnectionError!\n\ncheck your internet connection!\n\n")
   break
  except exceptions.Timeout: 
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
   user=f"{g}|{b}undefined status code"
   j="none"
  save_json[i]={"code:":code,"user:":user1,"url:":j}
  media=f"{g}# {y}"+i+" "*(15-len(i))
  code=f"{g}|     {y}"+str(code)+" "*5
  url=f"{g}|{y} "+j+" "*(70-len(j))+f"{g}#"
  print(media+user+code+url)
 print("#"*126)
 with open(u+".json","w") as f:
  dump(save_json,f,indent=4)
 print(f"\n{r}vist {g}https://en.wikipedia.org/wiki/List_of_HTTP_status_codes{r} to know more about status codes!\n")
 print(f"{g}Data has been saved in {u}.json")
 print(f"{b}Thank you\n")
def main(username):
 system("clear")
 print(banner)
 print(f"{r}NOTE:The data may not be completely accurate!\n")
 print(f"{r}NOTE: for educational purpose only!\n")
 if username == None:
  u=input(f"{y}Enter the username{r}:{g}")
  scanner(u)
 else:
  scanner(username)
if __name__ == "__main__":
 main(args.username)