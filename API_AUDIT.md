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
| `/logs/{agent_id}/list` | GET | ✅ Yes | Paginated logs | ✅ Protected via user RBAC. |
| `/logs/{agent_id}` | GET | ✅ Yes (Admin) | All logs | ✅ Admin-only. |
| `/analytics/global` | GET | ✅ Yes (Admin) | Aggregated stats | ✅ Admin-only. |
| `/analytics/{agent_id}` | GET | ✅ Yes (Admin) | Time series | ✅ Admin-only. |

### Agent Settings (Admin)
| Endpoint | Method | Auth Required | Notes |
|----------|--------|---------------|-------|
| `/api/admin/agent-users` | GET | ✅ Yes (Admin) | Mapping of agent_id -> user details. |
| `/api/admin/agent-settings/{agent_id}` | GET | ✅ Yes (Admin) | Read agent settings. |
| `/api/admin/agent-settings/{agent_id}` | PUT | ✅ Yes (Admin) | Update agent settings. |
| `/api/admin/agents/{agent_id}/test-call` | POST | ✅ Yes (Admin) | Admin-triggered test call. |

## 3. Dashboard Usage (`dashboard.js`)
The current Admin Dashboard relies on authenticated endpoints:
- `GET /api/admin/agent-users`
- `GET /api/admin/agent-settings/{agent_id}`
- `PUT /api/admin/agent-settings/{agent_id}`
- `POST /api/admin/agents/{agent_id}/test-call`
- `GET /logs/{agent_id}/list`

**Note**: The User Dashboard (`client_portal.html`) is currently a placeholder and does not utilize these endpoints yet.

## 4. Recommendations

### Immediate Actions (Security)
1.  **Ensure RBAC**: Keep admin-only protections on analytics and agent settings endpoints.
2.  **Keep Test Call Admin-Only**: `/api/admin/agents/{agent_id}/test-call` should remain restricted.

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
