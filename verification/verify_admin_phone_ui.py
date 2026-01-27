from playwright.sync_api import sync_playwright, expect
import time

def verify_admin_phone_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Larger viewport to avoid scrolling issues with modals
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        try:
            # 1. Login
            page.goto("http://localhost:8000/login")
            page.fill("input[name='username']", "admin_office")
            page.fill("input[name='password']", "password")
            page.click("button[type='submit']")

            # Wait for dashboard
            page.wait_for_selector("#section-dashboard", state="visible")
            print("Logged in")

            # 2. Navigate to Phone Numbers
            # Force click in case menu is animated/hidden? No, it's visible.
            page.click("a[data-section='phonenumbers']")
            # Wait for table to load
            page.wait_for_selector("#phonenumbers-table-body", state="visible")
            time.sleep(1)
            print("Navigated to Phone Numbers")

            # 3. Open Edit Modal (Assuming there is a phone number from previous tests)
            # We need to find a row with 'MODIFICA' button
            edit_btn = page.locator("button:has-text('MODIFICA')").first

            if edit_btn.count() == 0:
                print("No phone numbers found to edit. Adding one first.")
                page.click("button:has-text('Nuovo Numero')")
                # Wait for modal
                page.wait_for_selector("#add-phonenumber-modal", state="visible")

                page.fill("#add-phonenumber-form input[name='e164']", "+393339998877")
                page.fill("#add-phonenumber-form input[name='user_id']", "5")
                page.fill("#add-phonenumber-form textarea[name='notes']", "Created for UI test")

                # Force click save
                page.click("#add-phonenumber-form button[type='submit']", force=True)

                # Wait for modal to close and table to refresh
                page.wait_for_selector("#add-phonenumber-modal", state="hidden")
                time.sleep(2)

                edit_btn = page.locator("button:has-text('MODIFICA')").first

            print("Clicking Edit...")
            edit_btn.click()
            page.wait_for_selector("#edit-phonenumber-modal", state="visible")
            print("Opened Edit Modal")

            # 4. Fill Office Info
            page.fill("#edit-office-phone", "+390212345678")
            page.select_option("#edit-timezone", "Europe/London")

            # Toggle Monday (Label click)
            page.click("label[for='edit-open-Mon']")

            # Save
            print("Saving changes...")
            page.click("#edit-phonenumber-form button[type='submit']", force=True)

            # Wait for modal close
            page.wait_for_selector("#edit-phonenumber-modal", state="hidden")
            time.sleep(2) # Allow table refresh
            print("Saved changes")

            # 5. Verify Table
            # Look for summary in table
            if page.locator("text=+390212345678").count() > 0:
                print("Found updated office phone in table")
            else:
                print("WARNING: Updated phone not found in table text.")

            # Screenshot
            page.screenshot(path="verification/admin_phone_ui.png", full_page=True)
            print("Screenshot saved")

        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="verification/error.png")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_admin_phone_ui()
