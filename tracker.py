import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.kent.police.uk"
KENT_PAGINATED = BASE + "/news/news-search/GetPaginatedResults/"

CPS_BASE = "https://www.cps.gov.uk"
CPS_NEWS = CPS_BASE + "/news"

# CPS South East area covers Kent, Surrey, Sussex
CPS_AREA_ID = 8

LOOKBACK_YEARS = 5
MAX_PAGES = 120
MAX_ITEMS = 200

FEED_FILE = "feed.json"
STATE_FILE = "state.json"

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": BASE + "/news/news-search/",
}

LGBT_TERMS = [
    "homophobic", "homophobia",
    "transphobic", "transphobia",
    "biphobic", "biphobia",
    "sexual orientation",
    "gender identity",
    "lgbt", "lgbtq", "lgbtq+", "lgbtqia", "lgbtqia+",
    "gay", "lesbian", "bisexual",
    "trans", "transgender",
    "non-binary", "non binary", "nonbinary",
]

HATE_TERMS = [
    "hate crime", "hate-crime", "hatecrime",
    "hostility", "prejudice",
]

COURT_TERMS = [
    "court", "crown court", "magistrates",
    "jailed", "sentenced", "convicted",
    "pleaded guilty", "pleaded",
    "charged", "appeared", "remanded",
]

