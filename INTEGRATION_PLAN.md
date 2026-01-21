# Integration Branch Plan

## 1. Branch Inventory

### Local Branches
- `jules-5280578167186710350-a987767f`: Current working branch (QA checks).
- `landing-page-11717745976152594883`: Landing Page Implementation.

### Remote Feature Branches
1.  **`origin/landing-page-11717745976152594883`**
    - **Feature:** Landing Page.
    - **Description:** Adds modern marketing landing page (`templates/index.html`), mobile menu, and responsive design.

2.  **`origin/feature/stripe-integration-14308306324681726244`**
    - **Feature:** Phase 3 (Stripe).
    - **Description:** Complete Stripe integration (Checkout, Webhooks, Portal, Subscription Management). Includes QA tests.

3.  **`origin/rate-limit-middleware-3896987193650033929`**
    - **Feature:** Phase 2 (Admin & Security Backlog).
    - **Description:** comprehensive branch containing:
        - Admin Password Reset (`POST /admin/users/{user_id}/reset-password`).
        - Rate Limiting Middleware.
        - Log & Minutes Export Logic.
        - User Suspension Toggle.
        - Backup Retention Policy.

4.  **`origin/rate-limit-sensitive-endpoints-3463296538063082568`**
    - **Feature:** Phase 2 (Exports Fix).
    - **Description:** Finalizes CSV exports with path traversal fixes and sync mode. Likely depends on or supersedes parts of the middleware branch.

5.  **`origin/block-suspended-users-1543456083889213456`**
    - **Feature:** Phase 2 (Enforcement).
    - **Description:** Blocks suspended clients from accessing services (Login, Webhook, Test Call). Adds `check_client_suspended` dependency.

6.  **`origin/feat/db-setup-11543017062117725203`**
    - **Feature:** Phase 2 (Deprovisioning).
    - **Description:** Phone number deprovisioning logic, `mailer.py` refactor, `deprovision_job.py`, and `PhoneNumber` model.

## 2. Integration Strategy

The following branches will be merged into the integration branch in this order (to minimize conflicts, putting foundational changes first):

1.  `origin/saas-db-refactor` (Base, if not already main)
2.  `origin/feat/db-setup-11543017062117725203` (DB Schema & Mailer)
3.  `origin/rate-limit-middleware-3896987193650033929` (Core Admin/Security features)
4.  `origin/rate-limit-sensitive-endpoints-3463296538063082568` (Export fixes)
5.  `origin/block-suspended-users-1543456083889213456` (Suspension Enforcement)
6.  `origin/feature/stripe-integration-14308306324681726244` (Stripe - Phase 3)
7.  `origin/landing-page-11717745976152594883` (Frontend)

## 3. Proposed Branch Name

**`integration-release-v1`**

## 4. Notes
- The `rate-limit-middleware` branch appears to implement features (Password Reset, Rate Limiting) that were marked as "Missing" in the recent QA pass. This confirms that the QA pass was likely run on a branch *prior* to merging these features. Merging this branch is critical to resolving the QA failures.
- The `block-suspended-users` branch resolves the "Enforcement" QA failures.
- The `landing-page` branch matches the "Landing Page" QA success.
