import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
"User-Agent": "kent-court-tracker/1.0 (+https://github.com
)"
}

KENT_POLICE_BASE = "https://www.kent.police.uk
"
KENT_POLICE_SEARCH = KENT_POLICE_BASE + "/news/news-search/"

KEYWORDS = [
"homophobic",
"transphobic",
"biphobic",
"hate crime",
"sexual orientation",
"gender identity",
"LGBT",
"LGBTQ",
]

COURT_HINTS = [
"court",
"crown court",
"magistrates",
"jailed",
"sentenced",
"convicted",
"pleaded",
"charged",
]

def http_get(url: str) -> str:
r = requests.get(url, headers=HEADERS, timeout=30)
r.raise_for_status()
return r.text

def load_json(path: str, fallback):
try:
with open(path, "r", encoding="utf-8") as f:
return json.load(f)
except Exception:
return fallback

def save_json(path: str, data):
with open(path, "w", encoding="utf-8") as f:
json.dump(data, f, ensure_ascii=False, indent=2)

def extract_kent_police_links(query: str) -> list[str]:
url = KENT_POLICE_SEARCH + "?" + urlencode({"q": query})
html = http_get(url)
soup = BeautifulSoup(html, "html.parser")
