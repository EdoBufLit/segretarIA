from playwright.sync_api import sync_playwright, expect
import os

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    if not os.path.exists("verification"):
        os.makedirs("verification")

    # 1. Login
    page.goto("http://127.0.0.1:8000/login")
    page.fill("input[name='username']", "admin")
    page.fill("input[name='password']", "password123")
    page.click("button[type='submit']")
    page.wait_for_url("**/dashboard")

    # 2. Click on "Routing" in sidebar
    page.click("a[data-section='routing']")
    expect(page.locator("#section-routing")).to_be_visible()

    # 3. Check for "Nuovo Routing" button
    new_btn = page.locator("button", has_text="Nuovo Routing")
    expect(new_btn).to_be_visible()

    # 4. Open Modal
    new_btn.click()
    modal = page.locator("#add-routing-modal")
    expect(modal).to_be_visible()

    # 5. Take screenshot
    page.screenshot(path="verification/routing_modal.png")
    print("Screenshot saved")

    browser.close()

with sync_playwright() as playwright:
    run(playwright)
