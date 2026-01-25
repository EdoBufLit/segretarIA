from playwright.sync_api import sync_playwright
import time

def verify_client_numbers_section():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Login/Register as Client
        email = f"verify_nums_{int(time.time())}@example.com"
        username = f"user_{int(time.time())}"

        print(f"Registering {username}...")
        page.goto("http://localhost:8000/register")
        page.fill('input[name="username"]', username)
        page.fill('input[name="email"]', email)
        page.fill('input[name="password"]', "password123")
        page.fill('input[name="password_confirm"]', "password123")
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        if "/login" in page.url:
            page.fill('input[name="username"]', email)
            page.fill('input[name="password"]', "password123")
            page.click('button[type="submit"]')
            page.wait_for_load_state("networkidle")

        print(f"Logged in as Client. URL: {page.url}")

        # Debug: Screenshot dashboard
        page.screenshot(path="verification/debug_dashboard_sidebar.png")
        print("Captured debug_dashboard_sidebar.png")

        # Check if the link exists in DOM
        exists = page.locator('a[data-section="numbers"]').count()
        print(f"Number of 'Numeri' links found: {exists}")

        if exists > 0:
            print("Clicking 'Numeri' sidebar link...")
            page.click('a[data-section="numbers"]')

            # Wait for section to be visible
            page.wait_for_selector('#section-numbers:not(.hidden)')

            title = page.text_content("#page-title")
            assert "Numeri Assegnati" in title
            print("Page title correct.")

            time.sleep(1)

            content = page.text_content("#numbers-table-body")
            if "Nessun numero assegnato" in content:
                print("Verified empty state.")
            else:
                print(f"Table content: {content}")

            page.screenshot(path="verification/client_numbers_empty.png")
            print("Screenshot captured: client_numbers_empty.png")
        else:
            print("Sidebar link NOT found.")

        browser.close()

if __name__ == "__main__":
    verify_client_numbers_section()
