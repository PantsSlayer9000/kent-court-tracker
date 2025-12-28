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

KENT_PHRASES = [
    "kent police",
    "maidstone crown court",
    "canterbury crown court",
    "medway magistrates",
    "maidstone magistrates",
    "canterbury magistrates",
    "kent, england",
    "kent england",
    "kent, uk",
    "kent uk",
    "county of kent",
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

ALLOW_SOURCE_DOMAINS = [
    ".co.uk",
    ".gov.uk",
    ".police.uk",
    ".org.uk",
    ".ac.uk",
]

ALLOW_SOURCE_CONTAINS = [
    "bbc.co.uk",
    "itv.com",
    "cps.gov.uk",
    "kentonline.co.uk",
    "kentlive.news",
    "isleofthanetnews.com",
]

COURT_TERMS = [
    "court",
    "crown court",
    "magistrates",
    "sentenced",
    "jailed",
    "imprisoned",
    "convicted",
    "charged",
    "appeared",
    "remanded",
    "pleaded guilty",
    "pleaded",
]

HATE_TERMS = [
    "hate crime",
    "hate-crime",
    "hatecrime",
    "hostility",
    "prejudice",
]

LGBT_TERMS = [
    "homophobic",
    "homophobia",
    "transphobic",
    "transphobia",
    "biphobic",
    "biphobia",
    "sexual orientation",
    "gender identity",
    "lgbt",
    "lgbtq",
    "lgbtqia",
    "gay",
    "lesbian",
    "bisexual",
    "transgender",
    "non-binary",
    "non binary",
    "nonbinary",
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
    u = source_url.lower().strip()
    if any(u.endswith(d) or (d + "/") in u for d in ALLOW_SOURCE_DOMAINS):
        return True
    if any(x in u for x in ALLOW_SOURCE_CONTAINS):
        return True
    return False

def looks_like_kent_uk(text: str) -> bool:
    t = (text or "").lower()
    if any(b in t for b in BLOCK_TERMS):
        return False
    if any(p in t for p in KENT_PHRASES):
        return True
    if any(town in t for town in KENT_TOWNS):
        return True
    if "kent" in t and (" england" in t or " uk" in t or "kent police" in t):
        return True
    return False

def label_item(title: str, summary: str) -> str:
    t = ((title or "") + " " + (summary or "")).lower()
    if any(x in t for x in COURT_TERMS):
        return "Court update"
    if any(x in t for x in HATE_TERMS):
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

    # Keep queries simple. More queries beats one complicated query.
    base_negatives = '-"Kent State" -Ohio -USA -"United States" -Michigan'

    queries = [
        f'homophobic Kent Police {base_negatives}',
        f'transphobic Kent Police {base_negatives}',
        f'"hate crime" "sexual orientation" Kent {base_negatives}',
        f'"hate crime" "gender identity" Kent {base_negatives}',
        f'LGBT hate crime Maidstone {base_negatives}',
        f'LGBT hate crime Canterbury {base_negatives}',
        f'homophobic Maidstone court {base_negatives}',
        f'transphobic Canterbury court {base_negatives}',
        f'"sexual orientation" court Kent {base_negatives}',
        f'"gender identity" court Kent {base_negatives}',
        f'homophobic Kent site:kentonline.co.uk {base_negatives}',
        f'transphobic Kent site:kentonline.co.uk {base_negatives}',
        f'homophobic Kent site:kentlive.news {base_negatives}',
        f'transphobic Kent site:kentlive.news {base_negatives}',
        f'"hate crime" Kent site:bbc.co.uk {base_negatives}',
        f'"hate crime" Kent site:itv.com {base_negatives}',
        f'"hate crime" Kent site:cps.gov.uk {base_negatives}',
    ]

    collected = []
    for q in queries:
        url = build_google_rss_url(q)
        xml_text = fetch_rss(url)
        if not xml_text:
            continue

        items = rss_items(xml_text)[:MAX_ITEMS_PER_QUERY]
        kept = 0

        for it in items:
            link = it.get("url")
            if not link:
                continue
            if link in seen:
                continue
            if not within_lookback(it.get("published"), cutoff):
                continue

            src_url = it.get("source_url", "")
            if src_url and not is_uk_source(src_url):
                continue

            combined = f"{it.get('title','')} {it.get('summary','')} {it.get('source','')} {src_url}"
            if not looks_like_kent_uk(combined):
                continue

            # Loose LGBT signal. If the query was LGBT specific, the title may still be short.
            t = combined.lower()
            if not (any(x in t for x in LGBT_TERMS) or any(x in t for x in HATE_TERMS)):
                continue

            it["label"] = label_item(it.get("title", ""), it.get("summary", ""))
            it["found_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            collected.append(it)
            seen.add(link)
            kept += 1

        print("Query kept:", kept, "for:", q)

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
