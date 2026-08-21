from flask import Flask, Response, render_template, request, redirect, url_for, has_request_context
from sqlalchemy import and_, or_, case
from sqlalchemy import text
from bs4 import BeautifulSoup
import json
from urllib.parse import urlencode
import re
from math import ceil
from datetime import datetime, timedelta, timezone
from collections import Counter
from functools import lru_cache

from models import db, RawItem
from typing import Optional
from page_date_utils import fetch_actual_published_at
from crawler_utils import parse_date_safe
from keyword_collection import KeywordCollector
from env_loader import load_project_env
from monthly_reports import (
    build_monthly_report,
    normalize_report_month,
    previous_month,
    render_field_chart_svg,
    render_region_chart_svg,
    render_report_markdown,
)
from daily_news_pdf import render_daily_news_pdf
from trend_settings import DEFAULT_TREND_KEYWORDS, TREND_REGIONS

EXPORTABLE_SOURCE_TYPES = {"company", "event", "news", "paper", "policy", "thinktank"}
PRECISE_ARTICLE_KEYWORDS = {"vla", "vtla"}
MODEL_TITLE_CONTEXT_KEYWORDS = (
    "model", "モデル", "robot", "ロボット", "vision", "action", "tactile",
    "ai", "自動運転", "physical", "フィジカル",
)
ELEMENT_TECHNOLOGY_SUBCATEGORIES = [
    "センサ・センシング", "アクチュエータ", "ギヤ・減速機", "ダイレクトドライブモータ", "その他",
]
SENSOR_SENSING_SUBCATEGORIES = [
    "視覚センサ・カメラ", "聴覚センサ", "力触覚センサ", "その他",
]

load_project_env()

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///techinfo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)
keyword_collector = KeywordCollector()

def ensure_schema() -> None:
    db.create_all()
    existing_columns = {
        row[1]
        for row in db.session.execute(text("PRAGMA table_info(raw_items)")).fetchall()
    }
    if "actual_published_at" not in existing_columns:
        db.session.execute(text("ALTER TABLE raw_items ADD COLUMN actual_published_at VARCHAR(100)"))
        db.session.commit()
    if "crawl_batch_id" not in existing_columns:
        db.session.execute(text("ALTER TABLE raw_items ADD COLUMN crawl_batch_id VARCHAR(100)"))
        db.session.commit()
    if "is_new" not in existing_columns:
        db.session.execute(text("ALTER TABLE raw_items ADD COLUMN is_new BOOLEAN DEFAULT 0"))
        db.session.commit()
    translation_columns = {
        "translated_title": "VARCHAR(1000)",
        "translated_summary": "TEXT",
        "source_language": "VARCHAR(20)",
        "translation_provider": "VARCHAR(100)",
        "translated_at": "DATETIME",
    }
    for column_name, column_type in translation_columns.items():
        if column_name not in existing_columns:
            db.session.execute(text(f"ALTER TABLE raw_items ADD COLUMN {column_name} {column_type}"))
            db.session.commit()
    index_statements = [
        "CREATE INDEX IF NOT EXISTS ix_raw_items_published_at ON raw_items (published_at)",
        "CREATE INDEX IF NOT EXISTS ix_raw_items_source_type_published_at ON raw_items (source_type, published_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_raw_items_source_name ON raw_items (source_name)",
        "CREATE INDEX IF NOT EXISTS ix_raw_items_fetched_at ON raw_items (fetched_at DESC)",
        "CREATE INDEX IF NOT EXISTS ix_raw_items_crawl_batch_id ON raw_items (crawl_batch_id)",
    ]
    for statement in index_statements:
        db.session.execute(text(statement))
    db.session.commit()


with app.app_context():
    ensure_schema()


def clean_summary(text: Optional[str], max_length: int = 160) -> str:
    if not text:
        return "要約なし"

    plain = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    plain = " ".join(plain.split())

    if len(plain) > max_length:
        return plain[:max_length] + "..."
    return plain


def normalize_archive_month(value: str) -> str:
    normalized = (value or "").strip()
    if re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", normalized):
        return normalized
    return ""


def normalize_crawl_date(value: str) -> str:
    normalized = (value or "").strip()
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])-([0-2]\d|3[01])", normalized):
        return ""
    try:
        datetime.strptime(normalized, "%Y-%m-%d")
    except ValueError:
        return ""


def build_keyword_match_filter(keyword: str):
    """Build the DB filter for a user-entered keyword.

    VLA and VTLA are model names, so a source label such as
    ``VLA・VTLA Models`` must not make a VLA article appear in a VTLA search.
    For these terms, only an article title that names the model and has a
    robotics/model context is used. Google News RSS summaries include opaque
    redirect URLs, where a coincidental character sequence can otherwise
    produce false positives.
    """
    pattern = f"%{keyword}%"
    if keyword.casefold() in PRECISE_ARTICLE_KEYWORDS:
        return and_(
            RawItem.title.ilike(pattern),
            or_(*(RawItem.title.ilike(f"%{context}%") for context in MODEL_TITLE_CONTEXT_KEYWORDS)),
        )
    return or_(
        RawItem.title.ilike(pattern),
        RawItem.raw_summary.ilike(pattern),
        # arXiv stores author names and category metadata in raw_text.  Those
        # metadata fields must not make a paper match a user keyword; title
        # and abstract remain searchable for papers.
        and_(RawItem.source_type != "paper", RawItem.raw_text.ilike(pattern)),
        RawItem.source_name.ilike(pattern),
    )
    return normalized


def build_recent_crawl_dates(limit: int = 14) -> list[dict]:
    crawl_date = db.func.date(RawItem.fetched_at, "+9 hours")
    rows = (
        db.session.query(crawl_date.label("crawl_date"), db.func.count(RawItem.id))
        .filter(RawItem.fetched_at.isnot(None))
        .group_by(crawl_date)
        .order_by(crawl_date.desc())
        .limit(limit)
        .all()
    )
    return [{"date": date_value, "count": count} for date_value, count in rows if date_value]


def format_archive_month_label(archive_month: str) -> str:
    if not archive_month:
        return ""
    year, month = archive_month.split("-", 1)
    return f"{year}年{int(month)}月"


def build_archive_links() -> list[dict]:
    rows = (
        db.session.query(
            db.func.substr(RawItem.published_at, 1, 7).label("archive_month"),
            db.func.count(RawItem.id),
        )
        .filter(
            RawItem.published_at.isnot(None),
            RawItem.published_at != "",
            RawItem.published_at.op("GLOB")("20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]"),
        )
        .group_by("archive_month")
        .order_by(text("archive_month DESC"))
        .all()
    )
    links = []
    for archive_month, count in rows:
        normalized_month = normalize_archive_month(archive_month or "")
        if not normalized_month:
            continue
        links.append({
            "month": normalized_month,
            "label": format_archive_month_label(normalized_month),
            "count": count,
            "href": (
                url_for("archive_month_page", archive_month=normalized_month)
                if has_request_context()
                else f"/archive/{normalized_month}"
            ),
        })
    return links


def build_export_months(source_type: str) -> list[dict]:
    """Return the publication months that can be selected for a PDF export."""
    rows = (
        db.session.query(
            db.func.substr(RawItem.published_at, 1, 7).label("archive_month"),
            db.func.count(RawItem.id),
        )
        .filter(
            RawItem.source_type == source_type,
            RawItem.published_at.isnot(None),
            RawItem.published_at != "",
            RawItem.published_at.op("GLOB")("20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]"),
        )
        .group_by("archive_month")
        .order_by(text("archive_month DESC"))
        .all()
    )
    return [
        {
            "month": month,
            "label": format_archive_month_label(month),
            "count": count,
        }
        for raw_month, count in rows
        if (month := normalize_archive_month(raw_month or ""))
    ]


def build_display_category_priority():
    return case(
        (RawItem.source_type == "event", 0),
        (RawItem.source_name.like("Startup /%"), 2),
        (RawItem.source_type == "news", 1),
        (RawItem.source_type == "paper", 3),
        else_=4,
    )


def get_latest_crawl_batch_id() -> str:
    latest_item = (
        RawItem.query
        .filter(RawItem.crawl_batch_id.isnot(None), RawItem.crawl_batch_id != "")
        .order_by(RawItem.fetched_at.desc(), RawItem.id.desc())
        .first()
    )
    if not latest_item:
        return ""
    return latest_item.crawl_batch_id or ""


def dates_match(left: Optional[str], right: Optional[str]) -> bool:
    if not left or not right:
        return False
    left_dt = parse_date_safe(left)
    right_dt = parse_date_safe(right)
    if left_dt and right_dt:
        return left_dt.date() == right_dt.date()
    return left == right


COUNTRY_RULES = [
    ("日本", ["japan", "tokyo", "osaka", "yokohama", "tokyo big sight", "takanawa", "有明", "東京", "日本"]),
    ("米国", ["usa", "united states", "u.s.", "u.s.a.", "las vegas", "boston", "san jose", "silicon valley", "washington, d.c.", "nevada", "california", "massachusetts"]),
    ("韓国", ["korea", "seoul", "busan", "incheon", "대한민국", "한국"]),
    ("中国", ["china", "hangzhou", "shenzhen", "beijing", "shanghai", "zhejiang", "中国", "杭州", "深圳", "上海", "北京"]),
    ("英国", ["united kingdom", "uk", "london", "england", "britain"]),
    ("ドイツ", ["germany", "berlin", "munich", "hannover", "frankfurt"]),
    ("フランス", ["france", "paris", "lyon"]),
    ("ギリシャ", ["greece", "athens"]),
    ("シンガポール", ["singapore"]),
    ("台湾", ["taiwan", "taipei"]),
    ("カナダ", ["canada", "toronto", "vancouver", "montreal"]),
    ("アラブ首長国連邦", ["uae", "united arab emirates", "dubai", "abu dhabi"]),
    ("サウジアラビア", ["saudi arabia", "riyadh"]),
]

OFFICIAL_EVENT_DOMAINS = {
    "irex.nikkan.co.jp",
    "www.manufacturing-world.jp",
    "www.fiweek.jp",
    "www.nextech-week.jp",
    "www.expo2025.or.jp",
    "www.japan-it.jp",
    "www.ceatec.com",
    "ceatec.com",
    "aismiley.co.jp",
    "vision-ai-expo.jp",
    "humanoidssummit.com",
    "2026.ieee-humanoids.org",
    "robot-technology.jp",
    "tf.jma.or.jp",
}

