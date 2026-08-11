from __future__ import annotations

import argparse
import time
from datetime import datetime

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
    parser.add_argument("--fetched-month", help="取得月を YYYY-MM 形式で限定")
    parser.add_argument("--delay", type=float, default=0.1, help="1件ごとの待機秒")
    parser.add_argument("--batch-size", type=int, default=50, help="1 APIリクエスの記事数（最大64）")
    parser.add_argument("--dry-run", action="store_true", help="翻訳APIを呼ばず対象数のみ確認")
    parser.add_argument("--show-usage", action="store_true", help="今月のローカル記録文字数を表示して終了")
    return parser.parse_args()


def collect_targets(source_type: str | None, limit: int, fetched_month: str | None = None) -> list[RawItem]:
    query = RawItem.query.filter(
        RawItem.source_type.in_([source_type] if source_type else ["news", "paper"]),
        RawItem.translated_title.is_(None),
    ).order_by(RawItem.published_at.desc(), RawItem.id.desc())
    if fetched_month:
        try:
            month_start = datetime.strptime(fetched_month, "%Y-%m")
        except ValueError as exc:
            raise SystemExit("--fetched-month は YYYY-MM 形式で指定してください") from exc
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        query = query.filter(RawItem.fetched_at >= month_start, RawItem.fetched_at < next_month)
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
        targets = collect_targets(args.source_type, args.limit, args.fetched_month)
        estimated_characters = sum(len(item.title or "") for item in targets)
        print(f"translation targets: {len(targets)}, estimated_characters={estimated_characters}")
        if args.dry_run:
            return
        if not translator.available:
            raise SystemExit("GOOGLE_TRANSLATE_API_KEY を設定してください")

        translated_count = 0
        failed_count = 0
        stopped_by_limit = False
        batch_size = min(max(args.batch_size, 1), 64)
        for batch_start in range(0, len(targets), batch_size):
            batch = targets[batch_start:batch_start + batch_size]
            flat_texts = [item.title or "" for item in batch]
            try:
                translated, source_language = translator.translate(flat_texts)
                for index, item in enumerate(batch):
                    item.translated_title = translated[index] or None
                    item.source_language = source_language or None
                    item.translation_provider = translator.provider_name
                    item.translated_at = db.func.current_timestamp()
                db.session.commit()
                translated_count += len(batch)
            except TranslationQuotaExceeded as exc:
                db.session.rollback()
                print(f"translation stopped: {exc}")
                stopped_by_limit = True
                break
            except Exception as exc:
                db.session.rollback()
                failed_count += len(batch)
                first_id = batch[0].id if batch else "none"
                print(f"[WARN] translation failed: first_id={first_id} batch={len(batch)} error={type(exc).__name__}: {exc}")
            time.sleep(max(args.delay, 0))
        remaining_count = len(targets) - translated_count - failed_count
        print(
            f"translation complete: translated={translated_count}, failed={failed_count}, "
            f"remaining={remaining_count}, stopped_by_limit={stopped_by_limit}"
        )


if __name__ == "__main__":
    main()
