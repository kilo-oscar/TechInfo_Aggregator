import argparse
import hashlib
import json
import re
import time
from datetime import date
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

ORGANIZER_FOCUSED_QUERIES = [
    "日刊工業新聞社 主催 ロボット 展示会",
    "日刊工業新聞社 主催 ロボティクス 展示会",
    "日刊工業新聞社 主催 physical AI 展示会",
    "日刊工業新聞社 主催 ヒューマノイド 展示会",
    "日本ロボット工業会 主催 ロボット 展示会",
    "日本ロボット工業会 主催 ロボティクス 展示会",
    "日本ロボット工業会 主催 physical AI 展示会",
    "日本ロボット工業会 主催 ヒューマノイド 展示会",
    "日刊工業新聞社 日本ロボット工業会 展示会 ロボット",
    "日刊工業新聞社 日本ロボット工業会 展示会 ロボティクス",
    "site:nikkan.co.jp ロボット 展示会 日刊工業新聞社",
    "site:nikkan.co.jp ロボティクス 展示会 日刊工業新聞社",
    "site:nikkan.co.jp physical AI 展示会",
    "site:nikkan.co.jp ヒューマノイド 展示会",
    "site:nikkan.co.jp 日本ロボット工業会 展示会",
]

CORPORATE_EVENT_QUERIES = [
    'site:aws.amazon.com/jp "Physical AI" イベント OR 展示 OR 勉強会',
    'site:aws.amazon.com/jp robotics "AWS Summit Japan" 展示',
    'site:nvidia.com/ja-jp/events "Physical AI" OR ロボティクス',
    'site:events.microsoft.com/ja-jp robotics OR "Physical AI" Japan',
    'site:cloud.google.com/events/ja robotics OR "Physical AI"',
    'site:global.toyota/jp フィジカルAI イベント OR 展示',
    'site:global.honda/jp ロボット AI イベント OR 展示',
    'site:sony.com/ja ロボティクス AI イベント OR 展示',
    'site:fujitsu.com/jp フィジカルAI イベント OR 展示',
    'site:nec.com/ja ロボティクス AI イベント OR 展示',
    'site:hitachi.co.jp フィジカルAI イベント OR 展示',
    'site:mitsubishielectric.co.jp ロボット AI イベント OR 展示',
    'site:fanuc.co.jp ロボット AI イベント OR 展示会',
    'site:yaskawa.co.jp ロボット AI イベント OR 展示会',
    'site:khi.co.jp ロボット AI イベント OR 展示',
    'site:omron.com/jp/ja ロボット AI イベント OR 展示',
    'site:softbank.jp フィジカルAI イベント OR 展示',
    'site:nttdata.com/jp/ja ロボティクス AI イベント OR 展示',
]

DEFAULT_QUERIES = [
    "physical AI exhibition",
    "physical AI expo",
    "physical AI expo Japan",
    "physical AI expo Tokyo",
    "robotics exhibition",
    "robotics trade show",
    "robotics expo",
    "robotics expo Japan",
    "robotics exhibition Tokyo",
    "industrial robotics exhibition",
    "automation robotics expo",
    "embodied AI exhibition",
    "humanoid robot exhibition",
    "robotics summit expo",
    "日本 ロボット 展示会 AI",
    "日本 ヒューマノイド 展示会",
    "東京 ロボット 展示会",
    "Japan robot exhibition AI humanoid",
    "IREX Japan robot exhibition",
    "RoboDEX Japan robotics expo",
    "NexTech Week AI Expo Tokyo",
    "Manufacturing World Physical AI Expo Japan",
    "Japan IT Week AI Expo Japan",
    "CEATEC AI robotics Japan",
    "TECHNO-FRONTIER 工場の搬送と協働ロボット展",
    "ロボット 遠隔操作 展示会",
    "ロボット リモートオペレーション 展示会",
    "日本能率協会 ロボット 展示会",
    "ROBOT TECHNOLOGY JAPAN 2026",
    "Japan Robot Week official robotics exhibition Japan",
    "AI博覧会 東京国際フォーラム",
    "Vision AI Expo 幕張メッセ",
    "画像認識 AI Expo 幕張メッセ",
    "RoboNext 2026 日刊工業新聞 日本ロボット工業会",
    "国際ロボット展 日本ロボット工業会 日刊工業新聞",
    "日本ロボット工業会 展示会 ロボット",
    "日刊工業新聞 ロボット 展示会",
] + ORGANIZER_FOCUSED_QUERIES + CORPORATE_EVENT_QUERIES

