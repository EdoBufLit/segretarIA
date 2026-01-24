from db import SessionLocal
from models import User
from auth import hash_password

db = SessionLocal()
u = db.query(User).filter(User.username == "admin").first()
if u:
    u.password_hash = hash_password("password123")
    db.commit()
    print("Password reset.")
db.close()
