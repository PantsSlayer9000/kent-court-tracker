import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

KENT_POLICE_SEARCH = "https://www.kent.police.uk/news/news-search/"
CPS_NEWS_CENTRE = "https://www.cps.gov.uk/news"

# CPS South East is area=8 (Kent, Surrey, Sussex)
CPS_SOUTH_EAST_AREA_ID = 8
# CPS "Hate crime" filter is crime_type=21
CPS_HATE_CRIME_TYPE_ID = 21

USER_AGENT = "kent-court-tracker/1.0 (+https://github.com/)"

MAX_ITEMS = 50
MAX_PAGES_PER_SOURCE = 80
REQUEST_TIMEOUT = 25

STATE_FILE = "state.json"
FEED_FILE = "feed.json"

KENT_HINTS = [
    "kent", "maidstone", "canterbury", "medway", "chatham", "gillingham", "rochester",
    "ashford", "dartford", "gravesend", "tonbridge", "tunbridge", "sevenoaks",
    "folkestone", "dover", "deal", "whitstable", "herne bay", "sittingbourne",
    "sheerness", "isle of sheppey", "sheppey", "thanet", "margate", "ramsgate",
    "broadstairs", "swale", "faversham", "cranbrook", "tenterden",
    "maidstone crown court", "canterbury crown court"
]

STRONG_LGBT_HATE_TERMS = [
    "homophobic", "homophobia",
    "biphobic", "biphobia",
    "transphobic", "transphobia",
]

LGBT_TERMS = [
    "lgbt", "lgbtq", "lgbtq+", "lgbtqia", "lgbtqia+",
    "gay", "lesbian", "bisexual",
    "trans", "transgender",
    "non-binary", "non binary", "nonbinary",
    "sexual orientation", "gender identity",
]

HATE_TERMS = [
    "hate crime", "hate incident", "hate-crime", "hostility", "prejudice",
]

@dataclass
class Item:
    title: str
    url: str
    published: Optional[datetime]
    source: str
    summary: str

def http_get(url: str) -> str:
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.text

def load_state() -> Dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"seen_urls": []}
    except Exception:
        return {"seen_urls": []}

