from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_kpis(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Check KPIs in Dashboard Section
    # Using more specific selectors to avoid ambiguity with Analytics section
    expect(page.locator("#dash-kpi-clients")).to_be_visible()
    expect(page.locator("#dash-kpi-subs")).to_be_visible()
    expect(page.locator("#dash-kpi-mrr")).to_be_visible()
    expect(page.locator("#dash-kpi-revenue")).to_be_visible()

    # Check values are populated (not dashes)
    # Note: Mock data returns specific values (e.g. 1250.00)
    page.wait_for_selector("#dash-kpi-mrr:not(:has-text('—'))")

    print("SUCCESS: Dashboard KPIs visible and populated.")
    page.screenshot(path="verification/dashboard_kpis.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_kpis(page)
        finally:
            browser.close()
