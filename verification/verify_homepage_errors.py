from playwright.sync_api import sync_playwright

def verify_homepage_errors(page):
    errors = []
    page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: errors.append(str(exc)))

    page.goto("http://127.0.0.1:8000/")

    # Scroll to trigger scroll event listener
    page.evaluate("window.scrollTo(0, 500)")
    page.wait_for_timeout(500) # wait a bit

    if errors:
        print("Console/Page errors found:")
        for e in errors:
            print(f"- {e}")
        exit(1)
    else:
        print("No console errors found on homepage.")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_homepage_errors(page)
        finally:
            browser.close()
