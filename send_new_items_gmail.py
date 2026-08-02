from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
from datetime import date, datetime
from email.message import EmailMessage
from pathlib import Path
from collections import OrderedDict

from app import app
from crawler_utils import canonicalize_url, normalize_text, parse_date_safe
from models import RawItem


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "instance" / "notified_items.json"
MAX_SUMMARY_LENGTH = 220
SOURCE_TYPE_LABELS = {
    "news": "ニュース",
    "event": "展示会",
    "paper": "論文",
    "policy": "政策",
    "thinktank": "シンクタンク",
    "company": "企業",
    "github": "GitHub",
    "sns_post": "SNS",
}


def item_notification_key(item: RawItem) -> str:
    canonical_url = canonicalize_url(item.url)
    if canonical_url:
        return f"url:{canonical_url}"

    published_at = item.published_at or ""
    return f"title:{item.source_name}|{item.title}|{published_at}"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"sent_keys": []}

    with STATE_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
        if not isinstance(data, dict):
            return {"sent_keys": []}
        sent_keys = data.get("sent_keys", [])
        if not isinstance(sent_keys, list):
            sent_keys = []
        return {"sent_keys": sent_keys}


def save_state(sent_keys: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "sent_keys": sorted(sent_keys),
    }
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def get_target_crawl_batch_id() -> str:
    env_batch_id = normalize_text(os.getenv("CRAWL_BATCH_ID"), max_length=100)
    if env_batch_id:
        return env_batch_id

    latest_item = (
        RawItem.query
        .filter(RawItem.crawl_batch_id.isnot(None), RawItem.crawl_batch_id != "")
        .order_by(RawItem.fetched_at.desc(), RawItem.id.desc())
        .first()
    )
    if not latest_item:
        return ""
    return normalize_text(latest_item.crawl_batch_id, max_length=100)


def get_crawl_execution_date(target_batch_id: str) -> date:
    batch_id = normalize_text(target_batch_id, max_length=100)
    match = re.search(r"(\d{8})", batch_id)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    return datetime.now().date()


def is_same_day_published_item(item: RawItem, crawl_execution_date: date) -> bool:
    published_dt = parse_date_safe(item.published_at)
    if published_dt is None:
        return False

    return published_dt.date() == crawl_execution_date


def collect_new_items() -> tuple[list[RawItem], set[str], str, date | None]:
    state = load_state()
    sent_keys = set(state["sent_keys"])
    target_batch_id = get_target_crawl_batch_id()

    if not target_batch_id:
        return [], sent_keys, "", None

    crawl_execution_date = get_crawl_execution_date(target_batch_id)

    items = (
        RawItem.query
        .filter(RawItem.crawl_batch_id == target_batch_id)
        .order_by(RawItem.fetched_at.desc(), RawItem.id.desc())
        .all()
    )
    new_items: list[RawItem] = []
    run_seen_keys: set[str] = set()

    for item in items:
        if not is_same_day_published_item(item, crawl_execution_date):
            continue

        key = item_notification_key(item)
        if key in sent_keys or key in run_seen_keys:
            continue
        run_seen_keys.add(key)
        new_items.append(item)

    return new_items, sent_keys, target_batch_id, crawl_execution_date


def format_item_block(item: RawItem) -> str:
    summary = normalize_text(item.raw_summary or "", max_length=MAX_SUMMARY_LENGTH)
    lines = [
        f"[{item.source_type}] {item.title}",
        f"source: {item.source_name}",
        f"url: {canonicalize_url(item.url)}",
    ]
    if item.published_at:
        lines.append(f"published_at: {item.published_at}")
    lines.append(f"fetched_at: {item.fetched_at}")
    if summary:
        lines.append(f"summary: {summary}")
    return "\n".join(lines)


