from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_add_client_form(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Go to Clients
    page.click("a[data-section='users']")

    # Check Form Visibility
    expect(page.get_by_text("Nuovo Cliente")).to_be_visible()
    expect(page.locator("#agent_id")).to_be_visible()
    expect(page.locator("#studio_name")).to_be_visible()
    expect(page.locator("#email_to")).to_be_visible()
    expect(page.get_by_role("button", name="Aggiungi")).to_be_visible()

    print("SUCCESS: Add Client form is visible in Clients tab.")
    page.screenshot(path="verification/admin_clients_form.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_add_client_form(page)
        finally:
            browser.close()
