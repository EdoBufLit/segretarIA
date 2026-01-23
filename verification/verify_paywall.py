from playwright.sync_api import sync_playwright, expect
import random
import string
import re

def verify_paywall(page):
    # 1. Register new user (inactive sub)
    page.goto("http://localhost:8000/register")

    random_suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
    username = f"paywall_{random_suffix}"
    email = f"paywall_{random_suffix}@example.com"
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

    # 2. Check Redirect/Content at /dashboard
    # Expect to see Paywall content
    expect(page.locator("h1")).to_contain_text("Accesso Limitato")
    expect(page.get_by_text("Questa funzionalità richiede un abbonamento attivo")).to_be_visible()

    # 3. Check 'ATTIVA ORA' link
    # Should link to /plans
    attiva_btn = page.get_by_role("link", name="ATTIVA ORA")
    expect(attiva_btn).to_be_visible()
    attiva_btn.click()
    expect(page).to_have_url(re.compile(r"/plans"))

    # 4. Check API block
    # We are logged in. Try to fetch /api/logs
    # Go back to dashboard (paywall) first
    page.goto("http://localhost:8000/dashboard")

    response = page.request.get("http://localhost:8000/api/logs")
    if response.status != 403:
        raise Exception(f"Expected 403 for /api/logs, got {response.status}")

    print(f"API /api/logs returned {response.status} as expected.")

    page.screenshot(path="/home/jules/verification/paywall_verified.png", full_page=True)
    print("Paywall verified successfully.")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        try:
            verify_paywall(page)
        except Exception as e:
            print(f"Verification failed: {e}")
            page.screenshot(path="/home/jules/verification/paywall_failed.png")
            exit(1)
        finally:
            context.close()
            browser.close()
