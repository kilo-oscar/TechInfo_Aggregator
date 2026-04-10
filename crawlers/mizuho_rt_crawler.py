from __future__ import annotations

import json
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import parse_qs, urlparse
import urllib.parse

import feedparser
import requests
from bs4 import BeautifulSoup

from app import app
from crawler_utils import is_within_last_3_years, normalize_text, save_raw_item


SOURCE_NAME = "みずほリサーチ&テクノロジーズ"
SOURCE_TYPE = "thinktank"
SEARCH_URL = "https://html.duckduckgo.com/html/"
GOOGLE_NEWS_RSS_BASE = "https://news.google.com/rss/search"
JINA_READER_PREFIX = "https://r.jina.ai/http://"
TIMEOUT = 20
MAX_RESULTS_PER_QUERY = 10

ALLOWED_DOMAINS = ["mizuhobank.co.jp", "www.mizuhobank.co.jp"]
SEED_URLS = [
    "https://www.mizuhobank.co.jp/corporate/tech/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/report/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/project-case/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/news/index.html",
    "https://www.mizuhobank.co.jp/corporate/mhri/research/index.html",
    "https://www.mizuhobank.co.jp/corporate/mhri/research/report/index.html",
    "https://www.mizuhobank.co.jp/corporate/industry/",
    "https://www.mizuhobank.co.jp/corporate/industry/pdf/msif_265.pdf",
]
ALLOWED_PATH_KEYWORDS = [
    "/corporate/tech/report/",
    "/corporate/tech/project-case/",
    "/corporate/tech/news/",
    "/corporate/mhri/research/report/",
    "/corporate/mhri/research/",
    "/corporate/industry/",
    "/corporate/industry/pdf/",
]

QUERIES = [
    'site:mizuhobank.co.jp/corporate/tech/ "Physical AI" OR フィジカルAI OR embodied AI',
    'site:mizuhobank.co.jp/corporate/tech/ ロボット OR robotics OR ヒューマノイド',
    'site:mizuhobank.co.jp/corporate/tech/ 画像解析 OR 画像認識 OR 機械学習 OR 自然言語処理',
    'site:mizuhobank.co.jp/corporate/mhri/research/ ロボット OR robotics OR 自動化 OR AI',
    'site:mizuhobank.co.jp/corporate/tech/report/ AI OR 人工知能 OR 機械学習 OR データ分析',
    'site:mizuhobank.co.jp/corporate/tech/project-case/ AI OR 画像解析 OR センシング OR 制御',
    'site:mizuhobank.co.jp/corporate/tech/news/ AI OR ロボット OR 自動化 OR デジタルツイン',
    'site:mizuhobank.co.jp/corporate/mhri/research/report/ AI OR ロボット OR DX OR 自動化',
    'site:mizuhobank.co.jp/corporate/mhri/research/ 生成AI OR AI活用 OR 画像認識 OR センシング',
    'site:mizuhobank.co.jp/corporate/tech/ "digital twin" OR デジタルツイン OR simulation OR シミュレーション',
    'site:mizuhobank.co.jp/corporate/tech/ 産業用ロボット OR 協働ロボット OR 遠隔操作',
    'site:mizuhobank.co.jp/corporate/tech/ foundation model OR world model OR multimodal',
    'site:mizuhobank.co.jp/corporate/industry/ AI OR ロボット OR 自動化 OR DX',
    'site:mizuhobank.co.jp/corporate/industry/ 画像解析 OR 機械学習 OR データ分析',
    'site:mizuhobank.co.jp/corporate/industry/ 物流 OR 製造 OR 点検 OR 防災 AI',
    'site:mizuhobank.co.jp/corporate/industry/pdf/ AI OR フィジカルAI OR デジタルツイン OR PDF',
]

GOOGLE_NEWS_QUERIES = [
    'site:mizuhobank.co.jp/corporate/tech/ AI OR ロボット OR 自動化',
    'site:mizuhobank.co.jp/corporate/tech/ 画像解析 OR 機械学習 OR デジタルツイン',
    'site:mizuhobank.co.jp/corporate/mhri/research/ AI OR ロボット OR DX OR 自動化',
    'site:mizuhobank.co.jp/corporate/tech/project-case/ AI OR センシング OR 制御',
    'site:mizuhobank.co.jp/corporate/industry/ AI OR ロボット OR 自動化 OR DX',
]

PRIMARY_KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "フィジカル ai",
    "embodied ai",
    "エージェンティック ai",
    "agentic ai",
    "ロボット",
    "robot",
    "robotics",
    "ヒューマノイド",
    "humanoid",
    "自動化",
    "制御",
    "センシング",
    "デジタルツイン",
    "digital twin",
    "画像解析",
    "画像認識",
    "機械学習",
    "自然言語処理",
]

