from flask import Flask, render_template, request
from sqlalchemy import or_
from bs4 import BeautifulSoup

from models import db, RawItem
from typing import Optional

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///techinfo.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)

with app.app_context():
    db.create_all()


def clean_summary(text: Optional[str], max_length: int = 160) -> str:
    if not text:
        return "要約なし"

    plain = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    plain = " ".join(plain.split())

    if len(plain) > max_length:
        return plain[:max_length] + "..."
    return plain


@app.route("/")
def list_raw_items():
    q = request.args.get("q", "").strip()
    source_name = request.args.get("source_name", "").strip()
    source_type = request.args.get("source_type", "").strip()
    sort = request.args.get("sort", "fetched_at").strip()
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

    if source_type:
        query = query.filter(RawItem.source_type == source_type)

    sortable_columns = {
        "fetched_at": RawItem.fetched_at,
        "published_at": RawItem.published_at,
        "title": RawItem.title,
        "source_name": RawItem.source_name,
        "source_type": RawItem.source_type,
    }

    sort_column = sortable_columns.get(sort, RawItem.fetched_at)

    if order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    items = query.all()

    for item in items:
        item.display_summary = clean_summary(item.raw_summary)

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
        current_sort=sort,
        current_order=order,
        total_count=total_count,
        type_counts=type_counts,
    )


@app.route("/raw/<int:item_id>")
def raw_detail(item_id):
    item = RawItem.query.get_or_404(item_id)
    return render_template("raw_detail.html", item=item)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)