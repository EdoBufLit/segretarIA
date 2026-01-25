from playwright.sync_api import sync_playwright

def verify_frontend():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Verify Login
        print("Navigating to Login...")
        page.goto("http://localhost:8000/login")
        page.wait_for_load_state("networkidle")
        page.screenshot(path="verification/login_page.png")
        print("Login screenshot captured.")

        # Verify Register
        print("Navigating to Register...")
        page.goto("http://localhost:8000/register")
        page.wait_for_load_state("networkidle")
        page.screenshot(path="verification/register_page.png")
        print("Register screenshot captured.")

        browser.close()

if __name__ == "__main__":
    verify_frontend()
