# QA Notes

## Migration Status
- Head Revision: `c54084c35b28`
- Status: Up to date (verified via `alembic upgrade head`)

## Boot Verification
- Application starts successfully: YES
- Import errors: NONE (after fixing missing dependencies)
- Startup exceptions: NONE

## Dependencies
- Missing `itsdangerous` and `python-multipart`.
- Action: Installed via pip.
- Recommendation: Ensure these are added to `requirements.txt`.

## Smoke Test (Automated via Playwright)

### Landing Page
- **Load**: PASS (Status 200, Content Verified)
- **Login Link**: PASS (Points to `/login`)
- **Anchors**: PASS (Target `#prezzi` exists)

### Login Flow
- **Invalid Credentials**: PASS (Error message shown)
- **Valid Credentials**: PASS (Redirects to `/dashboard`)

### Dashboard Navigation
- **Sections Verified**:
  - Dashboard: PASS
  - Logs: PASS
  - Analytics: PASS
  - Settings: PASS
- **Console Errors**: NONE
- **Note**: The 'Clients' section mentioned in the spec does not appear in the sidebar navigation for the test user (Role: Admin). It might be restricted or removed. The sidebar contains: Dashboard, Logs, Analytics, Settings.

## Security Test: Rate Limiting
- **Test Script**: `tests/rate_limit_test.sh`
- **Target**: `POST /login` and `GET /admin/clients`
- **Requests**: 10 rapid requests (threshold expected: 5/min)
- **Result**: FAIL
    - `POST /login`: 10 requests returned 302 (Redirect)
    - `GET /admin/clients`: 10 requests returned 302 (Redirect)
- **Observation**: No `429 Too Many Requests` response received.
- **Root Cause**: `RateLimitMiddleware` is missing from `app.py`.
- **Severity**: High (Security Feature Missing)

## Enforcement Test: Suspended Users
- **Method**: Manual DB update to set `is_active=False` (API endpoint missing).
- **Target**: Block access for suspended users.
- **Results**:
    - **Login**: PASS (User blocked, redirected to login).
    - **Webhook (`/elevenlabs/webhook`)**: FAIL (Returned 200 OK, processed call).
        - *Reason*: Webhook uses `clients.json` which lacks status, and does not check DB.
    - **Test Call (`/clients/.../test-call`)**: FAIL (Returned 400 Config Error, not 403 Forbidden).
        - *Reason*: Endpoint does not verify `is_active` status.
    - **Admin API**: FAIL (Endpoint `POST /admin/users/{id}/toggle-active` is missing).
- **Severity**: Critical (Suspended users can still use the service via phone/webhook).

## Observations
- The application requires `itsdangerous` and `python-multipart` to be installed.
- "Statistiche" in the spec refers to the "Analytics" section in the UI.