def group_items_by_source_type(items: list[RawItem]) -> OrderedDict[str, list[RawItem]]:
    ordered_groups: OrderedDict[str, list[RawItem]] = OrderedDict()
    for item in items:
        source_type = (item.source_type or "").strip() or "other"
        ordered_groups.setdefault(source_type, []).append(item)
    return ordered_groups


def group_items_by_source_name(items: list[RawItem]) -> OrderedDict[str, list[RawItem]]:
    ordered_groups: OrderedDict[str, list[RawItem]] = OrderedDict()
    for item in items:
        source_name = (item.source_name or "").strip() or "unknown"
        ordered_groups.setdefault(source_name, []).append(item)
    return ordered_groups


def source_type_label(source_type: str) -> str:
    return SOURCE_TYPE_LABELS.get(source_type, source_type or "other")


def build_message(sender: str, recipients: list[str], items: list[RawItem]) -> EmailMessage:
    now_label = datetime.now().strftime("%Y-%m-%d %H:%M")
    msg = EmailMessage()
    msg["Subject"] = f"TechInfo_Aggregator 新規記事 {len(items)}件 {now_label}"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    body_parts = []
    if not items:
        body_parts.extend([
            "新着のニュースはありませんでした",
            "",
            f"配信時刻: {now_label}",
        ])
    else:
        groups = group_items_by_source_type(items)
        body_parts.extend([
            f"新規記事: {len(items)}件",
            "",
            "カテゴリ別サマリ",
        ])
        for source_type, group_items in groups.items():
            body_parts.append(f"- {source_type_label(source_type)}: {len(group_items)}件")

        body_parts.extend([
            "",
            "カテゴリ別新着一覧",
            "",
        ])

        for source_type, group_items in groups.items():
            body_parts.append(f"## {source_type_label(source_type)} ({len(group_items)}件)")
            body_parts.append("")
            source_name_groups = group_items_by_source_name(group_items)
            for source_name, source_items in source_name_groups.items():
                body_parts.append(f"### {source_name} ({len(source_items)}件)")
                body_parts.append("")
                for item in source_items:
                    body_parts.append(format_item_block(item))
                    body_parts.append("")

    msg.set_content("\n".join(body_parts).rstrip() + "\n")
    return msg


def send_gmail(items: list[RawItem], dry_run: bool = False) -> bool:
    sender = os.getenv("GMAIL_SENDER", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    recipients_raw = os.getenv("GMAIL_RECIPIENT", "").strip()
    recipients = [addr.strip() for addr in recipients_raw.split(",") if addr.strip()]

    if not sender or not app_password or not recipients:
        print("gmail skipped: set GMAIL_SENDER, GMAIL_APP_PASSWORD, GMAIL_RECIPIENT")
        return False

    msg = build_message(sender, recipients, items)

    if dry_run:
        print(msg.get_content())
        return True

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(msg)

    print(f"gmail sent: recipients={len(recipients)}, items={len(items)}")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="新規記事のみを Gmail 送信する")
    parser.add_argument("--dry-run", action="store_true", help="メール送信せず本文のみ表示する")
    parser.add_argument("--limit", type=int, default=0, help="送信件数を先頭から制限する")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    with app.app_context():
        new_items, sent_keys, target_batch_id, crawl_execution_date = collect_new_items()

        if args.limit and args.limit > 0:
            new_items = new_items[: args.limit]

        crawl_execution_date_label = crawl_execution_date.isoformat() if crawl_execution_date else "none"
        print(
            f"gmail target items: crawl_batch_id={target_batch_id or 'none'}, "
            f"crawl_execution_date={crawl_execution_date_label}, published_at_match=crawl_execution_date, count={len(new_items)}"
        )
        if send_gmail(new_items, dry_run=args.dry_run) and not args.dry_run:
            if new_items:
                sent_keys.update(item_notification_key(item) for item in new_items)
                save_state(sent_keys)
                print(f"gmail state updated: added={len(new_items)}")
            else:
                print("gmail sent: no new items message delivered")


if __name__ == "__main__":
    main()
