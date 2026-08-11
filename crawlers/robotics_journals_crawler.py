from __future__ import annotations

import argparse
import os
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote

import requests

from app import app
from crawler_utils import save_raw_item
from crawlers.ieee_xplore_crawler import crossref_work_to_item, is_physical_ai_related
from env_loader import load_project_env


CROSSREF_API_BASE = "https://api.crossref.org/journals"


@dataclass(frozen=True)
class Journal:
    key: str
    title: str
    issn: str
    broad_robotics_scope: bool = True


JOURNALS = [
    Journal("annual-review-cras", "Annual Review of Control, Robotics, and Autonomous Systems", "2573-5144"),
    Journal("ijrr", "The International Journal of Robotics Research", "1741-3176"),
    Journal("science-robotics", "Science Robotics", "2470-9476"),
    Journal("field-robotics", "Journal of Field Robotics", "1556-4967"),
    Journal("robotics-autonomous-systems", "Robotics and Autonomous Systems", "0921-8890"),
    Journal("frontiers-robotics-ai", "Frontiers in Robotics and AI", "2296-9144"),
    Journal("cyborg-bionic", "Cyborg and Bionic Systems", "2692-7632"),
    Journal("annual-reviews-control", "Annual Reviews in Control", "1367-5788", broad_robotics_scope=False),
]


def fetch_journal_items(journal: Journal, max_records: int = 25, mailto: str = "") -> list[dict]:
    current_year = datetime.now().year
    params = {
        "filter": f"from-pub-date:{current_year - 2}-01-01,until-pub-date:{current_year}-12-31",
        "rows": min(max(max_records, 1), 1000),
        "sort": "published",
        "order": "desc",
        "select": "DOI,URL,title,abstract,author,subject,container-title,type,published-online,published-print,published,issued,created",
    }
    if mailto:
        params["mailto"] = mailto
    agent = "TechInfoAggregator/1.0"
    if mailto:
        agent += f" (mailto:{mailto})"
    url = f"{CROSSREF_API_BASE}/{quote(journal.issn)}/works"
    response = requests.get(url, params=params, headers={"User-Agent": agent}, timeout=30)
    response.raise_for_status()
    payload = response.json()
    works = ((payload.get("message") or {}).get("items") or []) if isinstance(payload, dict) else []
    items = [
        item
        for work in works
        if isinstance(work, dict)
        if (item := crossref_work_to_item(work, source_name=f"Journal / {journal.title}"))
    ]
    if journal.broad_robotics_scope:
        return items
    return [item for item in items if is_physical_ai_related(item)]


def main() -> None:
    parser = argparse.ArgumentParser(description="主要ロボティクス誌をCrossrefから収集します。")
    parser.add_argument("--journals", nargs="+", choices=[journal.key for journal in JOURNALS])
    parser.add_argument("--max-records", type=int, default=25)
    args = parser.parse_args()

    load_project_env()
    mailto = os.environ.get("CROSSREF_MAILTO", "").strip()
    selected = [journal for journal in JOURNALS if not args.journals or journal.key in args.journals]
    inserted = 0
    skipped = 0
    failed = 0
    with app.app_context():
        for journal in selected:
            try:
                items = fetch_journal_items(journal, args.max_records, mailto)
                for item in items:
                    if save_raw_item(item):
                        inserted += 1
                    else:
                        skipped += 1
                print(f"{journal.title}: fetched={len(items)}")
            except (requests.RequestException, ValueError) as exc:
                failed += 1
                print(f"{journal.title}: failed ({exc})")
            finally:
                time.sleep(1.0)
    print(f"主要ロボティクス誌: inserted={inserted}, skipped={skipped}, failed_journals={failed}")


if __name__ == "__main__":
    main()
