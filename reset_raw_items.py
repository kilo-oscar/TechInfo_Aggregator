from app import app
from models import db, RawItem

with app.app_context():
    deleted = RawItem.query.delete()
    db.session.commit()
    print(f"deleted={deleted}")