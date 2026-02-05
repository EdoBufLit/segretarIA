import sys
import os

# Add root directory to path to allow imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import SessionLocal
from models import User, Agent, AgentRouting

def fix_agent_routing():
    db = SessionLocal()
    try:
        users = db.query(User).filter(User.role == "client").all()
        print(f"Found {len(users)} clients.")

        updated_count = 0
        created_count = 0

        for user in users:
            print(f"Processing user {user.username} (id={user.id})...")
            for agent in user.agents:
                print(f"  - Checking agent {agent.agent_id} ({agent.display_name})...")

                routing = db.query(AgentRouting).filter(AgentRouting.agent_id == agent.agent_id).first()
                if routing:
                    changed = False
                    if routing.user_id != user.id:
                        print(f"    -> UPDATING user_id from {routing.user_id} to {user.id}")
                        routing.user_id = user.id
                        changed = True

                    if not routing.is_active:
                         print("    -> REACTIVATING")
                         routing.is_active = True
                         routing.status = "active"
                         changed = True

                    if changed:
                        updated_count += 1
                    else:
                        print(f"    -> OK (Already correct)")

                else:
                    print(f"    -> CREATING new routing")
                    routing = AgentRouting(
                        user_id=user.id,
                        agent_id=agent.agent_id,
                        status="active",
                        is_active=True,
                        phone_number_id=None
                    )
                    db.add(routing)
                    created_count += 1

        db.commit()
        print(f"Migration completed. Created: {created_count}, Updated: {updated_count}")

    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    fix_agent_routing()
