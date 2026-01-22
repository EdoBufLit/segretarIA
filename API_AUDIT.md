# API Audit Report

## 1. Overview
This audit examines the existing API endpoints used by the dashboard for user and subscription status. The goal is to identify reliability and security gaps as we move to Phase 4A.

## 2. Endpoints Analysis

### User & Authentication
| Endpoint | Method | Auth Required | Payload | Sufficiency |
|----------|--------|---------------|---------|-------------|
| `/me` | GET | ✅ Yes | `username`, `role`, `studio_name` | ❌ **Insufficient**. Missing `is_active`, `email`, `stripe_customer_id`. |
| `/login` | POST | ❌ No (Public) | Session Cookie | N/A |
| `/logout` | GET | ❌ No (Public) | Redirect | N/A |

### Subscription & Billing
| Endpoint | Method | Auth Required | Payload | Notes |
|----------|--------|---------------|---------|-------|
| `/subscription/status` | GET | ✅ Yes | `plan_code`, `minutes_total`, `minutes_used`, `minutes_remaining`, `state`, `cycle_end` | ✅ **Sufficient** for status. Handles inactive state. |
| `/subscription/cancel` | POST | ✅ Yes | Status message | |
| `/billing/checkout` | POST | ✅ Yes | Checkout URL | |

### Logs & Analytics (Current Dashboard)
| Endpoint | Method | Auth Required | Payload | Security Risk |
|----------|--------|---------------|---------|---------------|
| `/logs/{agent_id}/list` | GET | ❌ **NO** | Paginated logs | 🚨 **CRITICAL**. Publicly accessible. Exposes call logs. |
| `/logs/{agent_id}` | GET | ❌ **NO** | All logs | 🚨 **CRITICAL**. Publicly accessible. |
| `/analytics/global` | GET | ❌ **NO** | Aggregated stats | 🚨 **CRITICAL**. Exposes global business metrics. |
| `/analytics/{agent_id}` | GET | ❌ **NO** | Time series | 🚨 **CRITICAL**. |

### Client Management (Admin)
| Endpoint | Method | Auth Required | Notes |
|----------|--------|---------------|-------|
| `/clients` | GET | ❌ **NO** | 🚨 **CRITICAL**. Dumps all client configs. |
| `/clients/{agent_id}` | GET | ❌ **NO** | 🚨 **CRITICAL**. Exposes client details. |
| `/clients/{agent_id}/update` | POST | ❌ **NO** | 🚨 **CRITICAL**. Allows unauthenticated updates. |
| `/clients/{agent_id}/test-call` | POST | ❌ **NO** | 🚨 **CRITICAL**. Allows unauthenticated call triggering (Cost/DoS risk). |

## 3. Dashboard Usage (`dashboard.js`)
The current `static/dashboard.js` (used by the Admin Dashboard) relies entirely on the **unsecured** endpoints listed above:
- `GET /clients`
- `POST /clients/add`
- `POST /clients/remove`
- `GET /logs/{agent_id}`
- `GET /clients/{agent_id}`
- `POST /clients/{agent_id}/update`
- `POST /clients/{agent_id}/test-call`

**Note**: The User Dashboard (`client_portal.html`) is currently a placeholder and does not utilize these endpoints yet.

## 4. Recommendations

### Immediate Actions (Security)
1.  **Secure Admin Endpoints**: Apply `Depends(get_current_admin_user)` to all `/clients/*`, `/logs/*`, and `/analytics/*` endpoints immediately.
2.  **Secure Test Call**: Apply strict auth to `/clients/{agent_id}/test-call`.

### For Frontend (User Dashboard)
1.  **Enhance `/me`**:
    - Add `is_active` (boolean).
    - Add `email` (string).
    - Add `subscription_state` (optional, or rely on `/subscription/status`).

    *Proposed Payload:*
    ```json
    {
      "id": 123,
      "username": "user",
      "email": "user@example.com",
      "role": "client",
      "studio_name": "My Studio",
      "is_active": true
    }
    ```

2.  **Create User-Scoped Log Endpoint**:
    - Instead of `/logs/{agent_id}/list` (which requires knowing agent_id and is currently insecure), create:
      - `GET /api/logs`: Automatically looks up the `agent_id` associated with the `current_user`.
      - Ensures users can only see their own logs.

3.  **Consolidated Status Endpoint (Optional)**:
    - To reduce round trips, consider a `/api/status` that returns both user info and subscription status.

## 5. Summary
The current API surface has significant security gaps in the admin/reporting endpoints. The `/me` endpoint is safe but lacks data needed for the frontend. The subscription endpoints are secure and well-structured.
