from playwright.sync_api import sync_playwright, expect

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("1. Testing Suspended User")
        # 1. Login
        page.goto("http://localhost:8000/login")
        page.fill("input[name='username']", "client_suspended")
        page.fill("input[name='password']", "password")
        page.click("button[type='submit']")

        # Wait for navigation
        page.wait_for_url("http://localhost:8000/dashboard")

        # 2. Verify Banner (Always visible)
        expect(page.get_by_text("Il tuo piano è scaduto o il servizio è disattivato")).to_be_visible()

        # 3. Verify Dashboard Blocked
        expect(page.get_by_text("Dashboard Limitata")).to_be_visible()

        # 4. Navigate to Logs
        page.click("a[data-section='logs']")
        # Verify Logs Blocked
        expect(page.get_by_text("Registro Bloccato")).to_be_visible()

        # 5. Navigate to Analytics
        page.click("a[data-section='analytics']")
        expect(page.get_by_text("Analytics Bloccati")).to_be_visible()

        # 6. Navigate to Numbers
        page.click("a[data-section='numbers']")
        expect(page.get_by_text("Gestione Numeri Bloccata")).to_be_visible()

        # Take Screenshot
        page.screenshot(path="verification/client_dashboard_suspended.png", full_page=True)
        print("Suspended user verified.")

        # Logout
        page.goto("http://localhost:8000/logout")

        print("2. Testing Active User")
        page.goto("http://localhost:8000/login")
        page.fill("input[name='username']", "client_active")
        page.fill("input[name='password']", "password")
        page.click("button[type='submit']")

        page.wait_for_url("http://localhost:8000/dashboard")

        # Verify NO Banner
        expect(page.get_by_text("Il tuo piano è scaduto")).not_to_be_visible()

        # Verify Normal Dashboard
        expect(page.get_by_text("Dashboard Limitata")).not_to_be_visible()
        expect(page.get_by_text("Minuti")).to_be_visible() # A card title

        # Navigate to Logs
        page.click("a[data-section='logs']")
        expect(page.get_by_text("Registro Bloccato")).not_to_be_visible()
        expect(page.get_by_text("Registro Chiamate")).to_be_visible()

        page.screenshot(path="verification/client_dashboard_active.png", full_page=True)
        print("Active user verified.")

        browser.close()

if __name__ == "__main__":
    run()
