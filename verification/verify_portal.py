from playwright.sync_api import sync_playwright, expect
import os
import random
import string
import sqlite3
from datetime import datetime, timedelta

DB_PATH = "app.db"

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def activate_subscription(username):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get user id
    cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    if not row:
        raise Exception(f"User {username} not found in DB")
    user_id = row[0]

    # Get Plan ID (assuming plans exist, e.g. pro -> code='pro')
    cursor.execute("SELECT id FROM plans WHERE code = 'pro'")
    plan_row = cursor.fetchone()
    if not plan_row:
        # Create plan if missing (test env)
        cursor.execute("INSERT INTO plans (code, minutes_per_cycle, is_active) VALUES ('pro', 100, 1)")
        plan_id = cursor.lastrowid
    else:
        plan_id = plan_row[0]

    # Insert Subscription
    now = datetime.utcnow()
    end = now + timedelta(days=30)
    cursor.execute("""
        INSERT INTO subscriptions (user_id, plan_id, state, cycle_start, cycle_end, updated_at)
        VALUES (?, ?, 'active', ?, ?, ?)
    """, (user_id, plan_id, now, end, now))

    conn.commit()
    conn.close()
    print(f"Activated subscription for {username}")

def verify_portal_button(page):
    # Use random user
    rand_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    username = f"portal_test_{rand_suffix}"
    email = f"portal_{rand_suffix}@test.com"
    password = "password123"

    print(f"Testing with user: {username}")

    # 1. Register
    page.goto("http://localhost:8000/register")
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='email']").fill(email)
    page.locator("input[name='password']").fill(password)
    page.locator("input[name='password_confirm']").fill(password)
    page.get_by_role("button", name="Registrati").click()

    # Wait for redirect to login
    page.wait_for_url("**/login?registered=1")

    # 2. Activate Subscription in DB
    activate_subscription(username)

    # 3. Login
    print("Logging in...")
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='password']").fill(password)
    page.get_by_test_id("login-submit").click()

    # 4. Wait for dashboard
    expect(page).to_have_url("http://localhost:8000/dashboard")

    if page.get_by_text("Accesso Limitato").is_visible():
        raise Exception("Still seeing Paywall!")

    print("Logged in, seeing Client Dashboard.")

    # 5. Intercept /billing/portal AND the target mock URL
    def handle_portal_api(route):
        print("Intercepted /billing/portal POST")
        route.fulfill(json={"status": "ok", "portal_url": "http://mock-portal.com/"})

    page.route("**/billing/portal", handle_portal_api)

    # Handle the navigation to the mock domain so it doesn't fail DNS
    page.route("http://mock-portal.com/", lambda route: route.fulfill(status=200, body="<html><body>Mock Portal</body></html>"))

    # 6. Verify Button
    btn = page.locator("#manage-billing-btn")
    expect(btn).to_be_visible()
    print("Portal button is visible.")

    # 7. Click and Verify Redirect
    btn.click()

    # Wait for navigation
    try:
        page.wait_for_url("http://mock-portal.com/", timeout=10000)
    except Exception as e:
        print("Redirection to portal failed.")
        print("Current URL:", page.url)
        page.screenshot(path="/home/jules/verification/portal_redirect_failed.png", full_page=True)
        raise e

    print("Portal button visible and redirection verified.")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            verify_portal_button(page)
        except Exception as e:
            print(f"Verification failed: {e}")
            page.screenshot(path="/home/jules/verification/portal_failed.png")
            exit(1)
        finally:
            context.close()
            browser.close()
