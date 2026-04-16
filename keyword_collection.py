from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from crawler_utils import canonicalize_url, normalize_text, save_raw_item


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
DUCKDUCKGO_HTML_SEARCH = "https://html.duckduckgo.com/html/"
TIMEOUT = 20
MAX_RESULTS = 12

NOISY_DOMAINS = {
    "news.google.com",
    "google.com",
    "www.google.com",
    "duckduckgo.com",
    "www.duckduckgo.com",
    "x.com",
    "www.facebook.com",
    "facebook.com",
    "www.instagram.com",
    "instagram.com",
}

NEWSY_DOMAINS = {
    "reuters.com",
    "www.reuters.com",
    "bloomberg.com",
    "www.bloomberg.com",
    "nikkei.com",
    "www.nikkei.com",
    "itmedia.co.jp",
    "monoist.itmedia.co.jp",
    "robotstart.info",
    "robostart.info",
    "prtimes.jp",
}

TOPIC_KEYWORDS = {
    "業績予想": ["業績予想", "通期予想", "来期予想", "forecast", "earnings forecast", "guidance"],
    "決算速報": ["決算速報", "決算", "決算発表", "financial results", "earnings", "results"],
    "physical_ai": ["physical ai", "physical-ai", "フィジカルai", "embodied ai", "embodied intelligence", "vla"],
    "robotics": ["robotics", "robot", "ロボティクス", "ロボット", "協働ロボット", "humanoid", "ヒューマノイド"],
    "ai": [
        "artificial intelligence",
        "ai",
        "生成ai",
        "人工知能",
        "aiエージェント",
        "ai エージェント",
        "エージェントai",
        "エージェント ai",
        "ai agent",
        "agent ai",
        "agentic ai",
        "machine learning",
    ],
    "real_haptics": ["real haptics", "real-haptics", "リアルハプティクス", "motion lib", "モーションリブ", "haptics"],
}


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    engine: str


def normalize_published(value: str) -> str:
    published = normalize_text(value, max_length=200)
    if not published:
        return ""
    try:
        dt = parsedate_to_datetime(published)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return published


def unwrap_duckduckgo_url(href: str) -> Optional[str]:
    if not href.startswith(("http://", "https://")):
        return None
    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        return qs.get("uddg", [None])[0]
    return href


def classify_source_type(domain: str, url: str, title: str, summary: str) -> str:
    lowered = " ".join([domain, url, title, summary]).lower()
    if domain in NEWSY_DOMAINS or any(term in lowered for term in ["news", "press", "速報", "報道", "media", "journal"]):
        return "news"
    return "company"


def matches_allowed_topics(*texts: str) -> bool:
    blob = " ".join(texts).lower()
    return any(keyword in blob for keywords in TOPIC_KEYWORDS.values() for keyword in keywords)


