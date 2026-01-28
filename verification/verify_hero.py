
import time
from playwright.sync_api import sync_playwright

def verify_hero_rotation():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("http://localhost:8000")

        # Wait for page load
        page.wait_for_selector("#hero-rotating-phrase")

        # Screenshot 1 (Initial: "il tuo studio")
        page.screenshot(path="verification/hero_1.png")
        print("Screenshot 1 taken.")

        # Wait for rotation (2400ms interval + transition time)
        # We need to capture the next phrase.
        time.sleep(3)

        # Screenshot 2 (Expected: "la tua azienda")
        page.screenshot(path="verification/hero_2.png")
        print("Screenshot 2 taken.")

        time.sleep(3)

        # Screenshot 3 (Expected: "la tua associazione")
        page.screenshot(path="verification/hero_3.png")
        print("Screenshot 3 taken.")

        browser.close()

if __name__ == "__main__":
    verify_hero_rotation()
