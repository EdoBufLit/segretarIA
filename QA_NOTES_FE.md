# Frontend QA Report

## Summary
The QA process identified a **CRITICAL FAILURE** in the application backend that prevents the frontend from functioning correctly.

**Status:** ❌ FAIL

## Test Results

| Test | Result |
|------|--------|
| Login successful | ✅ PASS |
| Service status is '...' | ❌ FAIL |
| UI did not update to SOSPESO (Text: ...) | ❌ FAIL |
| UI did not update back to ATTIVO | ❌ FAIL |
| Success toast visible | ✅ PASS |
| New log did not appear automatically | ❌ FAIL |

## Detailed Observations

### 1. Critical Backend Bug (`GET /me` 500 Internal Server Error)
The dashboard fails to load status information because the `GET /me` endpoint throws an exception.
- **Error:** `AttributeError: type object 'Subscription' has no attribute 'created_at'. Did you mean: 'updated_at'?`
- **Location:** `app.py`, line 1003, in `read_users_me`.
- **Cause:** The code attempts to order subscriptions by `Subscription.created_at`, but the `Subscription` model in `models.py` does not have a `created_at` column. It has `updated_at`.

### 2. Dashboard Status Bar
- Due to the 500 error on `/me`, the status bar stays in the loading state ("...").
- Polling continues but consistently receives 500 errors.

### 3. Logs
- Logs polling also relies on the dashboard being functional (though the logs endpoint itself might be fine, the `dashboard.js` polling logic might be interrupted or the browser state is compromised by the errors).
- The test "New log did not appear automatically" failed, likely as a side effect or because the initial admin data fetch (part of `initDashboard`) might also be affected if it relies on a shared failure path.

### Recommendations
1.  **HOTFIX:** Update `app.py` to use `Subscription.id` or `Subscription.updated_at` instead of `Subscription.created_at` for sorting.
2.  **Verify:** Re-run this QA suite after the fix.
