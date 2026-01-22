import json
import time
import sqlite3
from datetime import datetime
from playwright.sync_api import sync_playwright, expect

def qa_frontend():
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Capture console logs
        page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
        page.on("pageerror", lambda exc: print(f"BROWSER ERROR: {exc}"))

        # 1. Login
        print("Test 1: Login...")
        try:
            page.goto("http://127.0.0.1:8000/login")
            page.fill("input[name='username']", "admin")
            page.fill("input[name='password']", "password123")
            page.click("button[type='submit']")
            page.wait_for_url("http://127.0.0.1:8000/dashboard")
            results.append("PASS: Login successful")
        except Exception as e:
            results.append(f"FAIL: Login failed - {e}")
            return results

        # 2. Status Badges
        print("Test 2: Status Badges...")
        try:
            # Wait for status update
            # We poll every 15s in the dashboard.
            # But the first call is immediate.
            # If it stays "...", the call failed or JS error.
            page.wait_for_selector("#status-service")

            # Allow time for fetch
            time.sleep(2)

            status_text = page.locator("#status-service").inner_text()
            if "ATTIVO" in status_text:
                results.append("PASS: Service status is ATTIVO")
            elif "SOSPESO" in status_text:
                results.append(f"PASS: Service status is SOSPESO (unexpected but valid value)")
            else:
                results.append(f"FAIL: Service status is '{status_text}'")
        except Exception as e:
            results.append(f"FAIL: Status badges check failed - {e}")

        # 3. Polling (Active Status Toggle)
        print("Test 3: Polling (Active Status Toggle)...")
        try:
            # Modify DB to set is_active=0
            conn = sqlite3.connect("app.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_active = 0 WHERE username = 'admin'")
            conn.commit()
            conn.close()
            print("   -> DB updated to inactive. Waiting for poll (max 20s)...")

            # Wait for UI update
            try:
                # Polling interval is 15s. Wait 20s.
                expect(page.locator("#status-service")).to_have_text("SOSPESO", timeout=20000)
                results.append("PASS: UI updated to SOSPESO via polling")
            except AssertionError:
                txt = page.locator("#status-service").inner_text()
                results.append(f"FAIL: UI did not update to SOSPESO (Text: {txt})")

            # Restore
            conn = sqlite3.connect("app.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_active = 1 WHERE username = 'admin'")
            conn.commit()
            conn.close()

            # Wait for restore
            try:
                expect(page.locator("#status-service")).to_have_text("ATTIVO", timeout=20000)
                results.append("PASS: UI updated back to ATTIVO via polling")
            except AssertionError:
                results.append("FAIL: UI did not update back to ATTIVO")

        except Exception as e:
            results.append(f"FAIL: Polling test exception - {e}")

        # 4. Stripe Success Simulation
        print("Test 4: Stripe Success Simulation...")
        try:
            # We reload page with params
            page.goto("http://127.0.0.1:8000/dashboard?billing=success")
            # Check for toast
            # Wait for toast container
            try:
                expect(page.locator("#toast-container")).to_be_visible(timeout=5000)
                # Check text
                toast_text = page.locator("#toast-container").inner_text()
                if "Pagamento ricevuto" in toast_text:
                    results.append("PASS: Success toast visible")
                else:
                    results.append(f"FAIL: Toast text mismatch: {toast_text}")
            except:
                 results.append("FAIL: Toast not found")
        except Exception as e:
            results.append(f"FAIL: Stripe simulation failed - {e}")

        # 5. Logs Tab Polling
        print("Test 5: Logs Tab Polling...")
        try:
            # Click logs tab
            page.click("a[data-section='logs']")

            # Wait for section to be visible
            expect(page.locator("#section-logs")).not_to_have_class("hidden") # Or check visibility

            # Wait for table body (it's empty initially, so it might be 0 height but visible in DOM)
            # We need to wait for the polling to pick up the log we are about to write.

            # Write a new log to file
            log_entry = {
                "timestamp": datetime.utcnow().isoformat(),
                "agent_id": "test_agent",
                "data": {
                    "caller_number": "+393331234567",
                    "status": "success",
                    "duration_secs": 120,
                    "summary": "QA_AUTO_TEST_LOG"
                }
            }
            with open("logs/test_agent.log", "a") as f:
                f.write(json.dumps(log_entry) + "\n")
            print("   -> Log written. Waiting for refresh (max 20s)...")

            # Force selection if needed?
            # dashboard.js: initLogsSection -> fetch /clients -> populate dropdown -> loadLogsTable.
            # If clients.json has test_agent, it should be in dropdown.
            # If it's the first one, it is selected.
            # We created clients.json with test_agent.

            # Wait for log to appear
            try:
                expect(page.locator("td", has_text="QA_AUTO_TEST_LOG")).to_be_visible(timeout=20000)
                results.append("PASS: New log appeared via polling")
            except AssertionError:
                results.append("FAIL: New log did not appear automatically")

        except Exception as e:
            results.append(f"FAIL: Logs polling failed - {e}")

        browser.close()

    return results

if __name__ == "__main__":
    results = qa_frontend()
    print("\n=== QA RESULTS ===")
    for r in results:
        print(r)

    with open("QA_NOTES_FE.md", "w") as f:
        f.write("# Frontend QA Report\n\n")
        f.write("| Test | Result |\n")
        f.write("|------|--------|\n")
        for r in results:
            parts = r.split(": ", 1)
            status = "✅ PASS" if "PASS" in parts[0] else "❌ FAIL"
            desc = parts[1] if len(parts) > 1 else r
            f.write(f"| {desc} | {status} |\n")
