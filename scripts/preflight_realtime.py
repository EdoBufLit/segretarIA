import sys
import os
import logging
from sqlalchemy import text

# Add root to sys.path
sys.path.append(os.getcwd())

try:
    from db import SessionLocal
    from models import AgentRouting
except ImportError:
    # Fallback
    sys.path.append(os.path.dirname(os.getcwd()))
    from db import SessionLocal
    from models import AgentRouting

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("preflight")

def check_env_vars():
    errors = []

    # 1. PUBLIC_BASE_URL
    base_url = os.getenv("PUBLIC_BASE_URL")
    if not base_url:
        # Fallback check: DOMAIN_NAME
        domain = os.getenv("DOMAIN_NAME")
        if domain:
            base_url = f"https://{domain}" if not domain.startswith("http") else domain
        else:
            errors.append("[FAIL] PUBLIC_BASE_URL or DOMAIN_NAME not set.")

    if base_url:
        logger.info(f"[OK] Base URL found: {base_url}")
        # Check WS derivation
        if "https" in base_url:
            ws_url = base_url.replace("https://", "wss://")
        else:
            ws_url = base_url.replace("http://", "ws://")

        if not ws_url.startswith("ws"):
             errors.append(f"[FAIL] Could not derive valid WSS URL from {base_url}")
        else:
             logger.info(f"[OK] Derived WS URL: {ws_url}/ws/twilio")

    # 2. ELEVEN_API_KEY
    if not os.getenv("ELEVEN_API_KEY"):
        errors.append("[FAIL] ELEVEN_API_KEY is missing.")
    else:
        logger.info("[OK] ELEVEN_API_KEY is set.")

    # 3. TWILIO_AUTH_TOKEN
    sig_check = os.getenv("TWILIO_SIGNATURE_CHECK", "true").lower() == "true"
    if sig_check:
        if not os.getenv("TWILIO_AUTH_TOKEN"):
            errors.append("[FAIL] TWILIO_AUTH_TOKEN missing (required because TWILIO_SIGNATURE_CHECK=true).")
        else:
            logger.info("[OK] TWILIO_AUTH_TOKEN is set.")
    else:
        logger.warning("[WARN] TWILIO_SIGNATURE_CHECK is disabled.")

    return errors

def check_db_connectivity(db):
    try:
        db.execute(text("SELECT 1"))
        logger.info("[OK] Database connectivity established.")
        return []
    except Exception as e:
        return [f"[FAIL] Database connection failed: {e}"]

def check_routing(db):
    errors = []
    try:
        active_routings = db.query(AgentRouting).filter(AgentRouting.is_active == True).all()
        count = len(active_routings)

        if count == 0:
            errors.append("[FAIL] No active AgentRouting records found.")
        else:
            logger.info(f"[OK] Found {count} active AgentRouting records.")

            # Check Agent IDs
            invalid_agents = 0
            for r in active_routings:
                if not r.agent_id or len(r.agent_id.strip()) == 0:
                    invalid_agents += 1

            if invalid_agents > 0:
                errors.append(f"[FAIL] Found {invalid_agents} active routings with empty/invalid agent_id.")
            else:
                logger.info("[OK] All active agents have valid IDs.")

    except Exception as e:
        errors.append(f"[FAIL] Error checking routing table: {e}")

    return errors

def main():
    logger.info("Starting Preflight Checklist for Realtime Bridge...")
    all_errors = []

    # Environment Checks
    all_errors.extend(check_env_vars())

    # DB Checks
    try:
        db = SessionLocal()
        all_errors.extend(check_db_connectivity(db))
        if not all_errors: # Only check routing if DB is up
            all_errors.extend(check_routing(db))
    except Exception as e:
        all_errors.append(f"[FAIL] Failed to initialize DB session: {e}")
    finally:
        if 'db' in locals():
            db.close()

    print("-" * 30)
    if all_errors:
        logger.error("Preflight Failed with the following errors:")
        for err in all_errors:
            logger.error(err)
        sys.exit(1)
    else:
        logger.info("Preflight Passed! System appears ready.")
        sys.exit(0)

if __name__ == "__main__":
    main()
