import argparse
import sys
import os
import json
from sqlalchemy.orm import Session

# Add root to sys.path to import app modules
sys.path.append(os.getcwd())

try:
    from db import SessionLocal
    from models import PhoneNumber, AgentRouting, User
except ImportError:
    # Fallback for when running from scripts/ directory
    sys.path.append(os.path.dirname(os.getcwd()))
    from db import SessionLocal
    from models import PhoneNumber, AgentRouting, User

def resolve_routing(db: Session, to_number: str):
    """
    Simulates the routing logic used in /twilio/voice.
    """
    normalized_to = to_number.replace(" ", "").strip()

    # 1. Lookup Phone
    phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == normalized_to).first()

    result = {
        "routing_found": False,
        "phone_number_id": None,
        "agent_id": None,
        "user_id": None,
        "is_active": False,
        "has_active_plan": False,
        "reason": None
    }

    if not phone:
        result["reason"] = "Number not found"
        return result

    result["phone_number_id"] = phone.id

    user = phone.user
    if not user:
        result["reason"] = "User not found"
        return result

    result["user_id"] = user.id
    result["is_active"] = user.is_active
    result["has_active_plan"] = user.has_active_plan()

    if not user.is_active:
        result["reason"] = "User suspended"
        return result

    if not result["has_active_plan"]:
        result["reason"] = "No active plan"
        return result

    # 2. Lookup Routing
    routing = db.query(AgentRouting).filter(
        AgentRouting.phone_number_id == phone.id,
        AgentRouting.is_active == True
    ).first()

    if routing:
        result["routing_found"] = True
        result["agent_id"] = routing.agent_id
    else:
        result["reason"] = "Agent disabled or not configured"

    return result

def main():
    parser = argparse.ArgumentParser(description="Check routing for a Twilio number")
    parser.add_argument("--to", required=True, help="The E.164 number to check (e.g. +1234567890)")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = resolve_routing(db, args.to)
        print(json.dumps(result, indent=2))
    finally:
        db.close()

if __name__ == "__main__":
    main()