class KeywordCollector:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def format_google_news_url(self, query: str) -> str:
        params = {
            "q": query,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
        }
        return f"{GOOGLE_NEWS_RSS_BASE}?{urllib.parse.urlencode(params)}"

    def fetch_google_news_items(self, keyword: str) -> list[dict]:
        queries = [
            keyword,
            f'"{keyword}"',
        ]
        items: list[dict] = []
        seen_urls: set[str] = set()

        for query in queries:
            feed = feedparser.parse(self.format_google_news_url(query))
            for entry in getattr(feed, "entries", []):
                url = canonicalize_url(getattr(entry, "link", ""))
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                summary = normalize_text(getattr(entry, "summary", "") or "", max_length=2000)
                title = normalize_text(getattr(entry, "title", "") or "", max_length=500)
                if not matches_allowed_topics(keyword, title, summary):
                    continue
                published_at = normalize_published(getattr(entry, "published", "") or "")
                items.append({
                    "source_name": f"Keyword / Google News / {keyword}",
                    "source_type": "news",
                    "title": title,
                    "url": url,
                    "published_at": published_at,
                    "raw_summary": summary,
                    "raw_text": "\n\n".join([
                        summary,
                        f"Keyword collector source: Google News RSS",
                        f"Keyword: {keyword}",
                    ]).strip(),
                })
        return items

    def search_duckduckgo(self, keyword: str) -> list[SearchResult]:
        try:
            response = self.session.post(DUCKDUCKGO_HTML_SEARCH, data={"q": keyword}, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []

        for node in soup.select("a.result__a"):
            href = normalize_text(node.get("href", ""), max_length=2000)
            url = unwrap_duckduckgo_url(href) or ""
            url = canonicalize_url(url)
            if not url:
                continue
            domain = urlparse(url).netloc.lower()
            if domain in NOISY_DOMAINS:
                continue
            title = normalize_text(node.get_text(" ", strip=True), max_length=500)
            snippet = ""
            box = node.find_parent(class_="result")
            if box:
                snippet_node = box.select_one(".result__snippet")
                if snippet_node:
                    snippet = normalize_text(snippet_node.get_text(" ", strip=True), max_length=1200)
            results.append(SearchResult(title=title, url=url, snippet=snippet, engine="duckduckgo_html"))
            if len(results) >= MAX_RESULTS:
                break

        return results

    def fetch_page_item(self, keyword: str, result: SearchResult) -> Optional[dict]:
        try:
            response = self.session.get(result.url, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException:
            return None

        content_type = response.headers.get("Content-Type", "")
        if "text/html" not in content_type:
            return None

        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = normalize_text(soup.get_text(" ", strip=True), max_length=20000)
        if not page_text:
            return None

        keyword_terms = [term.lower() for term in re.split(r"\s+", keyword) if term.strip()]
        lowered_page_text = page_text.lower()
        if keyword_terms and not any(term in lowered_page_text for term in keyword_terms):
            return None

        title = ""
        for selector in ["meta[property='og:title']", "title", "h1"]:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                title = normalize_text(node.get("content", ""), max_length=500)
            else:
                title = normalize_text(node.get_text(" ", strip=True), max_length=500)
            if title:
                break
        if not title:
            title = result.title

        summary = ""
        for selector in ["meta[name='description']", "meta[property='og:description']", "main p", "article p", "p"]:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                summary = normalize_text(node.get("content", ""), max_length=2000)
            else:
                summary = normalize_text(node.get_text(" ", strip=True), max_length=2000)
            if len(summary) >= 30:
                break
        if not summary:
            summary = result.snippet

        if not matches_allowed_topics(keyword, title, summary, page_text[:5000]):
            return None

        published_at = ""
        for selector in ["meta[property='article:published_time']", "meta[name='pubdate']", "time[datetime]"]:
            node = soup.select_one(selector)
            if not node:
                continue
            value = normalize_text(node.get("content") or node.get("datetime") or node.get_text(" ", strip=True), max_length=100)
            if value:
                published_at = value[:10] if re.match(r"20\d{2}-\d{2}-\d{2}", value) else value
                break

        domain = urlparse(result.url).netloc.lower()
        source_type = classify_source_type(domain, result.url, title, summary)
        return {
            "source_name": f"Keyword / Web / {domain}",
            "source_type": source_type,
            "title": title,
            "url": result.url,
            "published_at": published_at,
            "raw_summary": summary,
            "raw_text": "\n\n".join([
                summary,
                f"Keyword collector source: {result.engine}",
                f"Keyword: {keyword}",
                f"Search title: {result.title}",
                f"Search snippet: {result.snippet}",
                page_text[:3000],
            ]).strip(),
        }

    def collect(self, keyword: str) -> dict:
        normalized_keyword = normalize_text(keyword, max_length=200)
        if not normalized_keyword:
            return {"keyword": "", "inserted": 0, "skipped": 0, "by_source": {}}

        candidate_items: list[dict] = []
        candidate_items.extend(self.fetch_google_news_items(normalized_keyword))

        for result in self.search_duckduckgo(normalized_keyword):
            item = self.fetch_page_item(normalized_keyword, result)
            if item:
                candidate_items.append(item)

        inserted = 0
        skipped = 0
        by_source: dict[str, int] = {}
        seen_urls: set[str] = set()

        for item in candidate_items:
            url = canonicalize_url(item.get("url"))
            if not url or url in seen_urls:
                skipped += 1
                continue
            seen_urls.add(url)
            item["url"] = url
            if save_raw_item(item):
                inserted += 1
                by_source[item["source_name"]] = by_source.get(item["source_name"], 0) + 1
            else:
                skipped += 1

        return {
            "keyword": normalized_keyword,
            "inserted": inserted,
            "skipped": skipped,
            "by_source": by_source,
        }
