from __future__ import annotations

from app import app
from crawler_utils import canonicalize_url
from models import RawItem, db


def _published_key(item: RawItem) -> str:
    return item.published_at or ""


def _group_key(item: RawItem) -> tuple[str, str, str]:
    return (item.source_name, item.title, _published_key(item))


def _choose_survivor(items: list[RawItem]) -> RawItem:
    return sorted(
        items,
        key=lambda item: (
            0 if item.url == canonicalize_url(item.url) else 1,
            0 if item.published_at else 1,
            item.fetched_at,
            item.id,
        ),
    )[0]


def cleanup_duplicates() -> dict[str, int]:
    items = RawItem.query.order_by(RawItem.id.asc()).all()

    duplicate_ids: set[int] = set()
    seen_urls: dict[str, RawItem] = {}
    grouped_items: dict[tuple[str, str, str], list[RawItem]] = {}

    for item in items:
        canonical_url = canonicalize_url(item.url)

        if canonical_url in seen_urls:
            winner = _choose_survivor([seen_urls[canonical_url], item])
            loser = item if winner.id == seen_urls[canonical_url].id else seen_urls[canonical_url]
            seen_urls[canonical_url] = winner
            duplicate_ids.add(loser.id)
        else:
            seen_urls[canonical_url] = item

        grouped_items.setdefault(_group_key(item), []).append(item)

    for group in grouped_items.values():
        alive = [item for item in group if item.id not in duplicate_ids]
        if len(alive) <= 1:
            continue

        survivor = _choose_survivor(alive)
        for item in alive:
            if item.id != survivor.id:
                duplicate_ids.add(item.id)

    deleted = 0
    if duplicate_ids:
        deleted = RawItem.query.filter(RawItem.id.in_(sorted(duplicate_ids))).delete(
            synchronize_session=False
        )
        db.session.commit()

    return {
        "deleted": deleted,
        "remaining": RawItem.query.count(),
    }


if __name__ == "__main__":
    with app.app_context():
        result = cleanup_duplicates()
        print(f"deleted={result['deleted']}, remaining={result['remaining']}")
