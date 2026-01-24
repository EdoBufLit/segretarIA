from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_admin_dashboard(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Check for Admin specific element
    try:
        expect(page.get_by_text("Clienti attuali")).to_be_visible(timeout=5000)
        print("Admin Dashboard Verified: Found 'Clienti attuali'")
    except:
        print("FAILED: Did not find 'Clienti attuali'. Role might be wrong.")
        # Check if we see client element
        if page.get_by_text("Attività giornaliera").is_visible():
            print("ERROR: Seeing Client Dashboard ('Attività giornaliera')")
        page.screenshot(path="verification/admin_fail.png")
        exit(1)

    # Screenshot for confirmation
    page.screenshot(path="verification/admin_success.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_admin_dashboard(page)
        finally:
            browser.close()
