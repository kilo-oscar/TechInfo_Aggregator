from __future__ import annotations

import argparse
import time

from app import app
from models import RawItem, db
from translation_service import (
    GoogleCloudTranslator,
    TranslationQuotaExceeded,
    get_monthly_character_limit,
    needs_japanese_translation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="海外ニュースと外国語論文の日本語訳をDBに保存する")
    parser.add_argument("--limit", type=int, default=100, help="処理件数。0で対象全件")
    parser.add_argument("--source-type", choices=["news", "paper"], help="種別を限定")
    parser.add_argument("--delay", type=float, default=0.1, help="1件ごとの待機秒")
    parser.add_argument("--dry-run", action="store_true", help="翻訳APIを呼ばず対象数のみ確認")
    parser.add_argument("--show-usage", action="store_true", help="今月のローカル記録文字数を表示して終了")
    return parser.parse_args()


def collect_targets(source_type: str | None, limit: int) -> list[RawItem]:
    query = RawItem.query.filter(
        RawItem.source_type.in_([source_type] if source_type else ["news", "paper"]),
        RawItem.translated_title.is_(None),
    ).order_by(RawItem.published_at.desc(), RawItem.id.desc())
    candidates = query.all()
    targets = [
        item for item in candidates
        if needs_japanese_translation(item.source_type, item.title, item.raw_summary)
    ]
    return targets[:limit] if limit > 0 else targets


def main() -> None:
    args = parse_args()
    translator = GoogleCloudTranslator()
    if args.show_usage:
        used = translator.usage_tracker.used_characters()
        limit = get_monthly_character_limit()
        print(f"translation usage: used={used}, limit={limit}, remaining={max(0, limit - used)}")
        return
    with app.app_context():
        targets = collect_targets(args.source_type, args.limit)
        print(f"translation targets: {len(targets)}")
        if args.dry_run:
            return
        if not translator.available:
            raise SystemExit("GOOGLE_TRANSLATE_API_KEY を設定してください")

        translated_count = 0
        failed_count = 0
        for item in targets:
            try:
                translated, source_language = translator.translate([item.title, item.raw_summary or ""])
                item.translated_title = translated[0] or None
                item.translated_summary = translated[1] or None
                item.source_language = source_language or None
                item.translation_provider = translator.provider_name
                item.translated_at = db.func.current_timestamp()
                db.session.commit()
                translated_count += 1
            except TranslationQuotaExceeded as exc:
                db.session.rollback()
                print(f"translation stopped: {exc}")
                break
            except Exception as exc:
                db.session.rollback()
                failed_count += 1
                print(f"[WARN] translation failed: id={item.id} error={type(exc).__name__}: {exc}")
            time.sleep(max(args.delay, 0))
        print(f"translation complete: translated={translated_count}, failed={failed_count}")


if __name__ == "__main__":
    main()