JAPAN_EVENT_SEED_URLS = [
    "https://irex.nikkan.co.jp/",
    "https://biz.nikkan.co.jp/eve/s-robot/",
    "https://robonext.nikkan.co.jp/",
    "https://robonext.nikkan.co.jp/exhibitguidance/",
    "https://www.manufacturing-world.jp/hub/en-gb.html",
    "https://www.manufacturing-world.jp/hub/ja-jp.html",
    "https://www.fiweek.jp/hub/en-gb/about/robodex.html",
    "https://www.fiweek.jp/hub/ja-jp/about/robodex.html",
    "https://www.nextech-week.jp/hub/en-gb.html",
    "https://www.nextech-week.jp/hub/ja-jp.html",
    "https://www.japan-it.jp/",
    "https://www.japan-it.jp/hub/ja-jp/about/itweek.html",
    "https://www.ceatec.com/",
    "https://tf.jma.or.jp/",
    "https://tf.jma.or.jp/outline/robot.html",
    "https://aismiley.co.jp/ai_hakurankai/",
    "https://aismiley.co.jp/ai_hakurankai/spring-2026/",
    "https://www.cbw-expo.jp/ja-jp.html",
    "https://www.cbw-expo.jp/ja-jp/visit.html",
    "https://www.cbw-expo.jp/ja-jp/exhibit/rem.html",
    "https://vision-ai-expo.jp/",
    "https://robot-technology.jp/",
    "https://robot-technology.jp/about/",
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
    "展示会",
    "見本市",
    "博覧会",
    "イベント",
    "robot",
    "ロボット",
    "ヒューマノイド",
    "国際ロボット展",
    "irex",
    "robonext",
    "japan robot week",
    "robodex",
    "nextech week",
    "physical ai expo",
    "日本ロボット工業会",
    "日刊工業新聞",
]

NEGATIVE_KEYWORDS = [
    "job",
    "career",
    "course",
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
    "求人",
    "採用",
    "転職",
    "ホテル",
    "旅行",
    "観光",
]

CORPORATE_EVENT_DOMAINS = {
    "aws.amazon.com",
    "amazon.com",
    "nvidia.com",
    "events.microsoft.com",
    "microsoft.com",
    "cloud.google.com",
    "google.com",
    "global.toyota",
    "global.honda",
    "sony.com",
    "fujitsu.com",
    "nec.com",
    "hitachi.co.jp",
    "mitsubishielectric.co.jp",
    "fanuc.co.jp",
    "yaskawa.co.jp",
    "khi.co.jp",
    "omron.com",
    "softbank.jp",
    "nttdata.com",
}

CORPORATE_HOSTING_KEYWORDS = [
    "主催", "共催", "hosted by", "organized by", "presented by",
    "公式イベント", "自社イベント", "開催します", "開催予定",
    "参加登録", "お申し込み", "register now", "registration",
    "aws summit", "aws startup loft", "nvidia gtc", "nvidia ai summit",
    "microsoft ai tour", "google cloud next",
]

CORPORATE_EVENT_TYPE_KEYWORDS = [
    "展示会", "展示", "expo", "exhibition", "summit", "conference",
    "イベント", "event", "セミナー", "webinar", "ウェビナー",
    "勉強会", "meetup", "workshop", "ハンズオン", "demo day",
]

CORPORATE_EXHIBITOR_ONLY_KEYWORDS = [
    "他社主催", "出展します", "出展いたします", "出展のお知らせ",
    "ブースにお越し", "弊社ブース", "visit our booth", "our booth",
]