VENUE_EVENT_DOMAINS = {
    "www.t-i-forum.co.jp",
    "www.m-messe.co.jp",
}

AGGREGATOR_EVENT_DOMAINS = {
    "qviro.com",
    "www.showsbee.com",
    "www.tradefairdates.com",
    "www.globaltradefairs.com",
    "globaltradefairs.com",
    "exhibitionsforyou.com",
    "expolume.com",
    "robohorizon.com",
    "automationexpo.com",
    "www.eventseye.com",
    "www.m2mconference.com",
    "www.seexpo.com",
    "expoquote.co",
    "jasumo.com",
    "seminar-hiroba.com",
    "techplay.jp",
}

PARENT_EVENT_SERIES = {
    "nextech-week",
    "japan-it-week",
    "manufacturing-world",
}


def extract_event_country(item: RawItem) -> str:
    if item.source_type != "event":
        return ""

    text_parts = [item.title or "", item.raw_summary or "", item.url or ""]
    raw_text = item.raw_text or ""
    if raw_text:
        payload_text = raw_text
        if raw_text.startswith("Event signature:"):
            payload_text = raw_text.split("\n\n", 1)[1] if "\n\n" in raw_text else raw_text
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            text_parts.extend([
                str(payload.get("location", "") or ""),
                str(payload.get("summary", "") or ""),
                str(payload.get("page_excerpt", "") or "")[:1500],
                str(payload.get("search_snippet", "") or ""),
                str(payload.get("event_name", "") or ""),
            ])

    blob = " ".join(text_parts).lower()
    for country_name, keywords in COUNTRY_RULES:
        if any(keyword in blob for keyword in keywords):
            return country_name
    return "その他"


def build_event_groups(items: list[RawItem]) -> list[dict]:
    groups: dict[str, list[RawItem]] = {}
    for item in items:
        country = extract_event_country(item)
        item.event_country = country
        groups.setdefault(country, []).append(item)

    ordered_countries = sorted(
        groups.keys(),
        key=lambda name: (name == "その他", name),
    )
    return [{"country": country, "items": groups[country]} for country in ordered_countries]


