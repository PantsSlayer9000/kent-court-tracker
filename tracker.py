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
MAX_ITEMS_PER_QUERY = 60

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

KENT_TOWNS = [
    "maidstone", "canterbury", "medway", "chatham", "gillingham", "rochester",
    "ashford", "dartford", "gravesend", "sevenoaks", "thanet", "margate",
    "ramsgate", "broadstairs", "dover", "folkestone", "hythe", "deal",
    "sittingbourne", "sheerness", "sheppey", "isle of sheppey", "swale",
    "faversham", "whitstable", "herne bay", "tunbridge wells", "tonbridge",
    "tenterden", "cranbrook",
]

KENT_UK_PHRASES = [
    "kent, uk", "kent uk",
    "kent, england", "kent england",
    "county of kent", "kent police",
    "maidstone crown court", "canterbury crown court",
    "medway magistrates", "maidstone magistrates", "canterbury magistrates",
]

BLOCK_TERMS = [
    "kent state",
    "kent state university",
    "kent, ohio",
    "ohio",
    "michigan",
    "usa",
    "u.s.",
    "united states",
]

LGBT_TERMS = [
    "homophobic", "homophobia",
    "transphobic", "transphobia",
    "biphobic", "biphobia",
    "sexual orientation",
    "gender identity",
    "lgbt", "lgbtq", "lgbtqia",
    "gay", "lesbian", "bisexual",
    "transgender", "non-binary", "non binary", "nonbinary",
]

HATE_OR_CASE_TERMS = [
    "hate crime", "hate-crime", "hatecrime",
    "court", "crown court", "magistrates",
    "sentenced", "jailed", "imprisoned", "convicted",
    "charged", "appeared", "pleaded", "pleaded guilty",
    "assault", "abuse", "attack",
]

UK_SITE_QUERIES = [
    # Kent local
    "site:kentonline.co.uk",
    "site:kentlive.news",
    "site:isleofthanetnews.com",
    # National and official
    "site:bbc.co.uk",
    "site:itv.com",
    "site:cps.gov.uk",
    "site:gov.uk",
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
    params = {"q": q, "hl": "en-GB", "gl": "GB", "ceid": "GB:en"}
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

def is_uk_source(source_url: str) -> bool:
    if not source_url:
        return False
    u = source_url.lower()
    if u.endswith(".edu") or ".edu/" in u:
        return False
    if u.endswith(".us") or ".us/" in u:
        return False
    if u.endswith(".co.uk") or ".co.uk/" in u:
        return True
    if u.endswith(".gov.uk") or ".gov.uk/" in u:
        return True
    if u.endswith(".police.uk") or ".police.uk/" in u:
        return True
    if u.endswith(".org.uk") or ".org.uk/" in u:
        return True
    if u.endswith(".ac.uk") or ".ac.uk/" in u:
        return True
    if "bbc.co.uk" in u:
        return True
    if "itv.com" in u:
        return True
    return False

def looks_like_kent_uk(text: str) -> bool:
    t = (text or "").lower()

    if any(b in t for b in BLOCK_TERMS):
        return False

    if any(p in t for p in KENT_UK_PHRASES):
        return True

    if any(town in t for town in KENT_TOWNS):
        return True

    # Allow plain "kent" only if it also includes a UK hint
    if "kent" in t and (" uk" in t or " england" in t or "kent police" in t):
        return True

    return False

def has_lgbt_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in LGBT_TERMS)

def has_case_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(x in t for x in HATE_OR_CASE_TERMS)

def label_item(title: str, summary: str) -> str:
    t = ((title or "") + " " + (summary or "")).lower()
    if any(x in t for x in ["court", "crown court", "magistrates", "sentenced", "jailed", "convicted", "charged"]):
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

        source_elem = item.find("source")
        source_name = ""
        source_url = ""
        if source_elem is not None:
            source_name = (source_elem.text or "").strip()
            source_url = (source_elem.attrib.get("url") or "").strip()

        dt = parse_rss_date(pub_date)
        published = dt.date().isoformat() if dt else None

        out.append({
            "title": title,
            "url": link,
            "published": published,
            "source": source_name if source_name else "Google News",
            "source_url": source_url,
            "summary": desc[:400] if desc else "",
        })
    return out

def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * LOOKBACK_YEARS)

    state = load_json(STATE_FILE, {"seen_urls": []})
    seen = set(state.get("seen_urls", []))

    lgbt_q = '"homophobic" OR "transphobic" OR "biphobic" OR "sexual orientation" OR "gender identity" OR lgbt OR lgbtq OR gay OR lesbian OR bisexual OR transgender'
    case_q = '"hate crime" OR court OR "crown court" OR magistrates OR sentenced OR jailed OR convicted OR charged OR appeared'
    kent_q = '"Kent UK" OR "Kent England" OR Maidstone OR Canterbury OR Medway OR Thanet OR Ashford OR Dartford OR Gravesend OR Sevenoaks OR Dover OR Folkestone OR Sittingbourne OR Sheerness OR Sheppey OR Swale OR Faversham OR Whitstable OR "Kent Police"'

    queries = []
    for site in UK_SITE_QUERIES:
        queries.append(f'({lgbt_q}) ({case_q}) ({kent_q}) {site} -("Kent State") -Ohio -USA -("United States")')

    # Add one broader UK query to catch other UK publishers
    queries.append(f'({lgbt_q}) ({case_q}) ({kent_q}) -("Kent State") -Ohio -USA -("United States")')

    collected = []

    for q in queries:
        url = build_google_rss_url(q)
        xml_text = fetch_rss(url)
        if not xml_text:
            continue

        items = rss_items(xml_text)[:MAX_ITEMS_PER_QUERY]
        for it in items:
            link = it.get("url")
            if not link:
                continue
            if link in seen:
                continue
            if not within_lookback(it.get("published"), cutoff):
                continue

            combined = f"{it.get('title','')} {it.get('summary','')} {it.get('source','')} {it.get('source_url','')}"
            if not looks_like_kent_uk(combined):
                continue

            # If summaries are short, keep it permissive, but require at least one of these
            if not (has_lgbt_signal(combined) or "hate crime" in combined.lower()):
                continue
            if not has_case_signal(combined):
                continue

            # UK publisher check via source url when present
            src_url = it.get("source_url", "")
            if src_url and not is_uk_source(src_url):
                continue

            it["label"] = label_item(it.get("title", ""), it.get("summary", ""))
            it["found_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            collected.append(it)
            seen.add(link)

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
