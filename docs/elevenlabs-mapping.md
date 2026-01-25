# ElevenLabs Webhook Mapping Feasibility Report

## 1. Database Schema Inspection
We inspected the Postgres schema (via SQLAlchemy models) and confirmed the following storage capabilities:

*   **Users:** Stored in `users` table.
*   **Agents:** Stored in `agents` table (`agent_id` string).
*   **Mapping:**
    *   `user_agent_access`: Many-to-Many link between `users` and `agents`.
    *   `agent_routing`: Explicit routing table linking `agent_id` (string) -> `user_id` and `phone_number_id`.
*   **Phone Numbers:** Stored in `phone_numbers` table (`e164`, `user_id`).
*   **Calls/Events:** Stored in `usage_events` (linked to subscription/user/agent).

## 2. Data Feasibility Findings

### A) Agent ID Storage
**Yes.** We store `agent_id` in both `agents` table and `agent_routing`.
*   `agents.agent_id`: The ElevenLabs Agent ID.
*   `agent_routing.agent_id`: Used for dynamic routing.

### B) Phone Number Storage
**Yes.** We store E.164 numbers in `phone_numbers`.
*   Webhook payload provides `to_number` / `caller_number`.
*   We can match incoming calls to `phone_numbers` table.

### C) Mapping Reliability
**High.** The system is designed to map `agent_id` to `User`.
*   **Primary Key:** `agent_id` from webhook matches `agent_routing.agent_id`.
*   **Secondary Key:** `to_number` from webhook matches `phone_numbers.e164`.

### D) Gaps & Unassigned Flow
*   If an `agent_id` is new (not in DB), the current system blocks execution ("unknown_agent").
*   If an agent exists but has no user ("orphaned_agent"), it blocks.
*   **Solution:** We need to capture these events instead of dropping them.

## 3. Feasibility Conclusion
*   **Can we reliably extract agent_id?** **YES**. It is present in the ElevenLabs webhook payload (`data.agent_id`).
*   **Can we reliably derive inbound phone_number?** **YES**. It is present in metadata (`phone_call.number` or `to_number`).
*   **Can we reliably identify the user?** **YES**, assuming the Admin has configured the `AgentRouting` or `Agent` assignment.
*   **Action Plan:** Implement a "Safe Unassigned Flow" to catch events where configuration is missing, ensuring no data loss.

## 4. Implementation Plan (Safe Unassigned Flow)
1.  **New Table:** `unassigned_events` to store raw payloads of unmatched calls.
2.  **Webhook Update:**
    *   Attempt resolution (Agent/Routing -> User).
    *   If fail: Insert into `unassigned_events`.
    *   Log structured warning.
    *   Return 200 OK (to prevent webhook retries on valid but unassigned events).
3.  **Admin UI:** Expose endpoint to list unassigned events for manual resolution.