CORPORATE_NAMED_PROGRAM_KEYWORDS = [
    "aws summit", "aws startup loft", "physical ai 開発支援プログラム",
    "nvidia gtc", "nvidia ai summit", "microsoft ai tour", "google cloud next",
]

SECONDARY_EVENT_HINTS = [
    "tokyo big sight",
    "intex osaka",
    "幕張メッセ",
    "東京ビッグサイト",
    "幕張メッセ",
    "東京国際フォーラム",
    "東京都立産業貿易センター",
    "マイドームおおさか",
    "ポートメッセなごや",
    "展示会場",
    "会場",
    "booth",
    "booth number",
    "来場",
    "visit",
    "register",
]

TRUSTED_EVENT_DOMAINS = {
    "irex.nikkan.co.jp",
    "biz.nikkan.co.jp",
    "robonext.nikkan.co.jp",
    "www.manufacturing-world.jp",
    "www.fiweek.jp",
    "www.nextech-week.jp",
    "www.japan-it.jp",
    "www.ceatec.com",
    "ceatec.com",
    "tf.jma.or.jp",
    "aismiley.co.jp",
    "vision-ai-expo.jp",
    "robot-technology.jp",
    "www.robot-technology.jp",
    "humanoidssummit.com",
    "2026.ieee-humanoids.org",
    "www.roboticssummit.com",
}

TARGET_ORGANIZER_KEYWORDS = [
    "日本ロボット工業会",
    "一般社団法人日本ロボット工業会",
    "the japan robot association",
    "japan robot association",
    "日刊工業新聞社",
    "株式会社日刊工業新聞社",
    "nikkan kogyo shimbun",
    "the nikkan kogyo shimbun",
]

ROBOTICS_TOPIC_KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "robot",
    "robotics",
    "ロボット",
    "ロボティクス",
    "humanoid",
    "ヒューマノイド",
    "協働ロボット",
    "industrial robot",
    "産業用ロボット",
    "agv",
    "amr",
    "遠隔操作",
    "リモートオペレーション",
    "ロボット 遠隔操作",
    "ロボット リモートオペレーション",
    "自律移動",
    "automation",
    "自動化",
    "embodied ai",
]

AGGREGATOR_DOMAINS = {
    "qviro.com",
    "www.showsbee.com",
    "www.tradefairdates.com",
    "www.globaltradefairs.com",
    "globaltradefairs.com",
    "exhibitionsforyou.com",
    "expolume.com",
    "robohorizon.com",
    "automationexpo.com",
}

EVENT_DOMAIN_HINTS = [
    "expo",
    "exhibition",
    "fair",
    "show",
    "summit",
    "week",
    "messe",
]

EXHIBITOR_PAGE_KEYWORDS = [
    "出展します",
    "出展いたします",
    "出展のお知らせ",
    "出展案内",
    "ブース出展",
    "ブース",
    "展示ブース",
    "小間",
    "booth no",
    "booth number",
    "our booth",
    "visit us at",
    "sponsor",
    "partner",
    "booth",
    "company_news",
    "pressrelease",
    "プレスリリース",
    "開催速報",
    "レポート",
    "blog",
    "note.com",
]

