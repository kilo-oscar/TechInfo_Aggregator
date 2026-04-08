from app import app
from crawler_utils import save_raw_item
from crawlers.official_site_common import fetch_html, extract_candidate_links, enrich_item

from crawler_utils import save_raw_item, is_within_last_3_years

NRI_SEED_URLS = [
    "https://www.nri.com/jp/news/index.html",
    "https://www.nri.com/jp/media/journal/",
    "https://www.nri.com/jp/knowledge/report/",
]


def fetch_nri_items() -> list[dict]:
    all_items = []

    for url in NRI_SEED_URLS:
        try:
            html = fetch_html(url)
            candidates = extract_candidate_links(url, html)
            all_items.extend(enrich_item(item, "野村総合研究所") for item in candidates)
        except Exception as e:
            print(f"[NRI] failed: {url} -> {e}")

    # URL重複除去
    unique = {}
    for item in all_items:
        unique[item["url"]] = item
    return list(unique.values())


def main() -> None:
    items = fetch_nri_items()

    with app.app_context():
        inserted = 0
        skipped = 0
        old_skipped = 0

        for item in items:
            if not is_within_last_3_years(item.get("published_at")):
                old_skipped += 1
                continue

            if item["url"] and save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(f"NRI crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")


if __name__ == "__main__":
    main()