AI_KEYWORDS = [
    "ai",
    "artificial intelligence",
    "生成ai",
    "生成 ai",
    "llm",
    "multimodal",
    "マルチモーダル",
    "機械学習",
    "深層学習",
    "画像解析",
    "画像認識",
    "自然言語処理",
]

INDUSTRY_KEYWORDS = [
    "自動化",
    "省人化",
    "制御",
    "センシング",
    "シミュレーション",
    "simulation",
    "デジタルツイン",
    "digital twin",
    "遠隔",
    "現場",
    "設備",
    "製造",
    "工場",
    "点検",
    "防災",
    "減災",
    "データ分析",
    "画像処理",
    "品質",
    "マネジメント",
    "インフラ",
    "衛星",
]

NEGATIVE_KEYWORDS = [
    "採用",
    "recruit",
    "人事",
    "株主",
    "決算",
]

DATE_PATTERNS = [
    re.compile(r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})"),
    re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日"),
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
}


@dataclass
class SearchResult:
    query: str
    title: str
    url: str
    snippet: str
    engine: str = "duckduckgo_html"
    published_at: str = ""


@dataclass
class SeedCandidate:
    title: str
    url: str
    summary: str = ""


def _canonicalize_url(url: str) -> str:
    normalized = (url or "").strip()
    if normalized.startswith("http://"):
        normalized = "https://" + normalized[len("http://"):]
    return normalized.split("#", 1)[0]


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(_canonicalize_url(url))
    path = parsed.path.lower()
    netloc = parsed.netloc.lower()

    if parsed.scheme not in ("http", "https"):
        return False
    if not any(netloc == domain or netloc.endswith(f".{domain}") for domain in ALLOWED_DOMAINS):
        return False
    return any(keyword in path for keyword in ALLOWED_PATH_KEYWORDS)


def _unwrap_redirect(href: str) -> Optional[str]:
    if not href.startswith(("http://", "https://")):
        return None

    parsed = urlparse(href)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        resolved = qs.get("uddg", [None])[0]
        return _canonicalize_url(resolved) if resolved else None
    return _canonicalize_url(href)


def _extract_date(text: str) -> str:
    normalized = normalize_text(text, max_length=2000)
    for pattern in DATE_PATTERNS:
        match = pattern.search(normalized)
        if not match:
            continue
        yyyy, mm, dd = match.groups()
        return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
    return ""


def _jina_reader_url(url: str) -> str:
    normalized = url
    if normalized.startswith("https://"):
        normalized = normalized[len("https://"):]
    elif normalized.startswith("http://"):
        normalized = normalized[len("http://"):]
    return f"{JINA_READER_PREFIX}{normalized}"


