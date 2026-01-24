from playwright.sync_api import sync_playwright, expect
import os

ADMIN_USER = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "password123")

def verify_suspend(page):
    # Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", ADMIN_USER)
    page.fill("input[name='password']", ADMIN_PASS)
    page.click("button[type='submit']")

    # Wait for dashboard
    page.wait_for_url("**/dashboard*")

    # Go to Clients
    page.click("a[data-section='users']")

    # Wait for table to load
    page.wait_for_selector("#users-table-body tr")

    # Find ANY client row
    client_row = page.locator("#users-table-body tr").filter(has=page.get_by_role("button", name="SOSPENDI")).first

    if client_row.count() == 0:
         print("No suspendable client found. Checking for suspended ones...")
         client_row = page.locator("#users-table-body tr").filter(has=page.get_by_role("button", name="RIATTIVA")).first
         if client_row.count() > 0:
             print("Found suspended user. Reactivating first.")
             client_row.get_by_role("button", name="RIATTIVA").click()
             page.click("#confirm-ok-btn")
             # Wait for status update - increase timeout
             expect(client_row).to_contain_text("ATTIVO", timeout=10000)
             # Re-fetch row for next step
             client_row = page.locator("#users-table-body tr").filter(has=page.get_by_role("button", name="SOSPENDI")).first

    if client_row.count() == 0:
        print("Still no suspendable row found. Exiting.")
        return

    # Capture user ID/email to re-find it reliably
    user_email = client_row.locator("td").nth(1).inner_text()
    print(f"Testing on user: {user_email}")

    # Click Sospendi
    client_row.get_by_role("button", name="SOSPENDI").click()

    # Confirm
    page.click("#confirm-ok-btn")

    # Locate row again by email to ensure freshness
    target_row = page.locator(f"#users-table-body tr:has-text('{user_email}')")

    # Wait for status update
    expect(target_row).to_contain_text("SOSPESO", timeout=10000)
    expect(target_row.get_by_role("button", name="RIATTIVA")).to_be_visible()

    print("User suspended successfully.")

    # Click Riattiva
    target_row.get_by_role("button", name="RIATTIVA").click()
    page.click("#confirm-ok-btn")

    expect(target_row).to_contain_text("ATTIVO", timeout=10000)
    print("User unsuspended successfully.")

    page.screenshot(path="verification/suspend_success.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_suspend(page)
        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="verification/suspend_error.png")
        finally:
            browser.close()
