from flask_sqlalchemy import SQLAlchemy
from datetime import datetime


db = SQLAlchemy()


class RawItem(db.Model):
    __tablename__ = "raw_items"

    id = db.Column(db.Integer, primary_key=True)
    source_name = db.Column(db.String(200), nullable=False)
    source_type = db.Column(db.String(100), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    url = db.Column(db.String(1000), unique=True, nullable=False)
    published_at = db.Column(db.String(100), nullable=True)
    actual_published_at = db.Column(db.String(100), nullable=True)
    crawl_batch_id = db.Column(db.String(100), nullable=True)
    is_new = db.Column(db.Boolean, nullable=False, default=False)
    raw_summary = db.Column(db.Text, nullable=True)
    raw_text = db.Column(db.Text, nullable=True)
    translated_title = db.Column(db.String(1000), nullable=True)
    translated_summary = db.Column(db.Text, nullable=True)
    source_language = db.Column(db.String(20), nullable=True)
    translation_provider = db.Column(db.String(100), nullable=True)
    translated_at = db.Column(db.DateTime, nullable=True)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<RawItem {self.id} {self.title}>"
