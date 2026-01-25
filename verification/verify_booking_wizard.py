from playwright.sync_api import sync_playwright

def verify_booking_wizard():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("Navigating to Landing Page...")
        page.goto("http://localhost:8000/")
        page.wait_for_load_state("networkidle")

        # Click 'Contattaci' button to open wizard
        print("Opening Booking Wizard...")
        page.click("button[data-booking-open]:first-of-type")

        # Wait for wizard to appear (it should have class 'flex' now)
        page.wait_for_selector("#booking-wizard.flex")
        page.wait_for_timeout(500) # Wait for transition/animation

        page.screenshot(path="verification/booking_wizard_step1.png")
        print("Captured Step 1 screenshot.")

        # Fill Step 1
        print("Filling Step 1...")
        page.fill("input[name='full_name']", "Mario Rossi")
        page.fill("input[name='email']", "mario@example.com")
        page.fill("input[name='phone']", "+393331234567")

        # Click Next
        page.click("#booking-wizard-next")

        # Wait for Step 2
        page.wait_for_timeout(500)
        page.screenshot(path="verification/booking_wizard_step2.png")
        print("Captured Step 2 screenshot.")

        browser.close()

if __name__ == "__main__":
    verify_booking_wizard()
