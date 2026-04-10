import urllib.parse
from email.utils import parsedate_to_datetime

import feedparser

from app import app

from crawler_utils import save_raw_item, is_within_last_3_years


GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"

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


def fetch_google_news_items(feed_url: str, logical_source_name: str) -> list[dict]:
    feed = feedparser.parse(feed_url)
    items = []

    for entry in feed.entries:
        raw_summary = getattr(entry, "summary", "") or ""
        published_at = normalize_published(entry)

        raw_text_parts = []
        if raw_summary:
            raw_text_parts.append(raw_summary)

        if getattr(entry, "published", None):
            raw_text_parts.append(f"Original published: {entry.published}")

        raw_text_parts.append(f"Google News feed source: {logical_source_name}")

        items.append({
            "source_name": logical_source_name,
            "source_type": "news",
            "title": (getattr(entry, "title", "") or "").strip(),
            "url": getattr(entry, "link", ""),
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


def build_queries() -> list[tuple[str, str]]:
    physical_ai_query = (
        '"Physical AI" OR "Embodied AI" OR "フィジカルAI" OR "Embodied Intelligence" '
        'OR "vision language action" OR VLA OR "robot manipulation" OR humanoid robotics'
    )

    robot_maker_query = (
        'FANUC OR ファナック OR "安川電機" OR Yaskawa OR '
        '"Universal Robots" OR "ユニバーサルロボット" OR "URロボット" OR '
        '("UR" AND (ロボット OR 協働ロボット OR cobot OR robot)) OR '
        '"協働ロボット" OR "industrial robot"'
    )

    return [
        ("Google News / Physical AI", physical_ai_query),
        ("Google News / Robot Makers", robot_maker_query),

        ("Startup / Robotics Japan",
         'ロボット スタートアップ 日本 OR robotics startup Japan'),

        ("Startup / Funding",
         'ロボット スタートアップ 資金調達 OR robotics startup funding Japan'),

        ("Startup / Humanoid",
         'ヒューマノイド スタートアップ OR humanoid robot startup'),

        ("Startup / Warehouse",
         '倉庫ロボット スタートアップ OR warehouse robotics startup'),

        ("Startup / AI Robotics",
         'AI ロボット スタートアップ OR AI robotics startup'),
    ]


def main() -> None:
    all_items = []

    for logical_source_name, query in build_queries():
        feed_url = format_google_news_url(query=query, hl="ja", gl="JP", ceid="JP:ja")
        items = fetch_google_news_items(feed_url=feed_url, logical_source_name=logical_source_name)
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


if __name__ == "__main__":
    main()
