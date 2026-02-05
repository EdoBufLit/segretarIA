from db import SessionLocal
from models import PhoneNumber

def verify_phone_number_state():
    db = SessionLocal()
    phone_number = db.query(PhoneNumber).filter(PhoneNumber.e164 == "+15557654321").first()
    if phone_number:
        print(f"Phone number found. Status: {phone_number.status}, Deprovision At: {phone_number.deprovision_at}, Notified At: {phone_number.notified_at}")
    else:
        print("Phone number not found.")
    db.close()

if __name__ == "__main__":
    verify_phone_number_state()
