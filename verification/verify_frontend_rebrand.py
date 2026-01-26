from playwright.sync_api import sync_playwright
import time
import os

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # 1. Verify Homepage
        print("Visiting Homepage...")
        page.goto("http://localhost:8000")

        # Wait for splash screen to go away or just wait a bit
        time.sleep(2)

        # Take screenshot
        page.screenshot(path="verification/homepage_rebrand.png")
        print("Screenshot saved to verification/homepage_rebrand.png")

        # Verify Navbar
        # Check if logo exists
        logo = page.locator("nav img[alt='Mr.Automa']")
        if logo.count() > 0:
            print("SUCCESS: Logo found in Navbar.")
        else:
            print("FAILURE: Logo NOT found in Navbar.")

        # Check if text is gone from the brand link
        # The brand link is the first 'a' in 'nav' usually, or the one containing the logo.
        brand_link = page.locator("nav a").first
        text_content = brand_link.text_content()
        print(f"Brand link text content: '{text_content}'")

        if "Mr.Automa" in text_content.strip():
             # Wait, the alt text might be picked up if image fails? No, text_content usually gets inner text.
             # If I removed the text node, it should be empty or just whitespace.
             # Actually, if I just have <img> inside <a>, text_content should be empty string.
             if text_content.strip() == "":
                 print("SUCCESS: Navbar brand text is empty (Logo Only).")
             else:
                 print(f"WARNING: Navbar brand text seems to contain: '{text_content}'. Check if this is intended.")
        else:
             print("SUCCESS: 'Mr.Automa' text NOT found in brand link.")

        browser.close()

if __name__ == "__main__":
    run()
