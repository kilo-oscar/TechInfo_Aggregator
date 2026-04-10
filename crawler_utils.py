import re
import unicodedata
import os
from functools import lru_cache
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from typing import Optional

from models import db, RawItem


@lru_cache(maxsize=1)
def get_current_crawl_batch_id() -> str:
    env_batch_id = normalize_text(os.environ.get("CRAWL_BATCH_ID"), max_length=100)
    if env_batch_id:
        return env_batch_id
    return datetime.utcnow().strftime("manual-%Y%m%d%H%M%S")

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


TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "rt_bn",
    "rt_ps",
    "rt_pc",
    "rt_pp",
    "rt_pr",
}


def canonicalize_url(url: Optional[str]) -> str:
    if not url:
        return ""

    raw = normalize_text(url)
    parts = urlsplit(raw)

    scheme = "https" if parts.scheme in {"http", "https"} else parts.scheme
    netloc = parts.netloc.lower()
    path = parts.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS
    ]
    query = urlencode(filtered_query, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def save_raw_item(data: dict) -> bool:
    canonical_url = canonicalize_url(data.get("url"))
    if not canonical_url:
        return False

    title = normalize_text(data.get("title"), max_length=500)
    source_name = normalize_text(data.get("source_name"), max_length=200)
    source_type = normalize_text(data.get("source_type"), max_length=100)
    published_at = normalize_text(data.get("published_at"), max_length=100) or None
    actual_published_at = normalize_text(data.get("actual_published_at"), max_length=100) or None
    crawl_batch_id = normalize_text(data.get("crawl_batch_id"), max_length=100) or get_current_crawl_batch_id()
    raw_summary = normalize_text(data.get("raw_summary"), max_length=2000) or None
    raw_text = data.get("raw_text")

    existing = RawItem.query.filter_by(url=canonical_url).first()
    if existing:
        changed = False
        if actual_published_at and existing.actual_published_at != actual_published_at:
            existing.actual_published_at = actual_published_at
            changed = True
        if changed:
            db.session.commit()
        return False

    duplicate_query = RawItem.query.filter(
        RawItem.source_name == source_name,
        RawItem.title == title,
    )
    if published_at:
        duplicate_query = duplicate_query.filter(RawItem.published_at == published_at)

    duplicate_item = duplicate_query.first()
    if duplicate_item:
        changed = False
        if actual_published_at and duplicate_item.actual_published_at != actual_published_at:
            duplicate_item.actual_published_at = actual_published_at
            changed = True
        if changed:
            db.session.commit()
        return False

    item = RawItem(
        source_name=source_name,
        source_type=source_type,
        title=title,
        url=canonical_url,
        published_at=published_at,
        actual_published_at=actual_published_at,
        crawl_batch_id=crawl_batch_id,
        raw_summary=raw_summary,
        raw_text=raw_text,
    )
    db.session.add(item)
    db.session.commit()
    return True
