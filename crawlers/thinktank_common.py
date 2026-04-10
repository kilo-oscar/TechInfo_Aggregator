import json
from urllib.parse import urlparse

from app import app
from crawler_utils import is_within_last_3_years, normalize_text, save_raw_item
from crawlers.official_site_common import (
    enrich_item,
    extract_candidate_links,
    fetch_html,
    text_contains_keywords,
)


DEFAULT_SUMMARY_SELECTORS = [
    "meta[name='description']",
    "meta[property='og:description']",
    "main p",
    "article p",
    ".article p",
    ".contents p",
    "p",
]


class ThinkTankCrawlerConfig:
    def __init__(
        self,
        source_name: str,
        seed_urls: list[str],
        allowed_domains: list[str],
        allowed_path_keywords: list[str] | None = None,
        extra_keywords: list[str] | None = None,
        excluded_path_keywords: list[str] | None = None,
        excluded_title_keywords: list[str] | None = None,
        source_type: str = "thinktank",
    ) -> None:
        self.source_name = source_name
        self.seed_urls = seed_urls
        self.allowed_domains = allowed_domains
        self.allowed_path_keywords = [kw.lower() for kw in (allowed_path_keywords or [])]
        self.extra_keywords = [kw.lower() for kw in (extra_keywords or [])]
        self.excluded_path_keywords = [kw.lower() for kw in (excluded_path_keywords or [])]
        self.excluded_title_keywords = [kw.lower() for kw in (excluded_title_keywords or [])]
        self.source_type = source_type


def _is_allowed_domain(url: str, allowed_domains: list[str]) -> bool:
    netloc = urlparse(url).netloc.lower()
    return any(netloc == domain or netloc.endswith(f".{domain}") for domain in allowed_domains)


def _looks_like_relevant_thinktank_item(item: dict, config: ThinkTankCrawlerConfig) -> bool:
    url = item.get("url", "")
    if not url or not _is_allowed_domain(url, config.allowed_domains):
        return False

    path = urlparse(url).path.lower()
    title = (item.get("title", "") or "").lower()

    if config.excluded_path_keywords and any(keyword in path for keyword in config.excluded_path_keywords):
        return False

    if config.excluded_title_keywords and any(keyword in title for keyword in config.excluded_title_keywords):
        return False

    blob = " ".join([
        item.get("title", ""),
        item.get("raw_summary", ""),
        item.get("raw_text", ""),
        url,
    ]).lower()

    if any(keyword in blob for keyword in config.extra_keywords):
        return True

    if text_contains_keywords(blob):
        return True

    if config.allowed_path_keywords and any(keyword in path for keyword in config.allowed_path_keywords):
        return True

    return False


def _build_item(item: dict, config: ThinkTankCrawlerConfig) -> dict:
    enriched = enrich_item(item, config.source_name)
    enriched["source_type"] = config.source_type
    enriched["title"] = normalize_text(enriched.get("title", ""), max_length=500)
    enriched["raw_summary"] = normalize_text(enriched.get("raw_summary", ""), max_length=2000)
    enriched["raw_text"] = json.dumps(
        {
            "kind": "thinktank_official",
            "source_name": config.source_name,
            "source_domain": urlparse(enriched.get("url", "")).netloc,
            "raw_text": normalize_text(enriched.get("raw_text", ""), max_length=5000),
        },
        ensure_ascii=False,
        indent=2,
    )
    return enriched


def fetch_thinktank_items(config: ThinkTankCrawlerConfig) -> list[dict]:
    items: list[dict] = []

    for seed_url in config.seed_urls:
        try:
            html = fetch_html(seed_url)
            for candidate in extract_candidate_links(seed_url, html):
                if _looks_like_relevant_thinktank_item(candidate, config):
                    items.append(_build_item(candidate, config))
        except Exception as exc:
            print(f"[{config.source_name}] failed: {seed_url} -> {exc}")

    unique: dict[str, dict] = {}
    for item in items:
        unique[item["url"]] = item
    return list(unique.values())


def run_thinktank_crawler(config: ThinkTankCrawlerConfig) -> None:
    items = fetch_thinktank_items(config)

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
            f"{config.source_name} crawler: inserted={inserted}, skipped={skipped}, old_skipped={old_skipped}"
        )
