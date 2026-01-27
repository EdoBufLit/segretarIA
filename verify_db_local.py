from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from models import PhoneNumber, AgentRouting, User

# SQLite
DATABASE_URL = "sqlite:///./app.db"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db = SessionLocal()

# Check for phone number
phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == '+390299914306').first()
if phone:
    print(f"Phone found: {phone.e164}, ID: {phone.id}, UserID: {phone.user_id}")
    # Check associated agent routing
    routing = db.query(AgentRouting).filter(AgentRouting.phone_number_id == phone.id).first()
    if routing:
        print(f"Routing found: AgentID: {routing.agent_id}, UserID: {routing.user_id}")
    else:
        print("Routing not found.")
else:
    print("Phone not found.")

db.close()
