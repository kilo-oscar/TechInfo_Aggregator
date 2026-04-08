import re
import unicodedata
from datetime import datetime, timedelta

from typing import Optional

from models import db, RawItem

def parse_date_safe(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None

    date_str = str(date_str).strip()

    patterns = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y年%m月%d日",
    ]

    for pattern in patterns:
        try:
            return datetime.strptime(date_str, pattern)
        except ValueError:
            pass

    return None


def is_within_last_3_years(date_str: Optional[str]) -> bool:
    dt = parse_date_safe(date_str)
    if dt is None:
        return False

    cutoff = datetime.now() - timedelta(days=365 * 3)
    return dt >= cutoff

def normalize_text(text: Optional[str], max_length: Optional[int] = None) -> str:
    if text is None:
        return ""

    text = str(text)
    text = unicodedata.normalize("NFKC", text)
    text = "".join(ch for ch in text if ch == "\n" or ch.isprintable())
    text = text.replace("\r", "\n").replace("\t", " ")
    text = re.sub(r"[ \u3000]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    if max_length is not None:
        text = text[:max_length]

    return text


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