from flask import Flask, render_template, request
from sqlalchemy import or_, case
from sqlalchemy import text
from bs4 import BeautifulSoup
import json
from urllib.parse import urlencode

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


@app.route("/")
def list_raw_items():
    q = request.args.get("q", "").strip()
    source_name = request.args.get("source_name", "").strip()
    source_type = request.args.get("source_type", "").strip()
    event_country = request.args.get("event_country", "").strip()
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
    event_preview_groups = build_event_groups(event_preview_items) if event_preview_items else []
    event_country_shortcuts = build_event_country_shortcuts(event_country, event_preview_groups, request.args)

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

    if sort == "published_at":
        published_is_empty = case((RawItem.published_at.is_(None), 1), (RawItem.published_at == "", 1), else_=0)
        if order == "asc":
            query = query.order_by(
                published_is_empty.asc(),
                RawItem.published_at.asc(),
                RawItem.fetched_at.asc(),
            )
        else:
            query = query.order_by(
                published_is_empty.asc(),
                RawItem.published_at.desc(),
                RawItem.fetched_at.desc(),
            )
    elif order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    items = query.all()

    for item in items:
        item.display_summary = clean_summary(item.raw_summary)

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
        current_sort=sort,
        current_order=order,
        total_count=total_count,
        type_counts=type_counts,
        event_groups=event_groups,
        event_country_tabs=event_country_tabs,
        available_event_countries=available_event_countries,
        event_country_shortcuts=event_country_shortcuts,
    )


@app.route("/raw/<int:item_id>")
def raw_detail(item_id):
    item = RawItem.query.get_or_404(item_id)
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
