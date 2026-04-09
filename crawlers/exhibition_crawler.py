import argparse
import hashlib
import json
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup

from app import app
from crawler_utils import normalize_text, save_raw_item

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SEARCH_URL = "https://html.duckduckgo.com/html/"
TIMEOUT = 20
DEFAULT_DELAY = 1.0
DEFAULT_MAX_RESULTS = 10

DEFAULT_QUERIES = [
    "physical AI exhibition",
    "physical AI expo",
    "robotics exhibition",
    "robotics trade show",
    "robotics expo",
    "industrial robotics exhibition",
    "automation robotics expo",
    "embodied AI exhibition",
    "humanoid robot exhibition",
    "robotics summit expo",
]

POSITIVE_KEYWORDS = [
    "expo",
    "exhibition",
    "trade show",
    "trade fair",
    "fair",
    "conference",
    "summit",
    "show",
    "event",
    "robot",
    "robotics",
    "automation",
    "physical ai",
    "embodied ai",
    "humanoid",
]

NEGATIVE_KEYWORDS = [
    "job",
    "career",
    "course",
    "webinar",
    "youtube",
    "facebook",
    "instagram",
    "linkedin",
    "hotel",
    "travel",
    "news article",
    "stock",
    "investor",
    "recruit",
]

MONTH_PATTERN = (
    r"January|February|March|April|May|June|July|August|September|October|November|December|"
    r"Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)


@dataclass
class SearchResult:
    query: str
    title: str
    url: str
    snippet: str
    engine: str = "duckduckgo_html"


class ExhibitionCrawler:
    def __init__(self, delay: float = DEFAULT_DELAY, max_results: int = DEFAULT_MAX_RESULTS):
        self.delay = delay
        self.max_results = max_results
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def search(self, query: str) -> list[SearchResult]:
        try:
            response = self.session.post(SEARCH_URL, data={"q": query}, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[WARN] search failed: query={query} error={exc}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []

        for a in soup.select("a.result__a"):
            href = a.get("href", "").strip()
            title = normalize_text(a.get_text(" ", strip=True), max_length=500)
            url = self.unwrap_redirect(href)
            if not title or not url:
                continue

            snippet = ""
            box = a.find_parent(class_="result")
            if box:
                snippet_node = box.select_one(".result__snippet")
                if snippet_node:
                    snippet = normalize_text(snippet_node.get_text(" ", strip=True), max_length=1000)

            results.append(SearchResult(query=query, title=title, url=url, snippet=snippet))
            if len(results) >= self.max_results:
                break

        return results

    def unwrap_redirect(self, href: str) -> Optional[str]:
        if not href.startswith(("http://", "https://")):
            return None
        parsed = urlparse(href)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            qs = parse_qs(parsed.query)
            return qs.get("uddg", [None])[0]
        return href

    def looks_like_event(self, result: SearchResult) -> bool:
        blob = f"{result.title} {result.snippet} {result.url}".lower()
        if any(bad in blob for bad in NEGATIVE_KEYWORDS):
            return False
        return any(good in blob for good in POSITIVE_KEYWORDS)

    def fetch_html(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            if "text/html" not in response.headers.get("Content-Type", ""):
                return None
            response.encoding = response.apparent_encoding
            return response.text
        except requests.RequestException as exc:
            print(f"[WARN] fetch failed: url={url} error={exc}")
            return None

    def extract_title(self, soup: BeautifulSoup) -> str:
        for selector in ["meta[property='og:title']", "title", "h1"]:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                text = normalize_text(node.get("content", ""), max_length=500)
            else:
                text = normalize_text(node.get_text(" ", strip=True), max_length=500)
            if text:
                return text
        return ""

    def extract_summary(self, soup: BeautifulSoup) -> str:
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
                text = normalize_text(node.get("content", ""), max_length=1200)
            else:
                text = normalize_text(node.get_text(" ", strip=True), max_length=1200)
            if len(text) >= 30:
                return text
        return ""

    def parse_date(self, value: str) -> Optional[str]:
        from datetime import datetime

        candidates = [
            "%B %d, %Y",
            "%b %d, %Y",
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y年%m月%d日",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
        return None

    def extract_date_range(self, text: str) -> tuple[Optional[str], Optional[str]]:
        text = text.replace("–", "-")

        patterns = [
            rf"(({MONTH_PATTERN})\s+\d{{1,2}}-\d{{1,2}},\s*\d{{4}})",
            rf"(\d{{1,2}}-\d{{1,2}}\s+({MONTH_PATTERN})\s+\d{{4}})",
            rf"(({MONTH_PATTERN})\s+\d{{1,2}},\s*\d{{4}})",
            r"(20\d{2}[/-]\d{1,2}[/-]\d{1,2})",
            r"(20\d{2}年\d{1,2}月\d{1,2}日)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            raw = normalize_text(match.group(1))

            m = re.match(r"([A-Za-z]+)\s+(\d{1,2})-(\d{1,2}),\s*(\d{4})", raw)
            if m:
                mon, d1, d2, year = m.groups()
                return self.parse_date(f"{mon} {d1}, {year}"), self.parse_date(f"{mon} {d2}, {year}")

            m = re.match(r"(\d{1,2})-(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
            if m:
                d1, d2, mon, year = m.groups()
                return self.parse_date(f"{mon} {d1}, {year}"), self.parse_date(f"{mon} {d2}, {year}")

            parsed = self.parse_date(raw)
            if parsed:
                return parsed, parsed

        return None, None

    def extract_location(self, text: str) -> str:
        patterns = [
            r"(?:Location|Venue|Place)[:\s]+([^|]{5,120})",
            r"(?:held at|takes place at|hosted at)\s+([^|]{5,120})",
            r"([A-Z][A-Za-z .&'\-/]{2,60},\s*[A-Z][A-Za-z .&'\-/]{2,60})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return normalize_text(match.group(1), max_length=120)
        return ""

    def extract_organizer(self, text: str) -> str:
        patterns = [
            r"(?:Organized by|Organizer|Organiser)[:\s]+([A-Z][A-Za-z0-9 .,&()'\-/]{2,100})",
            r"(?:organized by|organised by)\s+([A-Z][A-Za-z0-9 .,&()'\-/]{2,100})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return normalize_text(match.group(1), max_length=120)
        return ""

    def build_item(self, result: SearchResult) -> Optional[dict]:
        html = self.fetch_html(result.url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        page_text = normalize_text(soup.get_text(" ", strip=True), max_length=50000)
        title = self.extract_title(soup) or result.title
        summary = self.extract_summary(soup) or result.snippet or result.title
        start_date, end_date = self.extract_date_range(page_text)
        location = self.extract_location(page_text)
        organizer = self.extract_organizer(page_text)
        domain = urlparse(result.url).netloc

        raw_payload = {
            "kind": "exhibition_event",
            "search_query": result.query,
            "search_engine": result.engine,
            "event_name": title,
            "source_domain": domain,
            "official_url": result.url,
            "start_date": start_date,
            "end_date": end_date,
            "location": location,
            "organizer": organizer,
            "search_snippet": result.snippet,
            "summary": summary,
            "page_excerpt": page_text[:3000],
        }

        raw_text = json.dumps(raw_payload, ensure_ascii=False, indent=2)
        signature = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()[:10]
        event_title = title
        if start_date:
            event_title = f"{title} [{start_date}]"

        return {
            "source_name": f"Exhibition Search / {domain}",
            "source_type": "event",
            "title": normalize_text(event_title, max_length=500),
            "url": result.url,
            "published_at": start_date or "",
            "raw_summary": normalize_text(summary, max_length=2000),
            "raw_text": f"Event signature: {signature}\n\n{raw_text}",
        }

    def crawl(self, queries: list[str]) -> tuple[int, int]:
        seen_urls: set[str] = set()
        inserted = 0
        skipped = 0

        with app.app_context():
            for query in queries:
                print(f"[INFO] search query={query}")
                for result in self.search(query):
                    if not self.looks_like_event(result):
                        continue

                    canonical_url = self.unwrap_redirect(result.url) or result.url
                    if canonical_url in seen_urls:
                        continue
                    seen_urls.add(canonical_url)

                    item = self.build_item(result)
                    if not item or not item["url"]:
                        skipped += 1
                        continue

                    if save_raw_item(item):
                        inserted += 1
                        print(f"[SAVE] {item['title']}")
                    else:
                        skipped += 1
                    time.sleep(self.delay)

        return inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Search-based exhibition crawler for TechInfo_Aggregator")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS)
    parser.add_argument("--queries", nargs="*", default=DEFAULT_QUERIES)
    args = parser.parse_args()

    crawler = ExhibitionCrawler(delay=args.delay, max_results=args.max_results)
    inserted, skipped = crawler.crawl(args.queries)
    print(f"Exhibition crawler: inserted={inserted}, skipped={skipped}")


if __name__ == "__main__":
    main()
