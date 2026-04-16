import urllib.parse
from email.utils import parsedate_to_datetime

import feedparser
import requests

from app import app

from crawler_utils import canonicalize_url, is_within_last_3_years, normalize_text, save_raw_item


GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
TIMEOUT = 20
GOOGLE_NEWS_LOCALES = [
    ("ja", "JP", "JP:ja"),
    ("en-US", "US", "US:en"),
]

ROBOT_MAKER_REJECT_KEYWORDS = [
    "ur都市",
    "ur 都市",
    "都市機構",
    "都市再生",
    "まちづくり",
    "urban research",
    "ur days",
    "urキャラ",
    "レアキャラ",
    "jleague",
    "グランパス",
    "シンポジウム",
]

ROBOTICS_CONTEXT_KEYWORDS = [
    "ロボット",
    "協働ロボット",
    "cobot",
    "robot",
    "automation",
    "自動化",
    "産業用",
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


def fetch_google_news_feed(feed_url: str):
    try:
        response = requests.get(
            feed_url,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        print(f"[WARN] Google News feed request failed: url={feed_url} error={exc}")
        return None

    return feedparser.parse(response.content)


def fetch_google_news_items(
    *,
    feed_url: str,
    logical_source_name: str,
    query: str,
    locale_label: str,
    seen_urls: set[str],
    seen_entry_keys: set[str],
) -> list[dict]:
    feed = fetch_google_news_feed(feed_url)
    if feed is None:
        return []

    items = []

    for entry in feed.entries:
        url = canonicalize_url(getattr(entry, "link", ""))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        raw_summary = normalize_text(getattr(entry, "summary", "") or "", max_length=2000)
        published_at = normalize_published(entry)
        publisher = normalize_text(getattr(getattr(entry, "source", {}), "title", "") or "", max_length=200)
        title = normalize_text((getattr(entry, "title", "") or "").strip(), max_length=500)
        entry_key = f"{title}|{published_at}"
        if title and published_at and entry_key in seen_entry_keys:
            continue
        if title and published_at:
            seen_entry_keys.add(entry_key)

        raw_text_parts = []
        if raw_summary:
            raw_text_parts.append(raw_summary)

        if getattr(entry, "published", None):
            raw_text_parts.append(f"Original published: {entry.published}")

        if publisher:
            raw_text_parts.append(f"Publisher: {publisher}")

        raw_text_parts.append(f"Google News feed source: {logical_source_name}")
        raw_text_parts.append(f"Google News query: {query}")
        raw_text_parts.append(f"Google News locale: {locale_label}")

        items.append({
            "source_name": logical_source_name,
            "source_type": "news",
            "title": title,
            "url": url,
            "published_at": published_at,
            "raw_summary": raw_summary,
            "raw_text": "\n\n".join(raw_text_parts),
        })

    return items


def should_keep_google_news_item(item: dict) -> bool:
    source_name = (item.get("source_name") or "").strip()
    if source_name != "Google News / Robot Makers":
        return True

    combined_text = " ".join([
        item.get("title") or "",
        item.get("raw_summary") or "",
    ]).lower()

    if any(keyword in combined_text for keyword in ROBOT_MAKER_REJECT_KEYWORDS):
        return False

    if "universal robots" in combined_text or "ユニバーサルロボット" in combined_text:
        return True

    if " ur " in f" {combined_text} " or "ur-" in combined_text or "ur（" in combined_text or "ur(" in combined_text:
        return any(keyword in combined_text for keyword in ROBOTICS_CONTEXT_KEYWORDS)

    return True


def build_query_groups() -> list[tuple[str, list[str]]]:
    return [
        ("Google News / Physical AI", [
            '"Physical AI"',
            '"フィジカルAI"',
            '"Embodied AI" robot',
            '"Embodied Intelligence" robot',
            '("vision language action" OR "vision-language-action" OR VLA) robot',
            '"robot manipulation" AI',
            '("robot foundation model" OR "foundation model") robotics',
            'humanoid robotics AI',
        ]),
        ("Google News / AI Agents", [
            '"AIエージェント"',
            '"AI agent"',
            '"agentic AI"',
            '("AI agent" OR "AIエージェント") robotics',
            '("AI agent" OR "agentic AI") automation',
        ]),
        ("Google News / Robot Makers", [
            'FANUC OR ファナック',
            '"安川電機" OR Yaskawa',
            '"Universal Robots" OR "ユニバーサルロボット" OR "URロボット"',
            '("協働ロボット" OR cobot) (manufacturer OR maker OR 導入 OR 発表)',
            '("industrial robot" OR "産業用ロボット") (launch OR release OR 発表)',
        ]),
        ("Startup / Robotics Japan", [
            'ロボット スタートアップ 日本',
            'robotics startup Japan',
        ]),
        ("Startup / Funding", [
            'ロボット スタートアップ 資金調達',
            'robotics startup funding',
            'robot startup funding',
        ]),
        ("Startup / Humanoid", [
            'ヒューマノイド スタートアップ',
            'humanoid robot startup',
        ]),
        ("Startup / Warehouse", [
            '倉庫ロボット スタートアップ',
            'warehouse robotics startup',
            '物流ロボット スタートアップ',
        ]),
        ("Startup / AI Robotics", [
            'AI ロボット スタートアップ',
            'AI robotics startup',
            'robotics AI startup',
        ]),
    ]


def main() -> None:
    all_items = []
    source_counts: dict[str, int] = {}

    for logical_source_name, queries in build_query_groups():
        seen_urls: set[str] = set()
        seen_entry_keys: set[str] = set()
        source_counts[logical_source_name] = 0
        for query in queries:
            for hl, gl, ceid in GOOGLE_NEWS_LOCALES:
                locale_label = f"{gl}/{hl}"
                feed_url = format_google_news_url(query=query, hl=hl, gl=gl, ceid=ceid)
                items = fetch_google_news_items(
                    feed_url=feed_url,
                    logical_source_name=logical_source_name,
                    query=query,
                    locale_label=locale_label,
                    seen_urls=seen_urls,
                    seen_entry_keys=seen_entry_keys,
                )
                source_counts[logical_source_name] += len(items)
                all_items.extend(items)

    with app.app_context():
        inserted = 0
        skipped = 0
        old_skipped = 0

        for item in all_items:
            if not is_within_last_3_years(item.get("published_at")):
                old_skipped += 1
                continue

            if not should_keep_google_news_item(item):
                skipped += 1
                continue

            if item["url"] and save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(f"Google News から取得: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")
        for logical_source_name, count in source_counts.items():
            print(f"[INFO] {logical_source_name}: fetched={count}")


if __name__ == "__main__":
    main()