EXHIBITOR_URL_KEYWORDS = [
    "/exhibitor",
    "/exhibit/",
    "/exhibit?",
    "/company_news/",
    "/news/",
    "/blog/",
    "/reports/",
    "/report/",
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
        domain = urlparse(result.url).netloc.lower()
        if any(bad in blob for bad in NEGATIVE_KEYWORDS):
            return False
        if self.is_corporate_event_domain(domain):
            return self.looks_like_corporate_hosted_event(result.title, result.snippet)
        if not self.is_event_domain_candidate(domain):
            return False

        positive_match = any(good in blob for good in POSITIVE_KEYWORDS)
        secondary_match = any(hint in blob for hint in SECONDARY_EVENT_HINTS)
        has_year = bool(re.search(r"20\d{2}", blob))
        if not positive_match:
            return False
        if self.looks_like_exhibitor_page(result.url, result.title, result.snippet) and not self.is_event_site_exhibitor_page(result.url):
            return False
        return positive_match and (secondary_match or has_year)

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

    def is_official_event_domain(self, domain: str) -> bool:
        domain = (domain or "").lower()
        return domain in TRUSTED_EVENT_DOMAINS

    def is_corporate_event_domain(self, domain: str) -> bool:
        domain = (domain or "").lower().split(":", 1)[0]
        return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in CORPORATE_EVENT_DOMAINS)

    def looks_like_corporate_hosted_event(self, *texts: str) -> bool:
        blob = " ".join(texts).lower()
        if (
            any(keyword in blob for keyword in CORPORATE_EXHIBITOR_ONLY_KEYWORDS)
            and not any(keyword in blob for keyword in CORPORATE_NAMED_PROGRAM_KEYWORDS)
        ):
            return False
        return (
            any(keyword in blob for keyword in CORPORATE_HOSTING_KEYWORDS)
            and any(keyword in blob for keyword in CORPORATE_EVENT_TYPE_KEYWORDS)
            and self.is_robotics_related_event(blob)
        )

    def is_event_domain_candidate(self, domain: str) -> bool:
        domain = (domain or "").lower()
        if not domain or domain in AGGREGATOR_DOMAINS:
            return False
        if self.is_official_event_domain(domain):
            return True
        return any(hint in domain for hint in EVENT_DOMAIN_HINTS)

    def looks_like_exhibitor_page(self, url: str, *texts: str) -> bool:
        lower_url = (url or "").lower()
        if any(keyword in lower_url for keyword in EXHIBITOR_URL_KEYWORDS):
            return True

        blob = " ".join(texts).lower()
        if any(keyword in blob for keyword in EXHIBITOR_PAGE_KEYWORDS):
            if "公式" in blob or "official website" in blob or "official site" in blob:
                return False
            return True
        return False

    def is_event_site_exhibitor_page(self, url: str) -> bool:
        parsed = urlparse(url or "")
        domain = parsed.netloc.lower()
        path = parsed.path.lower()
        if not self.is_event_domain_candidate(domain):
            return False
        return any(keyword in path for keyword in EXHIBITOR_URL_KEYWORDS)

    def is_upcoming_event(self, start_date: Optional[str], end_date: Optional[str]) -> bool:
        target = end_date or start_date
        parsed = self.parse_date(target) if target and "/" in target else None
        if not parsed and target:
            parsed = target
        if not parsed:
            return False
        try:
            return parsed >= date.today().isoformat()
        except Exception:
            return False

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
            "%Y年%m月%d日(%a)",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                pass
        return None

    def extract_date_range(self, text: str) -> tuple[Optional[str], Optional[str]]:
        text = text.replace("–", "-")
        text = text.replace("〜", "-").replace("～", "-").replace("~", "-")

        compact_patterns = [
            r"(会期[:：]\s*20\d{2}年\d{1,2}月\d{1,2}日\s*(?:\([^)]*\))?\s*-\s*\d{1,2}日\s*(?:\([^)]*\))?)",
            r"(20\d{2}年(?:(?:\([^)]*\))|(?:（[^）]+）))?\d{1,2}月\d{1,2}日\s*(?:\([^)]*\))?\s*-\s*\d{1,2}月\d{1,2}日\s*(?:\([^)]*\))?)",
            r"(\d{1,2}\.\d{1,2}\s*(?:\([^)]*\))?\s*-\s*\d{1,2}\.\d{1,2}\s*(?:\([^)]*\))?)",
            r"(\d{1,2}/\d{1,2}\s*-\s*\d{1,2})",
            r"((?:20)?\d{2}/\d{1,2}/\d{1,2}\s*-\s*\d{1,2})",
            r"((?:20)?\d{2}/\d{1,2}/\d{1,2}-\d{1,2})",
            r"(20\d{2}年\d{1,2}月\d{1,2}日\s*(?:\([^)]*\))?\s*-\s*\d{1,2}日\s*(?:\([^)]*\))?)",
        ]

        for pattern in compact_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if not match:
                continue
            raw = normalize_text(match.group(1))

            m = re.match(r"会期[:：]\s*(20\d{2})年(\d{1,2})月(\d{1,2})日\s*(?:\([^)]*\))?\s*-\s*(\d{1,2})日\s*(?:\([^)]*\))?", raw)
            if m:
                year, month, d1, d2 = m.groups()
                return (
                    self.parse_date(f"{year}年{month}月{d1}日"),
                    self.parse_date(f"{year}年{month}月{d2}日"),
                )

            m = re.match(r"(20\d{2})年(?:(?:\([^)]*\))|(?:（[^）]+）))?(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*-\s*(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?", raw)
            if m:
                year, month1, d1, month2, d2 = m.groups()
                return (
                    self.parse_date(f"{year}年{month1}月{d1}日"),
                    self.parse_date(f"{year}年{month2}月{d2}日"),
                )

            m = re.match(r"(\d{1,2})\.(\d{1,2})\s*(?:\([^)]*\))?\s*-\s*(\d{1,2})\.(\d{1,2})\s*(?:\([^)]*\))?", raw)
            if m:
                month1, d1, month2, d2 = m.groups()
                year_match = re.search(r"(20\d{2})", text)
                if year_match:
                    year = year_match.group(1)
                    return (
                        self.parse_date(f"{year}/{month1}/{d1}"),
                        self.parse_date(f"{year}/{month2}/{d2}"),
                    )

            m = re.match(r"(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})", raw)
            if m:
                month, d1, d2 = m.groups()
                year_match = re.search(r"(20\d{2})", text)
                if year_match:
                    year = year_match.group(1)
                    return (
                        self.parse_date(f"{year}/{month}/{d1}"),
                        self.parse_date(f"{year}/{month}/{d2}"),
                    )

            m = re.match(r"((?:20)?\d{2})/(\d{1,2})/(\d{1,2})\s*-\s*(\d{1,2})", raw)
            if m:
                year, month, d1, d2 = m.groups()
                if len(year) == 2:
                    year = f"20{year}"
                return (
                    self.parse_date(f"{year}/{month}/{d1}"),
                    self.parse_date(f"{year}/{month}/{d2}"),
                )

            m = re.match(r"(20\d{2})年(\d{1,2})月(\d{1,2})日(?:\([^)]*\))?\s*-\s*(\d{1,2})日(?:\([^)]*\))?", raw)
            if m:
                year, month, d1, d2 = m.groups()
                return (
                    self.parse_date(f"{year}年{month}月{d1}日"),
                    self.parse_date(f"{year}年{month}月{d2}日"),
                )

        patterns = [
            rf"(({MONTH_PATTERN})\s+\d{{1,2}}-\d{{1,2}},\s*\d{{4}})",
            rf"(\d{{1,2}}-\d{{1,2}}\s+({MONTH_PATTERN})\s+\d{{4}})",
            rf"(({MONTH_PATTERN})\s+\d{{1,2}},\s*\d{{4}})",
            r"(20\d{2}年\d{1,2}月\d{1,2}日)",
            r"(20\d{2}[/-]\d{1,2}[/-]\d{1,2})",
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
            r"(?:会場|開催場所)[:：]\s*([^\n|]{4,120})",
            r"((?:東京ビッグサイト|幕張メッセ|東京国際フォーラム|インテックス大阪|ポートメッセなごや|東京都立産業貿易センター|マイドームおおさか)[^\n|]{0,80})",
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
            r"(?:Co-organized by|Co-organiser|Co-organizer)[:\s]+([A-Z][A-Za-z0-9 .,&()'\-/]{2,100})",
            r"(?:主催|運営)[:：]\s*([^\n|]{2,100})",
            r"(?:主催者|共催)[:：]\s*([^\n|]{2,140})",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return normalize_text(match.group(1), max_length=120)
        return ""

    def has_target_organizer(self, *texts: str) -> bool:
        blob = " ".join(texts).lower()
        return any(keyword in blob for keyword in TARGET_ORGANIZER_KEYWORDS)

    def is_robotics_related_event(self, *texts: str) -> bool:
        blob = " ".join(texts).lower()
        return any(keyword in blob for keyword in ROBOTICS_TOPIC_KEYWORDS)

    def normalize_event_title(self, title: str, summary: str, page_text: str) -> str:
        normalized_title = normalize_text(title, max_length=500)
        if normalized_title and normalized_title.lower() not in {"about", "top", "本展について"}:
            return normalized_title

        if "ロボットテクノロジージャパン" in page_text:
            year_match = re.search(r"ロボットテクノロジージャパン\s*(20\d{2})", page_text)
            if year_match:
                return f"ロボットテクノロジージャパン{year_match.group(1)} (RTJ{year_match.group(1)})"
            return "ロボットテクノロジージャパン (RTJ)"

        for source_text in [summary, page_text[:500]]:
            quoted = re.search(r"[「\"]([^\"\n]{6,100})[」\"]", source_text)
            if quoted:
                return normalize_text(quoted.group(1), max_length=500)

        return normalized_title or normalize_text(summary, max_length=120) or "展示会公式サイト"

    def crawl_seed_urls(self, urls: list[str]) -> tuple[int, int]:
        inserted = 0
        skipped = 0

        with app.app_context():
            for url in urls:
                result = SearchResult(
                    query="official_japan_seed",
                    title="",
                    url=url,
                    snippet="official japan event seed",
                    engine="official_seed",
                )
                item = self.build_item(result)
                if not item or not item["url"]:
                    skipped += 1
                    continue
                if save_raw_item(item):
                    inserted += 1
                    print(f"[SAVE][SEED] {item['title']}")
                else:
                    skipped += 1
                time.sleep(self.delay)

        return inserted, skipped

    def build_item(self, result: SearchResult) -> Optional[dict]:
        html = self.fetch_html(result.url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")
        page_text = normalize_text(soup.get_text(" ", strip=True), max_length=50000)
        title = self.extract_title(soup) or result.title
        summary = self.extract_summary(soup) or result.snippet or result.title
        title = self.normalize_event_title(title, summary, page_text)
        start_date, end_date = self.extract_date_range(page_text)
        location = self.extract_location(page_text)
        organizer = self.extract_organizer(page_text)
        domain = urlparse(result.url).netloc.lower()

        is_corporate_event = self.is_corporate_event_domain(domain)
        if not self.is_event_domain_candidate(domain) and not is_corporate_event:
            return None

        if (
            self.looks_like_exhibitor_page(result.url, title, summary)
            and not self.is_event_site_exhibitor_page(result.url)
            and not is_corporate_event
        ):
            return None

        if not self.is_robotics_related_event(
            result.query,
            result.title,
            result.snippet,
            title,
            summary,
            page_text[:5000],
            organizer,
        ):
            return None

        if is_corporate_event and not self.looks_like_corporate_hosted_event(
            result.title, result.snippet, title, summary, page_text[:10000], organizer,
        ):
            return None

        if domain.endswith("nikkan.co.jp"):
            if not self.has_target_organizer(title, summary, page_text[:5000], organizer):
                return None

        if not self.is_upcoming_event(start_date, end_date):
            return None

        raw_payload = {
            "kind": "corporate_physical_ai_event" if is_corporate_event else "exhibition_event",
            "search_query": result.query,
            "search_engine": result.engine,
            "page_kind": "corporate_hosted_event" if is_corporate_event else ("event_site_exhibitor" if self.is_event_site_exhibitor_page(result.url) else "event_page"),
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
            "source_name": f"Corporate Event / {domain}" if is_corporate_event else f"Exhibition Search / {domain}",
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
    seed_inserted, seed_skipped = crawler.crawl_seed_urls(JAPAN_EVENT_SEED_URLS)
    inserted, skipped = crawler.crawl(args.queries)
    inserted += seed_inserted
    skipped += seed_skipped
    print(f"Exhibition crawler: inserted={inserted}, skipped={skipped}")


if __name__ == "__main__":
    main()
