from flask import Flask, render_template, request
from sqlalchemy import or_, case
from sqlalchemy import text
from bs4 import BeautifulSoup
import json
from urllib.parse import urlencode
import re

from models import db, RawItem
from typing import Optional
from page_date_utils import fetch_actual_published_at
from crawler_utils import parse_date_safe

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///techinfo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

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
        "href": "/?" + urlencode(base_params),
    }]

    for group in groups:
        params = base_params + [("event_country", group["country"])]
        tabs.append({
            "label": group["country"],
            "country": group["country"],
            "count": len(group["items"]),
            "active": selected_country == group["country"],
            "href": "/?" + urlencode(params),
        })
    return tabs


def build_event_country_shortcuts(
    selected_country: str,
    groups: list[dict],
    args,
) -> list[dict]:
    if not groups:
        return []

    base_params = []
    for key in ["q", "source_name", "sort", "order"]:
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
            "href": "/?" + urlencode(params),
        })
    return shortcuts


def extract_news_category(item: RawItem) -> str:
    if item.source_type != "news":
        return ""

    source_name = (item.source_name or "").strip()
    if source_name.startswith("Google News / Physical AI"):
        return "Physical AI"
    if source_name.startswith("Google News / Robot Makers"):
        return "Robot Makers"
    if source_name.startswith("Google News / Real Haptics"):
        return "Real Haptics"
    if source_name.startswith("Startup /"):
        return "Startup"
    if source_name.startswith("Google News /"):
        return "Google News"
    return "その他"


def build_news_category_groups(items: list[RawItem]) -> list[dict]:
    groups: dict[str, list[RawItem]] = {}
    for item in items:
        category = extract_news_category(item)
        item.news_category = category
        groups.setdefault(category, []).append(item)

    ordered_categories = sorted(
        groups.keys(),
        key=lambda name: (name == "その他", name),
    )
    return [{"category": category, "items": groups[category]} for category in ordered_categories]


def build_news_category_shortcuts(selected_category: str, groups: list[dict], args) -> list[dict]:
    if not groups:
        return []

    base_params = []
    for key in ["q", "source_name", "sort", "order"]:
        value = (args.get(key) or "").strip()
        if value:
            base_params.append((key, value))

    shortcuts = []
    for group in groups:
        params = base_params + [("source_type", "news"), ("news_category", group["category"])]
        shortcuts.append({
            "label": group["category"],
            "count": len(group["items"]),
            "active": selected_category == group["category"],
            "href": "/?" + urlencode(params),
        })
    return shortcuts


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
    item.event_period = format_event_period(item.event_start_date, item.event_end_date)


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


