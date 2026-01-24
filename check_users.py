from db import SessionLocal
from models import User

db = SessionLocal()
users = db.query(User).all()
for u in users:
    print(f"User: {u.username}, Role: {u.role}, Active: {u.is_active}")
db.close()