def _fetch_mizuho_page(url: str) -> tuple[str, str]:
    response = requests.get(_jina_reader_url(url), headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    response.encoding = "utf-8"
    return response.text, "markdown"


def _search(query: str) -> list[SearchResult]:
    response = requests.post(SEARCH_URL, data={"q": query}, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results: list[SearchResult] = []

    for a in soup.select("a.result__a"):
        href = (a.get("href") or "").strip()
        url = _unwrap_redirect(href)
        if not url or not _is_allowed_url(url):
            continue

        title = normalize_text(a.get_text(" ", strip=True), max_length=500)
        if not title:
            continue

        snippet = ""
        box = a.find_parent(class_="result")
        if box:
            snippet_node = box.select_one(".result__snippet")
            if snippet_node:
                snippet = normalize_text(snippet_node.get_text(" ", strip=True), max_length=2000)

        results.append(
            SearchResult(
                query=query,
                title=title,
                url=url,
                snippet=snippet,
                engine="duckduckgo_html",
            )
        )
        if len(results) >= MAX_RESULTS_PER_QUERY:
            break

    return results


def _format_google_news_url(query: str, hl: str = "ja", gl: str = "JP", ceid: str = "JP:ja") -> str:
    params = {
        "q": query,
        "hl": hl,
        "gl": gl,
        "ceid": ceid,
    }
    return f"{GOOGLE_NEWS_RSS_BASE}?{urllib.parse.urlencode(params)}"


def _normalize_google_news_published(entry) -> str:
    published = getattr(entry, "published", "") or ""
    if not published:
        return ""

    try:
        dt = parsedate_to_datetime(published)
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return published


def _fetch_google_news_results(query: str) -> list[SearchResult]:
    feed_url = _format_google_news_url(query=query, hl="ja", gl="JP", ceid="JP:ja")
    feed = feedparser.parse(feed_url)
    results: list[SearchResult] = []

    for entry in feed.entries:
        url = getattr(entry, "link", "") or ""
        title = normalize_text(getattr(entry, "title", "") or "", max_length=500)
        snippet = normalize_text(getattr(entry, "summary", "") or "", max_length=2000)

        if not url or not title:
            continue
        if not _is_allowed_url(url):
            continue

        results.append(
            SearchResult(
                query=query,
                title=title,
                url=url,
                snippet=snippet,
                engine="google_news_rss",
                published_at=_normalize_google_news_published(entry),
            )
        )

    return results


def _extract_page_summary(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in [
        "meta[name='description']",
        "meta[property='og:description']",
        "main p",
        "article p",
        ".article p",
        ".contents p",
        "p",
    ]:
        node = soup.select_one(selector)
        if not node:
            continue
        if node.name == "meta":
            text = normalize_text(node.get("content", ""), max_length=2000)
        else:
            text = normalize_text(node.get_text(" ", strip=True), max_length=2000)
        if len(text) >= 20:
            return text
    return ""


def _extract_page_body(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for selector in ["main", "article", ".article", ".contents", ".content", "body"]:
        node = soup.select_one(selector)
        if not node:
            continue
        text = normalize_text(node.get_text("\n", strip=True), max_length=12000)
        if len(text) >= 100:
            return text
    return normalize_text(soup.get_text("\n", strip=True), max_length=12000)


def _extract_markdown_summary(text: str) -> str:
    lines = [normalize_text(line, max_length=500) for line in text.splitlines()]
    for line in lines:
        if not line:
            continue
        if line.startswith("Title: "):
            continue
        if line.startswith("URL Source: "):
            continue
        if line.startswith("Published Time: "):
            continue
        if line == "Markdown Content:":
            continue
        if line.startswith("# "):
            continue
        if line.startswith("## "):
            continue
        if line.startswith("### "):
            continue
        if line.startswith("* ["):
            continue
        if line.startswith("["):
            continue
        if line in {"TOP", "REPORT", "NEWS", "PROJECT CASE"}:
            continue
        if len(line) >= 20:
            return line[:2000]
    return ""


def _extract_markdown_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("Title: "):
            return normalize_text(line.replace("Title: ", "", 1), max_length=500)
        if line.startswith("# "):
            return normalize_text(line[2:], max_length=500)
    return fallback


def _extract_markdown_links(text: str) -> list[SeedCandidate]:
    seen: set[str] = set()
    candidates: list[SeedCandidate] = []

    for match in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
        title = normalize_text(match.group(1), max_length=500)
        url = _canonicalize_url(match.group(2))
        if not title or not _is_allowed_url(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        candidates.append(SeedCandidate(title=title, url=url))

    return candidates


def _extract_pdf_links_from_markdown(text: str) -> list[SeedCandidate]:
    seen: set[str] = set()
    candidates: list[SeedCandidate] = []

    for match in re.finditer(r"(https?://[^\s)]+\.pdf)", text, re.IGNORECASE):
        url = _canonicalize_url(match.group(1))
        if not _is_allowed_url(url) or url in seen:
            continue
        seen.add(url)
        filename = url.rsplit("/", 1)[-1]
        candidates.append(SeedCandidate(title=filename, url=url))

    return candidates


def _looks_relevant(title: str, summary: str, body_text: str, url: str) -> bool:
    blob = " ".join([title, summary, body_text, url]).lower()
    surface_blob = " ".join([title, summary, url]).lower()
    path = urlparse(url).path.lower()

    if any(keyword in surface_blob for keyword in NEGATIVE_KEYWORDS):
        return False

    if any(keyword in blob for keyword in PRIMARY_KEYWORDS):
        return True

    ai_hit = any(keyword in blob for keyword in AI_KEYWORDS)
    industry_hit = any(keyword in blob for keyword in INDUSTRY_KEYWORDS)

    if ai_hit and any(
        keyword in path
        for keyword in [
            "/corporate/tech/news/",
            "/corporate/tech/report/",
            "/corporate/tech/project-case/",
            "/corporate/industry/",
        ]
    ):
        return True

    return ai_hit and industry_hit


def _looks_relevant_surface(title: str, summary: str, url: str) -> bool:
    path = urlparse(_canonicalize_url(url)).path.lower()
    if path.startswith("/corporate/industry/pdf/"):
        return True
    return _looks_relevant(title, summary, "", url)


def _build_item(result: SearchResult) -> dict | None:
    title = result.title
    summary = result.snippet
    body_text = ""
    fetch_error = ""

    try:
        page_text, page_format = _fetch_mizuho_page(result.url)
        if page_format == "html":
            page_summary = _extract_page_summary(page_text)
            page_body = _extract_page_body(page_text)
            if page_summary:
                summary = page_summary
            body_text = page_body
        else:
            title = _extract_markdown_title(page_text, title)
            page_summary = _extract_markdown_summary(page_text)
            if page_summary:
                summary = page_summary
            body_text = normalize_text(page_text, max_length=12000)
    except Exception as exc:
        fetch_error = str(exc)

    if not _looks_relevant(title, summary, body_text, result.url):
        return None

    payload = {
        "kind": "thinktank_search_result",
        "source_name": SOURCE_NAME,
        "source_domain": urlparse(_canonicalize_url(result.url)).netloc,
        "search_query": result.query,
        "search_engine": result.engine,
        "search_snippet": result.snippet,
        "fetch_error": fetch_error,
        "raw_text": body_text[:5000],
    }

    return {
        "source_name": SOURCE_NAME,
        "source_type": SOURCE_TYPE,
        "title": normalize_text(title, max_length=500),
        "url": _canonicalize_url(result.url),
        "published_at": result.published_at or _extract_date(" ".join([title, summary, body_text])),
        "raw_summary": normalize_text(summary, max_length=2000),
        "raw_text": json.dumps(payload, ensure_ascii=False, indent=2),
    }


def _fetch_seed_results(seed_url: str) -> list[SearchResult]:
    page_text, page_format = _fetch_mizuho_page(seed_url)
    results: list[SearchResult] = []

    if page_format == "html":
        soup = BeautifulSoup(page_text, "html.parser")
        seen: set[str] = set()
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            url = _canonicalize_url(urllib.parse.urljoin(seed_url, href))
            title = normalize_text(a.get_text(" ", strip=True), max_length=500)
            if not title or not _is_allowed_url(url) or url in seen:
                continue
            seen.add(url)
            results.append(SearchResult(query=seed_url, title=title, url=url, snippet="", engine="seed_html"))
        return results

    for candidate in _extract_markdown_links(page_text):
        results.append(
            SearchResult(
                query=seed_url,
                title=candidate.title,
                url=candidate.url,
                snippet=candidate.summary,
                engine="seed_markdown",
            )
        )

    for candidate in _extract_pdf_links_from_markdown(page_text):
        results.append(
            SearchResult(
                query=seed_url,
                title=candidate.title,
                url=candidate.url,
                snippet=candidate.summary,
                engine="seed_pdf_markdown",
            )
        )

    if seed_url.lower().endswith(".pdf"):
        title = _extract_markdown_title(page_text, seed_url.rsplit("/", 1)[-1])
        summary = _extract_markdown_summary(page_text)
        results.append(
            SearchResult(
                query=seed_url,
                title=title,
                url=_canonicalize_url(seed_url),
                snippet=summary,
                engine="seed_pdf_direct",
            )
        )

    return results


def fetch_mizuho_items() -> list[dict]:
    search_results: dict[str, SearchResult] = {}

    for seed_url in SEED_URLS:
        try:
            for result in _fetch_seed_results(seed_url):
                search_results[result.url] = result
        except Exception as exc:
            print(f"[{SOURCE_NAME}] seed failed: {seed_url} -> {exc}")

    for query in QUERIES:
        try:
            for result in _search(query):
                search_results[result.url] = result
        except Exception as exc:
            print(f"[{SOURCE_NAME}] search failed: {query} -> {exc}")

    for query in GOOGLE_NEWS_QUERIES:
        try:
            for result in _fetch_google_news_results(query):
                search_results[result.url] = result
        except Exception as exc:
            print(f"[{SOURCE_NAME}] google news failed: {query} -> {exc}")

    items: list[dict] = []
    for result in search_results.values():
        if not _looks_relevant_surface(result.title, result.snippet, result.url):
            continue
        item = _build_item(result)
        if item:
            items.append(item)

    unique: dict[str, dict] = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())


def main() -> None:
    items = fetch_mizuho_items()

    with app.app_context():
        inserted = 0
        skipped = 0
        old_skipped = 0

        for item in items:
            published_at = item.get("published_at")
            if published_at and not is_within_last_3_years(published_at):
                old_skipped += 1
                continue

            if item.get("url") and save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(
            f"{SOURCE_NAME} crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}"
        )


if __name__ == "__main__":
    main()
