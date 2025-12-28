import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

FEED_FILE = "feed.json"
STATE_FILE = "state.json"

LOOKBACK_YEARS = 5
MAX_ITEMS = 250
MAX_ITEMS_PER_QUERY = 50

HEADERS = {
"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
"Accept": "application/rss+xml, application/xml;q=0.9, /;q=0.8",
"Accept-Language": "en-GB,en;q=0.9",
}

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search
"

Do not include plain "kent" here, it causes US "Kent State" results to pass.

KENT_UK_HINTS = [
"maidstone", "canterbury", "medway", "chatham", "gillingham", "rochester",
"ashford", "dartford", "gravesend", "sevenoaks", "thanet", "margate",
"ramsgate", "broadstairs", "dover", "folkestone", "hythe", "deal",
"sittingbourne", "sheerness", "sheppey", "isle of sheppey", "swale",
"faversham", "whitstable", "herne bay", "tunbridge wells", "tonbridge",
"tenterden", "cranbrook",
"kent police",
"kent, uk", "kent uk",
"kent, england", "kent england",
"maidstone crown court", "canterbury crown court",
"medway magistrates", "maidstone magistrates", "canterbury magistrates",
]

ALLOW_SOURCES = [
"kent online",
"kentlive",
"kent live",
"isle of thanet news",
"kent county council",
"bbc news",
"itv news",
"crown prosecution service",
"cps",
"hm courts",
"hmcts",
]

BLOCK_TERMS = [
"kent state",
"kent state university",
"ohio",
"michigan",
"washington state",
"united states",
"u.s.",
"usa",
"akron",
"grand rapids",
"seattle",
]

LGBT_TERMS = [
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

CASE_TERMS = [
"hate crime", "hate-crime", "hatecrime",
"court", "crown court", "magistrates",
"sentenced", "jailed", "imprisoned", "convicted",
"charged", "appeared", "pleaded", "pleaded guilty",
"assault", "abuse", "attack",
]

UK_SITE_QUERIES = [
'site:kentonline.co.uk',
'site:kentlive.news',
'site:isleofthanetnews.com',
'site:bbc.co.uk',
'site:itv.com',
'site:cps.gov.uk',
]

def load_json(path: str, fallback):
try:
with open(path, "r", encoding="utf-8") as f:
return json.load(f)
except Exception:
return fallback

def save_json(path: str, data) -> None:
with open(path, "w", encoding="utf-8") as f:
json.dump(data, f, ensure_ascii=False, indent=2)

def strip_html(s: str) -> str:
s = re.sub(r"<[^>]+>", " ", s or "")
s = re.sub(r"\s+", " ", s).strip()
return s

def parse_rss_date(pub_date: str):
if not pub_date:
return None
pub_date = pub_date.strip()
fmts = [
"%a, %d %b %Y %H:%M:%S %Z",
"%a, %d %b %Y %H:%M:%S %z",
]
for fmt in fmts:
try:
dt = datetime.strptime(pub_date, fmt)
if dt.tzinfo is None:
dt = dt.replace(tzinfo=timezone.utc)
return dt.astimezone(timezone.utc)
except Exception:
continue
return None

def build_google_rss_url(q: str) -> str:
params = {
"q": q,
"hl": "en-GB",
"gl": "GB",
"ceid": "GB:en",
}
return GOOGLE_NEWS_RSS + "?" + urlencode(params)

def fetch_rss(url: str):
try:
r = requests.get(url, headers=HEADERS, timeout=30)
if r.status_code >= 400:
print("RSS fetch failed", r.status_code)
return None
return r.text
except Exception as e:
print("RSS fetch error", str(e))
return None

def rss_items(xml_text: str):
out = []
try:
root = ET.fromstring(xml_text)
except Exception:
return out

for item in root.findall(".//item"):
    title = (item.findtext("title") or "").strip()
    link = (item.findtext("link") or "").strip()
    pub_date = (item.findtext("pubDate") or "").strip()
    desc = strip_html(item.findtext("description") or "")
    source = (item.findtext("source") or "").strip()

    dt = parse_rss_date(pub_date)
    published = dt.date().isoformat() if dt else None

    out.append({
        "title": title,
        "url": link,
        "published": published,
        "source": source if source else "Google News",
        "summary": desc[:400] if desc else "",
    })
return out


def has_lgbt(text: str) -> bool:
t = text.lower()
return any(x in t for x in LGBT_TERMS)

def looks_like_uk_kent(text: str, source: str) -> bool:
t = (text or "").lower()
s = (source or "").lower()

if any(b in t for b in BLOCK_TERMS) or any(b in s for b in BLOCK_TERMS):
    return False

if any(a in s for a in ALLOW_SOURCES):
    return True

return any(k in t for k in KENT_UK_HINTS)


def label_item(title: str, summary: str) -> str:
t = (title + " " + summary).lower()
if any(x in t for x in ["court", "crown court", "magistrates", "sentenced", "jailed", "convicted"]):
return "Court update"
if "hate crime" in t or "hate-crime" in t or "hatecrime" in t:
return "Hate crime update"
return "News report"

def within_lookback(published: str, cutoff: datetime) -> bool:
if not published:
return True
try:
dt = datetime.strptime(published, "%Y-%m-%d").replace(tzinfo=timezone.utc)
return dt >= cutoff
except Exception:
return True

def main() -> None:
cutoff = datetime.now(timezone.utc) - timedelta(days=365 * LOOKBACK_YEARS)

state = load_json(STATE_FILE, {"seen_urls": []})
seen = set(state.get("seen_urls", []))

lgbt_q = '"homophobic" OR "transphobic" OR "biphobic" OR "sexual orientation" OR "gender identity" OR lgbt OR lgbtq OR gay OR lesbian OR bisexual OR transgender OR "hate crime"'
case_q = '"hate crime" OR court OR "crown court" OR magistrates OR sentenced OR jailed OR convicted OR charged OR appeared'
kent_q = '"Kent UK" OR "Kent England" OR Maidstone OR Canterbury OR Medway OR Thanet OR Ashford OR Dartford OR Gravesend OR Sevenoaks OR Dover OR Folkestone OR "Kent Police"'

# Only UK focused queries, no general query
queries = []
for site in UK_SITE_QUERIES:
    q = f'({lgbt_q}) ({case_q}) ({kent_q}) {site} -("Kent State") -Ohio -Michigan -USA -("United States")'
    queries.append(q)

collected = []

for q in queries:
    url = build_google_rss_url(q)
    xml_text = fetch_rss(url)
    if not xml_text:
        continue

    items = rss_items(xml_text)[:MAX_ITEMS_PER_QUERY]
    for it in items:
        if not it.get("url"):
            continue
        if it["url"] in seen:
            continue
        if not within_lookback(it.get("published"), cutoff):
            continue

        title = it.get("title", "")
        summary = it.get("summary", "")
        source = it.get("source", "")

        combined = f"{title} {summary} {source}"
        if not has_lgbt(combined):
            continue
        if not looks_like_uk_kent(combined, source):
            continue

        it["label"] = label_item(title, summary)
        it["found_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        collected.append(it)
        seen.add(it["url"])

# De-dupe and sort
dedup = {}
for it in collected:
    dedup[it["url"]] = it

out = list(dedup.values())

def sort_key(x):
    return x.get("published") or "0000-00-00"

out.sort(key=sort_key, reverse=True)
out = out[:MAX_ITEMS]

state["seen_urls"] = list(seen)[:50000]
save_json(STATE_FILE, state)
save_json(FEED_FILE, out)

print("Saved items:", len(out))


if name == "main":
main()
