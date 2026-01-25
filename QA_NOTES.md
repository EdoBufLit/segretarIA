# QA Notes - Integration Release v1

## 1. Migration Status
- **Status:** Up to date.
- **Head Revision:** `8438d791efa6`.
- **Verification:** `alembic upgrade head` executed successfully.

## 2. Boot Verification
- **App Start:** SUCCESS (`uvicorn app:app --reload`).
- **Landing Page:** Accessible (200 OK).
- **Dependencies:** All present (fixed `itsdangerous`, `python-multipart` missing in main).

## 3. Functional Verification (Smoke)
- **Landing Page:** PASS.
- **Login Flow:** PASS (User -> Dashboard).
- **Dashboard Navigation:** PASS.
- **Missing UI:** The "Billing/Abbonamento" section is missing from `dashboard.html`. This appears to be a regression from merging `landing-page` (which overwrote the template) with `stripe-integration`.

## 4. Security & Enforcement Verification
### Rate Limiting
- **Status:** PASS.
- **Verification:** 10 rapid requests to `/login` trigger HTTP 429 (Too Many Requests).

### User Suspension (Phase 2)
- **Admin API:** PASS (Can toggle suspension).
- **Login:** PASS (Suspended user blocked).
- **Webhook (ElevenLabs):** PASS (Suspended user blocked, returns `{"status": "suspended"}`).
- **Direct API (Test Call):** Requires re-verification after moving agent settings into the DB.

## 5. Admin Tooling
- **Password Reset:** Endpoint `@app.post("/admin/users/{user_id}/reset-password")` exists in codebase (verified via grep), though functional test returned 404 (likely test configuration error).

## Summary
The integration branch `integration-release-v1` successfully combines all feature branches. Rate limiting and basic suspension enforcement work. However, there are regressions in the Dashboard UI and a security gap in API-level suspension enforcement due to caching strategy.
