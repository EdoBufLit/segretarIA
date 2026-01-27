from playwright.sync_api import sync_playwright
import time

def verify_barge_in_ui():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use a new context to store cookies
        context = browser.new_context()
        page = context.new_page()

        # 1. Login first (we need to be authenticated)
        # Assuming app is running at 127.0.0.1:3000 (standard preview port)
        page.goto("http://127.0.0.1:3000/login")
        page.fill("input[name='username']", "admin")
        page.fill("input[name='password']", "admin") # Default seed creds
        page.click("button[type='submit']")

        # Wait for redirect to dashboard
        page.wait_for_url("**/dashboard")

        # 2. Mock the active call API response to show the banner
        # We intercept the fetch call
        page.route("**/api/client/active-call", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": "ok", "active_call": {"call_sid": "mock_123", "status": "ai_active", "caller_number": "+393339998877", "office_phone_e164": "+39021234567"}}'
        ))

        # 3. Reload dashboard or wait for poll
        page.goto("http://127.0.0.1:3000/dashboard")

        # Wait for banner to appear (it polls every 3s)
        try:
            page.wait_for_selector("#active-call-banner:not(.hidden)", timeout=5000)
            print("Banner appeared!")
        except:
            print("Banner did not appear in time.")

        # 4. Take Screenshot of Active Call State
        page.screenshot(path="verification/active_call_banner.png")

        # 5. Test Click (Barge In)
        # Mock the POST response
        page.route("**/calls/mock_123/barge-in", lambda route: route.fulfill(
            status=200,
            content_type="application/json",
            body='{"status": "ok", "call_status": "human_requested"}'
        ))

        # Click the button
        page.click("button[onclick*='bargeInCall']")

        # Wait for loading state
        time.sleep(0.5)
        page.screenshot(path="verification/active_call_loading.png")

        # Wait for success state (polling mock needs to update or local optimistic UI)
        # The JS updates UI optimistically to "Richiesta inviata"
        time.sleep(1)
        page.screenshot(path="verification/active_call_success.png")

        browser.close()

if __name__ == "__main__":
    try:
        verify_barge_in_ui()
        print("Verification script ran successfully.")
    except Exception as e:
        print(f"Verification failed: {e}")