def build_country_tabs(
    source_type: str,
    selected_country: str,
    groups: list[dict],
    args,
    base_path: str,
) -> list[dict]:
    if source_type != "event" or not groups:
        return []

    base_params = []
    for key in ["q", "source_name", "source_type", "sort", "order"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    total_count = sum(len(group["items"]) for group in groups)
    tabs = [{
        "label": "すべて",
        "country": "",
        "count": total_count,
        "active": selected_country == "",
        "href": base_path + ("?" + urlencode(base_params) if base_params else ""),
    }]

    for group in groups:
        params = base_params + [("event_country", group["country"])]
        tabs.append({
            "label": group["country"],
            "country": group["country"],
            "count": len(group["items"]),
            "active": selected_country == group["country"],
            "href": base_path + ("?" + urlencode(params) if params else ""),
        })
    return tabs


def build_event_country_shortcuts(
    selected_country: str,
    groups: list[dict],
    args,
    base_path: str,
) -> list[dict]:
    if not groups:
        return []

    base_params = []
    for key in ["q", "source_name", "sort", "order", "crawl_date"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    shortcuts = []
    for group in groups:
        params = base_params + [("source_type", "event")]
        if group["country"]:
            params.append(("event_country", group["country"]))
        shortcuts.append({
            "label": group["country"],
            "count": len(group["items"]),
            "active": selected_country == group["country"],
            "href": base_path + ("?" + urlencode(params) if params else ""),
        })
    return shortcuts


def extract_news_category(item: RawItem) -> str:
    if item.source_type != "news":
        return ""

    source_name = (item.source_name or "").strip()
    if source_name.startswith("Google News / Physical AI"):
        return "Physical-AI"
    if source_name.startswith("Google News / Robot Makers"):
        return "Robot Makers"
    if source_name.startswith(("Google News / Real Haptics", "Google News / Haptics Robotics")):
        return "要素技術"
    if source_name.startswith("Google News / Robotics Sensing"):
        return "要素技術"
    if source_name.startswith("Google News / Robotics Components"):
        return "要素技術"
    if source_name.startswith("Startup /"):
        return "Startup"
    return "その他"


def extract_element_technology_category(item: RawItem) -> str:
    """Classify articles within the news category 「要素技術」."""
    if extract_news_category(item) != "要素技術":
        return ""

    blob = " ".join([
        item.title or "", item.raw_summary or "", item.raw_text or "",
    ]).lower()
    source_name = (item.source_name or "").lower()
    if source_name.startswith((
        "google news / robotics sensing",
        "google news / real haptics",
        "google news / haptics robotics",
    )):
        return "センサ・センシング"
    if any(keyword in blob for keyword in (
        "ダイレクトドライブ", "ddモータ", "ddモーター", "direct drive motor", "torque motor",
    )):
        return "ダイレクトドライブモータ"
    if any(keyword in blob for keyword in (
        "減速機", "精密減速機", "ハーモニックドライブ", "harmonic drive", "robot gear", "robot gearbox", "robot reducer",
    )):
        return "ギヤ・減速機"
    if any(keyword in blob for keyword in ("アクチュエータ", "actuator")):
        return "アクチュエータ"
    if any(keyword in blob for keyword in ("センサ", "センサー", "sensor")):
        return "センサ・センシング"
    return "その他"


def extract_sensor_sensing_category(item: RawItem) -> str:
    """Classify sensor and sensing articles into their sensing modality."""
    if extract_element_technology_category(item) != "センサ・センシング":
        return ""

    blob = " ".join([
        item.title or "", item.raw_summary or "", item.raw_text or "",
    ]).lower()
    if any(keyword in blob for keyword in (
        "力触覚", "力覚", "触覚", "force-torque", "force tactile", "tactile sensor", "tactile sensing", "haptic",
    )):
        return "力触覚センサ"
    if any(keyword in blob for keyword in (
        "聴覚", "音響", "音源定位", "robot hearing", "auditory", "audio perception", "sound source",
    )):
        return "聴覚センサ"
    if any(keyword in blob for keyword in (
        "視覚", "画像", "カメラ", "マシンビジョン", "ロボットビジョン", "machine vision", "visual sensing", "robot vision", "camera",
    )):
        return "視覚センサ・カメラ"
    return "その他"


@lru_cache(maxsize=10000)
def classify_paper_element_categories(title: str, summary: str) -> tuple[str, str]:
    """Return the two-level hardware category for one paper.

    The result is cached by title and abstract, which are immutable source
    metadata in normal operation.  This keeps the tile menu from re-running
    the same regular-expression classification thousands of times per page.
    """
    blob = " ".join([title or "", summary or ""])
    if re.search(r"\bdirect[- ]drive\b|\btorque motors?\b|ダイレクトドライブ", blob, re.IGNORECASE):
        return "ダイレクトドライブモータ", ""
    if re.search(r"\bharmonic drive\b|\breducers?\b|\bgearboxes?\b|\brobot gears?\b|減速機|ギヤ", blob, re.IGNORECASE):
        return "ギヤ・減速機", ""
    if re.search(r"\bactuators?\b|アクチュエータ", blob, re.IGNORECASE):
        return "アクチュエータ", ""
    if not re.search(
        r"\bsensors?\b|\bsensing\b|\bproprioceptive sensors?\b|\blidar\b|\bradar\b|"
        r"\bcameras?\b|\bevent camera\b|\bvisual sensors?\b|\bmicrophones?\b|"
        r"\baudio sensors?\b|\bauditory sensors?\b|\bacoustic sensors?\b|\brobot hearing\b|"
        r"\btactile\b|\bhaptic\b|\bforce[- ]torque\b|\bforce sensing\b|"
        r"センサ|センシング|視覚センサ|聴覚|触覚|力触覚",
        blob,
        re.IGNORECASE,
    ):
        if re.search(
            r"\bend[- ]effector\b|\bgrippers?\b|\btransmission\b|\bcable[- ]driven\b|"
            r"\bcompliant mechanism\b|\brobotic linkage\b|エンドエフェクタ|グリッパ|伝達機構",
            blob,
            re.IGNORECASE,
        ):
            return "その他", ""
        return "", ""
    if re.search(r"\btactile\b|\bhaptic\b|\bforce[- ]torque\b|\bforce sensing\b|触覚|力触覚|力覚", blob, re.IGNORECASE):
        return "センサ・センシング", "力触覚センサ"
    if re.search(r"\bauditory\b|\bacoustic\b|\brobot hearing\b|\baudio sensors?\b|\bmicrophones?\b|\bsound source\b|聴覚|音響|音源定位", blob, re.IGNORECASE):
        return "センサ・センシング", "聴覚センサ"
    if re.search(r"\bcameras?\b|\bevent camera\b|\bvisual sensors?\b|\bimaging sensor\b|視覚センサ|カメラ", blob, re.IGNORECASE):
        return "センサ・センシング", "視覚センサ・カメラ"
    return "センサ・センシング", "その他"


def extract_paper_element_category(item: RawItem) -> str:
    """Classify only papers whose title/abstract concerns a hardware element."""
    if item.source_type != "paper":
        return ""
    return classify_paper_element_categories(item.title or "", item.raw_summary or "")[0]


def extract_paper_sensor_category(item: RawItem) -> str:
    if item.source_type != "paper":
        return ""
    return classify_paper_element_categories(item.title or "", item.raw_summary or "")[1]


def extract_news_region(item: RawItem) -> str:
    if item.source_type != "news":
        return ""

    blob = " ".join([
        item.source_name or "",
        item.title or "",
        item.raw_summary or "",
        item.raw_text or "",
    ]).lower()

    domestic_markers = [
        "日本", "国内", "東京", "大阪", "名古屋", "福岡", "札幌",
        "japan", "tokyo", "osaka", "nagoya", "fukuoka", "sapporo",
        "日経", "itmedia", "monoist", "ascii.jp", "pr times", "prtimes",
        "ロボスタ", "robotstart", "robostart", "impress", "マイナビ", "共同通信",
        "nvidia | japan blog", "japan blog",
    ]
    overseas_markers = [
        "united states", "u.s.", "usa", "europe", "germany", "france", "uk",
        "china", "korea", "singapore", "taiwan", "canada", "australia",
        "reuters", "bloomberg", "techcrunch", "the robot report", "venturebeat",
        "ieee spectrum", "robotics 24/7", "siliconangle", "crn", "zdnet", "forbes",
    ]

    if any(marker in blob for marker in domestic_markers):
        return "日本国内の記事"
    if any(marker in blob for marker in overseas_markers):
        return "海外の記事"

    if any("\u3040" <= ch <= "\u30ff" or "\u4e00" <= ch <= "\u9fff" for ch in blob):
        return "日本国内の記事"
    return "海外の記事"


def build_news_category_groups(items: list[RawItem]) -> list[dict]:
    groups: dict[tuple[str, str], list[RawItem]] = {}
    for item in items:
        category = extract_news_category(item)
        region = extract_news_region(item)
        item.news_region = region
        item.news_category = category
        groups.setdefault((region, category), []).append(item)

    region_order = {
        "日本国内の記事": 0,
        "海外の記事": 1,
    }
    category_order = {
        "Physical-AI": 0,
        "Robot Makers": 1,
        "要素技術": 2,
        "Startup": 3,
        "その他": 9,
    }
    ordered_keys = sorted(
        groups.keys(),
        key=lambda value: (
            region_order.get(value[0], 9),
            category_order.get(value[1], 9),
            value[0],
            value[1],
        ),
    )
    return [
        {"region": region, "category": category, "items": groups[(region, category)]}
        for region, category in ordered_keys
    ]


def build_news_category_shortcuts(selected_region: str, selected_category: str, groups: list[dict], args, base_path: str) -> list[dict]:
    if not groups:
        return []

    base_params = []
    for key in ["q", "source_name", "sort", "order"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    shortcuts = []
    for group in groups:
        params = base_params + [
            ("source_type", "news"),
            ("news_region", group["region"]),
            ("news_category", group["category"]),
        ]
        shortcuts.append({
            "label": f'{group["region"]} / {group["category"]}',
            "count": len(group["items"]),
            "active": selected_region == group["region"] and selected_category == group["category"],
            "href": base_path + ("?" + urlencode(params) if params else ""),
        })
    return shortcuts


def build_news_category_menu(
    selected_category: str,
    selected_element_category: str,
    selected_sensor_sensing_category: str,
    args,
    base_path: str,
    base_query,
) -> list[dict]:
    base_params = []
    for key in ["q", "source_name", "sort", "order", "news_region", "crawl_date"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    menu_items = []
    for category in ["", "Physical-AI", "Robot Makers", "要素技術", "Startup", "その他"]:
        params = base_params + [("source_type", "news")]
        if category:
            params.append(("news_category", category))
        menu_item = {
            "label": category or "すべてのニュース",
            "active": selected_category == category,
            "href": base_path + "?" + urlencode(params),
            "children": [],
        }
        if category == "要素技術":
            element_items = [
                item for item in base_query.filter(
                    RawItem.source_type == "news",
                    or_(
                        RawItem.source_name.ilike("Google News / Robotics Sensing%"),
                        RawItem.source_name.ilike("Google News / Robotics Components%"),
                        RawItem.source_name.ilike("Google News / Real Haptics%"),
                        RawItem.source_name.ilike("Google News / Haptics Robotics%"),
                    ),
                ).all()
                if extract_news_category(item) == "要素技術"
            ]
            for element_category in ELEMENT_TECHNOLOGY_SUBCATEGORIES:
                child_params = params + [("element_technology_category", element_category)]
                child_item = {
                    "label": element_category,
                    "count": sum(
                        extract_element_technology_category(item) == element_category
                        for item in element_items
                    ),
                    "active": (
                        selected_category == "要素技術"
                        and selected_element_category == element_category
                    ),
                    "href": base_path + "?" + urlencode(child_params),
                    "children": [],
                }
                if element_category == "センサ・センシング":
                    for sensor_category in SENSOR_SENSING_SUBCATEGORIES:
                        sensor_params = child_params + [("sensor_sensing_category", sensor_category)]
                        child_item["children"].append({
                            "label": sensor_category,
                            "count": sum(
                                extract_sensor_sensing_category(item) == sensor_category
                                for item in element_items
                            ),
                            "active": (
                                selected_category == "要素技術"
                                and selected_element_category == "センサ・センシング"
                                and selected_sensor_sensing_category == sensor_category
                            ),
                            "href": base_path + "?" + urlencode(sensor_params),
                        })
                menu_item["children"].append(child_item)
        menu_items.append(menu_item)
    return menu_items


def extract_paper_categories(raw_text: str) -> list[str]:
    match = re.search(r"(?:^|\n)Categories:\s*([^\n]+)", raw_text or "")
    if not match:
        return []
    return [category.strip() for category in match.group(1).split(",") if category.strip()]


PAPER_CATEGORY_LABELS = {
    "cs.RO": "ロボティクス",
    "cs.AI": "人工知能",
    "cs.CV": "コンピュータビジョン・画像認識",
    "cs.LG": "機械学習",
    "eess.SY": "システム・制御工学",
    "cs.HC": "ヒューマン・コンピュータ・インタラクション",
    "cs.CL": "自然言語処理",
    "cs.MA": "マルチエージェントシステム",
    "cs.GR": "コンピュータグラフィックス",
    "cs.SE": "ソフトウェア工学",
    "math.OC": "最適化・制御",
}


def build_paper_category_catalog(paper_query) -> tuple[tuple[str, int], ...]:
    category_counts: Counter[str] = Counter()
    rows = (
        paper_query
        .filter(RawItem.source_name.ilike("arXiv%"))
        .with_entities(RawItem.raw_text)
        .all()
    )
    for (raw_text,) in rows:
        category_counts.update(extract_paper_categories(raw_text or ""))
    # cs.RO is attached to every collected robotics paper, so supplemental tags
    # are more useful as subcategories in the menu.
    category_counts.pop("cs.RO", None)
    return tuple(category_counts.most_common(10))


def build_paper_element_menu(selected_element: str, selected_sensor: str, args, base_path: str, base_query) -> list[dict]:
    base_params = []
    for key in ["q", "source_name", "sort", "order", "crawl_date", "paper_source", "paper_category"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))
    items = base_query.filter(RawItem.source_type == "paper").all()
    classifications = [
        classify_paper_element_categories(item.title or "", item.raw_summary or "")
        for item in items
    ]
    element_counts = Counter(element for element, _sensor in classifications if element)
    sensor_counts = Counter(
        sensor for element, sensor in classifications
        if element == "センサ・センシング" and sensor
    )
    menu = []
    for category in ELEMENT_TECHNOLOGY_SUBCATEGORIES:
        params = base_params + [("source_type", "paper"), ("paper_element_category", category)]
        entry = {
            "label": category,
            "count": element_counts[category],
            "active": selected_element == category,
            "href": base_path + "?" + urlencode(params),
            "children": [],
        }
        if category == "センサ・センシング":
            for sensor in SENSOR_SENSING_SUBCATEGORIES:
                sensor_params = params + [("paper_sensor_category", sensor)]
                entry["children"].append({
                    "label": sensor,
                    "count": sensor_counts[sensor],
                    "active": selected_element == category and selected_sensor == sensor,
                    "href": base_path + "?" + urlencode(sensor_params),
                })
        menu.append(entry)
    return menu


def build_paper_category_menu(selected_source: str, selected_category: str, args, base_path: str, base_query) -> tuple[list[dict], list[dict]]:
    paper_query = base_query.filter(RawItem.source_type == "paper")
    paper_count = paper_query.with_entities(db.func.count(RawItem.id)).scalar() or 0
    catalog = build_paper_category_catalog(paper_query)
    base_params = []
    for key in ["q", "source_name", "sort", "order", "crawl_date"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    menu_items = [{
        "label": "すべての論文",
        "value": "",
        "count": paper_count or 0,
        "active": not selected_source and not selected_category,
        "href": base_path + "?" + urlencode(base_params + [("source_type", "paper")]),
    }]
    for category, count in catalog:
        params = base_params + [("source_type", "paper"), ("paper_source", "arxiv"), ("paper_category", category)]
        menu_items.append({
            "label": f"{PAPER_CATEGORY_LABELS.get(category, category)}（#{category}）",
            "value": category,
            "count": count,
            "active": selected_source == "arxiv" and selected_category == category,
            "href": base_path + "?" + urlencode(params),
        })
    source_definitions = [
        ("arxiv", "arXiv系論文", RawItem.source_name.ilike("arXiv%")),
        ("ieee", "IEEE系論文", RawItem.source_name.ilike("IEEE%")),
        ("journals", "主要ロボティクス誌", RawItem.source_name.ilike("Journal /%")),
    ]
    source_groups = []
    for source_key, label, condition in source_definitions:
        count = paper_query.filter(condition).count()
        params = base_params + [("source_type", "paper"), ("paper_source", source_key)]
        source_groups.append({
            "key": source_key,
            "label": label,
            "count": count,
            "active": selected_source == source_key and not selected_category,
            "href": base_path + "?" + urlencode(params),
            "categories": menu_items[1:] if source_key == "arxiv" else [],
        })
    return menu_items, source_groups


def build_thinktank_menu(selected_source_name: str, args, base_path: str, base_query) -> list[dict]:
    thinktank_query = base_query.filter(RawItem.source_type == "thinktank")
    rows = (
        thinktank_query
        .with_entities(RawItem.source_name, db.func.count(RawItem.id))
        .group_by(RawItem.source_name)
        .order_by(RawItem.source_name.asc())
        .all()
    )
    base_params = []
    for key in ["q", "sort", "order", "crawl_date"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    total_count = sum(count for _source_name, count in rows)
    menu_items = [{
        "label": "すべてのシンクタンク",
        "count": total_count,
        "active": not selected_source_name,
        "href": base_path + "?" + urlencode(base_params + [("source_type", "thinktank")]),
    }]
    for company_name, count in rows:
        params = base_params + [("source_type", "thinktank"), ("source_name", company_name)]
        menu_items.append({
            "label": company_name,
            "count": count,
            "active": selected_source_name == company_name,
            "href": base_path + "?" + urlencode(params),
        })
    return menu_items


def parse_event_payload(item: RawItem) -> dict:
    if item.source_type != "event" or not item.raw_text:
        return {}

    payload_text = item.raw_text
    if payload_text.startswith("Event signature:"):
        payload_text = payload_text.split("\n\n", 1)[1] if "\n\n" in payload_text else payload_text

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def format_event_period(start_date: Optional[str], end_date: Optional[str]) -> str:
    if start_date and end_date:
        if start_date == end_date:
            return start_date
        return f"{start_date} - {end_date}"
    return start_date or end_date or ""


def enrich_event_fields(item: RawItem) -> None:
    payload = parse_event_payload(item)
    item.event_start_date = payload.get("start_date", "") if payload else ""
    item.event_end_date = payload.get("end_date", "") if payload else ""
    item.event_location = payload.get("location", "") if payload else ""
    # PDF generation uses this shared enrichment path without passing through
    # the event-list view, where the country had previously been assigned.
    item.event_country = extract_event_country(item)
    item.event_period = format_event_period(item.event_start_date, item.event_end_date)


def shift_calendar_month(calendar_month: str, offset: int) -> str:
    year, month = (int(part) for part in calendar_month.split("-", 1))
    month_index = year * 12 + month - 1 + offset
    return f"{month_index // 12:04d}-{month_index % 12 + 1:02d}"


def event_date_range(item: RawItem) -> tuple[Optional[datetime], Optional[datetime]]:
    start = parse_date_safe(getattr(item, "event_start_date", ""))
    end = parse_date_safe(getattr(item, "event_end_date", ""))
    if start and not end:
        end = start
    elif end and not start:
        start = end
    if start and end and end < start:
        start, end = end, start
    return start, end


def event_occurs_in_month(item: RawItem, calendar_month: str) -> bool:
    start, end = event_date_range(item)
    if not start or not end:
        return True
    month_start = datetime.strptime(f"{calendar_month}-01", "%Y-%m-%d")
    next_month_start = datetime.strptime(f"{shift_calendar_month(calendar_month, 1)}-01", "%Y-%m-%d")
    return start < next_month_start and end >= month_start


def build_event_calendar(items: list[RawItem], calendar_month: str, base_path: str) -> dict:
    month_start = datetime.strptime(f"{calendar_month}-01", "%Y-%m-%d")
    next_month_start = datetime.strptime(f"{shift_calendar_month(calendar_month, 1)}-01", "%Y-%m-%d")
    month_end = next_month_start - timedelta(days=1)
    events_by_date: dict[str, list[RawItem]] = {}
    undated_items: list[RawItem] = []
    country_styles = {
        "日本": "japan",
        "米国": "usa",
        "中国": "china",
        "韓国": "korea",
    }

    for item in items:
        item.event_country_style = country_styles.get(getattr(item, "event_country", ""), "other")
        start, end = event_date_range(item)
        if not start or not end:
            undated_items.append(item)
            continue
        current_date = max(start, month_start)
        last_date = min(end, month_end)
        while current_date <= last_date:
            events_by_date.setdefault(current_date.strftime("%Y-%m-%d"), []).append(item)
            current_date += timedelta(days=1)

    grid_start = month_start - timedelta(days=month_start.weekday())
    grid_end = month_end + timedelta(days=6 - month_end.weekday())
    weeks = []
    current_date = grid_start
    while current_date <= grid_end:
        week = []
        for _ in range(7):
            date_key = current_date.strftime("%Y-%m-%d")
            week.append({
                "date": date_key,
                "day": current_date.day,
                "in_month": current_date.month == month_start.month,
                "events": events_by_date.get(date_key, []),
            })
            current_date += timedelta(days=1)
        weeks.append(week)

    def month_url(target_month: str) -> str:
        params = request.args.to_dict(flat=True)
        params["source_type"] = "event"
        params["calendar_month"] = target_month
        params.pop("page", None)
        return f"{base_path}?{urlencode(params)}"

    countries = sorted(
        {getattr(item, "event_country", "") or "その他" for item in items},
        key=lambda country: (["日本", "米国", "中国", "韓国", "その他"].index(country)
                             if country in ["日本", "米国", "中国", "韓国", "その他"] else 99, country),
    )
    return {
        "month": calendar_month,
        "label": f"{month_start.year}年{month_start.month}月",
        "weeks": weeks,
        "undated_items": undated_items,
        "prev_url": month_url(shift_calendar_month(calendar_month, -1)),
        "next_url": month_url(shift_calendar_month(calendar_month, 1)),
        "country_legend": [
            {"country": country, "style": country_styles.get(country, "other")}
            for country in countries
        ],
    }


def extract_event_year(item: RawItem) -> str:
    for value in [getattr(item, "event_start_date", ""), item.published_at or "", item.title or ""]:
        if not value:
            continue
        match = re.search(r"(20\d{2})", value)
        if match:
            return match.group(1)
    return ""


def extract_event_series_key(item: RawItem) -> str:
    blob = " ".join([
        item.title or "",
        item.raw_summary or "",
        item.event_location or "",
        item.url or "",
    ]).lower()

    series_patterns = [
        ("vision-ai-expo", ["vision ai expo", "画像認識 ai expo"]),
        ("ai-hakurankai", ["ai博覧会", "ai hakurankai"]),
        ("nextech-week", ["nextech week", "nexttech week"]),
        ("japan-it-week", ["japan it week"]),
        ("ceatec", ["ceatec"]),
        ("irex", ["irex", "international robot exhibition", "国際ロボット展"]),
        ("robodex", ["robodex", "ロボデックス"]),
        ("manufacturing-world", ["manufacturing world", "ものづくり ワールド", "ものづくりワールド"]),
        ("humanoids-summit", ["humanoids summit"]),
        ("humanoid-robot-expo", ["ヒューマノイドロボット expo", "humanoid robot expo"]),
        ("physical-ai-expo", ["physical ai expo", "フィジカルai展", "フィジカル ai 展"]),
        ("robot-technology-japan", ["robot technology japan"]),
    ]
    for key, keywords in series_patterns:
        if any(keyword in blob for keyword in keywords):
            return key

    normalized = re.sub(r"\[[^\]]+\]", "", (item.title or "").lower())
    normalized = re.sub(r"20\d{2}", "", normalized)
    normalized = re.sub(r"[^a-z0-9一-龥ぁ-んァ-ヶ]+", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized[:80]


def extract_event_season_token(item: RawItem) -> str:
    blob = " ".join([item.title or "", item.raw_summary or "", item.url or ""]).lower()
    season_patterns = [
        ("spring", ["spring", "春"]),
        ("summer", ["summer", "夏"]),
        ("autumn", ["autumn", "fall", "秋"]),
        ("winter", ["winter", "冬"]),
    ]
    for season, keywords in season_patterns:
        if any(keyword in blob for keyword in keywords):
            return season
    return ""


def build_event_parent_key(item: RawItem) -> str:
    series_key = extract_event_series_key(item)
    year = extract_event_year(item)
    season = extract_event_season_token(item)
    return "::".join([series_key, year, season])


def classify_event_scope(item: RawItem) -> str:
    series_key = extract_event_series_key(item)
    if series_key not in PARENT_EVENT_SERIES:
        return "standalone"

    title_blob = " ".join([item.title or "", item.raw_summary or "", item.url or ""]).lower()
    child_markers = {
        "nextech-week": [
            "ai・人工知能expo",
            "フィジカルai expo",
            "ヒューマノイドロボット expo",
            "ヒューマノイドロボットexpo",
            "量子コンピューティングexpo",
            "ブロックチェーンexpo",
            "/visit/ai",
            "/visit/hr",
        ],
        "japan-it-week": [
            "現場dx expo",
            "ai・業務自動化",
            "/visit/ai",
            "/visit/deskless",
        ],
        "manufacturing-world": [
            "フィジカルai展",
            "/about/physicalai",
            "smart maintenance expo",
        ],
    }
    if any(marker in title_blob for marker in child_markers.get(series_key, [])):
        return "child"
    if "来場案内" in title_blob or "/visit/" in title_blob:
        return "child"
    return "parent"


def extract_child_event_identity(item: RawItem) -> str:
    """Return a stable identity so sibling exhibitions are not deduplicated."""
    blob = " ".join([item.title or "", item.raw_summary or "", item.url or ""]).lower()
    identities = [
        ("physical-ai-expo", ["フィジカルai expo", "フィジカルai展", "/about/physicalai", "/about/ph.html"]),
        ("humanoid-robot-expo", ["ヒューマノイドロボット expo", "ヒューマノイドロボットexpo", "/visit/hr"]),
        ("ai-expo", ["ai・人工知能expo", "/visit/ai"]),
        ("quantum-expo", ["量子コンピューティングexpo"]),
        ("blockchain-expo", ["ブロックチェーンexpo"]),
        ("field-dx-expo", ["現場dx expo", "/visit/deskless"]),
        ("ai-automation-expo", ["ai・業務自動化"]),
        ("smart-maintenance-expo", ["smart maintenance expo"]),
    ]
    for identity, markers in identities:
        if any(marker in blob for marker in markers):
            return identity
    normalized_title = re.sub(r"\[[^\]]+\]|20\d{2}", "", (item.title or "").lower())
    return re.sub(r"[^a-z0-9一-龥ぁ-んァ-ヶ]+", "-", normalized_title).strip("-")[:80]


def event_representation_score(item: RawItem) -> tuple[int, int, int]:
    payload = parse_event_payload(item)
    source_domain = str(payload.get("source_domain", "") or "")
    score = 0

    if source_domain in OFFICIAL_EVENT_DOMAINS:
        score += 100
    elif source_domain in VENUE_EVENT_DOMAINS:
        score += 90
    elif source_domain in AGGREGATOR_EVENT_DOMAINS:
        score += 20
    else:
        score += 50

    title_blob = f"{item.title or ''} {item.raw_summary or ''}".lower()
    if "公式" in title_blob or "official" in title_blob:
        score += 10
    if item.event_start_date:
        score += 5
    if item.event_end_date:
        score += 3
    if payload.get("search_engine") == "official_seed":
        score += 10

    # Prefer pages that are event pages themselves over exhibitor/news articles.
    noisy_terms = ["出展", "pressrelease", "プレスリリース", "開催速報", "ブース", "news", "article", "レポート", "guide"]
    if any(term in title_blob or term in (item.url or "").lower() for term in noisy_terms):
        score -= 25

    return (score, item.id or 0, len(item.raw_summary or ""))


def dedupe_event_items(items: list[RawItem]) -> list[RawItem]:
    grouped: dict[tuple[str, str, str, str], list[RawItem]] = {}
    others: list[RawItem] = []

    for item in items:
        enrich_event_fields(item)
        series_key = extract_event_series_key(item)
        event_year = extract_event_year(item)
        season_key = extract_event_season_token(item)
        if not series_key:
            others.append(item)
            continue
        country = extract_event_country(item)
        item.event_country = country
        scope_key = classify_event_scope(item)
        if scope_key == "child":
            scope_key = f"child:{extract_child_event_identity(item)}"
        grouped.setdefault((series_key, event_year, season_key, scope_key), []).append(item)

    representatives: list[RawItem] = []
    for _, candidates in grouped.items():
        candidates.sort(key=event_representation_score, reverse=True)
        representatives.append(candidates[0])

    series_with_dated_items = {
        extract_event_series_key(item)
        for item in representatives
        if extract_event_year(item)
    }
    representatives = [
        item
        for item in representatives
        if extract_event_year(item)
        or extract_event_series_key(item) not in series_with_dated_items
    ]

    representatives.extend(others)
    representatives.sort(key=lambda item: (item.published_at or "", item.id or 0), reverse=True)
    return representatives


def attach_event_hierarchy(items: list[RawItem], query_text: str = "") -> list[RawItem]:
    normalized_query = (query_text or "").strip().lower()
    for item in items:
        enrich_event_fields(item)
        item.event_series_key = extract_event_series_key(item)
        item.event_year = extract_event_year(item)
        item.event_season = extract_event_season_token(item)
        item.event_parent_key = build_event_parent_key(item)
        item.event_scope = classify_event_scope(item)
        item.child_events = []

    parent_map: dict[str, RawItem] = {}
    child_buckets: dict[str, list[RawItem]] = {}

    for item in items:
        if item.event_scope == "parent":
            existing = parent_map.get(item.event_parent_key)
            if existing is None or event_representation_score(item) > event_representation_score(existing):
                parent_map[item.event_parent_key] = item

    for item in items:
        if item.event_scope != "child":
            continue
        child_buckets.setdefault(item.event_parent_key, []).append(item)

    visible_items: list[RawItem] = []
    attached_child_ids: set[int] = set()

    for item in items:
        if item.event_scope == "child":
            continue
        if item.event_scope == "parent":
            children = sorted(
                child_buckets.get(item.event_parent_key, []),
                key=event_representation_score,
                reverse=True,
            )
            item.child_events = children
            attached_child_ids.update(child.id for child in children)
        visible_items.append(item)

    if normalized_query:
        for child_items in child_buckets.values():
            for child in child_items:
                blob = " ".join([child.title or "", child.raw_summary or "", child.url or ""]).lower()
                if normalized_query in blob and child.id not in attached_child_ids:
                    visible_items.append(child)

    visible_items.sort(key=lambda item: (item.published_at or "", item.id or 0), reverse=True)
    return visible_items


def render_item_list(*, archive_month: str = "", page_title: str = "Physical-AI情報収集クローラ", base_path: str = "/"):
    q = request.args.get("q", "").strip()
    requested_collection_status = request.args.get("collection_status", "").strip()
    source_name = request.args.get("source_name", "").strip()
    source_type = request.args.get("source_type", "").strip()
    event_country = request.args.get("event_country", "").strip()
    news_region = request.args.get("news_region", "").strip()
    news_category = request.args.get("news_category", "").strip()
    requested_element_technology_category = request.args.get("element_technology_category", "").strip()
    element_technology_category = (
        requested_element_technology_category
        if requested_element_technology_category in ELEMENT_TECHNOLOGY_SUBCATEGORIES
        else ""
    )
    requested_sensor_sensing_category = request.args.get("sensor_sensing_category", "").strip()
    sensor_sensing_category = (
        requested_sensor_sensing_category
        if requested_sensor_sensing_category in SENSOR_SENSING_SUBCATEGORIES
        else ""
    )
    requested_paper_category = request.args.get("paper_category", "").strip()
    paper_category = requested_paper_category if re.fullmatch(r"[a-z][a-z0-9-]*\.[A-Za-z0-9-]+", requested_paper_category) else ""
    requested_paper_source = request.args.get("paper_source", "").strip().lower()
    paper_source = requested_paper_source if requested_paper_source in {"arxiv", "ieee", "journals"} else ""
    paper_element_category = request.args.get("paper_element_category", "").strip()
    if paper_element_category not in ELEMENT_TECHNOLOGY_SUBCATEGORIES:
        paper_element_category = ""
    paper_sensor_category = request.args.get("paper_sensor_category", "").strip()
    if paper_sensor_category not in SENSOR_SENSING_SUBCATEGORIES:
        paper_sensor_category = ""
    sort = request.args.get("sort", "published_at").strip()
    order = request.args.get("order", "desc").strip()
    crawl_date = normalize_crawl_date(request.args.get("crawl_date", ""))
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    requested_per_page = request.args.get("per_page", 50, type=int) or 50
    per_page = requested_per_page if requested_per_page in {25, 50, 100} else 50
    requested_calendar_month = normalize_archive_month(request.args.get("calendar_month", ""))
    calendar_month = requested_calendar_month or datetime.now().strftime("%Y-%m")
    query = RawItem.query

    if crawl_date:
        # fetched_at is stored as naive UTC. Treat the selected crawler execution
        # date as JST and convert its boundaries back to UTC for an indexed range query.
        jst_start = datetime.strptime(crawl_date, "%Y-%m-%d")
        utc_start = jst_start - timedelta(hours=9)
        utc_end = utc_start + timedelta(days=1)
        query = query.filter(RawItem.fetched_at >= utc_start, RawItem.fetched_at < utc_end)

    if q:
        query = query.filter(build_keyword_match_filter(q))

    if archive_month:
        query = query.filter(RawItem.published_at.like(f"{archive_month}-%"))

    thinktank_menu_query = query

    if source_name:
        query = query.filter(RawItem.source_name == source_name)

    event_preview_query = query.filter(RawItem.source_type == "event")
    event_preview_items = event_preview_query.all()
    event_preview_items = dedupe_event_items(event_preview_items)
    event_preview_groups = build_event_groups(event_preview_items) if event_preview_items else []
    event_country_shortcuts = build_event_country_shortcuts(event_country, event_preview_groups, request.args, base_path)

    news_category_groups: list[dict] = []
    summary_query = query
    news_category_shortcuts = build_news_category_menu(
        news_category,
        element_technology_category,
        sensor_sensing_category,
        request.args,
        base_path,
        summary_query,
    )
    paper_category_shortcuts, paper_source_groups = build_paper_category_menu(
        paper_source, paper_category, request.args, base_path, summary_query
    )
    paper_element_menu = build_paper_element_menu(
        paper_element_category, paper_sensor_category, request.args, base_path, summary_query
    )
    thinktank_shortcuts = build_thinktank_menu(
        source_name, request.args, base_path, thinktank_menu_query
    )

    if source_type:
        query = query.filter(RawItem.source_type == source_type)
    if source_type == "paper" and paper_category:
        query = query.filter(RawItem.raw_text.like(f"%{paper_category}%"))
    if source_type == "paper" and paper_source == "arxiv":
        query = query.filter(RawItem.source_name.ilike("arXiv%"))
    elif source_type == "paper" and paper_source == "ieee":
        query = query.filter(RawItem.source_name.ilike("IEEE%"))
    elif source_type == "paper" and paper_source == "journals":
        query = query.filter(RawItem.source_name.ilike("Journal /%"))

    sortable_columns = {
        "fetched_at": RawItem.fetched_at,
        "published_at": RawItem.published_at,
        "title": RawItem.title,
        "source_name": RawItem.source_name,
        "source_type": RawItem.source_type,
    }

    sort_column = sortable_columns.get(sort, RawItem.published_at)
    display_category_priority = build_display_category_priority()

    if sort == "published_at":
        published_is_empty = case((RawItem.published_at.is_(None), 1), (RawItem.published_at == "", 1), else_=0)
        if order == "asc":
            query = query.order_by(
                published_is_empty.asc(),
                RawItem.published_at.asc(),
                display_category_priority.asc(),
                RawItem.fetched_at.asc(),
            )
        else:
            query = query.order_by(
                published_is_empty.asc(),
                RawItem.published_at.desc(),
                display_category_priority.asc(),
                RawItem.fetched_at.desc(),
            )
    elif order == "asc":
        query = query.order_by(sort_column.asc(), display_category_priority.asc(), RawItem.fetched_at.desc())
    else:
        query = query.order_by(sort_column.desc(), display_category_priority.asc(), RawItem.fetched_at.desc())

    trend_result_groups: list[dict] = []
    if source_type == "event":
        candidate_items = query.all()
        candidate_items = dedupe_event_items(candidate_items)
        candidate_items = attach_event_hierarchy(candidate_items, q)
        if event_country:
            candidate_items = [item for item in candidate_items if extract_event_country(item) == event_country]
        candidate_items = [item for item in candidate_items if event_occurs_in_month(item, calendar_month)]
        pagination_total = len(candidate_items)
        page = 1
        items = candidate_items
    elif source_type == "trend":
        # Do not let the selected crawl date hide a trend pair after a failed
        # Google request. The browser uses the same latest-or-placeholder set
        # as the daily PDF.
        candidate_items = build_latest_default_trend_items()
        latest_trends: dict[tuple[str, str], dict] = {}
        for candidate in candidate_items:
            series = build_google_trend_series(candidate)
            if series["time_range"] != "now 7-d":
                continue
            key = (series["keyword"], series["region"])
            if key not in latest_trends:
                series["available"] = bool(series["points"])
                series["detail_url"] = f"/raw/{candidate.id}" if candidate.id else ""
                latest_trends[key] = {"item": candidate, "series": series}

        grouped_trends: dict[str, dict] = {
            keyword: {"keyword": keyword, "by_region": {}, "item": None}
            for keyword in DEFAULT_TREND_KEYWORDS
        }
        for (keyword, region), entry in latest_trends.items():
            if keyword not in grouped_trends:
                continue
            group = grouped_trends[keyword]
            if group["item"] is None:
                group["item"] = entry["item"]
            group["by_region"][region] = entry["series"]

        all_trend_groups = []
        for keyword in DEFAULT_TREND_KEYWORDS:
            group = grouped_trends[keyword]
            region_series = []
            for region in ("日本", "世界"):
                region_series.append(group["by_region"].get(region, {
                    "keyword": keyword,
                    "region": region,
                    "available": False,
                    "rankings": [],
                    "last_updated_at": "未取得",
                }))
            all_trend_groups.append({"keyword": keyword, "series": region_series, "item": group["item"]})

        pagination_total = len(all_trend_groups)
        offset = (page - 1) * per_page
        trend_result_groups = all_trend_groups[offset:offset + per_page]
        items = [group["item"] for group in trend_result_groups if group["item"] is not None]
    elif source_type == "news" and (news_region or news_category or element_technology_category or sensor_sensing_category):
        candidate_items = query.all()
        candidate_items = [
            item for item in candidate_items
            if (not news_region or extract_news_region(item) == news_region)
            and (not news_category or extract_news_category(item) == news_category)
            and (not element_technology_category or extract_element_technology_category(item) == element_technology_category)
            and (not sensor_sensing_category or extract_sensor_sensing_category(item) == sensor_sensing_category)
        ]
        pagination_total = len(candidate_items)
        offset = (page - 1) * per_page
        items = candidate_items[offset:offset + per_page]
    elif source_type == "paper" and (paper_element_category or paper_sensor_category):
        candidate_items = [item for item in query.all() if (
            not paper_element_category or extract_paper_element_category(item) == paper_element_category
        ) and (
            not paper_sensor_category or extract_paper_sensor_category(item) == paper_sensor_category
        )]
        pagination_total = len(candidate_items)
        offset = (page - 1) * per_page
        items = candidate_items[offset:offset + per_page]
    else:
        pagination_total = query.order_by(None).with_entities(db.func.count(RawItem.id)).scalar() or 0
        offset = (page - 1) * per_page
        items = query.offset(offset).limit(per_page).all()

    for item in items:
        if item.source_type == "news":
            item.news_region = extract_news_region(item)
            item.news_category = extract_news_category(item)
            item.element_technology_category = extract_element_technology_category(item)
            item.sensor_sensing_category = extract_sensor_sensing_category(item)
        elif item.source_type == "paper":
            item.paper_element_category = extract_paper_element_category(item)
            item.paper_sensor_category = extract_paper_sensor_category(item)
        item.has_translation = bool(item.translated_title or item.translated_summary)
        item.display_title = item.translated_title or item.title
        item.display_summary = clean_summary(item.translated_summary or item.raw_summary)
        item.original_summary = clean_summary(item.raw_summary)
        if item.source_type == "trend" and not hasattr(item, "trend_series"):
            trend_series = build_google_trend_series(item)
            item.trend_series = trend_series if trend_series["time_range"] == "now 7-d" else None
        enrich_event_fields(item)

    event_groups: list[dict] = []
    event_calendar: dict = {}
    event_country_tabs: list[dict] = []
    available_event_countries: list[str] = []
    if items and all(item.source_type == "event" for item in items):
        event_groups = build_event_groups(items)
        available_event_countries = [group["country"] for group in event_preview_groups]
        event_country_tabs = build_country_tabs(source_type, event_country, event_preview_groups, request.args, base_path)
    if source_type == "event":
        event_calendar = build_event_calendar(items, calendar_month, base_path)

    source_names = [
        row[0]
        for row in db.session.query(RawItem.source_name)
        .distinct()
        .order_by(RawItem.source_name.asc())
        .all()
    ]

    source_types = [
        row[0]
        for row in summary_query.with_entities(RawItem.source_type)
        .distinct()
        .order_by(RawItem.source_type.asc())
        .all()
    ]
    # The daily-news view keeps the fixed Google Trends set visible even when
    # the latest collection only succeeded for some (or none) of its pairs.
    if crawl_date and "trend" not in source_types:
        source_types.append("trend")
        source_types.sort()

    type_counts_raw = (
        summary_query.with_entities(RawItem.source_type, db.func.count(RawItem.id))
        .group_by(RawItem.source_type)
        .all()
    )
    type_counts = {source_type: count for source_type, count in type_counts_raw}
    if crawl_date:
        type_counts["trend"] = len(DEFAULT_TREND_KEYWORDS) * len(TREND_REGIONS)
    if "event" in type_counts:
        # The event tile represents unique exhibitions, not raw records such
        # as Japanese/English variants of the same official event page.
        type_counts["event"] = len(event_preview_items)
    tile_params = {}
    for key in ["q", "source_name", "sort", "order", "crawl_date"]:
        value = (request.args.get(key) or "").strip()
        if value:
            tile_params[key] = value
    source_type_tiles = []
    for available_type in source_types:
        params = dict(tile_params)
        params["source_type"] = available_type
        source_type_tiles.append({
            "type": available_type,
            "count": type_counts.get(available_type, 0),
            "href": f"{base_path}?{urlencode(params)}",
            "active": source_type == available_type,
        })
    total_count = summary_query.with_entities(db.func.count(RawItem.id)).scalar()
    current_list_url = request.full_path if request.query_string else request.path
    if current_list_url.endswith("?"):
        current_list_url = current_list_url[:-1]
    archive_links = build_archive_links()
    recent_crawl_dates = build_recent_crawl_dates()
    today_jst_datetime = datetime.utcnow() + timedelta(hours=9)
    today_jst = today_jst_datetime.strftime("%Y-%m-%d")
    yesterday_jst = (today_jst_datetime - timedelta(days=1)).strftime("%Y-%m-%d")
    pagination_pages = max(1, ceil(pagination_total / per_page))

    def pagination_url(target_page: int) -> str:
        params = request.args.to_dict(flat=True)
        params["page"] = str(target_page)
        params["per_page"] = str(per_page)
        return f"{base_path}?{urlencode(params)}"

    pagination = {
        "page": page,
        "per_page": per_page,
        "total": pagination_total,
        "pages": pagination_pages,
        "start": ((page - 1) * per_page + 1) if (items or trend_result_groups) else 0,
        "end": min(page * per_page, pagination_total),
        "has_prev": page > 1,
        "has_next": page < pagination_pages,
        "prev_url": pagination_url(page - 1) if page > 1 else "",
        "next_url": pagination_url(page + 1) if page < pagination_pages else "",
    }
    collection_keyword = request.args.get("collection_keyword", "").strip()
    collection_inserted = request.args.get("collection_inserted", "").strip()
    collection_skipped = request.args.get("collection_skipped", "").strip()
    collection_status = requested_collection_status
    collection_sources = request.args.get("collection_sources", "").strip()
    is_collection_result_view = collection_status == "ok" and bool(q)
    is_tile_result_view = source_type in EXPORTABLE_SOURCE_TYPES
    is_export_result_view = is_collection_result_view or is_tile_result_view
    if is_collection_result_view:
        export_pdf_params = {"q": q}
        export_pdf_endpoint = "search_results_pdf"
    else:
        if source_type == "event":
            # Event exports intentionally cover the complete domestic and
            # international event catalog, independent of the calendar view.
            export_pdf_params = {"source_type": "event"}
        else:
            export_pdf_params = {
                key: value
                for key, value in request.args.to_dict(flat=True).items()
                if key in {
                    "q", "source_name", "source_type", "crawl_date",
                    "news_region", "news_category", "element_technology_category", "sensor_sensing_category", "paper_source", "paper_category",
                } and value
            }
            if archive_month:
                export_pdf_params["archive_month"] = archive_month
        export_pdf_endpoint = "filtered_search_results_pdf"

    # News exports can be large enough to make PDF generation slow.  Require a
    # publication month on the result-page export menu and prebuild the exact
    # URLs for each selectable month so every existing filter is retained.
    is_news_month_export_view = (
        source_type == "news" and not is_collection_result_view
    )
    news_export_months = []
    if is_news_month_export_view:
        for month in build_export_months("news"):
            month_params = {**export_pdf_params, "archive_month": month["month"]}
            news_export_months.append({
                **month,
                "open_href": url_for(
                    export_pdf_endpoint, **month_params, disposition="inline"
                ),
                "download_href": url_for(
                    export_pdf_endpoint, **month_params, disposition="attachment"
                ),
            })

    return render_template(
        "list.html",
        page_title=page_title,
        archive_month=archive_month,
        archive_month_label=format_archive_month_label(archive_month),
        archive_links=archive_links,
        filter_form_action=base_path,
        reset_href=base_path,
        archive_index_href=url_for("archive_index"),
        items=items,
        source_names=source_names,
        source_types=source_types,
        current_q=q,
        current_source_name=source_name,
        current_source_type=source_type,
        current_event_country=event_country,
        current_news_region=news_region,
        current_news_category=news_category,
        current_element_technology_category=element_technology_category,
        current_sensor_sensing_category=sensor_sensing_category,
        current_paper_category=paper_category,
        current_paper_source=paper_source,
        current_paper_element_category=paper_element_category,
        current_paper_sensor_category=paper_sensor_category,
        current_sort=sort,
        current_order=order,
        current_crawl_date=crawl_date,
        recent_crawl_dates=recent_crawl_dates,
        all_news_href=url_for("list_raw_items"),
        today_news_href=url_for("list_raw_items", crawl_date=today_jst),
        yesterday_news_href=url_for("list_raw_items", crawl_date=yesterday_jst),
        daily_news_pdf_open_href=url_for("today_news_pdf", date=crawl_date, disposition="inline") if crawl_date else "",
        daily_news_pdf_download_href=url_for("today_news_pdf", date=crawl_date, disposition="attachment") if crawl_date else "",
        search_results_pdf_open_href=url_for(export_pdf_endpoint, **export_pdf_params, disposition="inline") if is_export_result_view else "",
        search_results_pdf_download_href=url_for(export_pdf_endpoint, **export_pdf_params, disposition="attachment") if is_export_result_view else "",
        is_news_month_export_view=is_news_month_export_view,
        news_export_months=news_export_months,
        selected_news_export_month=archive_month if any(
            month["month"] == archive_month for month in news_export_months
        ) else "",
        is_collection_result_view=is_collection_result_view,
        is_export_result_view=is_export_result_view,
        is_all_news_view=request.path == "/" and not request.query_string,
        is_today_news_view=request.path == "/" and crawl_date == today_jst,
        is_yesterday_news_view=request.path == "/" and crawl_date == yesterday_jst,
        is_daily_news_view=request.path == "/" and bool(crawl_date),
        pagination=pagination,
        per_page_options=[25, 50, 100],
        total_count=total_count,
        type_counts=type_counts,
        source_type_tiles=source_type_tiles,
        trend_result_groups=trend_result_groups,
        event_groups=event_groups,
        event_calendar=event_calendar,
        event_calendar_href=url_for("list_raw_items", source_type="event"),
        event_country_tabs=event_country_tabs,
        available_event_countries=available_event_countries,
        event_country_shortcuts=event_country_shortcuts,
        news_category_shortcuts=news_category_shortcuts,
        paper_category_shortcuts=paper_category_shortcuts,
        paper_source_groups=paper_source_groups,
        paper_element_menu=paper_element_menu,
        thinktank_shortcuts=thinktank_shortcuts,
        available_news_regions=["日本国内の記事", "海外の記事"],
        available_news_categories=["Physical-AI", "Robot Makers", "要素技術", "Startup", "その他"],
        available_element_technology_subcategories=ELEMENT_TECHNOLOGY_SUBCATEGORIES,
        available_sensor_sensing_subcategories=SENSOR_SENSING_SUBCATEGORIES,
        collection_keyword=collection_keyword,
        collection_inserted=collection_inserted,
        collection_skipped=collection_skipped,
        collection_status=collection_status,
        collection_sources=collection_sources,
        current_list_url=current_list_url,
    )


@app.route("/")
def list_raw_items():
    return render_item_list()


def build_pdf_category_groups(items: list[RawItem]) -> list[dict]:
    source_type_definitions = [
        ("news", "ニュース"),
        ("paper", "論文"),
        ("event", "イベント・展示会"),
        ("company", "企業情報"),
        ("policy", "政策・行政情報"),
        ("thinktank", "シンクタンク情報"),
        ("trend", "Google Trends"),
    ]
    source_type_labels = dict(source_type_definitions)
    grouped_items = {source_type: [] for source_type, _label in source_type_definitions}

    def pdf_subcategory(item: RawItem) -> str:
        if item.source_type == "news":
            region = "国内" if extract_news_region(item) == "日本国内の記事" else "海外"
            return f"{region} / {extract_news_category(item) or 'その他'}"
        if item.source_type == "paper":
            source_name = item.source_name or ""
            if source_name.lower().startswith("arxiv"):
                categories = extract_paper_categories(item.raw_text or "")
                category = next((value for value in categories if value != "cs.RO"), "cs.RO")
                category_label = PAPER_CATEGORY_LABELS.get(category, category)
                return f"arXiv / {category_label}（#{category}）"
            if source_name.lower().startswith("ieee"):
                publication = re.search(r"(?:^|\n)Publication:\s*([^\n]+)", item.raw_text or "")
                publication_name = publication.group(1).strip() if publication else source_name.removeprefix("IEEE /").strip()
                if publication_name.startswith("IEEE /"):
                    publication_name = publication_name.removeprefix("IEEE /").strip()
                return f"IEEE / {publication_name or 'その他'}"
            if source_name.startswith("Journal /"):
                return f"主要誌 / {source_name.removeprefix('Journal /').strip()}"
            return source_name or "その他の論文"
        if item.source_type == "event":
            return extract_event_country(item) or "その他"
        return item.source_name or "その他"

    for item in items:
        subcategory = pdf_subcategory(item)
        pdf_item = {
            "title": item.translated_title or item.title,
            "summary": clean_summary(item.translated_summary or item.raw_summary, max_length=150),
            "source_name": item.source_name or "",
            "published_at": item.published_at or "",
            "url": item.url or "",
            "subcategory": subcategory,
        }
        if item.source_type == "event":
            enrich_event_fields(item)
            pdf_item.update({
                "event_start_date": item.event_start_date or "",
                "event_end_date": item.event_end_date or item.event_start_date or "",
                "event_country": getattr(item, "event_country", "") or extract_event_country(item),
            })
        if item.source_type == "trend":
            series = build_google_trend_series(item)
            pdf_item["trend"] = {
                key: series[key]
                for key in (
                    "keyword", "region", "latest_value", "average_value", "peak_value",
                    "values", "start_date", "end_date", "interval_label", "point_count", "rankings", "last_updated_at",
                )
            }
        grouped_items.setdefault(item.source_type or "other", []).append(pdf_item)
    category_groups = [
        {
            "category": source_type_labels.get(source_type, source_type or "その他"),
            "count": len(group_items),
            "items": group_items,
            "subcategories": [
                {"label": label, "count": count}
                for label, count in sorted(
                    Counter(item["subcategory"] for item in group_items).items(),
                    key=lambda entry: (-entry[1], entry[0]),
                )
            ],
        }
        for source_type, group_items in grouped_items.items()
        if group_items
    ]
    return category_groups


def build_daily_information_pdf(report_date: str) -> tuple[bytes, int]:
    jst_start = datetime.strptime(report_date, "%Y-%m-%d")
    utc_start = jst_start - timedelta(hours=9)
    utc_end = utc_start + timedelta(days=1)
    items = (
        RawItem.query
        .filter(RawItem.fetched_at >= utc_start, RawItem.fetched_at < utc_end)
        .order_by(RawItem.source_type.asc(), RawItem.published_at.desc(), RawItem.fetched_at.desc())
        .all()
    )
    # A Google Trends request may be rate-limited or temporarily unavailable.
    # Daily reports always show the fixed 8 keywords × 2 regions, using the
    # last successful snapshot rather than omitting failed combinations.
    items = [item for item in items if item.source_type != "trend"]
    items.extend(build_latest_default_trend_items())
    pdf_data = render_daily_news_pdf(report_date, build_pdf_category_groups(items))
    return pdf_data, len(items)


@app.route("/today-news.pdf")
def today_news_pdf():
    report_date = normalize_crawl_date(request.args.get("date", ""))
    disposition = request.args.get("disposition", "attachment").strip().lower()
    if disposition not in {"inline", "attachment"}:
        disposition = "attachment"
    if not report_date:
        report_date = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")
    pdf_data, _item_count = build_daily_information_pdf(report_date)
    return Response(
        pdf_data,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="daily-information-{report_date}.pdf"'},
    )


@app.route("/search-results.pdf")
def search_results_pdf():
    keyword = request.args.get("q", "").strip()[:200]
    if not keyword:
        return Response("検索キーワードを指定してください。", status=400, content_type="text/plain; charset=utf-8")
    disposition = request.args.get("disposition", "attachment").strip().lower()
    if disposition not in {"inline", "attachment"}:
        disposition = "attachment"
    items = (
        RawItem.query
        .filter(build_keyword_match_filter(keyword))
        .order_by(RawItem.source_type.asc(), RawItem.published_at.desc(), RawItem.fetched_at.desc())
        .all()
    )
    created_date = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")
    pdf_data = render_daily_news_pdf(
        created_date,
        build_pdf_category_groups(items),
        report_title="Physical-AIキーワード検索結果レポート",
        scope_description=f'検索キーワード「{keyword}」に一致する収集情報を種別ごとに整理しています。',
        footer_label=f"検索結果: {keyword}",
        group_items_by_year=True,
    )
    return Response(
        pdf_data,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="keyword-search-results-{created_date}.pdf"'},
    )


@app.route("/filtered-results.pdf")
def filtered_search_results_pdf():
    source_type = request.args.get("source_type", "").strip()
    if source_type not in EXPORTABLE_SOURCE_TYPES:
        return Response("PDF出力対象の種別を指定してください。", status=400, content_type="text/plain; charset=utf-8")

    query = RawItem.query.filter(RawItem.source_type == source_type)
    keyword = request.args.get("q", "").strip()[:200]
    if keyword and source_type != "event":
        query = query.filter(build_keyword_match_filter(keyword))
    source_name = request.args.get("source_name", "").strip()[:200]
    if source_name and source_type != "event":
        query = query.filter(RawItem.source_name == source_name)
    crawl_date = normalize_crawl_date(request.args.get("crawl_date", ""))
    if crawl_date and source_type != "event":
        jst_start = datetime.strptime(crawl_date, "%Y-%m-%d")
        utc_start = jst_start - timedelta(hours=9)
        query = query.filter(RawItem.fetched_at >= utc_start, RawItem.fetched_at < utc_start + timedelta(days=1))
    archive_month = normalize_archive_month(request.args.get("archive_month", ""))
    if archive_month and source_type != "event":
        query = query.filter(RawItem.published_at.like(f"{archive_month}-%"))

    items = query.order_by(RawItem.published_at.desc(), RawItem.fetched_at.desc()).all()
    if source_type == "news":
        news_region = request.args.get("news_region", "").strip()
        news_category = request.args.get("news_category", "").strip()
        element_technology_category = request.args.get("element_technology_category", "").strip()
        sensor_sensing_category = request.args.get("sensor_sensing_category", "").strip()
        items = [
            item for item in items
            if (not news_region or extract_news_region(item) == news_region)
            and (not news_category or extract_news_category(item) == news_category)
            and (
                not element_technology_category
                or extract_element_technology_category(item) == element_technology_category
            )
            and (
                not sensor_sensing_category
                or extract_sensor_sensing_category(item) == sensor_sensing_category
            )
        ]
    elif source_type == "paper":
        paper_source = request.args.get("paper_source", "").strip().lower()
        paper_category = request.args.get("paper_category", "").strip()
        if paper_source == "arxiv":
            items = [item for item in items if (item.source_name or "").lower().startswith("arxiv")]
        elif paper_source == "ieee":
            items = [item for item in items if (item.source_name or "").lower().startswith("ieee")]
        elif paper_source == "journals":
            items = [item for item in items if (item.source_name or "").startswith("Journal /")]
        if paper_category:
            items = [item for item in items if paper_category in (item.raw_text or "")]
    elif source_type == "event":
        # Export every unique event record. Do not collapse child exhibitions
        # into their parent or apply the month/country filters used by the
        # interactive calendar.
        items = dedupe_event_items(items)

    disposition = request.args.get("disposition", "attachment").strip().lower()
    if disposition not in {"inline", "attachment"}:
        disposition = "attachment"
    labels = {
        "company": "企業情報", "event": "イベント・展示会", "news": "ニュース",
        "paper": "論文", "policy": "政策・行政情報", "thinktank": "シンクタンク情報",
    }
    label = labels[source_type]
    created_date = (datetime.utcnow() + timedelta(hours=9)).strftime("%Y-%m-%d")
    scope_description = (
        "DBに保存されている国内外すべてのイベント・展示会を、重複整理してまとめています。"
        if source_type == "event"
        else f'Webアプリで選択した「{label}」の検索・絞り込み結果をまとめています。'
    )
    pdf_data = render_daily_news_pdf(
        created_date,
        build_pdf_category_groups(items),
        report_title=f"Physical-AI {label}検索結果レポート",
        scope_description=scope_description,
        footer_label=f"検索結果: {label}",
        group_items_by_year=True,
        include_yearly_event_calendar=source_type == "event",
    )
    return Response(
        pdf_data,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{source_type}-search-results-{created_date}.pdf"'},
    )


@app.route("/archive")
def archive_index():
    archive_links = build_archive_links()
    return render_template("archive.html", archive_links=archive_links)


@app.route("/archive/<archive_month>")
def archive_month_page(archive_month):
    normalized_month = normalize_archive_month(archive_month)
    if not normalized_month:
        return redirect(url_for("archive_index"))
    return render_item_list(
        archive_month=normalized_month,
        page_title=f"{format_archive_month_label(normalized_month)} アーカイブ",
        base_path=url_for("archive_month_page", archive_month=normalized_month),
    )


@app.route("/reports")
def monthly_report_index():
    report_months = []
    for archive in build_archive_links():
        report_months.append({
            **archive,
            "report_href": url_for("monthly_report_page", report_month=archive["month"]),
            "markdown_href": url_for("monthly_report_markdown", report_month=archive["month"]),
        })
    return render_template("reports.html", report_months=report_months)


def get_monthly_report(report_month: str) -> dict | None:
    normalized_month = normalize_report_month(report_month)
    if not normalized_month:
        return None
    items = RawItem.query.filter(RawItem.published_at.like(f"{normalized_month}-%")).all()
    prior_month = previous_month(normalized_month)
    previous_items = RawItem.query.filter(RawItem.published_at.like(f"{prior_month}-%")).all()
    return build_monthly_report(normalized_month, items, previous_items)


@app.route("/reports/<report_month>")
def monthly_report_page(report_month):
    report = get_monthly_report(report_month)
    if report is None:
        return redirect(url_for("monthly_report_index"))
    return render_template("monthly_report.html", report=report)


@app.route("/reports/<report_month>.md")
def monthly_report_markdown(report_month):
    report = get_monthly_report(report_month)
    if report is None:
        return redirect(url_for("monthly_report_index"))
    markdown = render_report_markdown(report)
    disposition = "attachment" if request.args.get("download") == "1" else "inline"
    return Response(
        markdown,
        content_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'{disposition}; filename="techinfo-report-{report["month"]}.md"'},
    )


@app.route("/reports/<report_month>/charts/<chart_name>.svg")
def monthly_report_chart(report_month, chart_name):
    report = get_monthly_report(report_month)
    if report is None:
        return redirect(url_for("monthly_report_index"))
    renderers = {
        "fields": render_field_chart_svg,
        "regions": render_region_chart_svg,
    }
    renderer = renderers.get(chart_name)
    if renderer is None:
        return Response("chart not found", status=404, content_type="text/plain; charset=utf-8")
    return Response(renderer(report), content_type="image/svg+xml; charset=utf-8")


def build_google_trend_series(item: RawItem) -> dict:
    try:
        payload = json.loads(item.raw_text or "{}")
    except json.JSONDecodeError:
        payload = {}
    points = payload.get("points", []) if isinstance(payload, dict) else []
    if not isinstance(points, list):
        points = []
    chart_points = []
    chart_values = []
    point_datetimes = []
    if points:
        denominator = max(len(points) - 1, 1)
        for index, point in enumerate(points):
            try:
                value = max(0, min(100, int(point.get("value", 0))))
            except (TypeError, ValueError):
                value = 0
            chart_values.append(value)
            chart_points.append(f"{index / denominator * 100:.2f},{100 - value:.2f}")
            point_datetime = point.get("datetime", "")
            try:
                parsed_datetime = datetime.strptime(point_datetime, "%Y-%m-%d %H:%M")
            except (TypeError, ValueError):
                parsed_datetime = parse_date_safe(point.get("date"))
            if parsed_datetime:
                point_datetimes.append(parsed_datetime)
    interval_label = "取得間隔"
    if len(point_datetimes) >= 2:
        interval_seconds = (point_datetimes[1] - point_datetimes[0]).total_seconds()
        if interval_seconds < 86400:
            interval_label = f"{max(round(interval_seconds / 3600), 1)}時間間隔"
        elif interval_seconds < 86400 * 8:
            interval_label = f"{max(round(interval_seconds / 86400), 1)}日間隔"
        else:
            interval_label = f"{round(interval_seconds / 86400)}日間隔"
    start_date = point_datetimes[0].strftime("%m/%d %H:%M") if point_datetimes else ""
    end_date = point_datetimes[-1].strftime("%m/%d %H:%M") if point_datetimes else ""
    regional_interest = payload.get("regional_interest", []) if isinstance(payload, dict) else []
    if not isinstance(regional_interest, list):
        regional_interest = []
    rankings = []
    for rank, region_value in enumerate(regional_interest[:5], start=1):
        if not isinstance(region_value, dict):
            continue
        rankings.append({
            "rank": rank,
            "name": region_value.get("name", "地域名不明"),
            "value": region_value.get("value", 0),
        })
    fetched_at = getattr(item, "fetched_at", None)
    if fetched_at:
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        last_updated_at = fetched_at.astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M JST")
    else:
        last_updated_at = "未取得"
    return {
        "item": item,
        "keyword": payload.get("keyword", item.title),
        "region": payload.get("region_label", item.source_name),
        "explore_url": payload.get("explore_url", item.url),
        "latest_value": payload.get("latest_value"),
        "average_value": payload.get("average_value"),
        "peak_value": payload.get("peak_value"),
        "time_range": payload.get("time_range", ""),
        "rankings": rankings,
        "points": " ".join(chart_points),
        "values": chart_values,
        "point_count": len(points),
        "start_date": start_date,
        "end_date": end_date,
        "interval_label": interval_label,
        "error": payload.get("error", ""),
        "last_updated_at": last_updated_at,
    }


def build_unavailable_trend_item(keyword: str, geo: str, region_label: str) -> RawItem:
    """Return a display-only placeholder for a never-successful trend pair."""
    explore_params = {"q": keyword, "date": "now 7-d"}
    if geo:
        explore_params["geo"] = geo
    return RawItem(
        source_name=f"Google Trends / {region_label}",
        source_type="trend",
        title=f"Google Trends: {keyword} / {region_label}",
        url="https://trends.google.com/trends/explore?" + urlencode(explore_params),
        published_at="",
        raw_summary="Google Trendsの取得データはまだありません。",
        raw_text=json.dumps({
            "provider": "Google Trends",
            "keyword": keyword,
            "geo": geo,
            "region_label": region_label,
            "time_range": "now 7-d",
            "explore_url": "https://trends.google.com/trends/explore?" + urlencode(explore_params),
            "points": [],
            "regional_interest": [],
            "error": "まだ正常に取得されたデータがありません。",
        }, ensure_ascii=False),
    )


def build_latest_default_trend_items() -> list[RawItem]:
    """Return exactly one current-or-last-known item for every default pair."""
    expected_titles = {
        f"Google Trends: {keyword} / {region_label}"
        for keyword in DEFAULT_TREND_KEYWORDS
        for _geo, region_label in TREND_REGIONS
    }
    rows = (
        RawItem.query
        .filter(RawItem.source_type == "trend", RawItem.title.in_(expected_titles))
        .order_by(RawItem.fetched_at.desc(), RawItem.id.desc())
        .all()
    )
    latest_by_title: dict[str, RawItem] = {}
    for row in rows:
        latest_by_title.setdefault(row.title, row)

    items: list[RawItem] = []
    for keyword in DEFAULT_TREND_KEYWORDS:
        for geo, region_label in TREND_REGIONS:
            title = f"Google Trends: {keyword} / {region_label}"
            items.append(latest_by_title.get(title) or build_unavailable_trend_item(keyword, geo, region_label))
    return items


@app.route("/trends")
def google_trends_page():
    items = build_latest_default_trend_items()
    latest: dict[tuple[str, str], dict] = {}
    for item in items:
        series = build_google_trend_series(item)
        if series["time_range"] != "now 7-d":
            continue
        key = (series["keyword"], series["region"])
        latest.setdefault(key, series)
    grouped: dict[str, dict[str, dict]] = {keyword: {} for keyword in DEFAULT_TREND_KEYWORDS}
    for series in latest.values():
        if series["keyword"] in grouped:
            grouped[series["keyword"]][series["region"]] = series
    keyword_groups = []
    for keyword in DEFAULT_TREND_KEYWORDS:
        series_list = []
        for geo, region in (("JP", "日本"), ("", "世界")):
            series_list.append(grouped[keyword].get(region, {
                "keyword": keyword,
                "region": region,
                "points": "",
                "error": "まだ正常な取得データがありません。",
                "last_updated_at": "未取得",
                "explore_url": "https://trends.google.com/trends/explore?" + urlencode({
                    "q": keyword,
                    "date": "now 7-d",
                    **({"geo": geo} if geo else {}),
                }),
            }))
        keyword_groups.append({"keyword": keyword, "series": series_list})
    return render_template("trends.html", keyword_groups=keyword_groups)


@app.route("/collect-keyword", methods=["POST"])
def collect_keyword():
    keyword = request.form.get("keyword", "").strip()
    if not keyword:
        return redirect(url_for("list_raw_items", collection_status="empty"))

    try:
        result = keyword_collector.collect(keyword)
        source_labels = [f"{name}:{count}" for name, count in sorted(result["by_source"].items())]
        return redirect(url_for(
            "list_raw_items",
            q=keyword,
            collection_status="ok",
            collection_keyword=result["keyword"],
            collection_inserted=result["inserted"],
            collection_skipped=result["skipped"],
            collection_sources=" | ".join(source_labels[:8]),
        ))
    except Exception:
        return redirect(url_for("list_raw_items", q=keyword, collection_status="error", collection_keyword=keyword))


@app.route("/raw/<int:item_id>")
def raw_detail(item_id):
    item = RawItem.query.get_or_404(item_id)
    item.has_translation = bool(item.translated_title or item.translated_summary)
    return_to = request.args.get("return_to", "").strip()
    if not return_to.startswith("/"):
        return_to = "/"
    enrich_event_fields(item)
    if item.source_type == "event":
        parent_key = build_event_parent_key(item)
        sibling_items = RawItem.query.filter(RawItem.source_type == "event").all()
        sibling_items = dedupe_event_items(sibling_items)
        sibling_items = attach_event_hierarchy(sibling_items, "")
        item.child_events = []
        for candidate in sibling_items:
            if getattr(candidate, "event_parent_key", "") == parent_key and getattr(candidate, "event_scope", "") == "parent":
                item.child_events = getattr(candidate, "child_events", [])
                break
    if item.url and not item.actual_published_at:
        try:
            actual_published_at = fetch_actual_published_at(item.url)
        except Exception:
            actual_published_at = ""
        if actual_published_at:
            item.actual_published_at = actual_published_at
            db.session.commit()

    item.date_mismatch = bool(
        item.published_at and item.actual_published_at and not dates_match(item.published_at, item.actual_published_at)
    )
    return render_template("raw_detail.html", item=item, return_to=return_to)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
