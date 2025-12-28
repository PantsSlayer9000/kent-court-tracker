import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

FEED_FILE = "feed.json"
STATE_FILE = "state.json"

LOOKBACK_YEARS = 5
MAX_ITEMS = 300
MAX_ITEMS_PER_QUERY = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

KENT_HINTS = [
    "kent", "medway", "swale", "sheppey", "isle of sheppey", "sheerness",
    "sittingbourne", "faversham", "canterbury", "ashford", "maidstone",
    "dartford", "gravesend", "sevenoaks", "thanet", "margate", "ramsgate",
    "broadstairs", "dover", "folkestone", "hythe", "tunbridge wells",
    "tonbridge", "gillingham", "chatham", "rochester", "deal", "whitstable",
    "herne bay",
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
]

# Local and regional sources to bias results towards
SITE_HINTS = [
    "site:kentonline.co.uk",
    "site:kentlive.news",
    "site:isleofthanetnews.com",
    "site:bbc.co.uk",
    "site:cps.gov.uk",
    "site:itv.com",
]

BASE_QUERY = (
    '('
    '"homophobic" OR "transphobic" OR "biphobic" OR "sexual orientation" OR "gender identity" OR lgbt OR lgbtq OR gay OR lesbian OR bisexual OR transgender OR "hate crime"'
    ') '
    '('
    'Kent OR Medway OR Swale OR Sheppey OR Sheerness OR Sittingbourne OR Faversham OR Canterbury OR Ashford OR Maidstone OR Dartford OR Gravesend OR Sevenoaks OR Thanet OR Margate OR Ramsgate OR Broadstairs OR Dover OR Folkestone OR Gillingham OR Chatham OR Rochester'
    ')'
)

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

def parse_rss_date(pub_date: str) -> datetime | None:
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

def fetch_rss(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code >= 400:
            print("RSS fetch failed", r.status_code, url)
            return None
        return r.text
    except Exception as e:
        print("RSS fetch error", str(e))
        return None

def rss_items(xml_text: str) -> list[dict]:
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

def relevant(it: dict) -> bool:
    text = (it.get("title", "") + " " + it.get("summary", "") + " " + it.get("source", "")).lower()
    has_kent = any(k in text for k in KENT_HINTS)
    has_lgbt = any(t in text for t in LGBT_TERMS)
    # You said “any”, so do not force court words, but label them if present
    return has_kent and has_lgbt

def label_item(it: dict) -> str:
    text = (it.get("title", "") + " " + it.get("summary", "")).lower()
    if any(t in text for t in ["court", "crown court", "magistrates", "sentenced", "jailed", "convicted"]):
        return "Court update"
    if "hate crime" in text or "hate-crime" in text or "hatecrime" in text:
        return "Hate crime update"
    return "News report"

def within_lookback(it: dict, cutoff: datetime) -> bool:
    p = it.get("published")
    if not p:
        return True
    try:
        dt = datetime.strptime(p, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt >= cutoff
    except Exception:
        return True

def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * LOOKBACK_YEARS)

    state = load_json(STATE_FILE, {"seen_urls": []})
    seen = set(state.get("seen_urls", []))

    queries = [BASE_QUERY] + [BASE_QUERY + " " + s for s in SITE_HINTS]

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
            if not within_lookback(it, cutoff):
                continue
            if not relevant(it):
                continue

            it["label"] = label_item(it)
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

if __name__ == "__main__":
    main()
