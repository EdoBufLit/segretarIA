from playwright.sync_api import sync_playwright, expect
import random
import string
import re

def verify_banner(page):
    # 1. Register a new user (who will have no subscription)
    page.goto("http://localhost:8000/register")

    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    username = f"banner_user_{random_suffix}"
    email = f"banner_{random_suffix}@example.com"
    password = "password123"

    page.locator("input[name='username']").fill(username)
    page.locator("input[name='email']").fill(email)
    page.locator("input[name='password']").fill(password)
    page.locator("input[name='password_confirm']").fill(password)
    page.get_by_role("button", name="Registrati").click()

    # Login
    page.locator("input[name='username']").fill(username)
    page.locator("input[name='password']").fill(password)
    page.get_by_role("button", name="Entra").click()

    # Wait for dashboard
    expect(page).to_have_url("http://localhost:8000/dashboard")

    # 2. Verify Banner is Visible
    banner = page.locator("#activation-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Attiva il tuo assistente")

    # 3. Click "ATTIVA ORA" and verify redirection to /plans
    page.get_by_role("link", name="ATTIVA ORA").click()
    expect(page).to_have_url(re.compile(r"/plans"))

    # 4. Verify Plans Page content
    expect(page.get_by_text("Attiva o Aggiorna il tuo piano")).to_be_visible()
    expect(page.get_by_role("heading", name="Starter")).to_be_visible()
    expect(page.get_by_role("heading", name="Pro")).to_be_visible()
    expect(page.get_by_role("heading", name="Business")).to_be_visible()

    page.screenshot(path="/home/jules/verification/banner_and_plans.png", full_page=True)
    print("Banner and Plans Page Verified")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            verify_banner(page)
        except Exception as e:
            print(f"Verification failed: {e}")
            page.screenshot(path="/home/jules/verification/banner_failed.png")
        finally:
            context.close()
            browser.close()