@app.route("/")
def list_raw_items():
    q = request.args.get("q", "").strip()
    source_name = request.args.get("source_name", "").strip()
    source_type = request.args.get("source_type", "").strip()
    event_country = request.args.get("event_country", "").strip()
    news_category = request.args.get("news_category", "").strip()
    sort = request.args.get("sort", "published_at").strip()
    order = request.args.get("order", "desc").strip()
    query = RawItem.query

    if q:
        query = query.filter(
            or_(
                RawItem.title.ilike(f"%{q}%"),
                RawItem.raw_summary.ilike(f"%{q}%"),
                RawItem.raw_text.ilike(f"%{q}%"),
                RawItem.source_name.ilike(f"%{q}%"),
            )
        )

    if source_name:
        query = query.filter(RawItem.source_name == source_name)

    event_preview_query = query.filter(RawItem.source_type == "event")
    event_preview_items = event_preview_query.all()
    event_preview_items = dedupe_event_items(event_preview_items)
    event_preview_groups = build_event_groups(event_preview_items) if event_preview_items else []
    event_country_shortcuts = build_event_country_shortcuts(event_country, event_preview_groups, request.args)

    news_preview_query = query.filter(RawItem.source_type == "news")
    news_preview_items = news_preview_query.all()
    news_category_groups = build_news_category_groups(news_preview_items) if news_preview_items else []
    news_category_shortcuts = build_news_category_shortcuts(news_category, news_category_groups, request.args)

    if source_type:
        query = query.filter(RawItem.source_type == source_type)

    sortable_columns = {
        "fetched_at": RawItem.fetched_at,
        "published_at": RawItem.published_at,
        "title": RawItem.title,
        "source_name": RawItem.source_name,
        "source_type": RawItem.source_type,
    }

    sort_column = sortable_columns.get(sort, RawItem.published_at)
    new_priority = case((RawItem.is_new.is_(True), 0), else_=1)

    if sort == "published_at":
        published_is_empty = case((RawItem.published_at.is_(None), 1), (RawItem.published_at == "", 1), else_=0)
        if order == "asc":
            query = query.order_by(
                new_priority.asc(),
                published_is_empty.asc(),
                RawItem.published_at.asc(),
                RawItem.fetched_at.asc(),
            )
        else:
            query = query.order_by(
                new_priority.asc(),
                published_is_empty.asc(),
                RawItem.published_at.desc(),
                RawItem.fetched_at.desc(),
            )
    elif order == "asc":
        query = query.order_by(new_priority.asc(), sort_column.asc(), RawItem.fetched_at.desc())
    else:
        query = query.order_by(new_priority.asc(), sort_column.desc(), RawItem.fetched_at.desc())

    items = query.all()
    if items and all(item.source_type == "event" for item in items):
        items = dedupe_event_items(items)
        items = attach_event_hierarchy(items, q)
    elif items and all(item.source_type == "news" for item in items):
        news_groups = build_news_category_groups(items)
        if news_category:
            items = [item for group in news_groups if group["category"] == news_category for item in group["items"]]

    for item in items:
        item.display_summary = clean_summary(item.raw_summary)
        enrich_event_fields(item)

    event_groups: list[dict] = []
    event_country_tabs: list[dict] = []
    available_event_countries: list[str] = []
    if items and all(item.source_type == "event" for item in items):
        event_groups = build_event_groups(items)
        available_event_countries = [group["country"] for group in event_groups]
        event_country_tabs = build_country_tabs(source_type, event_country, event_groups, request.args)
        if event_country:
            event_groups = [group for group in event_groups if group["country"] == event_country]
            items = [item for group in event_groups for item in group["items"]]

    source_names = [
        row[0]
        for row in db.session.query(RawItem.source_name)
        .distinct()
        .order_by(RawItem.source_name.asc())
        .all()
    ]

    source_types = [
        row[0]
        for row in db.session.query(RawItem.source_type)
        .distinct()
        .order_by(RawItem.source_type.asc())
        .all()
    ]

    type_counts_raw = (
        db.session.query(RawItem.source_type, db.func.count(RawItem.id))
        .group_by(RawItem.source_type)
        .all()
    )
    type_counts = {source_type: count for source_type, count in type_counts_raw}
    total_count = db.session.query(db.func.count(RawItem.id)).scalar()

    return render_template(
        "list.html",
        items=items,
        source_names=source_names,
        source_types=source_types,
        current_q=q,
        current_source_name=source_name,
        current_source_type=source_type,
        current_event_country=event_country,
        current_news_category=news_category,
        current_sort=sort,
        current_order=order,
        total_count=total_count,
        type_counts=type_counts,
        event_groups=event_groups,
        event_country_tabs=event_country_tabs,
        available_event_countries=available_event_countries,
        event_country_shortcuts=event_country_shortcuts,
        news_category_shortcuts=news_category_shortcuts,
        available_news_categories=[group["category"] for group in news_category_groups],
    )


@app.route("/raw/<int:item_id>")
def raw_detail(item_id):
    item = RawItem.query.get_or_404(item_id)
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
    return render_template("raw_detail.html", item=item)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
