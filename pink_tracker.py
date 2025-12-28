import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

FEED_FILE = "pinknews.json"
STATE_FILE = "pink_state.json"

LOOKBACK_YEARS = 5
MAX_ITEMS = 200
MAX_ITEMS_PER_QUERY = 60

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

AREAS = [
    "ashford", "broadstairs", "canterbury", "chatham", "dartford", "deal", "dover",
    "faversham", "folkestone", "gillingham", "gravesend", "herne bay", "hythe",
    "isle of sheppey", "maidstone", "margate", "medway", "ramsgate", "rochester",
    "sevenoaks", "sheerness", "sheppey", "sittingbourne", "swale", "thanet",
    "tonbridge", "tunbridge wells", "whitstable",
]

BLOCK_TERMS = [
    "kent state",
    "kent state university",
    "kent, ohio",
    "ohio",
    "usa",
    "u.s.",
    "united states",
]

TOPIC_TERMS = [
    "lgbt", "lgbtq", "lgbtq+", "lgbtqia", "lgbtqia+",
    "gay", "lesbian", "bisexual", "trans", "transgender",
    "non-binary", "non binary", "nonbinary",
    "homophobic", "homophobia",
    "transphobic", "transphobia",
    "biphobic", "biphobia",
    "hate crime", "hate-crime", "hatecrime",
    "sexual orientation", "gender identity",
    "pride",
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

def fetch_rss(q: str):
    url = build_google_rss_url(q)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code >= 400:
            print("RSS fetch failed", r.status_code, "for query:", q)
            return None
        return r.text
    except Exception as e:
        print("RSS fetch error", str(e), "for query:", q)
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

def is_pinknews(it) -> bool:
    su = (it.get("source_url") or "").lower()
    sn = (it.get("source") or "").lower()
    u = (it.get("url") or "").lower()
    return ("thepinknews.com" in su) or ("pinknews" in sn) or ("thepinknews.com" in u)

def looks_like_kent_area(text: str) -> bool:
    t = (text or "").lower()
    if any(b in t for b in BLOCK_TERMS):
        return False
    if "kent" in t:
        return True
    for a in AREAS:
        if a in t:
            return True
    return False

def has_topic_signal(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in TOPIC_TERMS)

def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * LOOKBACK_YEARS)

    state = load_json(STATE_FILE, {"seen_urls": []})
    seen = set(state.get("seen_urls", []))

    base_neg = '-"Kent State" -Ohio -USA -"United States"'
    queries = [
        f'site:thepinknews.com kent lgbt {base_neg}',
        f'site:thepinknews.com kent hate crime {base_neg}',
        f'site:thepinknews.com kent homophobic {base_neg}',
        f'site:thepinknews.com kent transphobic {base_neg}',
        f'site:thepinknews.com maidstone lgbt {base_neg}',
        f'site:thepinknews.com canterbury lgbt {base_neg}',
        f'site:thepinknews.com medway lgbt {base_neg}',
        f'site:thepinknews.com thanet lgbt {base_neg}',
        f'site:thepinknews.com swale lgbt {base_neg}',
        f'site:thepinknews.com sittingbourne lgbt {base_neg}',
    ]

    collected = []
    for q in queries:
        xml_text = fetch_rss(q)
        if not xml_text:
            continue

        items = rss_items(xml_text)[:MAX_ITEMS_PER_QUERY]
        kept = 0

        for it in items:
            link = it.get("url") or ""
            if not link:
                continue
            if link in seen:
                continue

            if it.get("published"):
                try:
                    dt = datetime.strptime(it["published"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    if dt < cutoff:
                        continue
                except Exception:
                    pass

            combined = f'{it.get("title","")} {it.get("summary","")} {it.get("source","")} {it.get("source_url","")} {it.get("url","")}'
            if not looks_like_kent_area(combined):
                continue
            if not has_topic_signal(combined):
                continue
            if not is_pinknews(it):
                continue

            it["label"] = "PinkNews"
            it["found_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
            collected.append(it)
            seen.add(link)
            kept += 1

        print("Query kept:", kept, "for:", q)

    dedup = {it["url"]: it for it in collected}
    out = list(dedup.values())
    out.sort(key=lambda x: x.get("published") or "0000-00-00", reverse=True)
    out = out[:MAX_ITEMS]

    state["seen_urls"] = list(seen)[:50000]
    save_json(STATE_FILE, state)
    save_json(FEED_FILE, out)

    print("Saved items:", len(out))

if __name__ == "__main__":
    main()
