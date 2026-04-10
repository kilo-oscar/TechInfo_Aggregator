import json
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from crawler_utils import normalize_text


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}

DATE_PATTERNS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日 %H時%M分",
    "%Y年%m月%d日",
]

META_SELECTORS = [
    ("meta[property='article:published_time']", "content"),
    ("meta[property='og:article:published_time']", "content"),
    ("meta[name='article:published_time']", "content"),
    ("meta[name='publish_date']", "content"),
    ("meta[name='pubdate']", "content"),
    ("meta[name='date']", "content"),
    ("meta[itemprop='datePublished']", "content"),
    ("time[datetime]", "datetime"),
    ("time[itemprop='datePublished']", "datetime"),
]

JSON_DATE_KEYS = [
    "datePublished",
    "dateCreated",
    "uploadDate",
    "releaseCompleDate",
]


def _normalize_date(value: Optional[str]) -> str:
    text = normalize_text(value, max_length=100)
    if not text:
        return ""

    if text.endswith("Z"):
        text = text[:-1] + "+0000"
    if re.search(r"[+-]\d{2}:\d{2}$", text):
        text = text[:-3] + text[-2:]

    for pattern in DATE_PATTERNS:
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d")
        except ValueError:
            continue

    match = re.search(r"(20\d{2})[/-年](\d{1,2})[/-月](\d{1,2})", text)
    if match:
        yyyy, mm, dd = match.groups()
        return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"

    return ""


def _extract_json_dates(blob: str) -> list[str]:
    dates: list[str] = []

    try:
        payload = json.loads(blob)
    except json.JSONDecodeError:
        payload = None

    def walk(node) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key in JSON_DATE_KEYS and isinstance(value, str):
                    normalized = _normalize_date(value)
                    if normalized:
                        dates.append(normalized)
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    if payload is not None:
        walk(payload)
        if dates:
            return dates

    for key in JSON_DATE_KEYS:
        for match in re.finditer(rf'"{re.escape(key)}"\s*:\s*"([^"]+)"', blob):
            normalized = _normalize_date(match.group(1))
            if normalized:
                dates.append(normalized)
    return dates


def extract_actual_published_at_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for selector, attr in META_SELECTORS:
        node = soup.select_one(selector)
        if not node:
            continue
        normalized = _normalize_date(node.get(attr, ""))
        if normalized:
            return normalized

    for script in soup.select("script[type='application/ld+json']"):
        if not script.string and not script.get_text(strip=True):
            continue
        blob = script.string or script.get_text(" ", strip=True)
        dates = _extract_json_dates(blob)
        if dates:
            return dates[0]

    next_data = soup.select_one("script#__NEXT_DATA__")
    if next_data:
        dates = _extract_json_dates(next_data.get_text(" ", strip=True))
        if dates:
            return dates[0]

    return ""


def fetch_actual_published_at(url: str, timeout: int = 15) -> str:
    normalized_url = normalize_text(url, max_length=1000)
    if not normalized_url.startswith(("http://", "https://")):
        return ""
    if normalized_url.lower().endswith(".pdf"):
        return ""

    response = requests.get(normalized_url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    content_type = (response.headers.get("Content-Type", "") or "").lower()
    if "html" not in content_type and "<html" not in response.text[:500].lower():
        return ""

    response.encoding = response.apparent_encoding
    return extract_actual_published_at_from_html(response.text)
