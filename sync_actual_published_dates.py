from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from app import app
from crawler_utils import parse_date_safe
from models import RawItem, db
from page_date_utils import fetch_actual_published_at


MAX_WORKERS = 6


def iter_target_items() -> list[RawItem]:
    return (
        RawItem.query
        .filter(RawItem.url.isnot(None))
        .order_by(RawItem.id.asc())
        .all()
    )


def fetch_one(item: RawItem) -> tuple[int, str, str, str]:
    try:
        actual_published_at = fetch_actual_published_at(item.url)
    except Exception as exc:
        return item.id, item.published_at or "", "", f"error: {exc}"
    return item.id, item.published_at or "", actual_published_at, ""


def dates_match(left: str, right: str) -> bool:
    left_dt = parse_date_safe(left)
    right_dt = parse_date_safe(right)
    if left_dt and right_dt:
        return left_dt.date() == right_dt.date()
    return bool(left and right and left == right)


def main() -> None:
    with app.app_context():
        items = iter_target_items()
        updated = 0
        mismatched = 0
        checked = 0
        errors = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(fetch_one, item): item for item in items}

            for future in as_completed(futures):
                item = futures[future]
                checked += 1
                item_id, published_at, actual_published_at, error = future.result()
                if error:
                    errors += 1
                    print(f"[ERROR] id={item_id} url={item.url} {error}")
                    continue
                if not actual_published_at:
                    continue

                db_item = RawItem.query.get(item_id)
                if not db_item:
                    continue

                if db_item.actual_published_at != actual_published_at:
                    db_item.actual_published_at = actual_published_at
                    updated += 1

                if published_at and not dates_match(published_at, actual_published_at):
                    mismatched += 1
                    print(
                        f"[MISMATCH] id={item_id} stored={published_at} actual={actual_published_at} url={item.url}"
                    )

        db.session.commit()
        print(
            f"checked={checked} updated={updated} mismatched={mismatched} errors={errors}"
        )


if __name__ == "__main__":
    main()
