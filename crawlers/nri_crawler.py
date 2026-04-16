import json
from urllib.parse import urlparse, urljoin

from bs4 import BeautifulSoup

from app import app
from crawler_utils import is_within_last_3_years, normalize_text, save_raw_item
from crawlers.official_site_common import fetch_html, extract_date


SOURCE_NAME = "野村総合研究所"
SOURCE_TYPE = "thinktank"

SEED_URLS = [
    "https://www.nri.com/jp/knowledge/report/list.html",
    "https://www.nri.com/jp/media/journal/",
    "https://www.nri.com/jp/media/column/",
]

ALLOWED_DOMAINS = {"nri.com", "www.nri.com"}
ALLOWED_PATH_HINTS = [
    "/jp/knowledge/report/",
    "/jp/media/journal/",
    "/jp/media/column/",
    "/jp/knowledge/publication/",
]
EXCLUDED_PATH_HINTS = [
    "/jp/news/",
    "/news-release/",
    "/recruit/",
    "/event/",
    "/seminar/",
    "/podcast/",
    "/movie/",
    "/contact/",
    "/privacy",
    "/policy",
]

STRONG_KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "フィジカル（物理的な）ai",
    "embodied ai",
    "ai agent",
    "agent ai",
    "agentic ai",
    "aiエージェント",
    "ai エージェント",
    "エージェントai",
    "エージェント ai",
    "エンボディドai",
    "humanoid",
    "ヒューマノイド",
    "人型ロボット",
    "自律ロボット",
    "産業ロボット",
    "協働ロボット",
    "ロボティクス",
    "robotics",
    "robot",
    "ロボット",
    "vision language action",
    "vla",
    "world model",
    "world models",
    "デジタルツイン",
    "digital twin",
    "マニピュレーション",
    "manipulation",
    "把持",
    "grasp",
    "力制御",
    "force control",
    "動作計画",
    "motion planning",
    "センシング",
    "sensing",
    "autonomous mobile robot",
    "amr",
]

CONTEXT_KEYWORDS = [
    "製造業",
    "製造現場",
    "工場",
    "物流",
    "倉庫",
    "現場",
    "自律",
    "自動運転",
    "フィジカル",
    "物理世界",
    "simulation",
    "シミュレーション",
    "foundation model",
    "基盤モデル",
    "マルチモーダル",
    "multimodal",
    "automation",
    "自動化",
    "agent",
    "agentic",
]

AI_KEYWORDS = [" ai ", "ai", "人工知能"]

NEGATIVE_KEYWORDS = [
    "金融",
    "銀行",
    "証券",
    "保険",
    "株式",
    "投資",
    "市場",
    "金利",
    "為替",
    "マクロ経済",
    "経済見通し",
    "マーケティング",
    "広告",
    "crm",
    "会計",
    "税",
    "法務",
    "ガバナンス",
    "サイバーセキュリティ",
    "セキュリティ",
    "個人情報",
    "チャットボット",
    "llm活用",
    "生成aiを活用",
    "バックオフィス",
    "営業改革",
    "人事",
    "ヘルスケアビジネス",
    "gx",
    "脱炭素",
    "バイオ燃料",
]


def _is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    if parsed.netloc.lower() not in ALLOWED_DOMAINS:
        return False
    path = parsed.path.lower()
    if not any(hint in path for hint in ALLOWED_PATH_HINTS):
        return False
    if any(hint in path for hint in EXCLUDED_PATH_HINTS):
        return False
    return True


def _text_blob(*parts: str) -> str:
    return normalize_text(" ".join(p for p in parts if p), max_length=8000).lower()


def _has_negative_without_robotics(blob: str) -> bool:
    has_negative = any(kw.lower() in blob for kw in NEGATIVE_KEYWORDS)
    has_robotics = any(kw.lower() in blob for kw in STRONG_KEYWORDS)
    return has_negative and not has_robotics


