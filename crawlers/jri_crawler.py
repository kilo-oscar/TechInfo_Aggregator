from app import app
from crawler_utils import is_within_last_3_years, save_raw_item
from crawlers.thinktank_common import ThinkTankCrawlerConfig, fetch_thinktank_items


CONFIG = ThinkTankCrawlerConfig(
    source_name="日本総合研究所",
    seed_urls=[
        "https://www.jri.co.jp/page.jsp?lang=ja",
        "https://www.jri.co.jp/page.jsp?id=372",
        "https://www.jri.co.jp/page.jsp?id=101417",
        "https://www.jri.co.jp/page.jsp?id=103194",
        "https://www.jri.co.jp/page.jsp?id=101419",
        "https://www.jri.co.jp/company/business/system/advtechlab/",
        "https://www.jri.co.jp/company/business/system/advtechlab/research/",
        "https://www.jri.co.jp/page.jsp?id=111906",
    ],
    allowed_domains=["jri.co.jp"],
    allowed_path_keywords=[
        "/company/business/system/advtechlab/",
        "/advanced/advanced-technology/detail/",
        "/advanced/awards/detail/",
        "/report/",
        "/publication/",
        "/file/",
    ],
    extra_keywords=[
        "physical ai",
        "フィジカルai",
        "フィジカル ai",
        "agentic ai",
        "エージェンティック ai",
        "ロボット基盤モデル",
        "生成ai",
        "生成 ai",
        "ロボット",
        "humanoid",
        "ヒューマノイド",
        "robot",
        "robotics",
        "embodied",
        "embodied ai",
        "自動運転",
        "省人化",
        "製造業",
        "シミュレーション",
        "デジタルツイン",
        "先端技術リサーチ",
    ],
    excluded_path_keywords=[
        "/contact/",
        "/privacy",
        "/purpose",
    ],
    excluded_title_keywords=[
        "こちら",
        "大城武史",
    ],
)

FOCUS_KEYWORDS = [
    "physical ai",
    "フィジカルai",
    "フィジカル ai",
    "embodied ai",
    "agentic ai",
    "エージェンティック ai",
    "robot",
    "robotics",
    "ロボット",
    "ヒューマノイド",
    "humanoid",
    "デジタルツイン",
    "シミュレーション",
]

AI_KEYWORDS = [
    "ai",
    "生成ai",
    "生成 ai",
    "機械学習",
    "自然言語処理",
]

ROBOTICS_KEYWORDS = [
    "robot",
    "robotics",
    "ロボット",
    "ヒューマノイド",
    "humanoid",
    "physical ai",
    "フィジカルai",
    "フィジカル ai",
    "embodied ai",
]

EXCLUDED_URL_KEYWORDS = [
    "#modal-",
    "/report/medium/",
    "/purpose/",
    "/privacy",
    "/contact/",
]


def _is_relevant_jri_item(item: dict) -> bool:
    title = item.get("title", "") or ""
    summary = item.get("raw_summary", "") or ""
    url = item.get("url", "") or ""

    lower_url = url.lower()
    if any(keyword in lower_url for keyword in EXCLUDED_URL_KEYWORDS):
        return False

    title_blob = f"{title} {summary}".lower()
    full_blob = f"{title} {summary} {item.get('raw_text', '')} {url}".lower()

    if any(keyword in title_blob for keyword in FOCUS_KEYWORDS):
        return True

    ai_hit = any(keyword in title_blob for keyword in AI_KEYWORDS)
    robotics_hit = any(keyword in full_blob for keyword in ROBOTICS_KEYWORDS)
    return ai_hit and robotics_hit


def main() -> None:
    items = [item for item in fetch_thinktank_items(CONFIG) if _is_relevant_jri_item(item)]

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

        print(f"{CONFIG.source_name} crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")


if __name__ == "__main__":
    main()
