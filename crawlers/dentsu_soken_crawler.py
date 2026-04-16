from __future__ import annotations

import re
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from app import app
from crawler_utils import canonicalize_url, is_within_last_3_years, normalize_text, save_raw_item
from keyword_collection import DUCKDUCKGO_HTML_SEARCH, USER_AGENT, unwrap_duckduckgo_url


SOURCE_NAME = "電通総研"
TIMEOUT = 20
MAX_RESULTS_PER_QUERY = 10
MAX_TECH_BLOG_ARCHIVE_PAGES = 12
ALLOWED_DOMAINS = {
    "dentsusoken.com",
    "www.dentsusoken.com",
    "group.dentsusoken.com",
    "mfg.dentsusoken.com",
    "tech.dentsusoken.com",
}
ALLOWED_PATH_HINTS = [
    "/news/release/",
    "/news/topics/",
    "/column/",
    "/insight/",
    "/blog/",
    "/feature/",
    "/entry/",
]
TOPIC_KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "フィジカル ai",
    "embodied ai",
    "embodied intelligence",
    "vision language action",
    "vision-language-action",
    "vla",
    "ai agent",
    "agent ai",
    "agentic ai",
    "aiエージェント",
    "ai エージェント",
    "エージェントai",
    "エージェント ai",
    "lerobot",
    "so-arm101",
    "robot foundation model",
    "ロボット基盤モデル",
    "robot",
    "robotics",
    "ロボット",
    "ロボティクス",
    "humanoid",
    "ヒューマノイド",
    "協働ロボット",
    "cobot",
    "産業用ロボット",
    "自律移動",
    "amr",
    "agv",
    "manipulation",
    "ロボット制御",
    "遠隔操作",
    "リモートオペレーション",
    "ロボット 遠隔操作",
    "ロボット リモートオペレーション",
]
SEARCH_QUERIES = [
    "site:dentsusoken.com Physical AI 電通総研",
    "site:dentsusoken.com フィジカルAI 電通総研",
    "site:dentsusoken.com Embodied AI 電通総研",
    "site:dentsusoken.com ロボット 電通総研",
    "site:dentsusoken.com ロボティクス 電通総研",
    "site:dentsusoken.com ヒューマノイド 電通総研",
    "site:dentsusoken.com 協働ロボット 電通総研",
    "site:dentsusoken.com AMR OR AGV 電通総研",
    "site:dentsusoken.com ロボット 遠隔操作 電通総研",
    "site:dentsusoken.com ロボット リモートオペレーション 電通総研",
    "site:mfg.dentsusoken.com ロボット 電通総研",
    "site:mfg.dentsusoken.com ロボティクス 電通総研",
    "site:tech.dentsusoken.com フィジカルAI 電通総研",
    "site:tech.dentsusoken.com Physical AI 電通総研",
    "site:tech.dentsusoken.com AIエージェント 電通総研",
    "site:tech.dentsusoken.com AI agent 電通総研",
    "site:tech.dentsusoken.com agentic AI 電通総研",
    "site:tech.dentsusoken.com ロボット 電通総研",
    "site:tech.dentsusoken.com ロボティクス 電通総研",
    "site:tech.dentsusoken.com VLA 電通総研",
    "site:tech.dentsusoken.com ロボット 遠隔操作 電通総研",
    "site:tech.dentsusoken.com ロボット リモートオペレーション 電通総研",
]
TECH_BLOG_ARCHIVE_URL = "https://tech.dentsusoken.com/archive"


def _blob_has_topic(*texts: str) -> bool:
    blob = " ".join(texts).lower()
    for keyword in TOPIC_KEYWORDS:
        normalized_keyword = keyword.lower()
        if re.fullmatch(r"[a-z0-9 \-]+", normalized_keyword):
            pattern = r"(?<![a-z0-9])" + re.escape(normalized_keyword).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
            if re.search(pattern, blob):
                return True
            continue
        if normalized_keyword in blob:
            return True
    return False


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    if domain not in ALLOWED_DOMAINS:
        return False
    return any(hint in path for hint in ALLOWED_PATH_HINTS)