def _is_physical_ai_relevant(title: str, summary: str, body: str, url: str) -> bool:
    blob = _text_blob(title, summary, body, url)

    if _has_negative_without_robotics(blob):
        return False

    strong_hits = sum(1 for kw in STRONG_KEYWORDS if kw.lower() in blob)
    context_hits = sum(1 for kw in CONTEXT_KEYWORDS if kw.lower() in blob)
    ai_hit = any(kw.lower() in blob for kw in AI_KEYWORDS)

    if strong_hits >= 1:
        return True

    if ai_hit and context_hits >= 2 and any(x in blob for x in ["製造", "工場", "物流", "現場", "自律", "物理世界"]):
        return True

    return False


def _extract_candidates(seed_url: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    seen = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        title = normalize_text(a.get_text(" ", strip=True), max_length=500)
        if not href or not title:
            continue

        full_url = urljoin(seed_url, href)
        if not _is_allowed_url(full_url):
            continue

        parent_text = normalize_text(a.parent.get_text(" ", strip=True) if a.parent else title, max_length=1000)
        published_at = extract_date(f"{title} {parent_text}")

        key = full_url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)

        candidates.append({
            "title": title,
            "url": full_url,
            "published_at": published_at,
            "raw_summary": parent_text[:300],
            "raw_text": f"{title} {parent_text} {full_url}",
        })

    return candidates


def _enrich_from_detail(item: dict) -> dict:
    try:
        html = fetch_html(item["url"])
    except Exception:
        return item

    soup = BeautifulSoup(html, "html.parser")
    title = item.get("title", "")
    og_title = soup.select_one("meta[property='og:title']")
    if og_title and og_title.get("content"):
        title = normalize_text(og_title["content"], max_length=500)
    elif soup.select_one("h1"):
        title = normalize_text(soup.select_one("h1").get_text(" ", strip=True), max_length=500)

    summary = item.get("raw_summary", "")
    desc = soup.select_one("meta[name='description']") or soup.select_one("meta[property='og:description']")
    if desc and desc.get("content"):
        summary = normalize_text(desc["content"], max_length=2000)

    text_parts = []
    for node in soup.select("main p, article p, .article p, .contents p, p"):
        txt = normalize_text(node.get_text(" ", strip=True), max_length=500)
        if txt:
            text_parts.append(txt)
        if len(" ".join(text_parts)) > 2500:
            break
    body = normalize_text(" ".join(text_parts), max_length=3000)

    published_at = item.get("published_at", "")
    if not published_at:
        published_at = extract_date(_text_blob(title, summary, body)[:1500])

    return {
        "title": title,
        "url": item["url"],
        "published_at": published_at,
        "raw_summary": summary,
        "raw_text": body or item.get("raw_text", ""),
    }


def fetch_nri_items() -> list[dict]:
    candidates = []
    for seed_url in SEED_URLS:
        try:
            html = fetch_html(seed_url)
        except Exception as exc:
            print(f"[{SOURCE_NAME}] failed: {seed_url} -> {exc}")
            continue

        for item in _extract_candidates(seed_url, html):
            if _is_physical_ai_relevant(item["title"], item.get("raw_summary", ""), item.get("raw_text", ""), item["url"]):
                candidates.append(item)

    unique_candidates = {}
    for item in candidates:
        unique_candidates[item["url"]] = item

    refined_items = []
    for item in unique_candidates.values():
        enriched = _enrich_from_detail(item)
        if _is_physical_ai_relevant(
            enriched.get("title", ""),
            enriched.get("raw_summary", ""),
            enriched.get("raw_text", ""),
            enriched.get("url", ""),
        ):
            refined_items.append({
                "source_name": SOURCE_NAME,
                "source_type": SOURCE_TYPE,
                "title": normalize_text(enriched.get("title", ""), max_length=500),
                "url": enriched.get("url", ""),
                "published_at": enriched.get("published_at", ""),
                "raw_summary": normalize_text(enriched.get("raw_summary", ""), max_length=2000),
                "raw_text": json.dumps(
                    {
                        "kind": "thinktank_official",
                        "source_name": SOURCE_NAME,
                        "source_domain": urlparse(enriched.get("url", "")).netloc,
                        "raw_text": normalize_text(enriched.get("raw_text", ""), max_length=5000),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            })

    unique = {}
    for item in refined_items:
        if item["url"]:
            unique[item["url"]] = item
    return list(unique.values())


def main() -> None:
    items = fetch_nri_items()

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
