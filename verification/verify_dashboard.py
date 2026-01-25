import os
import threading
import uvicorn
import time
from app import app, get_current_user_page, get_db
from models import User, Subscription, Plan
from unittest.mock import MagicMock
from playwright.sync_api import sync_playwright
from datetime import datetime

# --- MOCKS ---
mock_user = MagicMock(spec=User)
mock_user.id = 1
mock_user.username = "client_user"
mock_user.email = "client@test.com"
mock_user.role = "client"
mock_user.is_active = True
mock_user.studio_name = "Test Studio"
mock_user.agents = []

mock_sub = MagicMock(spec=Subscription)
mock_sub.id = 1
mock_sub.state = "active"
mock_sub.plan = MagicMock(spec=Plan)
mock_sub.plan.code = "pro"
mock_sub.plan.minutes_per_cycle = 500
mock_sub.cycle_start = datetime.utcnow()
mock_sub.cycle_end = datetime.utcnow()
mock_sub.updated_at = datetime.utcnow()

# Mock DB Session
mock_db = MagicMock()

query_mock = mock_db.query.return_value
# For subscription query: .filter().first() -> mock_sub
query_mock.filter.return_value.first.return_value = mock_sub
# For fallback subscription query: .filter().order_by().first() -> mock_sub
query_mock.filter.return_value.order_by.return_value.first.return_value = mock_sub
# For usage query: .filter().scalar() -> 120 (seconds) -> 2 minutes used
query_mock.filter.return_value.scalar.return_value = 120

# OVERRIDE DEPENDENCIES
app.dependency_overrides[get_current_user_page] = lambda: mock_user
app.dependency_overrides[get_db] = lambda: mock_db

def run_server():
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="error")

def verify_dashboard():
    # Start server
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(5) # Wait for server

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            print("Navigating to dashboard...")
            # Set viewport
            page.set_viewport_size({"width": 1280, "height": 800})

            page.goto("http://127.0.0.1:8001/dashboard")

            # Wait a bit for JS
            page.wait_for_timeout(3000)

            # Take screenshot
            print("Taking screenshot...")
            page.screenshot(path="verification/dashboard_client.png", full_page=True)

            browser.close()
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify_dashboard()
