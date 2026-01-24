from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_admin_analytics(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Click Analytics
    page.click("a[data-section='analytics']")

    # Verify KPIs visible
    expect(page.get_by_text("Utenti Totali")).to_be_visible()
    expect(page.get_by_text("Abbonamenti Attivi")).to_be_visible()
    expect(page.get_by_text("Ultimi Pagamenti")).to_be_visible()

    # Verify no heatmap
    if page.locator("#heatmap-container").is_visible():
        print("ERROR: Heatmap still visible!")
        exit(1)

    print("SUCCESS: KPIs visible, Heatmap gone.")
    page.screenshot(path="verification/analytics_kpi.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_admin_analytics(page)
        finally:
            browser.close()
