from playwright.sync_api import sync_playwright

def verify_landing():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Verify Landing Page
        print("Navigating to Landing Page...")
        page.goto("http://localhost:8000/")
        page.wait_for_load_state("networkidle")
        page.screenshot(path="verification/landing_page.png")
        print("Landing page screenshot captured.")

        browser.close()

if __name__ == "__main__":
    verify_landing()
