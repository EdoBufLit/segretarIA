from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_admin_clients(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Click Clienti
    page.click("a[data-section='users']")

    # Verify table loads
    expect(page.locator("h3:has-text('Gestione Clienti')")).to_be_visible()

    # Wait for table rows (assuming admin is in the list)
    page.wait_for_selector("#users-table-body tr")

    # Check if admin row exists (admin user should be there)
    expect(page.get_by_text(ADMIN_USER)).to_be_visible()

    print("SUCCESS: Client management table loaded.")
    page.screenshot(path="verification/admin_clients_tab.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_admin_clients(page)
        finally:
            browser.close()