KENT_HINTS = [
    "kent", "maidstone", "canterbury", "medway", "chatham", "gillingham", "rochester",
    "ashford", "dartford", "gravesend", "tonbridge", "tunbridge", "sevenoaks",
    "folkestone", "dover", "deal", "whitstable", "herne bay", "sittingbourne",
    "sheerness", "sheppey", "isle of sheppey", "thanet", "margate", "ramsgate",
    "broadstairs", "swale", "faversham", "cranbrook", "tenterden",
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

def safe_get(url: str) -> str | None:
    try:
        r = requests.get(url, headers=BROWSER_HEADERS, timeout=30)
        if r.status_code == 403:
            return None
        r.raise_for_status()
        return r.text
    except requests.RequestException:
        return None

def parse_published_kent(text: str) -> datetime | None:
    m = re.search(r"Published:\s*(\d{2}:\d{2})\s*(\d{2}/\d{2}/\d{4})", text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1) + " " + m.group(2), "%H:%M %d/%m/%Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def parse_published_cps(text: str) -> datetime | None:
    m = re.search(r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%d %B %Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())

def looks_relevant(text_lower: str) -> bool:
    has_lgbt = any(t in text_lower for t in LGBT_TERMS)
    has_hate = any(t in text_lower for t in HATE_TERMS)
    has_court = any(t in text_lower for t in COURT_TERMS)
    # If it says homophobic, transphobic, biphobic, take it even without court terms
    strong = any(t in text_lower for t in ["homophobic", "transphobic", "biphobic"])
    return (strong and has_lgbt) or (has_lgbt and (has_hate or has_court))

def is_kent_related(text_lower: str) -> bool:
    return any(h in text_lower for h in KENT_HINTS)

def parse_article_title_summary(url: str) -> tuple[str, str]:
    html = safe_get(url)
    if not html:
        return "", ""
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = soup.find("h1")
    if h1:
        title = norm(h1.get_text(" ", strip=True))
    summary = ""
    for sel in ["main p", "article p", ".content p", "p"]:
        p = soup.select_one(sel)
        if not p:
            continue
        t = norm(p.get_text(" ", strip=True))
        if len(t) >= 40:
            summary = t
            break
    return title, summary

def fetch_kent_police(cutoff: datetime) -> list[dict]:
    items: list[dict] = []

    # These categories exist on Kent Police news pages
    categories = [
        "Policing news",
        "Justice Seen Justice Done",
    ]

    for ct in categories:
        blocked = False

        for page in range(1, MAX_PAGES + 1):
            params = {"ct": ct, "page": page}
            url = KENT_PAGINATED + "?" + urlencode(params)
            html = safe_get(url)

            if html is None:
                blocked = True
                break

            soup = BeautifulSoup(html, "html.parser")
            cards = soup.find_all("h3")
            if not cards:
                break

            page_dates: list[datetime] = []

            for h3 in cards:
                a = h3.find("a", href=True)
                if not a:
                    continue

                title = norm(a.get_text(" ", strip=True))
                link = urljoin(BASE, a["href"])

                container = h3.parent
                blob = norm(container.get_text(" ", strip=True))
                published_dt = parse_published_kent(blob)
                if published_dt:
                    page_dates.append(published_dt)

                text_lower = (title + " " + blob).lower()
                if published_dt and published_dt < cutoff:
                    continue
                if not looks_relevant(text_lower):
                    continue

                art_title, art_summary = parse_article_title_summary(link)
                if art_title:
                    title = art_title

                label = "Kent Police"
                if any(t in text_lower for t in COURT_TERMS):
                    label = "Court update"
                elif any(t in text_lower for t in HATE_TERMS):
                    label = "Hate crime update"

                items.append({
                    "source": "Kent Police",
                    "label": label,
                    "title": title,
                    "url": link,
                    "published": published_dt.date().isoformat() if published_dt else None,
                    "summary": art_summary[:400] if art_summary else "",
                })

                if len(items) >= MAX_ITEMS:
                    return items

            if page_dates and max(page_dates) < cutoff:
                break

        if blocked:
            print("Kent Police blocked this run (403). Skipping Kent Police source.")
            break

    return items

def fetch_cps(cutoff: datetime) -> list[dict]:
    items: list[dict] = []

    # Crime type IDs vary on CPS site, so we keep it broad and filter in text.
    # We only lock the area to South East.
    for page in range(0, MAX_PAGES):
        url = f"{CPS_NEWS}?area={CPS_AREA_ID}&page={page}"
        html = safe_get(url)
        if not html:
            break

        soup = BeautifulSoup(html, "html.parser")
        h3s = soup.find_all("h3")
        if not h3s:
            break

        page_dates: list[datetime] = []

        for h3 in h3s:
            a = h3.find("a", href=True)
            if not a:
                continue

            title = norm(a.get_text(" ", strip=True))
            link = urljoin(CPS_BASE, a["href"])

            container = h3.parent
            blob = norm(container.get_text(" ", strip=True))
            published_dt = parse_published_cps(blob)
            if published_dt:
                page_dates.append(published_dt)

            text_lower = (title + " " + blob).lower()

            if published_dt and published_dt < cutoff:
                continue

            if not looks_relevant(text_lower):
                continue

            art_title, art_summary = parse_article_title_summary(link)
            if art_title:
                title = art_title

            confirm_lower = (title + " " + art_summary).lower()
            if not is_kent_related(confirm_lower):
                continue

            label = "Court update" if any(t in confirm_lower for t in COURT_TERMS) else "CPS update"

            items.append({
                "source": "CPS South East",
                "label": label,
                "title": title,
                "url": link,
                "published": published_dt.date().isoformat() if published_dt else None,
                "summary": art_summary[:400] if art_summary else "",
            })

            if len(items) >= MAX_ITEMS:
                return items

        if page_dates and max(page_dates) < cutoff:
            break

    return items

def sort_key(it: dict) -> str:
    return it.get("published") or ""

def main() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * LOOKBACK_YEARS)

    state = load_json(STATE_FILE, {"seen_urls": []})
    seen = set(state.get("seen_urls", []))

    items: list[dict] = []
    items.extend(fetch_cps(cutoff))
    items.extend(fetch_kent_police(cutoff))

    # De-dupe by URL
    dedup = {}
    for it in items:
        u = it.get("url")
        if u:
            dedup[u] = it

    out = list(dedup.values())
    out.sort(key=sort_key, reverse=True)
    out = out[:MAX_ITEMS]

    for it in out:
        seen.add(it.get("url"))

    state["seen_urls"] = list(seen)[:20000]
    save_json(STATE_FILE, state)
    save_json(FEED_FILE, out)

    print("Saved items:", len(out))

if __name__ == "__main__":
    main()
