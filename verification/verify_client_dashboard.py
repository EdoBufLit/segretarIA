from playwright.sync_api import sync_playwright
import time

def verify_client_dashboard():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Register a new user to access dashboard
        print("Navigating to Register...")
        page.goto("http://localhost:8000/register")

        # Fill registration form
        email = f"test_client_{int(time.time())}@example.com"
        username = f"user_{int(time.time())}"

        page.fill('input[name="username"]', username)
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', "password123")
        page.fill('input[name="password_confirm"]', "password123")

        print(f"Registering user {username} ({email})...")
        page.click('button[type="submit"]')

        # Wait for navigation
        page.wait_for_load_state("networkidle")

        # Check current URL
        print(f"Current URL: {page.url}")

        # If redirected to login, login
        if "/login" in page.url:
            print("Redirected to login, logging in...")
            page.fill('input[name="username"]', email)
            page.fill('input[name="password"]', "password123")
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")

        print(f"Current URL after login attempt: {page.url}")

        if "/dashboard" in page.url:
            print("Successfully reached dashboard.")
            # Wait a bit for charts/dashboard specific js to load if any
            page.wait_for_timeout(2000)
            page.screenshot(path="verification/client_dashboard.png")
            print("Client Dashboard screenshot captured.")
        else:
            print("Failed to reach dashboard.")
            page.screenshot(path="verification/failed_dashboard_access.png")

        browser.close()

if __name__ == "__main__":
    verify_client_dashboard()
