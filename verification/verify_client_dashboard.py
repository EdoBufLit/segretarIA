from playwright.sync_api import sync_playwright, expect
import random
import string
import time
import re

def verify_client_dashboard(page):
    # 1. Register
    page.goto("http://localhost:8000/register")

    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    username = f"client_{random_suffix}"
    email = f"client_{random_suffix}@example.com"
    password = "password123"

    page.locator("input[name='username']").fill(username)
    page.locator("input[name='email']").fill(email)
    page.locator("input[name='password']").fill(password)
    page.locator("input[name='password_confirm']").fill(password)

    # Click button. Text is "Registrati"
    page.get_by_role("button", name="Registrati").click()

    # Should redirect to login?
    expect(page).to_have_url(re.compile(r"/login\?registered=1"))

    # 2. Login
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='password']").fill(password)

    # Button text is "Entra" in login.html
    page.get_by_role("button", name="Entra").click()

    # 3. Verify Dashboard
    # Should redirect to /dashboard
    expect(page).to_have_url("http://localhost:8000/dashboard")

    # Check for Client Dashboard specific elements
    # "Panoramica" appears twice (sidebar + title). Check at least one is visible.
    expect(page.get_by_role("heading", name="Panoramica")).to_be_visible()

    expect(page.get_by_text("Minuti Mensili")).to_be_visible()

    # Check that Admin elements are NOT present (e.g. "Clienti attuali", "Aggiungi Cliente")
    # "Clienti attuali" is in admin dashboard
    expect(page.get_by_text("Clienti attuali")).not_to_be_visible()

    # Take screenshot
    page.screenshot(path="/home/jules/verification/client_dashboard.png", full_page=True)
    print("Client Dashboard Verified")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Client Test
        context1 = browser.new_context()
        page1 = context1.new_page()
        try:
            verify_client_dashboard(page1)
        except Exception as e:
            print(f"Client verification failed: {e}")
            page1.screenshot(path="/home/jules/verification/client_failed.png")
        finally:
            context1.close()

        browser.close()
