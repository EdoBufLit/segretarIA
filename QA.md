# QA Checklist: Billing, Emails, & Landing

This document outlines the verification steps for the critical paths of the Segreteria IA application.

## 1. Public Landing Page
- [ ] **Load**: Access homepage (`/`). Status 200.
- [ ] **Intro Overlay**: First visit shows "Automa AI" overlay. Reload hides it (sessionStorage).
- [ ] **Layout**: No horizontal scroll or broken sections. Dark theme consistent.
- [ ] **Content**: Terms like "Studio legale" replaced with inclusive business terms.

## 2. Pricing Display
- [ ] **Homepage**: "Piani Flessibili" section shows 3 cards (Starter/Pro/Business).
- [ ] **Dedicated Page**: `/billing/plans` matches homepage content.
- [ ] **Data Source**: Prices (29€/79€/199€) come from backend config, not hardcoded HTML.

## 3. Stripe Checkout Flow
- [ ] **Initiate**: Clicking "Acquista" (logged in) redirects to Stripe Checkout.
- [ ] **URL**: URL is valid (no "localhost" in production).
- [ ] **Cancel**: Clicking "Back" or "Cancel" on Stripe redirects to `HOMEPAGE/?billing=cancel`.
- [ ] **Success**: Completing payment redirects to `/dashboard?billing=success`.

## 4. Subscription Activation (Webhook)
- [ ] **Webhook**: `checkout.session.completed` event received at `/stripe/webhook`.
- [ ] **Database**: User subscription state updates to `active`.
- [ ] **Idempotency**: Retrying webhook does not create duplicate subscriptions.

## 5. Client Dashboard
- [ ] **Unpaid User**: Shows status "NON ATTIVO" / "SOSPESO". "ATTIVA ORA" button visible.
- [ ] **Paid User**: Shows status "ATTIVO". "ATTIVA ORA" button hidden.
- [ ] **Access**: Client cannot access Admin routes (e.g. `/admin/*`, `/api/admin/*`).

## 6. Emails (Notifications)
- [ ] **Lead Form**: Submitting homepage contact form sends email to `LEADS_EMAIL_TO` (or admin).
- [ ] **Payment Success**: Receiving successful payment webhook sends notification to `ADMIN_EMAIL`.
- [ ] **Format**: Emails contain relevant details (User email, Plan, Timestamp).

## 7. Smoke Test
Run `python verification/smoke_test.py` to verify endpoint availability.
