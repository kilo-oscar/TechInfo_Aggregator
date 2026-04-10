# crawlers/mizuho_rt_crawler.py

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import Browser, Page, sync_playwright

# 既存プロジェクト側の共通保存処理に合わせて import を調整してください
# たとえば、以前の crawler 群で使っている関数名に合わせる想定です。
try:
    from crawlers.thinktank_common import (
        save_items,
        normalize_text,
        is_old_article,
        make_item,
    )
except Exception:
    # プロジェクト側の共通関数名が違う場合でも、最低限単体動作しやすいようにフォールバック
    def normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "")).strip()

    def is_old_article(_title: str, _summary: str, _published_at: Optional[str], _days: int = 3650) -> bool:
        return False

    def make_item(
        source_name: str,
        title: str,
        url: str,
        summary: str = "",
        published_at: Optional[str] = None,
        category: str = "thinktank",
    ) -> dict:
        return {
            "source_name": source_name,
            "title": title,
            "url": url,
            "summary": summary,
            "published_at": published_at,
            "category": category,
        }

    def save_items(items: list[dict], source_name: str = "みずほリサーチ&テクノロジーズ"):
        # 既存DB保存ロジックが使えない場合の簡易表示
        inserted = len(items)
        skipped = 0
        old_skipped = 0
        print(f"{source_name} crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")
        return inserted, skipped, old_skipped


SOURCE_NAME = "みずほリサーチ&テクノロジーズ"

# 公開ページで確認しやすい導線
SEED_URLS = [
    "https://www.mizuhobank.co.jp/corporate/mhri/research/report/index.html",
    "https://www.mizuhobank.co.jp/corporate/mhri/research/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/report/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/project-case/index.html",
    "https://www.mizuhobank.co.jp/corporate/tech/news/index.html",
]

ALLOWED_DOMAINS = {
    "www.mizuhobank.co.jp",
    "mizuhobank.co.jp",
}

# Physical AI 周辺をやや広めに拾う
KEYWORDS = [
    "physical ai",
    "embodied ai",
    "agent ai",
    "robot",
    "robotics",
    "humanoid",
    "autonomy",
    "automation",
    "manipulation",
    "vision language action",
    "vla",
    "foundation model",
    "world model",
    "digital twin",
    "simulation",
    "multimodal",
    "ai",
    "ロボット",
    "ロボティクス",
    "ヒューマノイド",
    "自動化",
    "物理ai",
    "フィジカルai",
    "エンボディドai",
    "デジタルツイン",
    "シミュレーション",
    "画像解析",
    "画像認識",
    "自然言語処理",
    "制御",
    "センシング",
]

# ノイズ低減
EXCLUDE_PATTERNS = [
    r"/contact/",
    r"/privacy/",
    r"/policy/",
    r"/recruit/",
    r"/sitemap/",
    r"/faq/",
    r"\.pdf$",
    r"\.xlsx?$",
    r"\.docx?$",
]


@dataclass
class Candidate:
    title: str
    url: str
    summary: str = ""
    published_at: Optional[str] = None


def is_allowed_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if parsed.netloc not in ALLOWED_DOMAINS:
            return False
        for pat in EXCLUDE_PATTERNS:
            if re.search(pat, url, re.IGNORECASE):
                return False
        return True
    except Exception:
        return False


def keyword_score(text: str) -> int:
    s = (text or "").lower()
    return sum(1 for kw in KEYWORDS if kw.lower() in s)


def is_relevant(title: str, summary: str, url: str) -> bool:
    blob = " ".join([title or "", summary or "", url or ""])
    return keyword_score(blob) > 0


def uniq_by_url(items: Iterable[Candidate]) -> List[Candidate]:
    seen = set()
    out: List[Candidate] = []
    for item in items:
        key = item.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def extract_date(text: str) -> Optional[str]:
    if not text:
        return None

    text = normalize_text(text)

    patterns = [
        r"(20\d{2})[./-](\d{1,2})[./-](\d{1,2})",
        r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return None


def new_page(browser: Browser) -> Page:
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="ja-JP",
        java_script_enabled=True,
        ignore_https_errors=True,
    )
    page = context.new_page()
    page.set_default_timeout(30000)
    return page


def fetch_html(page: Page, url: str) -> str:
    page.goto(url, wait_until="domcontentloaded")
    time.sleep(1.5)
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass
    return page.content()