def _extract_published_at(soup: BeautifulSoup, page_text: str) -> str:
    selectors = [
        "meta[property='article:published_time']",
        "meta[name='pubdate']",
        "time[datetime]",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue
        value = normalize_text(
            node.get("content") or node.get("datetime") or node.get_text(" ", strip=True),
            max_length=100,
        )
        if re.match(r"20\d{2}-\d{2}-\d{2}", value):
            return value[:10]

    patterns = [
        r"(20\d{2}-\d{2}-\d{2})",
        r"(20\d{2}/\d{1,2}/\d{1,2})",
        r"(20\d{2}年\d{1,2}月\d{1,2}日)",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text)
        if match:
            return normalize_text(match.group(1), max_length=20)
    return ""


def _extract_date_from_url(url: str) -> str:
    match = re.search(r"/entry/(20\d{2})/(\d{2})/(\d{2})(?:/|$)", url)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{year}-{month}-{day}"


def _extract_page_text(soup: BeautifulSoup, url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower() == "tech.dentsusoken.com" and "/entry/" in parsed.path.lower():
        parts = []
        for selector in [".entry-header", ".entry-content"]:
            node = soup.select_one(selector)
            if node:
                parts.append(node.get_text(" ", strip=True))
        if parts:
            return normalize_text("\n\n".join(parts), max_length=20000)

    for selector in ["main", "article"]:
        node = soup.select_one(selector)
        if node:
            return normalize_text(node.get_text(" ", strip=True), max_length=20000)

    return normalize_text(soup.get_text(" ", strip=True), max_length=20000)


class DentsuSokenCrawler:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def search(self, query: str) -> list[dict]:
        try:
            response = self.session.post(DUCKDUCKGO_HTML_SEARCH, data={"q": query}, timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[{SOURCE_NAME}] search failed: query={query} error={exc}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[dict] = []

        for node in soup.select("a.result__a"):
            href = normalize_text(node.get("href", ""), max_length=2000)
            url = canonicalize_url(unwrap_duckduckgo_url(href) or "")
            if not url or not _is_allowed_url(url):
                continue

            title = normalize_text(node.get_text(" ", strip=True), max_length=500)
            snippet = ""
            box = node.find_parent(class_="result")
            if box:
                snippet_node = box.select_one(".result__snippet")
                if snippet_node:
                    snippet = normalize_text(snippet_node.get_text(" ", strip=True), max_length=1200)

            if not _blob_has_topic(query, title, snippet, url):
                continue

            results.append({
                "query": query,
                "title": title,
                "url": url,
                "snippet": snippet,
            })
            if len(results) >= MAX_RESULTS_PER_QUERY:
                break

        return results

    def fetch_tech_blog_candidates(self) -> list[dict]:
        candidates: dict[str, dict] = {}
        archive_url = TECH_BLOG_ARCHIVE_URL

        for _ in range(MAX_TECH_BLOG_ARCHIVE_PAGES):
            try:
                response = self.session.get(archive_url, timeout=TIMEOUT)
                response.raise_for_status()
            except requests.RequestException as exc:
                print(f"[{SOURCE_NAME}] tech blog archive failed: url={archive_url} error={exc}")
                break

            response.encoding = response.apparent_encoding
            soup = BeautifulSoup(response.text, "html.parser")

            for node in soup.select("a[href]"):
                href = normalize_text(node.get("href", ""), max_length=2000)
                if not href.startswith("https://tech.dentsusoken.com/entry/"):
                    continue

                url = canonicalize_url(href)
                if not url or not _is_allowed_url(url):
                    continue

                title = normalize_text(node.get_text(" ", strip=True), max_length=500)
                item = candidates.get(url)
                if item is None:
                    candidates[url] = {
                        "query": "tech_blog_archive",
                        "title": title,
                        "url": url,
                        "snippet": "",
                    }
                elif title and len(title) > len(item.get("title", "")):
                    item["title"] = title

            next_link = soup.select_one("a[href*='archive?page=']")
            if not next_link:
                break

            next_href = normalize_text(next_link.get("href", ""), max_length=2000)
            if not next_href or canonicalize_url(next_href) == canonicalize_url(archive_url):
                break
            archive_url = next_href

        return list(candidates.values())

    def build_item(self, result: dict) -> dict | None:
        try:
            response = self.session.get(result["url"], timeout=TIMEOUT)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[{SOURCE_NAME}] fetch failed: url={result['url']} error={exc}")
            return None

        if "text/html" not in response.headers.get("Content-Type", ""):
            return None

        response.encoding = response.apparent_encoding
        soup = BeautifulSoup(response.text, "html.parser")
        page_text = _extract_page_text(soup, result["url"])
        if "Entry is not found" in page_text or "お探しの記事は見つかりませんでした" in page_text:
            return None
        if not page_text or not _blob_has_topic(result["title"], result["snippet"], page_text[:6000]):
            return None

        title = result["title"]
        for selector in ["meta[property='og:title']", "title", "h1"]:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                candidate = normalize_text(node.get("content", ""), max_length=500)
            else:
                candidate = normalize_text(node.get_text(" ", strip=True), max_length=500)
            if candidate:
                title = candidate
                break

        if not _blob_has_topic(title, result["snippet"], page_text[:6000]):
            return None

        summary = result["snippet"]
        summary_selectors = ["meta[name='description']", "meta[property='og:description']", "main p", "article p", "p"]
        parsed = urlparse(result["url"])
        if parsed.netloc.lower() == "tech.dentsusoken.com" and "/entry/" in parsed.path.lower():
            summary_selectors = [".entry-content p", *summary_selectors]

        for selector in summary_selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                candidate = normalize_text(node.get("content", ""), max_length=2000)
            else:
                candidate = normalize_text(node.get_text(" ", strip=True), max_length=2000)
            if len(candidate) >= 30:
                summary = candidate
                break

        if not _blob_has_topic(title, summary, page_text[:6000]):
            return None

        published_at = _extract_date_from_url(result["url"]) or _extract_published_at(soup, page_text)
        return {
            "source_name": SOURCE_NAME,
            "source_type": "thinktank",
            "title": title,
            "url": result["url"],
            "published_at": published_at,
            "raw_summary": summary,
            "raw_text": "\n\n".join([
                f"Search query: {result['query']}",
                f"Search title: {result['title']}",
                f"Search snippet: {result['snippet']}",
                page_text[:5000],
            ]).strip(),
        }

    def crawl(self) -> tuple[int, int, int]:
        candidates: dict[str, dict] = {}
        for query in SEARCH_QUERIES:
            for result in self.search(query):
                candidates[result["url"]] = result
        for result in self.fetch_tech_blog_candidates():
            candidates[result["url"]] = result

        inserted = 0
        skipped = 0
        old_skipped = 0

        with app.app_context():
            for result in candidates.values():
                item = self.build_item(result)
                if not item:
                    skipped += 1
                    continue

                published_at = item.get("published_at")
                if published_at and not is_within_last_3_years(published_at):
                    old_skipped += 1
                    continue

                if save_raw_item(item):
                    inserted += 1
                else:
                    skipped += 1

        return inserted, skipped, old_skipped


def main() -> None:
    crawler = DentsuSokenCrawler()
    inserted, skipped, old_skipped = crawler.crawl()
    print(f"{SOURCE_NAME} crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")


if __name__ == "__main__":
    main()
