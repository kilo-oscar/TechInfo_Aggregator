import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


DEFAULT_HEADERS = {
    "User-Agent": "TechInfoAggregator/0.1 (+local development)"
}

KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "embodied ai",
    "robot",
    "robotics",
    "ロボット",
    "humanoid",
    "ヒューマノイド",
    "manipulation",
    "協働ロボット",
    "産業用ロボット",
    "fanuc",
    "ファナック",
    "安川",
    "yaskawa",
    "universal robots",
    "ur",
]

DATE_PATTERNS = [
    re.compile(r"(20\d{2}[/-]\d{1,2}[/-]\d{1,2})"),
    re.compile(r"(20\d{2}年\d{1,2}月\d{1,2}日)"),
]


def fetch_html(url: str, timeout: int = 20) -> str:
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding  # ←これが重要
    time.sleep(0.5)
    return response.text


def text_contains_keywords(text: str) -> bool:
    lower = text.lower()
    return any(keyword in lower for keyword in KEYWORDS)


def extract_date(text: str) -> str:
    for pattern in DATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return ""


def make_absolute(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def extract_candidate_links(base_url: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []

    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        title = a.get_text(" ", strip=True)

        if not href or not title:
            continue

        full_url = make_absolute(base_url, href)
        surrounding = a.parent.get_text(" ", strip=True) if a.parent else title
        combined = f"{title} {surrounding} {full_url}"

        if text_contains_keywords(combined):
            candidates.append({
                "title": title,
                "url": full_url,
                "published_at": extract_date(combined),
                "raw_summary": surrounding[:300],
                "raw_text": combined,
            })

    return dedupe_by_url(candidates)


def dedupe_by_url(items: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for item in items:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def enrich_item(item: dict, source_name: str) -> dict:
    return {
        "source_name": source_name,
        "source_type": "thinktank",
        "title": item["title"],
        "url": item["url"],
        "published_at": item.get("published_at", ""),
        "raw_summary": item.get("raw_summary", ""),
        "raw_text": item.get("raw_text", ""),
    }