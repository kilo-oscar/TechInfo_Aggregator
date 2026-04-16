import argparse
import json
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import parse_qs, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from app import app
from crawler_utils import is_within_last_3_years, normalize_text, save_raw_item
from crawlers.official_site_common import fetch_html, extract_candidate_links

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
SEARCH_URL = "https://html.duckduckgo.com/html/"
TIMEOUT = 20
DEFAULT_DELAY = 1.0
DEFAULT_MAX_RESULTS = 10
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"

POLICY_KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "フィジカルAI",
    "ai agent",
    "agent ai",
    "agentic ai",
    "aiエージェント",
    "ai エージェント",
    "エージェントai",
    "エージェント ai",
    "aiロボティクス",
    "ai robotics",
    "embodied ai",
    "robot",
    "robotics",
    "ロボット",
    "ロボティクス",
    "humanoid",
    "ヒューマノイド",
    "manipulation",
    "遠隔操作",
    "ロボット 遠隔操作",
    "ロボット リモートオペレーション",
    "リモートオペレーション",
    "teleoperation",
    "ハプティクス",
    "haptics",
    "ムーンショット",
    "society 5.0",
    "自動化",
    "自律",
    "協働ロボット",
    "産業用ロボット",
]

NEGATIVE_KEYWORDS = [
    "youtube",
    "facebook",
    "instagram",
    "linkedin",
    "採用",
    "入札",
    "調達情報",
    "調達公告",
    "官報",
]

SOURCE_CONFIGS = [
    {
        "name": "METI / Robot Policy",
        "domain": "meti.go.jp",
        "seed_urls": [
            "https://www.meti.go.jp/policy/mono_info_service/mono/robot/index.html",
            "https://www.meti.go.jp/shingikai/mono_info_service/ai_robotics/index.html",
            "https://www.meti.go.jp/rss/",
        ],
        "queries": [
            'site:meti.go.jp ロボット 政策 AI',
            'site:meti.go.jp AIロボティクス ロボット政策',
            'site:meti.go.jp フィジカルAI ロボティクス',
            'site:meti.go.jp AIエージェント 自動化',
            'site:meti.go.jp ロボット 遠隔操作',
            'site:meti.go.jp ロボット リモートオペレーション',
        ],
        "news_query": 'site:meti.go.jp ロボット OR AIロボティクス OR フィジカルAI OR AIエージェント OR 産業用ロボット OR 遠隔操作 OR リモートオペレーション',
    },
    {
        "name": "MEXT / AI・Robot",
        "domain": "mext.go.jp",
        "seed_urls": [
            "https://www.mext.go.jp/",
        ],
        "queries": [
            'site:mext.go.jp ロボット AI 文部科学省',
            'site:mext.go.jp ムーンショット ロボット AI',
            'site:mext.go.jp AI for Science ロボット',
            'site:mext.go.jp AIエージェント 研究',
            'site:mext.go.jp ロボット 遠隔操作',
            'site:mext.go.jp ロボット リモートオペレーション',
        ],
        "news_query": 'site:mext.go.jp ロボット OR AI OR AIエージェント OR ムーンショット OR 遠隔操作 OR リモートオペレーション',
    },
    {
        "name": "Cabinet Office / Society 5.0",
        "domain": "cao.go.jp",
        "seed_urls": [
            "https://www8.cao.go.jp/cstp/society5_0/",
        ],
        "queries": [
            'site:cao.go.jp Society 5.0 AI ロボット',
            'site:cao.go.jp AI ロボティクス 関係府省',
            'site:cao.go.jp AIエージェント 自動化',
            'site:cao.go.jp ロボット 遠隔操作',
            'site:cao.go.jp ロボット リモートオペレーション',
        ],
        "news_query": 'site:cao.go.jp Society 5.0 OR ロボット OR AI OR AIエージェント OR 遠隔操作 OR リモートオペレーション',
    },
    {
        "name": "NEDO / Robot・AI",
        "domain": "nedo.go.jp",
        "seed_urls": [
            "https://www.nedo.go.jp/koubo/",
            "https://www.nedo.go.jp/activities/ZZJP2_100063.html",
            "https://www.nedo.go.jp/activities/ZZJP2_100133.html",
        ],
        "queries": [
            'site:nedo.go.jp ロボット AI 公募',
            'site:nedo.go.jp フィジカルAI ロボット',
            'site:nedo.go.jp AIロボット マルチモーダル',
            'site:nedo.go.jp AIエージェント 自動化',
            'site:nedo.go.jp ロボット 遠隔操作',
            'site:nedo.go.jp ロボット リモートオペレーション',
        ],
        "news_query": 'site:nedo.go.jp ロボット OR AIロボット OR フィジカルAI OR AIエージェント OR 公募 OR 遠隔操作 OR リモートオペレーション',
    },
    {
        "name": "JST / Moonshot・AIP",
        "domain": "jst.go.jp",
        "seed_urls": [
            "https://www.jst.go.jp/moonshot/program/goal3/index.html",
            "https://www.jst.go.jp/kisoken/presto/research_area/bunya2024-1.html",
            "https://www.jst.go.jp/kisoken/boshuu/teian/top/ryoiki/ryoiki_p11.html",
        ],
        "queries": [
            'site:jst.go.jp ムーンショット 目標3 ロボット',
            'site:jst.go.jp AI ロボット 研究領域',
            'site:jst.go.jp AIエージェント 研究',
            'site:jst.go.jp ロボット 遠隔操作',
            'site:jst.go.jp ロボット リモートオペレーション',
        ],
        "news_query": 'site:jst.go.jp ロボット OR AI OR AIエージェント OR ムーンショット OR 遠隔操作 OR リモートオペレーション',
    },
    {
        "name": "MIC / ICT・Remote Robotics",
        "domain": "soumu.go.jp",
        "seed_urls": [
            "https://www.soumu.go.jp/",
        ],
        "queries": [
            'site:soumu.go.jp ロボット AI 遠隔操作',
            'site:soumu.go.jp AI ロボット 5G',
            'site:soumu.go.jp AIエージェント 自動化',
            'site:soumu.go.jp ロボット リモートオペレーション',
        ],
        "news_query": 'site:soumu.go.jp ロボット OR AI OR AIエージェント OR 遠隔操作 OR リモートオペレーション OR 5G',
    },
]

