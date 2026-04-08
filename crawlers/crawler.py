import json
from pathlib import Path

from app import app
from models import db, RawItem


BASE_DIR = Path(__file__).resolve().parent.parent
DUMMY_DATA_PATH = BASE_DIR / "dummy_data.json"


def save_raw_item(data: dict) -> bool:
    existing = RawItem.query.filter_by(url=data["url"]).first()
    if existing:
        return False

    item = RawItem(
        source_name=data["source_name"],
        source_type=data["source_type"],
        title=data["title"],
        url=data["url"],
        published_at=data.get("published_at"),
        raw_summary=data.get("raw_summary"),
        raw_text=data.get("raw_text"),
    )
    db.session.add(item)
    db.session.commit()
    return True


def fetch_dummy_items() -> list:
    with open(DUMMY_DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> None:
    with app.app_context():
        inserted = 0
        skipped = 0

        for item in fetch_dummy_items():
            if save_raw_item(item):
                inserted += 1
            else:
                skipped += 1

        print(f"dummy_data.json から読み込みました: inserted={inserted}, skipped={skipped}")


if __name__ == "__main__":
    main()