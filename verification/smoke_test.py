import requests
import sys
import time

BASE_URL = "http://127.0.0.1:8000"

def check_url(path, method="GET", expected_code=200):
    url = f"{BASE_URL}{path}"
    try:
        if method == "GET":
            resp = requests.get(url)
        elif method == "POST":
            resp = requests.post(url)

        if resp.status_code == expected_code:
            print(f"[PASS] {method} {path} -> {resp.status_code}")
            return True
        else:
            print(f"[FAIL] {method} {path} -> Expected {expected_code}, got {resp.status_code}")
            return False
    except Exception as e:
        print(f"[ERR ] {method} {path} -> {e}")
        return False

def smoke_test():
    print(f"Running Smoke Test against {BASE_URL}...")

    checks = [
        ("/", "GET", 200),
        ("/health", "GET", 200),
        ("/login", "GET", 200),
        ("/billing/plans", "GET", 200),
        # /dashboard requires auth, so expecting redirect to login (302) or 200 if requests followed redirects (requests follows by default)
        # If following redirects, it lands on /login (200). If not, 302.
        # Let's assume follows redirects = 200 (login page)
        ("/dashboard", "GET", 200),

        # Admin route protected -> redirect to login or 403?
        # Usually redirects to login for unauth users.
        ("/admin/clients", "GET", 200),
    ]

    failed = 0
    for path, method, code in checks:
        if not check_url(path, method, code):
            failed += 1

    # Test Lead POST (expecting validation error 400 or 422, ensuring endpoint is reachable)
    print("Testing /lead POST (Validation Error)...")
    resp = requests.post(f"{BASE_URL}/lead", json={})
    if resp.status_code in [400, 422]:
        print(f"[PASS] POST /lead -> {resp.status_code} (Validation Error as expected)")
    else:
        print(f"[FAIL] POST /lead -> Expected 400/422, got {resp.status_code}")
        failed += 1

    if failed > 0:
        print(f"\nSmoke Test FAILED with {failed} errors.")
        sys.exit(1)
    else:
        print("\nSmoke Test PASSED.")
        sys.exit(0)

if __name__ == "__main__":
    smoke_test()
