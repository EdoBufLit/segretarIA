import argparse
import sys
import os
import json
from datetime import datetime
from sqlalchemy.orm import Session

# Add root to sys.path to import app modules
sys.path.append(os.getcwd())

try:
    from db import SessionLocal
    from models import PhoneNumber, AgentRouting, User
except ImportError:
    sys.path.append(os.path.dirname(os.getcwd()))
    from db import SessionLocal
    from models import PhoneNumber, AgentRouting, User

def json_serial(obj):
    """JSON serializer for objects not serializable by default json code"""
    if isinstance(obj, (datetime,)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")

def verify_routing(db: Session, to_number: str, expected_user_id: int, expected_agent_id: str):
    normalized_to = to_number.replace(" ", "").strip()

    report = {
        "input": {
            "to": to_number,
            "normalized": normalized_to,
            "expected_user_id": expected_user_id,
            "expected_agent_id": expected_agent_id
        },
        "findings": [],
        "runtime_resolution": {},
        "status": "PASS"
    }

    # 1. Lookup PhoneNumber
    phone = db.query(PhoneNumber).filter(PhoneNumber.e164 == normalized_to).first()

    if not phone:
        report["status"] = "FAIL"
        report["findings"].append(f"PhoneNumber not found for {normalized_to}")
        # Fuzzy search
        fuzzy = db.query(PhoneNumber).filter(PhoneNumber.e164.like(f"%{normalized_to.replace('+','').replace('39','')}%")).all()
        if fuzzy:
            report["findings"].append(f"Did you mean: {[p.e164 for p in fuzzy]}?")
        return report

    report["findings"].append(f"Found PhoneNumber ID {phone.id} for {phone.e164}")

    # 2. Check User Link
    if phone.user_id != expected_user_id:
        report["status"] = "FAIL"
        report["findings"].append(f"PhoneNumber.user_id mismatch: Found {phone.user_id}, Expected {expected_user_id}")
    else:
        report["findings"].append(f"PhoneNumber linked correctly to User ID {phone.user_id}")

    # 3. Lookup AgentRouting
    routing = db.query(AgentRouting).filter(AgentRouting.phone_number_id == phone.id).first()

    if not routing:
        report["status"] = "FAIL"
        report["findings"].append(f"No AgentRouting found for PhoneNumber ID {phone.id}")
        return report

    report["findings"].append(f"Found AgentRouting ID {routing.id}")

    # 4. Verify Routing Details
    if routing.user_id != expected_user_id:
        report["status"] = "FAIL"
        report["findings"].append(f"AgentRouting.user_id mismatch: Found {routing.user_id}, Expected {expected_user_id}")

    if routing.agent_id != expected_agent_id:
        report["status"] = "FAIL"
        report["findings"].append(f"AgentRouting.agent_id mismatch: Found {routing.agent_id}, Expected {expected_agent_id}")

    if not routing.is_active:
        report["status"] = "WARN" # Not strictly a verification fail if we just want to verify data integrity, but for functionality it fails
        report["findings"].append("AgentRouting is NOT active")
    else:
        report["findings"].append("AgentRouting is active")

    # 5. Runtime Resolution Simulation
    # Re-implementing logic from app.py / check_routing.py for consistency verification
    user = phone.user
    runtime_result = {
        "resolved": False,
        "reason": None
    }

    if not user:
        runtime_result["reason"] = "User not found"
    elif not user.is_active:
        runtime_result["reason"] = "User suspended"
    elif not user.has_active_plan():
        runtime_result["reason"] = "No active plan"
    elif not routing.is_active:
        runtime_result["reason"] = "Agent disabled"
    else:
        runtime_result["resolved"] = True
        runtime_result["agent_id"] = routing.agent_id

    report["runtime_resolution"] = runtime_result

    if runtime_result["resolved"] and runtime_result["agent_id"] == expected_agent_id:
        report["findings"].append("Runtime resolution matches expected agent.")
    else:
        if report["status"] == "PASS": # If data was fine but runtime failed
             report["status"] = "FAIL"
        report["findings"].append(f"Runtime resolution failed or mismatch: {runtime_result}")

    return report

def main():
    parser = argparse.ArgumentParser(description="Verify routing data integrity for a specific number")
    parser.add_argument("--to", required=True, help="E.164 phone number")
    parser.add_argument("--user-id", required=True, type=int, help="Expected User ID")
    parser.add_argument("--agent-id", required=True, help="Expected Agent ID")

    args = parser.parse_args()

    db = SessionLocal()
    try:
        report = verify_routing(db, args.to, args.user_id, args.agent_id)
        print(json.dumps(report, indent=2, default=json_serial))

        if report["status"] == "FAIL":
            sys.exit(1)
        sys.exit(0)
    finally:
        db.close()

if __name__ == "__main__":
    main()
