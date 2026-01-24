import os
import time
from playwright.sync_api import sync_playwright, expect

def verify_delete_user():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # 1. Login as Admin
        page.goto("http://127.0.0.1:8000/login")
        page.fill("input[name='username']", "admin")
        page.fill("input[name='password']", "password")
        page.click("button[type='submit']")

        # Wait for dashboard
        page.wait_for_url("http://127.0.0.1:8000/dashboard")
        print("Logged in as admin")

        # 2. Create a test user via API (easiest way to ensure clean state)
        # Using context.request to make API call
        api = context.request
        res = api.post("http://127.0.0.1:8000/register", form={
            "username": "delete_me",
            "email": "delete_me@example.com",
            "password": "password123",
            "password_confirm": "password123"
        })
        if res.status == 302 or res.status == 200:
            print("User registered")
        else:
            print(f"Register failed: {res.status} {res.text()}")

        # 3. Suspend the user via API (so "Elimina" button appears)
        # Find user ID first. Admin list.
        res = api.get("http://127.0.0.1:8000/admin/users?q=delete_me")
        data = res.json()
        if data["total"] > 0:
            user_id = data["items"][0]["id"]
            api.post(f"http://127.0.0.1:8000/admin/users/{user_id}/suspend")
            print(f"Suspended user {user_id}")
        else:
            print("User not found for suspension")
            return

        # 4. Navigate to Clients Tab
        page.reload() # Refresh to update state or just click tab
        # Click "Clienti" sidebar link.
        # Note: sidebar link has data-section="users" but text is "Clienti"
        page.click("a[data-section='users']")

        # Wait for table to load
        page.wait_for_selector("#users-table-body tr")

        # Search for user to be safe
        page.fill("#users-search", "delete_me")
        page.click("button:has-text('Cerca')")
        time.sleep(1) # wait for fetch

        # 5. Verify "Elimina" button exists
        # Look for row containing "delete_me"
        row = page.locator("tr", has_text="delete_me")
        expect(row).to_be_visible()

        elimina_btn = row.locator("button", has_text="ELIMINA")
        expect(elimina_btn).to_be_visible()
        print("Elimina button visible")

        # 6. Click Elimina -> Screenshot Modal
        elimina_btn.click()
        modal = page.locator("#confirm-modal")
        expect(modal).to_be_visible()

        # Screenshot 1: Modal initial state
        page.screenshot(path="verification/1_modal_initial.png")
        print("Screenshot 1 taken")

        # 7. Type "ELIMINA"
        input_field = page.locator("#confirm-input")
        expect(input_field).to_be_visible()
        input_field.fill("ELIMINA")

        # Screenshot 2: Ready to confirm
        page.screenshot(path="verification/2_modal_filled.png")
        print("Screenshot 2 taken")

        # 8. Confirm
        confirm_btn = page.locator("#confirm-ok-btn")
        expect(confirm_btn).not_to_be_disabled()
        confirm_btn.click()

        # 9. Verify User Gone
        time.sleep(2) # Wait for reload/fetch

        # Search again or check if row is gone
        page.fill("#users-search", "delete_me")
        page.click("button:has-text('Cerca')")
        time.sleep(1)

        # Row should not be visible or table empty message
        # If filtered list is empty, loop might be empty.
        count = row.count()
        if count == 0:
            print("User successfully deleted from UI")
        else:
            print("User still visible?!")

        page.screenshot(path="verification/3_final.png")

        browser.close()

if __name__ == "__main__":
    # Ensure verification dir exists
    os.makedirs("verification", exist_ok=True)
    verify_delete_user()
