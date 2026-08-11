from __future__ import annotations

import argparse
import os
import time
from datetime import datetime
from typing import Any

import requests
from bs4 import BeautifulSoup

from app import app
from crawler_utils import normalize_text, save_raw_item
from env_loader import load_project_env


# IEEE's Crossref member ID. Crossref's public REST API requires no account or API key.
CROSSREF_IEEE_WORKS_URL = "https://api.crossref.org/members/263/works"
DEFAULT_QUERIES = [
    "physical AI",
    "embodied AI robotics",
    "vision language action robot",
    "humanoid robot",
    "haptics robot",
]

PHYSICAL_AI_TERMS = [
    "physical ai",
    "physical artificial intelligence",
    "embodied ai",
    "embodied artificial intelligence",
    "embodied intelligence",
    "vision language action",
    "vision-language-action",
    "vla model",
    "humanoid",
    "robot",
    "robotics",
    "haptic",
    "cyborg",
    "bionic",
]


def crossref_date(work: dict[str, Any]) -> str:
    for field in ["published-online", "published-print", "published", "issued", "created"]:
        date_payload = work.get(field) or {}
        date_parts = date_payload.get("date-parts") if isinstance(date_payload, dict) else None
        if not date_parts or not isinstance(date_parts, list) or not date_parts[0]:
            continue
        parts = date_parts[0]
        try:
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else 1
            day = int(parts[2]) if len(parts) > 2 else 1
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            continue
    return ""


def first_text(value: Any, max_length: int) -> str:
    if isinstance(value, list):
        value = value[0] if value else ""
    return normalize_text(value, max_length=max_length)


def clean_crossref_abstract(value: Any) -> str:
    abstract = first_text(value, 20000)
    if not abstract:
        return ""
    # Abstracts may be deposited as JATS XML fragments.
    return normalize_text(BeautifulSoup(abstract, "html.parser").get_text(" ", strip=True), max_length=10000)


def extract_authors(work: dict[str, Any]) -> list[str]:
    authors = []
    for author in work.get("author") or []:
        if not isinstance(author, dict):
            continue
        name = normalize_text(" ".join(filter(None, [author.get("given"), author.get("family")])), max_length=200)
        if name:
            authors.append(name)
    return authors


def crossref_work_to_item(work: dict[str, Any], source_name: str = "IEEE / Crossref") -> dict[str, Any] | None:
    title = first_text(work.get("title"), 500)
    doi = normalize_text(work.get("DOI"), max_length=300)
    resource_url = normalize_text(work.get("URL"), max_length=1000)
    url = f"https://doi.org/{doi}" if doi else resource_url
    if not title or not url:
        return None

    abstract = clean_crossref_abstract(work.get("abstract"))
    authors = extract_authors(work)
    subjects = [normalize_text(subject, max_length=200) for subject in (work.get("subject") or []) if subject]
    publication = first_text(work.get("container-title"), 500)

    metadata_lines = []
    if authors:
        metadata_lines.append("Authors: " + ", ".join(authors))
    if subjects:
        metadata_lines.append("Crossref subjects: " + ", ".join(dict.fromkeys(subjects)))
    if publication:
        metadata_lines.append("Publication: " + publication)
    if work.get("type"):
        metadata_lines.append("Content type: " + normalize_text(work.get("type"), max_length=100))
    if doi:
        metadata_lines.append("DOI: " + doi)

    return {
        "source_name": source_name,
        "source_type": "paper",
        "title": title,
        "url": url,
        "published_at": crossref_date(work),
        "raw_summary": abstract or "概要なし（Crossref書誌メタデータのみ取得）",
        "raw_text": "\n\n".join(([abstract] if abstract else []) + metadata_lines),
    }


def is_physical_ai_related(item: dict[str, Any]) -> bool:
    searchable = " ".join([
        item.get("title") or "",
        item.get("raw_summary") or "",
        item.get("raw_text") or "",
    ]).lower()
    return any(term in searchable for term in PHYSICAL_AI_TERMS)


def fetch_ieee_items(query: str, max_records: int = 25, mailto: str = "") -> list[dict[str, Any]]:
    current_year = datetime.now().year
    params = {
        "query": query,
        "filter": f"from-pub-date:{current_year - 2}-01-01,until-pub-date:{current_year}-12-31",
        "rows": min(max(max_records, 1), 1000),
        "select": "DOI,URL,title,abstract,author,subject,container-title,type,published-online,published-print,published,issued,created",
    }
    if mailto:
        params["mailto"] = mailto
    agent = "TechInfoAggregator/1.0"
    if mailto:
        agent += f" (mailto:{mailto})"
    response = requests.get(CROSSREF_IEEE_WORKS_URL, params=params, headers={"User-Agent": agent}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    works = ((payload.get("message") or {}).get("items") or []) if isinstance(payload, dict) else []
    return [
        item
        for work in works
        if isinstance(work, dict)
        if (item := crossref_work_to_item(work))
        if is_physical_ai_related(item)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="CrossrefからIEEE論文の書誌メタデータを収集します。")
    parser.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES)
    parser.add_argument("--max-records", type=int, default=25)
    args = parser.parse_args()

    load_project_env()
    mailto = os.environ.get("CROSSREF_MAILTO", "").strip()
    inserted = 0
    skipped = 0
    failed = 0
    seen_urls: set[str] = set()
    with app.app_context():
        for query in args.queries:
            try:
                items = fetch_ieee_items(query, args.max_records, mailto)
            except (requests.RequestException, ValueError) as exc:
                failed += 1
                print(f"IEEE/Crossref query failed ({query}): {exc}")
                continue
            finally:
                # Keep anonymous/Public-pool access comfortably below burst limits.
                time.sleep(1.0)
            for item in items:
                if item["url"] in seen_urls:
                    skipped += 1
                    continue
                seen_urls.add(item["url"])
                if save_raw_item(item):
                    inserted += 1
                else:
                    skipped += 1

    print(f"IEEE/Crossref から取得: inserted={inserted}, skipped={skipped}, failed_queries={failed}")


if __name__ == "__main__":
    main()
