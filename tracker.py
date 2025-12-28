import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode, urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "kent-court-tracker/1.2"}

KENT_POLICE_BASE = "https://www.kent.police.uk"
KENT_POLICE_SEARCH = KENT_POLICE_BASE + "/news/news-search/"

LOOKBACK_YEARS = 5
MAX_PAGES_PER_TERM = 120
MAX_LINKS_PER_PAGE = 30
MAX_FEED_ITEMS = 400
MAX_SEEN_URLS = 20000

SEARCH_TERMS = [
    "homophobic",
    "transphobic",
    "biphobic",
    "sexual orientation",
    "gender identity",
    "lgbt",
    "lgbtq",
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


def parse_published_dt(published: str) -> datetime | None:
    if not published:
        return None
    published = published.strip()
    for fmt in ("%H:%M %d/%m/%Y", "%H:%M %d/%m/%y"):
        try:
            return datetime.strptime(published, fmt)
        except ValueError:
            continue
    return None


def extract_kent_police_links(query: str, page: int) -> list[str]:
    params = {"q": query, "page": str(page), "fdte": "", "tdte": ""}
    url = KENT_POLICE_SEARCH + "?" + urlencode(params)
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

    return sorted(list(links))[:MAX_LINKS_PER_PAGE]


def is_relevant_lgbt_hate(text_lower: str) -> bool:
    strong = [
        "homophobic", "homophobia",
        "transphobic", "transphobia",
        "biphobic", "biphobia",
        "sexual orientation",
        "gender identity",
    ]
    if any(s in text_lower for s in strong):
        return True

    has_hate = any(h in text_lower for h in HATE_TERMS)
    has_lgbt = any(
        l in text_lower
        for l in [
            "lgbt", "lgbtq", "lgbtqia",
            "gay", "lesbian", "bisexual",
            "trans", "transgender",
            "non-binary", "non binary", "nonbinary",
        ]
    )
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
    m = re.search(
        r"Published:\s*([0-9]{1,2}:[0-9]{2}\s[0-9]{2}/[0-9]{2}/[0-9]{4})",
        text_all,
    )
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

    court_hit = any(h in hay for h in COURT_HINTS)

    label = "Police update"
    if court_hit:
        label = "Court update"
    elif any(h in hay for h in HATE_TERMS):
        label = "Hate crime update"

    tags = []
    for k in (LGBT_CORE_TERMS + HATE_TERMS):
        if k.lower() in hay:
            tags.append(k)
    tags = sorted(list(set(tags)))

    found_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    published_dt = parse_published_dt(published)
    published_iso = published_dt.isoformat() + "Z" if published_dt else ""

    return {
        "id": url,
        "source": "Kent Police",
        "label": label,
        "title": title or "Untitled",
        "published": published,
        "published_iso": published_iso,
        "url": url,
        "summary": summary[:400],
        "tags": tags,
        "found_at": found_at,
    }


def sort_key(item: dict) -> str:
    return item.get("published_iso") or item.get("found_at") or ""


def main() -> None:
    cutoff = datetime.utcnow() - timedelta(days=365 * LOOKBACK_YEARS)

    state = load_json("state.json", {"seen_urls": []})
    seen = set(state.get("seen_urls", []))

    feed = load_json("feed.json", [])
    if not isinstance(feed, list):
        feed = []

    new_items: list[dict] = []

    for term in SEARCH_TERMS:
        for page in range(1, MAX_PAGES_PER_TERM + 1):
            try:
                links = extract_kent_police_links(term, page)
            except Exception:
                break

            if not links:
                break

            page_oldest_dt: datetime | None = None
            any_dt = False

            for link in links:
                if link in seen:
                    continue

                seen.add(link)

                try:
                    item = parse_kent_police_article(link)
                except Exception:
                    item = None

                if not item:
                    continue

                dt = parse_published_dt(item.get("published", ""))
                if dt:
                    any_dt = True
                    if page_oldest_dt is None or dt < page_oldest_dt:
                        page_oldest_dt = dt

                    if dt < cutoff:
                        continue

                new_items.append(item)

            if any_dt and page_oldest_dt and page_oldest_dt < cutoff:
                break

    merged: list[dict] = []
    seen_ids: set[str] = set()

    for it in (new_items + feed):
        it_id = it.get("id") or it.get("url")
        if not it_id:
            continue
        if it_id in seen_ids:
            continue
        seen_ids.add(it_id)
        merged.append(it)

    merged.sort(key=sort_key, reverse=True)
    merged = merged[:MAX_FEED_ITEMS]

    state_out = {"seen_urls": list(seen)[:MAX_SEEN_URLS]}

    save_json("feed.json", merged)
    save_json("state.json", state_out)


if __name__ == "__main__":
    main()
