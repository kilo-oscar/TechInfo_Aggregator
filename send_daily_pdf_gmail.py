from __future__ import annotations

import argparse
import json
import os
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from app import app, build_daily_information_pdf, normalize_crawl_date


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "instance" / "sent_daily_pdf_dates.json"
JST = timezone(timedelta(hours=9))
GMAIL_ATTACHMENT_LIMIT = 24 * 1024 * 1024


def previous_jst_date(now: datetime | None = None) -> str:
    current_jst = now.astimezone(JST) if now else datetime.now(JST)
    return (current_jst.date() - timedelta(days=1)).isoformat()


def load_sent_dates() -> set[str]:
    if not STATE_PATH.exists():
        return set()
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    values = payload.get("sent_dates", []) if isinstance(payload, dict) else []
    return {value for value in values if isinstance(value, str)}


def save_sent_dates(sent_dates: set[str]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": datetime.now(JST).isoformat(timespec="seconds"),
        "sent_dates": sorted(sent_dates),
    }
    temporary_path = STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(STATE_PATH)


def build_pdf_message(
    sender: str,
    recipients: list[str],
    report_date: str,
    item_count: int,
    pdf_data: bytes,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = f"Physical-AIデイリー情報収集レポート {report_date}（{item_count}件）"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(
        "\n".join([
            "Physical-AIデイリー情報収集レポートを送付します。",
            "",
            f"対象取得日: {report_date}（日本時間）",
            f"収集件数: {item_count}件",
            f"送信日時: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S')}（日本時間）",
            "",
        ])
    )
    message.add_attachment(
        pdf_data,
        maintype="application",
        subtype="pdf",
        filename=f"daily-information-{report_date}.pdf",
    )
    return message


def send_daily_pdf(report_date: str, *, dry_run: bool = False, force: bool = False) -> bool:
    sent_dates = load_sent_dates()
    if report_date in sent_dates and not force:
        print(f"daily pdf gmail skipped: already sent date={report_date}")
        return True

    sender = os.getenv("GMAIL_SENDER", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    recipients = [
        address.strip()
        for address in os.getenv("GMAIL_RECIPIENT", "").split(",")
        if address.strip()
    ]
    if not sender or not app_password or not recipients:
        print("daily pdf gmail skipped: set GMAIL_SENDER, GMAIL_APP_PASSWORD, GMAIL_RECIPIENT")
        return False

    with app.app_context():
        pdf_data, item_count = build_daily_information_pdf(report_date)
    if len(pdf_data) > GMAIL_ATTACHMENT_LIMIT:
        raise RuntimeError(
            f"PDFがGmail添付の安全上限を超えています: {len(pdf_data)} bytes"
        )
    message = build_pdf_message(sender, recipients, report_date, item_count, pdf_data)

    if dry_run:
        print(
            f"daily pdf gmail dry-run: date={report_date}, items={item_count}, "
            f"pdf_bytes={len(pdf_data)}, recipients={len(recipients)}"
        )
        return True

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(sender, app_password)
        smtp.send_message(message)

    sent_dates.add(report_date)
    save_sent_dates(sent_dates)
    print(
        f"daily pdf gmail sent: date={report_date}, items={item_count}, "
        f"pdf_bytes={len(pdf_data)}, recipients={len(recipients)}"
    )
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="指定日のデイリー情報PDFをGmailで送信する")
    parser.add_argument("--date", default="", help="対象取得日（YYYY-MM-DD、既定は日本時間の前日）")
    parser.add_argument("--dry-run", action="store_true", help="PDFを生成するが送信しない")
    parser.add_argument("--force", action="store_true", help="送信済みの日付でも再送信する")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report_date = normalize_crawl_date(args.date) if args.date else previous_jst_date()
    if not report_date:
        raise SystemExit("--date は YYYY-MM-DD 形式の実在する日付を指定してください")
    if not send_daily_pdf(report_date, dry_run=args.dry_run, force=args.force):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