def save_state(state: Dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def save_feed(items: List[Item]) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    payload = {
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "count": len(items),
        "items": [
            {
                "title": it.title,
                "url": it.url,
                "published": it.published.date().isoformat() if it.published else None,
                "source": it.source,
                "summary": it.summary,
            }
            for it in items
        ],
    }
    with open(FEED_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def normalise_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def is_kent_related(text_lower: str) -> bool:
    return any(h in text_lower for h in KENT_HINTS)

def is_relevant_lgbt_hate(text_lower: str) -> bool:
    if any(t in text_lower for t in STRONG_LGBT_HATE_TERMS):
        return True
    has_lgbt = any(t in text_lower for t in LGBT_TERMS)
    has_hate = any(t in text_lower for t in HATE_TERMS)
    return has_lgbt and has_hate

def extract_kent_police_published(block_text: str) -> Optional[datetime]:
    # Example: "Published: 09:45 20/11/2025"
    m = re.search(r"Published:\s*(\d{2}:\d{2})\s*(\d{2}/\d{2}/\d{4})", block_text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1) + " " + m.group(2), "%H:%M %d/%m/%Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def extract_cps_published(block_text: str) -> Optional[datetime]:
    # Example: "09 August 2024"
    m = re.search(r"\b(\d{1,2}\s+[A-Za-z]+\s+\d{4})\b", block_text)
    if not m:
        return None
    try:
        dt = datetime.strptime(m.group(1), "%d %B %Y")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None

def parse_article_basic(url: str) -> Tuple[str, str]:
    """
    Fetch an article and return (title, summary).
    Summary is first reasonable paragraph, or empty string.
    """
    html = http_get(url)
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = normalise_space(h1.get_text(" ", strip=True))

    summary = ""
    # Try a few common containers
    for selector in ["main p", "article p", ".content p", ".rich-text p", "p"]:
        p = soup.select_one(selector)
        if not p:
            continue
        txt = normalise_space(p.get_text(" ", strip=True))
        if len(txt) >= 40:
            summary = txt
            break

    return title, summary

def fetch_kent_police_items(cutoff: datetime) -> List[Item]:
    items: List[Item] = []
    categories = ["Policing news", "Appeals", "Most Wanted"]

    for ct in categories:
        for page in range(1, MAX_PAGES_PER_SOURCE + 1):
            url = (
                f"{KENT_POLICE_SEARCH}"
                f"?ct={requests.utils.quote(ct)}&fdte=&tdte=&q=&page={page}"
            )
            html = http_get(url)
            soup = BeautifulSoup(html, "html.parser")

            page_items = []
            for h3 in soup.select("h3"):
                a = h3.find("a", href=True)
                if not a:
                    continue
                href = a["href"].strip()
                title = normalise_space(a.get_text(" ", strip=True))
                full_url = urljoin(KENT_POLICE_SEARCH, href)

                container = h3.parent
                container_text = normalise_space(container.get_text(" ", strip=True))
                published = extract_kent_police_published(container_text)

                if published and published < cutoff:
                    continue

                # Use listing text as quick filter
                candidate = (title + " " + container_text).lower()
                if not is_relevant_lgbt_hate(candidate):
                    continue

                # Pull nicer summary from article
                art_title, art_summary = parse_article_basic(full_url)
                if art_title:
                    title = art_title

                page_items.append(
                    Item(
                        title=title,
                        url=full_url,
                        published=published,
                        source="Kent Police",
                        summary=art_summary,
                    )
                )

            if not page_items:
                # Stop if we have paged far enough that everything is older than cutoff
                # Heuristic: if page contains dates and the newest date is older than cutoff, break
                page_text = normalise_space(soup.get_text(" ", strip=True))
                dates = [d for d in re.findall(r"Published:\s*\d{2}:\d{2}\s*\d{2}/\d{2}/\d{4}", page_text)]
                if dates:
                    parsed = [extract_kent_police_published(x) for x in dates]
                    parsed = [p for p in parsed if p]
                    if parsed and max(parsed) < cutoff:
                        break

            items.extend(page_items)

            if len(items) >= MAX_ITEMS:
                return items[:MAX_ITEMS]

    return items[:MAX_ITEMS]

def fetch_cps_south_east_hatecrime_items(cutoff: datetime) -> List[Item]:
    items: List[Item] = []

    for page in range(1, MAX_PAGES_PER_SOURCE + 1):
        url = f"{CPS_NEWS_CENTRE}?area={CPS_SOUTH_EAST_AREA_ID}&crime_type={CPS_HATE_CRIME_TYPE_ID}&page={page}"
        html = http_get(url)
        soup = BeautifulSoup(html, "html.parser")

        page_blocks = []
        for h3 in soup.select("h3"):
            a = h3.find("a", href=True)
            if not a:
                continue

            href = a["href"].strip()
            title = normalise_space(a.get_text(" ", strip=True))
            full_url = urljoin(CPS_NEWS_CENTRE, href)

            container = h3.parent
            container_text = normalise_space(container.get_text(" ", strip=True))
            published = extract_cps_published(container_text)

            if published and published < cutoff:
                continue

            candidate = (title + " " + container_text).lower()

            # South East includes Kent, Surrey, Sussex, so filter to Kent
            if not is_kent_related(candidate):
                # Sometimes Kent is only in the article, so allow strong terms through to article check
                if not any(t in candidate for t in STRONG_LGBT_HATE_TERMS):
                    continue

            if not is_relevant_lgbt_hate(candidate):
                continue

            art_title, art_summary = parse_article_basic(full_url)
            if art_title:
                title = art_title

            # Conf
