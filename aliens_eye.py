#! /usr/bin/python3
from requests import get,exceptions
from os import system
from argparse import ArgumentParser
from json import dump
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
def scanner(u):
 save_json={}
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
 "keybase":f"https://keybase.io/{u}",
 "buzzfeed":f"https://buzzfeed.com/{u}",
 "slideshare":f"https://slideshare.net/{u}",
 "mixcloud":f"https://mixcloud.com/{u}",
 "soundcloud":f"https://soundcloud.com/{u}",
 "badoo":f"https://badoo.com/en/{u}",
 "imgur":f"https://imgur.com/user/{u}",
 "spotify":f"https://open.spotify.com/user/{u}",
 "pastebin":f"https://pastebin.com/u/{u}",
 "wattpad":f"https://wattpad.com/user/{u}",
 "canva":f"https://canva.com/{u}",
 "codecademy":f"https://codecademy.com/{u}",
 "last":f"https://last.fm/user/{u}",
 "blip":f"https://blip.fm/{u}",
 "dribbble":f"https://dribbble.com/{u}",
 "gravatar":f"https://en.gravatar.com/{u}",
 "foursquare":f"https://foursquare.com/{u}",
 "creativemarket":f"https://creativemarket.com/{u}",
 "ello":f"https://ello.co/{u}",
 "cash":f"https://cash.me/{u}",
 "angel":f"https://angel.co/{u}",
 "wikipedia":f"https://www.wikipedia.org/wiki/User:{u}",
 "500px":f"https://500px.com/{u}",
 "houzz":f"https://houzz.com/user/{u}",
 "tripadvisor":f"https://tripadvisor.com/members/{u}",
 "kongregate":f"https://kongregate.com/accounts/{u}",
 "blogspot":f"https://{u}.blogspot.com/",
 "tumblr":f"https://{u}.tumblr.com/",
 "wordpress":f"https://{u}.wordpress.com/",
 "devianart":f"https://{u}.devianart.com/",
 "designspiration":f"https://www.designspiration.net/{u}",
 "slack":f"https://{u}.slack.com/",
 "livejournal":f"https://{u}.livejournal.com/",
 "newgrounds":f"https://{u}.newgrounds.com/",
 "hubpages":f"https://{u}.hubpages.com",
 "contently":f"https://{u}.contently.com",
 "steamcommunity":f"https://steamcommunity.com/id/{u}",
 "freelancer":f"https://www.freelancer.com/u/{u}",
 "dailymotion":f"https://www.dailymotion.com/{u}",
 "instructables":f"https://www.instructables.com/member/{u}",
 "etsy":f"https://www.etsy.com/shop/{u}",
 "scribd":f"https://www.scribd.com/{u}",
 "colourlovers":f"https://www.colourlovers.com/love/{u}",
 "patreon":f"https://www.patreon.com/{u}",
 "behance":f"https://www.behance.net/{u}",
 "goodreads":f"https://www.goodreads.com/{u}",
 "gumroad":f"https://www.gumroad.com/{u}",
 "codementor":f"https://www.codementor.io/{u}",
 "reverbnation":f"https://www.reverbnation.com/{u}",
 "bandcamp":f"https://www.bandcamp.com/{u}",
 "ifttt":f"https://www.ifttt.com/p/{u}",
 "trakt":f"https://www.trakt.tv/users/{u}",
 "okcupid":f"https://www.okcupid.com/profile/{u}",
 "trip":f"https://www.trip.skyscanner.com/user/{u}",
 "zone-h":f"http://www.zone-h.org/archive/notifier={u}"
 }
 print(f"\n{y}Fetching details of {u}:\n")
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
  with open(u+".json","w") as f:
   dump(save_json,f,indent=4)
 print("#"*126)
 print(f"\n{y}Data has been saved in {u}.json")
def main(usernames):
 system("clear")
 print(banner)
 print(f"{r}NOTE:The data may not be completely accurate!\n")
 print(f"{r}NOTE: for educational purpose only!\n")
 if usernames == []:
  usernames=input(f"{y}Enter the username{r}:{g}").split()
 for username in usernames:
    scanner(username)
 print(f"\n{r}vist {g}https://en.wikipedia.org/wiki/List_of_HTTP_status_codes{r} to know more about status codes!\n")
 print(f"{b}Thank you\n")
if __name__ == "__main__":
 main(args.username)
