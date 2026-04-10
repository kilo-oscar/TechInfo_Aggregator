import json
import urllib.parse
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import feedparser
from bs4 import BeautifulSoup

from app import app
from crawler_utils import is_within_last_3_years, normalize_text, save_raw_item
from crawlers.official_site_common import fetch_html, extract_candidate_links

GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"

OFFICIAL_SOURCE_NAME = "Motion Lib / Real Haptics"
OFFICIAL_SEED_URLS = [
    "https://www.motionlib.com/",
    "https://www.motionlib.com/technology/",
    "https://www.motionlib.com/news/",
    "https://www.motionlib.com/movie/",
    "https://www.motionlib.com/case/",
]

OFFICIAL_EXTRA_KEYWORDS = [
    "real haptics",
    "realhaptics",
    "リアルハプティクス",
    "motion lib",
    "motionlib",
    "abc core",
    "abccore",
    "力触覚",
    "触覚",
    "遠隔操作",
    "teleoperation",
    "automation",
    "モーションリブ",
    "ロボット制御装置",
]

NEWS_QUERIES = [
    ("Google News / Real Haptics", '"Real Haptics" OR リアルハプティクス OR Motion Lib OR モーションリブ'),
    ("Google News / Haptics Robotics", '力触覚 ロボット OR haptics robotics OR haptic teleoperation'),
]


def format_google_news_url(query: str, hl: str = "ja", gl: str = "JP", ceid: str = "JP:ja") -> str:
    params = {
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid,
    }
    return f"{GOOGLE_NEWS_RSS_BASE}?{urllib.parse.urlencode(params)}"


def normalize_published(entry) -> str:
    published = getattr(entry, "published", "") or ""
    if not published:
        return ""
    try:
        dt = parsedate_to_datetime(published)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return published


def fetch_google_news_items(feed_url: str, logical_source_name: str) -> list[dict]:
    feed = feedparser.parse(feed_url)
    items = []

    for entry in feed.entries:
        raw_summary = getattr(entry, "summary", "") or ""
        published_at = normalize_published(entry)
        raw_payload = {
            "kind": "real_haptics_news",
            "source": logical_source_name,
            "published_at": published_at,
            "summary": raw_summary,
        }
        items.append({
            "source_name": logical_source_name,
            "source_type": "news",
            "title": normalize_text(getattr(entry, "title", ""), max_length=500),
            "url": getattr(entry, "link", ""),
            "published_at": published_at,
            "raw_summary": normalize_text(raw_summary, max_length=2000),
            "raw_text": json.dumps(raw_payload, ensure_ascii=False, indent=2),
        })
    return items


def item_matches_real_haptics(item: dict) -> bool:
    blob = " ".join([
        item.get("title", ""),
        item.get("raw_summary", ""),
        item.get("raw_text", ""),
        item.get("url", ""),
    ]).lower()
    return any(keyword in blob for keyword in OFFICIAL_EXTRA_KEYWORDS)


def enrich_official_item(item: dict) -> dict:
    return {
        "source_name": OFFICIAL_SOURCE_NAME,
        "source_type": "company",
        "title": normalize_text(item.get("title", ""), max_length=500),
        "url": item.get("url", ""),
        "published_at": item.get("published_at", ""),
        "raw_summary": normalize_text(item.get("raw_summary", ""), max_length=2000),
        "raw_text": json.dumps({
            "kind": "real_haptics_official",
            "source_domain": urlparse(item.get("url", "")).netloc,
            "raw_text": normalize_text(item.get("raw_text", ""), max_length=5000),
        }, ensure_ascii=False, indent=2),
    }


def fetch_official_items() -> list[dict]:
    all_items = []

    for url in OFFICIAL_SEED_URLS:
        try:
            html = fetch_html(url)
            candidates = extract_candidate_links(url, html)
            for item in candidates:
                if not item_matches_real_haptics(item):
                    continue
                all_items.append(enrich_official_item(item))
        except Exception as exc:
            print(f"[RealHaptics] failed: {url} -> {exc}")

    unique = {}
    for item in all_items:
        unique[item["url"]] = item
    return list(unique.values())


def extract_page_summary(url: str) -> str:
    try:
        html = fetch_html(url)
    except Exception:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for selector in [
        "meta[name='description']",
        "meta[property='og:description']",
        "main p",
        "article p",
        "p",
    ]:
        node = soup.select_one(selector)
        if not node:
            continue
        if node.name == "meta":
            text = node.get("content", "")
        else:
            text = node.get_text(" ", strip=True)
        text = normalize_text(text, max_length=1200)
        if len(text) >= 30:
            return text
    return ""


def main() -> None:
    official_items = fetch_official_items()
    news_items = []
    for logical_source_name, query in NEWS_QUERIES:
        feed_url = format_google_news_url(query=query, hl="ja", gl="JP", ceid="JP:ja")
        for item in fetch_google_news_items(feed_url=feed_url, logical_source_name=logical_source_name):
            if item_matches_real_haptics(item):
                news_items.append(item)

    with app.app_context():
        inserted = 0
        skipped = 0
        old_skipped = 0

        for item in official_items:
            if not item.get("raw_summary"):
                item["raw_summary"] = extract_page_summary(item["url"])
            if item["url"] and save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        for item in news_items:
            if item.get("published_at") and not is_within_last_3_years(item.get("published_at")):
                old_skipped += 1
                continue
            if item["url"] and save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(
            f"Real Haptics crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}"
        )


if __name__ == "__main__":
    main()
