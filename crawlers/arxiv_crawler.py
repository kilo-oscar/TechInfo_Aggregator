import time
import requests
import feedparser

from app import app

from crawler_utils import save_raw_item, is_within_last_3_years

ARXIV_API_URL = "http://export.arxiv.org/api/query"
REQUEST_RETRY_DELAYS = [3, 10, 20]


def fetch_arxiv_items(
    search_query: str,
    max_results: int = 10,
    start: int = 0,
    sort_by: str = "submittedDate",
    sort_order: str = "descending",
) -> list[dict]:
    params = {
        "search_query": search_query,
        "start": start,
        "max_results": max_results,
        "sortBy": sort_by,
        "sortOrder": sort_order,
    }

    headers = {
        "User-Agent": "TechInfoAggregator/0.1"
    }

    last_exc = None
    response = None
    for attempt, delay_seconds in enumerate([0] + REQUEST_RETRY_DELAYS, start=1):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            response = requests.get(ARXIV_API_URL, params=params, headers=headers, timeout=30)
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            last_exc = exc
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code != 429 and attempt > 1:
                break
            if status_code != 429 and attempt == 1:
                break
    else:
        response = None

    if last_exc and response is None:
        raise last_exc

    feed = feedparser.parse(response.text)
    items = []

    for entry in feed.entries:
        authors = []
        if hasattr(entry, "authors"):
            authors = [author.name for author in entry.authors]

        categories = []
        if hasattr(entry, "tags"):
            categories = [tag["term"] for tag in entry.tags]

        raw_text_parts = []

        if getattr(entry, "summary", None):
            raw_text_parts.append(entry.summary.strip())

        if authors:
            raw_text_parts.append("Authors: " + ", ".join(authors))

        if categories:
            raw_text_parts.append("Categories: " + ", ".join(categories))

        items.append({
            "source_name": "arXiv",
            "source_type": "paper",
            "title": entry.title.strip().replace("\n", " "),
            "url": entry.link,
            "published_at": getattr(entry, "published", ""),
            "raw_summary": getattr(entry, "summary", "").strip(),
            "raw_text": "\n\n".join(raw_text_parts),
        })

    return items


def main() -> None:
    search_query = 'cat:cs.RO AND (all:robot OR all:manipulation OR all:"vision language action")'

    # 連続アクセスを避けるため軽く待つ
    time.sleep(1.0)

    try:
        items = fetch_arxiv_items(
            search_query=search_query,
            max_results=20,
            sort_by="submittedDate",
            sort_order="descending",
        )
    except requests.RequestException as exc:
        print(f"arXiv crawler skipped: {exc}")
        items = []

    with app.app_context():
        inserted = 0
        skipped = 0

        old_skipped = 0

        for item in items:
            if not is_within_last_3_years(item.get("published_at")):
                old_skipped += 1
                continue

            if save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(f"arXiv から取得: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}")


if __name__ == "__main__":
    main()
