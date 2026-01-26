from playwright.sync_api import sync_playwright, expect
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("1. Login as Admin")
        page.goto("http://localhost:8000/login")
        page.fill("input[name='username']", "admin")
        page.fill("input[name='password']", "admin")
        page.click("button[type='submit']")

        page.wait_for_url("http://localhost:8000/dashboard")

        print("2. Navigate to Clients")
        page.click("a[data-section='users']")

        # Wait for table to load (it fetches via AJAX)
        page.wait_for_selector("#users-table-body tr")

        # 3. Find client_active row
        # We can search for it
        page.fill("#users-search", "client_active")
        page.click("button:has-text('Cerca')")

        # Wait for results
        # We expect one row with client_active@example.com
        row = page.locator("tr", has_text="client_active@example.com")
        expect(row).to_be_visible()

        print("3. Toggle Off")
        # Find the checkbox in that row
        checkbox = row.locator("input[type='checkbox']")

        # It should be checked initially
        expect(checkbox).to_be_checked()

        # Uncheck it (Click the label or the checkbox)
        checkbox.click(force=True) # checkbox is hidden/sr-only, so we might need force or click label
        # The label is `label.inline-flex`
        # row.locator("label").click() might be better

        # Wait for toast "Utente sospeso"
        expect(page.locator("div#toast-container")).to_contain_text("Utente sospeso")

        # Verify text changed to "Disattivato"
        expect(row.locator("span", has_text="Disattivato")).to_be_visible()

        print("4. Toggle On")
        checkbox.click(force=True)

        # Wait for toast "Utente riattivato"
        expect(page.locator("div#toast-container")).to_contain_text("Utente riattivato")

        # Verify text changed to "Attivo"
        expect(row.locator("span", has_text="Attivo")).to_be_visible()

        # Screenshot
        page.screenshot(path="verification/admin_toggle.png", full_page=True)
        print("Admin toggle verified.")

        browser.close()

if __name__ == "__main__":
    run()
