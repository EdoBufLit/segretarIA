from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_admin_status(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Check Status Bar "ATTIVO"
    # The selector is #status-service
    expect(page.locator("#status-service")).to_have_text("ATTIVO")

    # Check NO activation banner
    # The banner id is "activation-banner" or check specifically for "ATTIVA ORA"
    if page.locator("#activation-banner").is_visible():
        print("ERROR: Activation banner is visible for Admin!")
        exit(1)

    print("SUCCESS: Admin status is ATTIVO and no activation banner.")
    page.screenshot(path="verification/admin_status_clean.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_admin_status(page)
        finally:
            browser.close()
