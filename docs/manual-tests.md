# Manual test checklist

Use this checklist to validate admin seeding, registration, and role-based redirects.

## Admin seeding

1. Start with an empty database (e.g., remove `app.db` or use a fresh database URL).
2. Set environment variables (optional):
   - `ADMIN_USERNAME` (default: `admin`)
   - `ADMIN_PASSWORD` (default: `password123`)
   - `ADMIN_EMAIL` (default: `admin@example.com`)
3. Start the application.
4. Confirm that exactly one admin user exists with the configured username.
5. Restart the application and verify no duplicate admin users are created.

## Admin login

1. Navigate to `/login`.
2. Log in with the admin credentials from the environment.
3. Confirm the user is redirected to `/dashboard`.
4. Attempt to access `/client/dashboard` and confirm access is denied (403).

## Client registration

1. Navigate to `/register`.
2. Register a new user with a unique username/email and a password >= 8 characters.
3. Confirm the app redirects to `/login?registered=1` and shows the success message.
4. Log in with the newly created client credentials.
5. Confirm the user is redirected to `/client/dashboard` and sees the client dashboard placeholder.

## Client access restrictions

1. While logged in as the client, attempt to access `/dashboard` and verify access is denied (403).
2. Attempt to register another user with the same username or email and confirm the registration form shows the appropriate error message.
