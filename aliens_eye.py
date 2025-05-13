#!/usr/bin/python3
import aiohttp
import asyncio
import json
import sys
import time
import logging
from pathlib import Path
from argparse import ArgumentParser
from datetime import datetime
from typing import Dict, List, Any
import re
from urllib.parse import urlparse
COLORS = {
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[36m",
    "purple": "\033[35m",
    "white": "\033[37m",
    "reset": "\033[0m"
}
logger = logging.getLogger("username_scanner")
class AIUsernameScanner:
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/115.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept-Language": "en-US,en;q=0.5",
            "Connection": "keep-alive",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }
        self.error_keywords = [
            "not found", "doesn't exist", "didn't find", "does not exist", "something went wrong", "no such user",
            "user not found", "cannot find", "can't find", "not exist", "profile not found", "account does not exist",
            "username not found", "no user found", "no results found", "no such username", "isn't available", 
            "that content is unavailable", "page not found", "404", "error", "sorry", "oops", "unavailable",
            "account suspended", "invalid username", "account not found", "account terminated", "account disabled"
        ]
        self.positive_keywords = [
            "follow", "subscribe", "like", "share", "following", "followers", "profile", "user", "posts", 
            "photos", "bio", "status", "tweets", "joined", "member since", "online", "verified", "active",
            "comments", "uploads", "reviews", "friends", "connections", "activity", "timeline"
        ]
        self.meta_keywords = [
            "profile picture", "profile image", "avatar", "user page", "username", "user profile", 
            "account info", "account information", "user information"
        ]
        self.auth_patterns = [
            "/login", "/signin", "/register", "/join", "auth", "oauth", "authenticate", "account/login",
            "session/new", "user/login", "members/login"
        ]
        self.sites_data = self._load_sites_data()
        self.results_dir = Path("results")
        self.results_dir.mkdir(exist_ok=True)
        self.pattern_cache = {}
    def generate_username_variations(self, username: str, level: str) -> List[str]:
        """Generate username variations based on scan level."""
        variations = [username]  
        if level == "basic":
            return variations
        if level == "intermediate" or level == "advanced":
            variations.extend([
                f"{username}_",         
                f"_{username}",         
                f"{username}.",         
                f".{username}",         
                f"{username.replace(' ', '_')}", 
                f"{username.replace(' ', '.')}", 
                f"{username}1",         
                f"{username}123", 
                f"{username}007",       
                f"{username}098",
                f"{username}x",
                f"__{username}",       
                f"__{username}__",       
            ])
        if level == "advanced":
            prefixes = ["real", "official", "the", "its", "im", "actual", "true",
    "mr", "ms", "dr", "iam", "thisis", "hey", "yo", 
    "only", "itz", "iamthe", "theonly"
]
            suffixes = [    "official", "real", "account", "verified", "original", "tv", "here",
    "live", "online", "page", "world", "spot", "media",
    "inc", "group", "team", "zone", "plus", "today"]
            for prefix in prefixes:
                variations.append(f"{prefix}{username}")
                variations.append(f"{prefix}_{username}")
                variations.append(f"{prefix}.{username}")
            for suffix in suffixes:
                variations.append(f"{username}{suffix}")
                variations.append(f"{username}_{suffix}")
                variations.append(f"{username}.{suffix}")
        return list(dict.fromkeys(variations))
    def _load_sites_data(self) -> Dict[str, str]:
        """Load sites data from JSON file with fallback paths."""
        possible_paths = [
            Path("/usr/local/bin/sites.json"),
            Path("/data/data/com.termux/files/usr/bin/sites.json"),
            Path("sites.json")
        ]
        for path in possible_paths:
            try:
                with open(path) as f:
                    logger.info(f"Loaded sites data from {path}")
                    return json.load(f)
            except FileNotFoundError:
                continue
        logger.error("Could not find sites.json file. Make sure it exists in one of the expected locations.")
        return {}
    def display_banner(self):
        """Display the ASCII art banner with colors."""
        r, g, y, b, p, w = COLORS["red"], COLORS["green"], COLORS["yellow"], COLORS["blue"], COLORS["purple"], COLORS["white"]
        banner = f"""{y}
"{b}New AI detection   
  feature improves
   accuracy by 40%{y}"        "{b}Scans {len(self.sites_data)} websites{y}"
       {r}★   {w}\\{y}  _.-'~~~~'-._  {w} /{y}
   {b}☾{y}      .-~ {g}\\__/{p}  \\__/{y} ~-.         .
        .-~  {g} ({r}oo{g}) {p} ({r}oo{p})    {y}~-.
       (_____{g}//~~\\\\{p}//~~\\\\{y}______)       {p}☆{y}
  _.-~`                         `~-._
 /{p}O{b}={g}O{r}={y}O{w}={p}O{b}={g}O{r}={y}O{w}={g}O{r}={y}={g}O{r}={y}O{w}O{w}={p}O{b}={g}O{r}={g}O{r}={y}O{w}={y}O{w}={p}O{b}={g}O{r}={y}O{y}\\     {w}✴
{y} \\___________________________________/
            \\x {w}x{y} x {w}x{y} x {w}x{y} x/    {b}✫{y}
    .  {w}*{y}     \\{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}_{w}x{y}/
              {r}AI-POWERED{g}
   ___   __   _________  ___  ____
  / _ | / /  /  _/ __/ |/ ( )/ __/
 / __ |/ /___/ // _//    /|/_\\ \\  
/_/ |_/____/___/___/_/|_/  /___/  
{b}
    ________  ________        
   {b}/ ____/\\ \\/ / ____/ {r} _    __{w}__ __
  {b}/ __/    \\  / __/   {r} | |  / /{w} // /
 {b}/ /___    / / /___    {r}| | / / {w}// /
{b}/_____/   /_/_____/  {r}  | |/ /{w}__  __/
                      {r} |___/ {w} /_/  

{g}by {y}arxhr007 {COLORS["reset"]}
"""
        print(banner)
        print(f"{COLORS['red']}NOTE: For educational purposes only!{COLORS['reset']}\n")
    async def check_internet(self) -> bool:
        """Check if internet connection is available."""
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get("https://www.google.com/", timeout=5) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Internet connection check failed: {e}")
            return False
    def extract_meta_tags(self, content: str) -> List[str]:
        """Extract metadata from HTML content."""
        meta_tags = []
        meta_pattern = re.compile(r'<meta[^>]*content=["\'](.*?)["\'][^>]*>', re.IGNORECASE)
        for match in meta_pattern.finditer(content):
            meta_tags.append(match.group(1))
        title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE)
        if title_match:
            meta_tags.append(title_match.group(1))
        og_title = re.search(r'<meta[^>]*property=["\'](og:title)["\'][^>]*content=["\'](.*?)["\']', content, re.IGNORECASE)
        if og_title:
            meta_tags.append(og_title.group(2))
        og_desc = re.search(r'<meta[^>]*property=["\'](og:description)["\'][^>]*content=["\'](.*?)["\']', content, re.IGNORECASE)
        if og_desc:
            meta_tags.append(og_desc.group(2))
        return meta_tags
    def extract_dom_structure(self, content: str) -> Dict[str, int]:
        """Extract basic DOM structure information."""
        dom_info = {}
        dom_info['img_count'] = len(re.findall(r'<img[^>]*>', content, re.IGNORECASE))
        dom_info['input_count'] = len(re.findall(r'<input[^>]*>', content, re.IGNORECASE))
        dom_info['form_count'] = len(re.findall(r'<form[^>]*>', content, re.IGNORECASE))
        dom_info['profile_section_count'] = len(re.findall(r'class=["\'](.*?profile.*?)["\']', content, re.IGNORECASE))
        dom_info['error_section_count'] = len(re.findall(r'class=["\'](.*?error.*?|.*?not-found.*?)["\']', content, re.IGNORECASE))
        return dom_info
    def analyze_url_structure(self, url: str, username: str) -> Dict[str, Any]:
        """Analyze URL structure for redirects and auth patterns."""
        parsed_url = urlparse(url)
        result = {
            'domain': parsed_url.netloc,
            'path': parsed_url.path,
            'has_username_in_path': username.lower() in parsed_url.path.lower(),
            'has_auth_pattern': any(auth in parsed_url.path.lower() for auth in self.auth_patterns),
            'is_homepage': parsed_url.path in ('', '/')
        }
        return result
    async def detect_with_ai(self, content: str, url: str, username: str, site_name: str, 
                              http_code: int, response_time: float) -> Dict[str, Any]:
        """
        Use AI techniques to determine if a profile exists based on multiple factors:
        1. Content analysis (keyword matching with weighted scoring)
        2. HTTP status code
        3. URL structure analysis
        4. DOM structure analysis
        5. Metadata analysis
        6. Historical pattern recognition from previous scans
        """
        content_lower = content.lower()
        url_lower = url.lower()
        score = 0
        confidence = 0
        error_matches = sum(keyword in content_lower for keyword in self.error_keywords)
        positive_matches = sum(keyword in content_lower for keyword in self.positive_keywords)
        score -= error_matches * 2
        score += positive_matches * 1.5
        if http_code == 200:
            score += 5
        elif http_code == 404:
            score -= 10
        elif http_code >= 500:
            score -= 3  
        elif http_code >= 300 and http_code < 400:
            url_analysis = self.analyze_url_structure(url, username)
            if url_analysis['has_auth_pattern']:
                score -= 3  
            elif url_analysis['has_username_in_path']:
                score += 2  
        url_analysis = self.analyze_url_structure(url, username)
        if url_analysis['has_username_in_path'] and not url_analysis['is_homepage']:
            score += 3
        if url_analysis['is_homepage'] and http_code == 200:
            score -= 5  
        dom_info = self.extract_dom_structure(content)
        if dom_info['error_section_count'] > 0:
            score -= 3 * dom_info['error_section_count']
        if dom_info['profile_section_count'] > 0:
            score += 4 * dom_info['profile_section_count']
        if dom_info['img_count'] > 5:
            score += 2
        if dom_info['form_count'] > 0 and dom_info['input_count'] > 2:
            score -= 2
        meta_tags = self.extract_meta_tags(content)
        meta_content = ' '.join(meta_tags).lower()
        if username.lower() in meta_content:
            score += 5
        meta_error_matches = sum(keyword in meta_content for keyword in self.error_keywords)
        if meta_error_matches > 0:
            score -= 3 * meta_error_matches
        meta_positive_matches = sum(keyword in meta_content for keyword in self.positive_keywords + self.meta_keywords)
        if meta_positive_matches > 0:
            score += 2 * meta_positive_matches
        if site_name in self.pattern_cache:
            site_patterns = self.pattern_cache[site_name]
            for pattern, weight in site_patterns.items():
                if re.search(pattern, content_lower):
                    score += weight
        if response_time < 0.5 and http_code == 404:
            score -= 2
        abs_score = abs(score)
        if abs_score > 15:
            confidence = 95
        elif abs_score > 10:
            confidence = 85
        elif abs_score > 5:
            confidence = 70
        else:
            confidence = 50
        if score > 3:
            status = "Found"
        elif score < -3:
            status = "Not Found"
        else:
            status = "Maybe"
        if status in ["Found", "Not Found"]:
            self._update_pattern_cache(site_name, content_lower, status)
        return {
            "status": status,
            "confidence": confidence,
            "score": score,
            "analysis": {
                "error_keywords": error_matches,
                "positive_keywords": positive_matches,
                "dom_analysis": dom_info,
                "url_analysis": url_analysis,
                "http_code": http_code,
                "response_time": response_time
            }
        }
    def _update_pattern_cache(self, site_name: str, content: str, status: str):
        """Update the pattern cache with new learned patterns."""
        if site_name not in self.pattern_cache:
            self.pattern_cache[site_name] = {}
        if status == "Found":
            profile_patterns = [
                r'<div[^>]*class=["\'](.*?profile.*?|.*?user.*?|.*?account.*?)["\'][^>]*>',
                r'<h1[^>]*>(.*?)</h1>',
                r'<img[^>]*alt=["\'](.*?profile.*?|.*?avatar.*?|.*?user.*?)["\'][^>]*>'
            ]
            for pattern in profile_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:
                    pattern_key = f"profile_pattern_{len(self.pattern_cache[site_name])}"
                    self.pattern_cache[site_name][pattern_key] = 3  
        elif status == "Not Found":
            error_patterns = [
                r'<div[^>]*class=["\'](.*?error.*?|.*?not-found.*?|.*?missing.*?)["\'][^>]*>',
                r'<h1[^>]*>(.*?not found.*?|.*?doesn\'t exist.*?|.*?error.*?)</h1>'
            ]
            for pattern in error_patterns:
                matches = re.findall(pattern, content, re.IGNORECASE)
                if matches:

                    pattern_key = f"error_pattern_{len(self.pattern_cache[site_name])}"
                    self.pattern_cache[site_name][pattern_key] = -3  
    async def scan_username(self, site_name: str, url_template: str, username: str, 
                           session: aiohttp.ClientSession, semaphore: asyncio.Semaphore) -> Dict[str, Any]:
        """Scan a single site for the given username."""
        try:
            url = url_template.format(username)
        except (KeyError, IndexError):
            url = url_template.replace("{}", username)
            if "{" in url:  
                url = f"https://{site_name}.com/{username}"
        except Exception as e:
            logger.debug(f"URL formatting error for {site_name}: {e}")
            url = f"https://{site_name}.com/{username}"
        status_text = "Unknown"
        code = 0
        response_time = 0
        content = ""
        ai_analysis = {}
        async with semaphore:  
            start_time = time.time()
            try:
                async with session.get(url, timeout=10, allow_redirects=True) as response:
                    content = await response.text()
                    code = response.status
                    response_time = time.time() - start_time
                    ai_analysis = await self.detect_with_ai(content, str(response.url), username, 
                                                           site_name, code, response_time)
                    status_text = ai_analysis["status"]
            except asyncio.TimeoutError:
                status_text = "Timeout"
                code = 408
                response_time = time.time() - start_time
            except Exception as e:
                status_text = f"Error"
                code = 500
                response_time = time.time() - start_time
                logger.debug(f"Error scanning {site_name}: {str(e)}")
        if status_text == "Found":
            status_color = COLORS["green"]
        elif status_text == "Maybe":
            status_color = COLORS["yellow"]
        else:
            status_color = COLORS["red"]
        code_color = COLORS["green"] if code == 200 else COLORS["red"]
        url_color = status_color
        display_site = site_name[:20]
        confidence = ai_analysis.get("confidence", 0) if ai_analysis else 0
        confidence_str = f" ({confidence}%)" if confidence > 0 else ""
        print(f"{COLORS['green']}# {COLORS['yellow']}{display_site:20}{COLORS['white']}| "
              f"{status_color}{status_text:10}{confidence_str:8}{COLORS['white']}| "
              f"{code_color}{str(code):^10}{COLORS['white']}| "
              f"{url_color}{url}{COLORS['reset']} "
              f"({response_time:.2f}s)")
        return {
            "site": site_name,
            "url": url,
            "status": status_text,
            "code": code,
            "response_time": round(response_time, 2),
            "confidence": confidence,
            "ai_analysis": ai_analysis
        }
    async def scan_all_sites(self, username: str) -> List[Dict[str, Any]]:
        """Scan all sites for the given username."""
        results = []
        conn_limit = min(50, len(self.sites_data))  
        semaphore = asyncio.Semaphore(conn_limit)
        print(f"\n{COLORS['purple']}Scanning '{COLORS['yellow']}{username}{COLORS['purple']}' across "
              f"{len(self.sites_data)} sites (max {conn_limit} concurrent connections)...{COLORS['reset']}\n")
        self._print_table_header()
        start_time = time.time()
        async with aiohttp.ClientSession(headers=self.headers) as session:
            tasks = [
                self.scan_username(site, tmpl, username, session, semaphore) 
                for site, tmpl in self.sites_data.items()
            ]
            results = await asyncio.gather(*tasks)
        total_time = time.time() - start_time
        found_count = sum(1 for r in results if r["status"] == "Found")
        maybe_count = sum(1 for r in results if r["status"] == "Maybe")
        not_found_count = sum(1 for r in results if r["status"] == "Not Found")
        error_count = sum(1 for r in results if r["status"] not in ["Found", "Not Found", "Maybe"])
        high_confidence = [r for r in results if r.get("confidence", 0) >= 85 and r["status"] == "Found"]
        print(f"\n{COLORS['green']}Scan completed in {total_time:.2f} seconds")
        print(f"{COLORS['green']}Found: {found_count} | {COLORS['yellow']}Maybe: {maybe_count} | "
              f"{COLORS['red']}Not Found: {not_found_count} | Errors: {error_count}{COLORS['reset']}")
        if high_confidence:
            print(f"\n{COLORS['green']}High confidence matches ({len(high_confidence)}):{COLORS['reset']}")
            for result in high_confidence[:5]:  
                print(f"{COLORS['yellow']}{result['site']}: {COLORS['green']}{result['url']}{COLORS['reset']} ({result['confidence']}% confidence)")
            if len(high_confidence) > 5:
                print(f"{COLORS['yellow']}... and {len(high_confidence) - 5} more{COLORS['reset']}")
        return results
    async def scan_with_variations(self, base_username: str, level: str = "basic") -> Dict[str, List[Dict[str, Any]]]:
        """Scan all variations of a username based on the specified level."""
        variations = self.generate_username_variations(base_username, level)
        all_results = {}
        print(f"\n{COLORS['blue']}Scan level: {COLORS['yellow']}{level.upper()}")
        print(f"{COLORS['blue']}Generated {len(variations)} username variations to scan")
        if len(variations) > 1:
            print(f"{COLORS['yellow']}Variations: {', '.join(variations[:5])}" + 
                (f" and {len(variations)-5} more..." if len(variations) > 5 else ""))
        for username in variations:
            print(f"\n{COLORS['purple']}Scanning variation: {COLORS['yellow']}{username}{COLORS['reset']}")
            results = await self.scan_all_sites(username)
            all_results[username] = results
        return all_results
    def _print_table_header(self):
        """Print the table header for scan results."""
        print(f"{COLORS['blue']}# {COLORS['yellow']}{'SITE':20}{COLORS['blue']}| "
              f"{COLORS['yellow']}{'STATUS + CONFIDENCE':18}{COLORS['blue']}| "
              f"{COLORS['yellow']}{'HTTP CODE':10}{COLORS['blue']}| "
              f"{COLORS['yellow']}URL (RESPONSE TIME){COLORS['reset']}")
        print(f"{COLORS['green']}{'#' * 90}{COLORS['reset']}")
    def save_results_with_variations(self, base_username: str, all_results: Dict[str, List[Dict[str, Any]]], 
                                level: str) -> str:
        """Save scan results for all username variations to a JSON file."""
        variations_data = {}
        scan_summary = {
            "base_username": base_username,
            "scan_level": level,
            "timestamp": datetime.now().isoformat(),
            "total_variations": len(all_results),
            "total_sites_scanned": sum(len(results) for results in all_results.values()),
        }
        found_counts = {}
        high_confidence_matches = {}
        for username, results in all_results.items():
            found_counts[username] = sum(1 for r in results if r["status"] == "Found")
            high_confidence_matches[username] = sum(1 for r in results if r.get("confidence", 0) >= 85 and r["status"] == "Found")
            variations_data[username] = {
                "scan_info": {
                    "username": username,
                    "sites_scanned": len(results),
                    "found": found_counts[username],
                    "maybe": sum(1 for r in results if r["status"] == "Maybe"),
                    "not_found": sum(1 for r in results if r["status"] == "Not Found"),
                    "errors": sum(1 for r in results if r["status"] not in ["Found", "Not Found", "Maybe"]),
                    "high_confidence_matches": high_confidence_matches[username]
                },
                "sites": {r["site"]: {
                    "status": r["status"],
                    "code": r["code"], 
                    "url": r["url"],
                    "response_time": r["response_time"],
                    "confidence": r.get("confidence", 0),
                    "ai_analysis": r.get("ai_analysis", {})
                } for r in results}
            }
        scan_summary["total_found"] = sum(found_counts.values())
        scan_summary["total_high_confidence"] = sum(high_confidence_matches.values())
        scan_summary["best_variations"] = sorted(found_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        results_data = {
            "scan_summary": scan_summary,
            "variations": variations_data
        }
        filename = self.results_dir / f"{base_username}_{level}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            json.dump(results_data, f, indent=4)
        return str(filename)
    def display_results_from_file(self, file_path: str) -> None:
        """Display saved results from a JSON file."""
        try:
            with open(file_path, 'r') as f:
                data = json.load(f)
            if "scan_summary" in data and "variations" in data:
                summary = data["scan_summary"]
                print(f"{COLORS['green']}{'=' * 90}")
                print(f"{COLORS['blue']}SCAN RESULTS SUMMARY: {COLORS['yellow']}{summary.get('base_username', 'Unknown')}")
                print(f"{COLORS['blue']}Scan level: {COLORS['white']}{summary.get('scan_level', 'Unknown')}")
                print(f"{COLORS['blue']}Date: {COLORS['white']}{summary.get('timestamp', 'Unknown')}")
                print(f"{COLORS['blue']}Total Variations: {COLORS['white']}{summary.get('total_variations', 0)}")
                print(f"{COLORS['blue']}Total Sites Scanned: {COLORS['white']}{summary.get('total_sites_scanned', 0)}")
                print(f"{COLORS['blue']}Total Found: {COLORS['green']}{summary.get('total_found', 0)}")
                print(f"{COLORS['blue']}Total High Confidence: {COLORS['green']}{summary.get('total_high_confidence', 0)}")
                print(f"{COLORS['green']}{'=' * 90}")
                print(f"{COLORS['blue']}Best Variations:")
                for username, count in summary.get('best_variations', []):
                    print(f"{COLORS['yellow']}{username}: {COLORS['green']}{count} profiles found")
                print(f"{COLORS['green']}{'=' * 90}")
                print(f"{COLORS['blue']}Available variations:")
                for i, username in enumerate(data["variations"].keys(), 1):
                    print(f"{COLORS['white']}{i}. {COLORS['yellow']}{username}")
                choice = input(f"\n{COLORS['green']}Enter number to see details (or 'all' for all, or press Enter to exit): {COLORS['yellow']}")
                if choice.lower() == 'all':
                    for username, variation_data in data["variations"].items():
                        self._display_variation_results(username, variation_data)
                elif choice.isdigit():
                    choice_idx = int(choice) - 1
                    if 0 <= choice_idx < len(data["variations"]):
                        username = list(data["variations"].keys())[choice_idx]
                        self._display_variation_results(username, data["variations"][username])
            else:
                scan_info = data.get("scan_info", {})
                print(f"{COLORS['green']}{'=' * 90}")
                print(f"{COLORS['blue']}SCAN RESULTS: {COLORS['yellow']}{scan_info.get('username', 'Unknown')}")
                print(f"{COLORS['blue']}Date: {COLORS['white']}{scan_info.get('timestamp', 'Unknown')}")
                print(f"{COLORS['blue']}Sites Scanned: {COLORS['white']}{scan_info.get('sites_scanned', 0)}")
                print(f"{COLORS['blue']}Found: {COLORS['green']}{scan_info.get('found', 0)} | "
                    f"{COLORS['blue']}Maybe: {COLORS['yellow']}{scan_info.get('maybe', 0)} | "
                    f"{COLORS['blue']}Not Found: {COLORS['red']}{scan_info.get('not_found', 0)} | "
                    f"{COLORS['blue']}Errors: {COLORS['red']}{scan_info.get('errors', 0)}")
                high_conf = scan_info.get('high_confidence_matches', 0)
                if high_conf > 0:
                    print(f"{COLORS['blue']}High Confidence Matches: {COLORS['green']}{high_conf}")
                print(f"{COLORS['green']}{'=' * 90}")
                self._print_table_header()
                def sort_key(item):
                    status_priority = {"Found": 0, "Maybe": 1, "Not Found": 2}.get(item[1].get("status", ""), 3)
                    confidence = item[1].get("confidence", 0)
                    return (-confidence, status_priority)
                sorted_sites = sorted(data.get("sites", {}).items(), key=sort_key)
                for site_name, info in sorted_sites:
                    status = info.get("status", "Unknown")
                    code = info.get("code", 0)
                    url = info.get("url", "")
                    response_time = info.get("response_time", 0)
                    confidence = info.get("confidence", 0)
                    if status == "Found":
                        status_color = COLORS["green"]
                    elif status == "Maybe":
                        status_color = COLORS["yellow"]
                    else:
                        status_color = COLORS["red"]
                    code_color = COLORS["green"] if code == 200 else COLORS["red"]
                    url_color = status_color
                    display_site = site_name[:20]
                    confidence_str = f" ({confidence}%)" if confidence > 0 else ""
                    print(f"{COLORS['green']}# {COLORS['yellow']}{display_site:20}{COLORS['white']}| "
                        f"{status_color}{status:10}{confidence_str:8}{COLORS['white']}| "
                        f"{code_color}{str(code):^10}{COLORS['white']}| "
                        f"{url_color}{url}{COLORS['reset']} "
                        f"({response_time:.2f}s)")
                print(f"{COLORS['green']}{'=' * 90}{COLORS['reset']}")
        except FileNotFoundError:
            print(f"{COLORS['red']}File not found: {file_path}{COLORS['reset']}")
        except json.JSONDecodeError:
            print(f"{COLORS['red']}Invalid JSON file: {file_path}{COLORS['reset']}")
        except Exception as e:
            print(f"{COLORS['red']}Error reading file: {e}{COLORS['reset']}")
    def _display_variation_results(self, username, variation_data):
        """Display results for a specific username variation."""
        scan_info = variation_data.get("scan_info", {})
        print(f"{COLORS['green']}{'=' * 90}")
        print(f"{COLORS['blue']}SCAN RESULTS FOR VARIATION: {COLORS['yellow']}{username}")
        print(f"{COLORS['blue']}Found: {COLORS['green']}{scan_info.get('found', 0)} | "
            f"{COLORS['blue']}Maybe: {COLORS['yellow']}{scan_info.get('maybe', 0)} | "
            f"{COLORS['blue']}Not Found: {COLORS['red']}{scan_info.get('not_found', 0)} | "
            f"{COLORS['blue']}Errors: {COLORS['red']}{scan_info.get('errors', 0)}")
        high_conf = scan_info.get('high_confidence_matches', 0)
        if high_conf > 0:
            print(f"{COLORS['blue']}High Confidence Matches: {COLORS['green']}{high_conf}")
        print(f"{COLORS['green']}{'=' * 90}")
        self._print_table_header()
        def sort_key(item):
            site_info = item[1]
            status_priority = {"Found": 0, "Maybe": 1, "Not Found": 2}.get(site_info.get("status", ""), 3)
            confidence = site_info.get("confidence", 0)
            return (-confidence, status_priority)
        sites = variation_data.get("sites", {})
        sorted_sites = sorted(sites.items(), key=sort_key)
        for site_name, info in sorted_sites:
            status = info.get("status", "Unknown")
            code = info.get("code", 0)
            url = info.get("url", "")
            response_time = info.get("response_time", 0)
            confidence = info.get("confidence", 0)
            if status == "Found":
                status_color = COLORS["green"]
            elif status == "Maybe":
                status_color = COLORS["yellow"]
            else:
                status_color = COLORS["red"]
            code_color = COLORS["green"] if code == 200 else COLORS["red"]
            url_color = status_color
            display_site = site_name[:20]
            confidence_str = f" ({confidence}%)" if confidence > 0 else ""
            print(f"{COLORS['green']}# {COLORS['yellow']}{display_site:20}{COLORS['white']}| "
                f"{status_color}{status:10}{confidence_str:8}{COLORS['white']}| "
                f"{code_color}{str(code):^10}{COLORS['white']}| "
                f"{url_color}{url}{COLORS['reset']} "
                f"({response_time:.2f}s)")
        print(f"{COLORS['green']}{'=' * 90}{COLORS['reset']}")
    def display_variations_summary(self, all_results: Dict[str, List[Dict[str, Any]]]) -> None:
        """Display a summary of results for all username variations."""
        print(f"\n{COLORS['green']}{'=' * 90}")
        print(f"{COLORS['blue']}SUMMARY OF VARIATIONS:")

        sorted_variations = sorted(
            all_results.items(),
            key=lambda x: sum(1 for r in x[1] if r["status"] == "Found"),
            reverse=True
        )
        for username, results in sorted_variations:
            found_count = sum(1 for r in results if r["status"] == "Found")
            maybe_count = sum(1 for r in results if r["status"] == "Maybe")
            high_confidence = sum(1 for r in results if r.get("confidence", 0) >= 85 and r["status"] == "Found")
            if found_count > 0:
                status_color = COLORS["green"]
            elif maybe_count > 0:
                status_color = COLORS["yellow"]
            else:
                status_color = COLORS["red"]
            print(f"{status_color}{username:20}{COLORS['white']}| "
                f"{COLORS['green']}Found: {found_count:3}{COLORS['white']} | "
                f"{COLORS['yellow']}Maybe: {maybe_count:3}{COLORS['white']} | "
                f"{COLORS['blue']}High Conf: {high_confidence:3}")
        print(f"{COLORS['green']}{'=' * 90}{COLORS['reset']}")
async def main():
    parser = ArgumentParser(description="AI-Enhanced Username Scanner - Find usernames across social media platforms")
    parser.add_argument("username", nargs='*', help='Usernames to scan (e.g., $ python3 script.py user1 user2)')
    parser.add_argument("-r", "--read", help='Path to JSON file to read and display', type=str)
    parser.add_argument("-c", "--concurrent", help='Maximum number of concurrent connections (default: auto)', type=int)
    parser.add_argument("-v", "--verbose", help='Enable verbose output', action='store_true')
    parser.add_argument("-l", "--level", help='Scan level (basic, intermediate, advanced)', choices=['basic', 'intermediate', 'advanced'])
    args = parser.parse_args()
    scanner = AIUsernameScanner()
    scanner.display_banner()
    if args.read:
        scanner.display_results_from_file(args.read)
        return
    internet_available = await scanner.check_internet()
    if not internet_available:
        logger.error("No internet connection available. Please check your connection and try again.")
        return
    if args.username:
        username = args.username[0]
    else:
        username = input(f"{COLORS['green']}Enter username to scan: {COLORS['yellow']}")
    if not username or len(username) < 2:
        logger.error("Invalid username. Please provide a valid username.")
        return
    if not args.level:
        print(f"\n{COLORS['green']}Select scan level:")
        print(f"{COLORS['white']}1. {COLORS['blue']}Basic{COLORS['white']} - Just the username as entered")
        print(f"{COLORS['white']}2. {COLORS['yellow']}Intermediate{COLORS['white']} - Adds variations with underscores, dots, etc.")
        print(f"{COLORS['white']}3. {COLORS['red']}Advanced{COLORS['white']} - Adds common prefixes/suffixes like 'real', 'official', etc.")
        level_choice = input(f"\n{COLORS['green']}Enter choice (1-3): {COLORS['yellow']}")
        level_map = {"1": "basic", "2": "intermediate", "3": "advanced"}
        scan_level = level_map.get(level_choice, "basic")
    else:
        scan_level = args.level
    if args.verbose:
        logger.setLevel(logging.DEBUG)
    all_results = await scanner.scan_with_variations(username, scan_level)
    result_file = scanner.save_results_with_variations(username, all_results, scan_level)
    print(f"\n{COLORS['green']}Results saved to: {COLORS['blue']}{result_file}{COLORS['reset']}")
    total_found = sum(sum(1 for r in results if r["status"] == "Found") for results in all_results.values())
    print(f"\n{COLORS['green']}Summary: Found {total_found} profiles across {len(all_results)} username variations")
    if args.username and len(args.username) > 1:
        for next_username in args.username[1:]:
            print(f"\n{COLORS['green']}Continue with next username: {COLORS['yellow']}{next_username}{COLORS['reset']}")
            all_results = await scanner.scan_with_variations(next_username, scan_level)
            result_file = scanner.save_results_with_variations(next_username, all_results, scan_level)
            print(f"\n{COLORS['green']}Results saved to: {COLORS['blue']}{result_file}{COLORS['reset']}")
    print(f"\n{COLORS['green']}Thank you for using AI-Enhanced OSINT Username Scanner!{COLORS['reset']}")
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n\n{COLORS['red']}Scan interrupted by user.{COLORS['reset']}")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)
