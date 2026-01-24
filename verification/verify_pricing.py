from playwright.sync_api import sync_playwright, expect

def verify_pricing(page):
    page.goto("http://127.0.0.1:8000/billing/plans")
    expect(page.get_by_text("Scegli il tuo piano")).to_be_visible()

    # Check for Starter price (Mocked as 29€)
    expect(page.get_by_text("29€")).to_be_visible()

    # Check for Pro price (Mocked as 79€)
    expect(page.get_by_text("79€")).to_be_visible()

    # Check for Business price (Mocked as 199€)
    expect(page.get_by_text("199€")).to_be_visible()

    page.screenshot(path="verification/pricing_plans.png")
    print("Screenshot saved to verification/pricing_plans.png")

if __name__ == "__main__":
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            verify_pricing(page)
        except Exception as e:
            print(f"Error: {e}")
            page.screenshot(path="verification/error.png")
        finally:
            browser.close()