def extract_links_from_html(base_url: str, html: str) -> List[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: List[Candidate] = []

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = normalize_text(a.get_text(" ", strip=True))

        if not href or not title:
            continue

        abs_url = urljoin(base_url, href)
        if not is_allowed_url(abs_url):
            continue

        parent_text = ""
        parent = a.parent
        if parent:
            parent_text = normalize_text(parent.get_text(" ", strip=True))

        published_at = extract_date(parent_text) or extract_date(title)
        summary = parent_text[:400] if parent_text and parent_text != title else ""

        candidates.append(
            Candidate(
                title=title,
                url=abs_url,
                summary=summary,
                published_at=published_at,
            )
        )

    return uniq_by_url(candidates)


def refine_article(page: Page, candidate: Candidate) -> Candidate:
    """
    個別記事を開いて title/summary/date を補強する。
    """
    try:
        html = fetch_html(page, candidate.url)
        soup = BeautifulSoup(html, "html.parser")

        title = candidate.title
        og_title = soup.select_one("meta[property='og:title']")
        if og_title and og_title.get("content"):
            title = normalize_text(og_title["content"])

        if not title:
            h1 = soup.select_one("h1")
            if h1:
                title = normalize_text(h1.get_text(" ", strip=True))

        summary = candidate.summary
        desc = soup.select_one("meta[name='description']")
        if desc and desc.get("content"):
            summary = normalize_text(desc["content"])

        if not summary:
            ps = [
                normalize_text(p.get_text(" ", strip=True))
                for p in soup.select("p")
            ]
            ps = [p for p in ps if len(p) >= 40]
            if ps:
                summary = ps[0][:500]

        published_at = candidate.published_at
        if not published_at:
            body_text = normalize_text(soup.get_text(" ", strip=True))
            published_at = extract_date(body_text[:3000])

        return Candidate(
            title=title or candidate.title,
            url=candidate.url,
            summary=summary or candidate.summary,
            published_at=published_at or candidate.published_at,
        )
    except Exception:
        return candidate


def crawl_seed(browser: Browser, seed_url: str) -> List[Candidate]:
    candidates: List[Candidate] = []
    page = new_page(browser)

    try:
        html = fetch_html(page, seed_url)
        initial = extract_links_from_html(seed_url, html)

        # seed一覧ページ上でまず関連性判定
        filtered = [
            c for c in initial
            if is_relevant(c.title, c.summary, c.url)
        ]

        # 取りこぼし対策:
        # URL自体が /report/ /news/ /project-case/ を含むものは追加で候補化
        for c in initial:
            url_l = c.url.lower()
            if any(x in url_l for x in ["/report/", "/news/", "/project-case/", "/research/"]):
                filtered.append(c)

        filtered = uniq_by_url(filtered)

        # 上位だけ本文確認
        scored = sorted(
            filtered,
            key=lambda x: keyword_score(" ".join([x.title, x.summary, x.url])),
            reverse=True,
        )[:80]

        article_page = new_page(browser)
        refined: List[Candidate] = []
        for c in scored:
            item = refine_article(article_page, c)
            if is_relevant(item.title, item.summary, item.url):
                refined.append(item)

        candidates.extend(refined)

    finally:
        try:
            page.context.close()
        except Exception:
            pass

    return uniq_by_url(candidates)


def convert_to_items(candidates: Iterable[Candidate]) -> List[dict]:
    items: List[dict] = []
    for c in candidates:
        title = normalize_text(c.title)
        summary = normalize_text(c.summary)

        if not title or not c.url:
            continue

        if is_old_article(title, summary, c.published_at):
            continue

        items.append(
            make_item(
                source_name=SOURCE_NAME,
                title=title,
                url=c.url,
                summary=summary,
                published_at=c.published_at,
                category="thinktank",
            )
        )
    return items


def main() -> None:
    all_candidates: List[Candidate] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )

        try:
            for url in SEED_URLS:
                try:
                    results = crawl_seed(browser, url)
                    all_candidates.extend(results)
                except Exception as e:
                    print(f"[{SOURCE_NAME}] failed: {url} -> {e}")
        finally:
            browser.close()

    all_candidates = uniq_by_url(all_candidates)
    items = convert_to_items(all_candidates)
    inserted, skipped, old_skipped = save_items(items, source_name=SOURCE_NAME)
    print(f"{SOURCE_NAME} crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")


if __name__ == "__main__":
    main()