DATE_PATTERNS = [
    re.compile(r"(20\d{2}[/-]\d{1,2}[/-]\d{1,2})"),
    re.compile(r"(20\d{2}年\d{1,2}月\d{1,2}日)"),
]


@dataclass
class SearchResult:
    query: str
    title: str
    url: str
    snippet: str
    source_name: str
    source_domain: str
    engine: str = "duckduckgo_html"


class GovernmentPolicyCrawler:
    def __init__(self, delay: float = DEFAULT_DELAY, max_results: int = DEFAULT_MAX_RESULTS):
        self.delay = delay
        self.max_results = max_results
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def search(self, query: str, source_name: str, source_domain: str) -> list[SearchResult]:
        try:
            response = self.session.post(SEARCH_URL, data={"q": query}, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[WARN] government search failed: query={query} error={exc}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []

        for a in soup.select("a.result__a"):
            href = a.get("href", "").strip()
            title = normalize_text(a.get_text(" ", strip=True), max_length=500)
            url = self.unwrap_redirect(href)
            if not title or not url:
                continue
            if source_domain not in (urlparse(url).netloc or ""):
                continue

            snippet = ""
            box = a.find_parent(class_="result")
            if box:
                snippet_node = box.select_one(".result__snippet")
                if snippet_node:
                    snippet = normalize_text(snippet_node.get_text(" ", strip=True), max_length=1000)

            result = SearchResult(
                query=query,
                title=title,
                url=url,
                snippet=snippet,
                source_name=source_name,
                source_domain=source_domain,
            )
            if self.looks_like_policy(result):
                results.append(result)
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

    def looks_like_policy(self, result: SearchResult) -> bool:
        blob = f"{result.title} {result.snippet} {result.url}".lower()
        if any(bad in blob for bad in NEGATIVE_KEYWORDS):
            return False
        return any(word in blob for word in POLICY_KEYWORDS)

    def fetch_html(self, url: str) -> Optional[str]:
        try:
            response = self.session.get(url, timeout=TIMEOUT)
            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                return None
            response.encoding = response.apparent_encoding
            return response.text
        except requests.RequestException as exc:
            print(f"[WARN] government fetch failed: url={url} error={exc}")
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
                text = normalize_text(node.get("content", ""), max_length=1600)
            else:
                text = normalize_text(node.get_text(" ", strip=True), max_length=1600)
            if len(text) >= 30:
                return text
        return ""

    def extract_date(self, soup: BeautifulSoup, fallback_text: str = "") -> str:
        candidates = []
        for selector in [
            "meta[property='article:published_time']",
            "meta[name='date']",
            "time[datetime]",
        ]:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                value = node.get("content", "")
            else:
                value = node.get("datetime", "") or node.get_text(" ", strip=True)
            if value:
                candidates.append(value)

        if fallback_text:
            candidates.append(fallback_text)

        for raw in candidates:
            normalized = self.normalize_date(raw)
            if normalized:
                return normalized
        return ""

    def normalize_date(self, value: str) -> str:
        value = normalize_text(value, max_length=100)
        if not value:
            return ""

        for fmt in [
            "%Y-%m-%d",
            "%Y/%m/%d",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y年%m月%d日",
        ]:
            try:
                from datetime import datetime
                return datetime.strptime(value[:19], fmt).date().isoformat()
            except ValueError:
                pass

        try:
            return parsedate_to_datetime(value).date().isoformat()
        except Exception:
            pass

        for pattern in DATE_PATTERNS:
            match = pattern.search(value)
            if match:
                raw = match.group(1)
                raw = raw.replace("年", "-").replace("月", "-").replace("日", "")
                raw = raw.replace("/", "-")
                parts = raw.split("-")
                if len(parts) == 3:
                    yyyy, mm, dd = parts
                    return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
        return ""

    def build_item_from_search_result(self, result: SearchResult) -> Optional[dict]:
        parsed = urlparse(result.url)
        source_domain = parsed.netloc
        is_pdf = result.url.lower().endswith(".pdf")
        title = result.title
        summary = result.snippet
        published_at = self.normalize_date(result.snippet)
        raw_text = {
            "kind": "government_policy_search",
            "query": result.query,
            "engine": result.engine,
            "source_domain": source_domain,
            "is_pdf": is_pdf,
        }

        if not is_pdf:
            html = self.fetch_html(result.url)
            if html:
                soup = BeautifulSoup(html, "html.parser")
                page_title = self.extract_title(soup)
                if page_title:
                    title = page_title
                page_summary = self.extract_summary(soup)
                if page_summary:
                    summary = page_summary
                page_date = self.extract_date(soup, fallback_text=result.snippet)
                if page_date:
                    published_at = page_date

        if not self.text_matches_policy(f"{title} {summary} {result.url}"):
            return None

        return {
            "source_name": result.source_name,
            "source_type": "policy",
            "title": normalize_text(title, max_length=500),
            "url": result.url,
            "published_at": published_at,
            "raw_summary": normalize_text(summary, max_length=2000),
            "raw_text": json.dumps(raw_text, ensure_ascii=False, indent=2),
        }

    def text_matches_policy(self, text: str) -> bool:
        lower = (text or "").lower()
        if any(bad in lower for bad in NEGATIVE_KEYWORDS):
            return False
        return any(word in lower for word in POLICY_KEYWORDS)


def format_google_news_url(query: str, hl: str = "ja", gl: str = "JP", ceid: str = "JP:ja") -> str:
    from urllib.parse import urlencode

    params = {
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid,
    }
    return f"{GOOGLE_NEWS_RSS_BASE}?{urlencode(params)}"


def normalize_feed_published(entry) -> str:
    published = getattr(entry, "published", "") or ""
    if not published:
        return ""
    try:
        dt = parsedate_to_datetime(published)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return published


def fetch_google_news_items(feed_url: str, logical_source_name: str, source_domain: str) -> list[dict]:
    feed = feedparser.parse(feed_url)
    items = []

    for entry in feed.entries:
        url = getattr(entry, "link", "")
        if source_domain not in (urlparse(url).netloc or ""):
            continue
        title = normalize_text(getattr(entry, "title", "") or "", max_length=500)
        raw_summary = normalize_text(getattr(entry, "summary", "") or "", max_length=2000)
        if not any(word in f"{title} {raw_summary} {url}".lower() for word in POLICY_KEYWORDS):
            continue
        items.append({
            "source_name": logical_source_name,
            "source_type": "policy",
            "title": title,
            "url": url,
            "published_at": normalize_feed_published(entry),
            "raw_summary": raw_summary,
            "raw_text": json.dumps({
                "kind": "government_policy_google_news",
                "source_domain": source_domain,
            }, ensure_ascii=False, indent=2),
        })
    return items


def fetch_seed_items(source_name: str, seed_urls: list[str]) -> list[dict]:
    items: list[dict] = []
    for url in seed_urls:
        try:
            html = fetch_html(url)
            candidates = extract_candidate_links(url, html)
            for item in candidates:
                blob = " ".join([
                    item.get("title", ""),
                    item.get("raw_summary", ""),
                    item.get("raw_text", ""),
                    item.get("url", ""),
                ])
                if not any(word in blob.lower() for word in POLICY_KEYWORDS):
                    continue
                items.append({
                    "source_name": source_name,
                    "source_type": "policy",
                    "title": normalize_text(item.get("title", ""), max_length=500),
                    "url": item.get("url", ""),
                    "published_at": item.get("published_at", ""),
                    "raw_summary": normalize_text(item.get("raw_summary", ""), max_length=2000),
                    "raw_text": json.dumps({
                        "kind": "government_policy_seed",
                        "seed_url": url,
                        "raw_text": normalize_text(item.get("raw_text", ""), max_length=5000),
                    }, ensure_ascii=False, indent=2),
                })
        except Exception as exc:
            print(f"[WARN] seed crawl failed: {url} -> {exc}")
    return items


def dedupe_by_url(items: list[dict]) -> list[dict]:
    unique = {}
    for item in items:
        url = item.get("url", "")
        if not url:
            continue
        unique[url] = item
    return list(unique.values())


def build_default_items(delay: float = DEFAULT_DELAY, max_results: int = DEFAULT_MAX_RESULTS) -> list[dict]:
    crawler = GovernmentPolicyCrawler(delay=delay, max_results=max_results)
    items: list[dict] = []

    for config in SOURCE_CONFIGS:
        source_name = config["name"]
        source_domain = config["domain"]

        items.extend(fetch_seed_items(source_name=source_name, seed_urls=config.get("seed_urls", [])))

        for query in config.get("queries", []):
            results = crawler.search(query=query, source_name=source_name, source_domain=source_domain)
            for result in results:
                item = crawler.build_item_from_search_result(result)
                if item:
                    items.append(item)
            time.sleep(delay)

        news_query = config.get("news_query", "")
        if news_query:
            feed_url = format_google_news_url(query=news_query, hl="ja", gl="JP", ceid="JP:ja")
            items.extend(fetch_google_news_items(feed_url, source_name, source_domain))
            time.sleep(delay)

    return dedupe_by_url(items)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="政府系Physical AI / Robotics政策クローラ")
    parser.add_argument("--max-results", type=int, default=DEFAULT_MAX_RESULTS, help="各検索クエリの最大取得件数")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="リクエスト間隔（秒）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    all_items = build_default_items(delay=args.delay, max_results=args.max_results)

    with app.app_context():
        inserted = 0
        skipped = 0
        old_skipped = 0

        for item in all_items:
            published_at = item.get("published_at")
            if published_at and not is_within_last_3_years(published_at):
                old_skipped += 1
                continue
            if item.get("url") and save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(
            f"Government policy crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}"
        )


if __name__ == "__main__":
    main()
