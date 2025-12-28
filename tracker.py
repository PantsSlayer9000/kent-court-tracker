START tracker.py
import json
import re
from datetime import datetime
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
"User-Agent": "kent-court-tracker/1.1"
}

KENT_POLICE_BASE = "https://www.kent.police.uk
"
KENT_POLICE_SEARCH = KENT_POLICE_BASE + "/news/news-search/"

SEARCH_TERMS = [
"homophobic",
"transphobic",
"biphobic",
"sexual orientation",
"gender identity",
"lgbt",
"lgbtq",
"hate crime",
]

LGBT_CORE_TERMS = [
"homophobic", "homophobia",
"transphobic", "transphobia",
"biphobic", "biphobia",
"sexual orientation",
"gender identity",
"lgbt", "lgbtq", "lgbtqia",
"gay", "lesbian", "bisexual",
"trans", "transgender",
"non-binary", "non binary", "nonbinary",
]

HATE_TERMS = [
"hate crime",
"hate-crime",
"hatecrime",
]

COURT_HINTS = [
"court",
"crown court",
"magistrates",
"jailed",
"sentenced",
"convicted",
"pleaded guilty",
"pleaded",
"charged",
"appeared",
"remanded",
"trial",
"hearing",
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

def save_json(path: str, data) -> None:
with open(path, "w", encoding="utf-8") as f:
json.dump(data, f, ensure_ascii=False, indent=2)

def extract_kent_police_links(query: str) -> list[str]:
url = KENT_POLICE_SEARCH + "?" + urlencode({"q": query})
html = http_get(url)
soup = BeautifulSoup(html, "html.parser")

links: set[str] = set()

for a in soup.select("h3 a"):
    href = (a.get("href") or "").strip()
    if href.startswith("/news/"):
        links.add(urljoin(KENT_POLICE_BASE, href.split("?")[0]))

if not links:
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("/news/") and "/latest/" in href:
            links.add(urljoin(KENT_POLICE_BASE, href.split("?")[0]))

return sorted(links)


def is_relevant_lgbt_hate(text_lower: str) -> bool:
# Strong signals
strong = [
"homophobic", "homophobia",
"transphobic", "transphobia",
"biphobic", "biphobia",
"sexual orientation",
"gender identity",
]
if any(s in text_lower for s in strong):
return True

# Weaker: hate crime + LGBT mention
has_hate = any(h in text_lower for h in HATE_TERMS)
has_lgbt = any(l in text_lower for l in ["lgbt", "lgbtq", "lgbtqia", "gay", "lesbian", "bisexual", "trans", "transgender", "non-binary", "non binary", "nonbinary"])
return has_hate and has_lgbt


def parse_kent_police_article(url: str) -> dict | None:
html = http_get(url)
soup = BeautifulSoup(html, "html.parser")

title = ""
h1 = soup.find("h1")
if h1:
    title = " ".join(h1.get_text(" ", strip=True).split())

if not title:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        title = og["content"].strip()

text_all = soup.get_text("\n", strip=True)

published = ""
m = re.search(r"Published:\s*([0-9]{2}:[0-9]{2}\s[0-9]{2}/[0-9]{2}/[0-9]{4})", text_all)
if m:
    published = m.group(1)

summary = ""
meta_desc = soup.find("meta", attrs={"name": "description"})
if meta_desc and meta_desc.get("content"):
    summary = " ".join(meta_desc["content"].strip().split())
else:
    p = soup.find("p")
    if p:
        summary = " ".join(p.get_text(" ", strip=True).split())

hay = (title + " " + summary + " " + text_all).lower()

if not is_relevant_lgbt_hate(hay):
    return None

court_hit = any(h in hay for h in [x.lower() for x in COURT_HINTS])

label = "Police update"
if court_hit:
    label = "Court update"
elif any(h in hay for h in [x.lower() for x in HATE_TERMS]):
    label = "Hate crime update"

tags = []
for k in LGBT_CORE_TERMS + HATE_TERMS:
    if k.lower() in hay:
        tags.append(k)

tags = sorted(list(set(tags)))

return {
    "id": url,
    "source": "Kent Police",
    "label": label,
    "title": title or "Untitled",
    "published": published,
    "url": url,
    "summary": summary[:400],
    "tags": tags,
    "found_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
}


def main() -> None:
state = load_json("state.json", {"seen_urls": []})
seen = set(state.get("seen_urls", []))

feed = load_json("feed.json", [])
if not isinstance(feed, list):
    feed = []

new_items: list[dict] = []

for term in SEARCH_TERMS:
    try:
        links = extract_kent_police_links(term)
    except Exception:
        continue

    for link in links[:25]:
        if link in seen:
            continue

        seen.add(link)

        try:
            item = parse_kent_police_article(link)
        except Exception:
            item = None

        if item:
            new_items.append(item)

merged: list[dict] = []
seen_ids: set[str] = set()

for it in new_items + feed:
    it_id = it.get("id") or it.get("url")
    if not it_id:
        continue
    if it_id in seen_ids:
        continue
    seen_ids.add(it_id)
    merged.append(it)

merged = merged[:200]
state_out = {"seen_urls": list(seen)[:2000]}

save_json("feed.json", merged)
save_json("state.json", state_out)


if name == "main":
main()
END tracker.py
