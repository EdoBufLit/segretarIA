# Phase 4A Implementation Plan: Postgres + Workers + Observability

This plan outlines the steps to refactor the application for production readiness by introducing a persistent SQL database (Postgres), an asynchronous worker queue (Redis/RQ), and enhanced observability.

## 1. Inventory & Analysis

- **Current DB**: SQLite (`app.db`).
- **Heavy Webhooks**:
    - `POST /elevenlabs/webhook`: Performs OpenAI transcription/analysis, SMTP email sending, and database metering synchronously.
- **Audit**: Currently logs to `admin_audit.log` (flat file).

## 2. Infrastructure Changes

### Dependencies
Update `requirements.txt` to include:
- `psycopg2-binary` (Postgres driver)
- `redis` (Redis client)
- `rq` (Redis Queue)
- `sentry-sdk` (Error monitoring)
- `structlog` (Structured JSON logging)

### Database Configuration (`db.py`)
- Modify `create_engine` to read `DATABASE_URL` from environment variables.
- Default to `sqlite:///./app.db` if not set (maintains dev compatibility).

## 3. Asynchronous Task Queue

### Worker Setup
- Create `worker.py`: Entry point to run the RQ worker process.
- Create `jobs.py`: Define standalone functions for heavy tasks:
    - `process_call_summary(transcript, agent_id)`
    - `send_call_email(to, subject, body)`
    - `meter_usage(agent_id, duration)`

### Refactor Webhooks (`app.py`)
- **ElevenLabs Webhook**:
    - Validate payload/signature (fast).
    - Enqueue `process_call_summary` and `meter_usage` jobs.
    - Return `200 OK` immediately.
- **Stripe Webhook**:
    - Keep synchronous for now (fast DB updates), or optionally enqueue if latency increases.

## 4. Observability & Audit

### Logging (`app.py` / `logging_config.py`)
- Configure `structlog` to output logs as JSON for production.
- Initialize `sentry_sdk` in `app.py` startup event if `SENTRY_DSN` is present.

### Persistent Audit Trail (`models.py`, `audit_logger.py`)
- Add `AuditEvent` model to `models.py`:
    - `id`, `timestamp`, `admin_username`, `action`, `target`, `details`.
- Update `audit_logger.py` to write to the `AuditEvent` table in addition to/instead of the file.

## 5. Implementation Steps (Order of Operations)

1.  **Dependencies**: Update `requirements.txt`.
2.  **Models**: Add `AuditEvent` to `models.py`.
3.  **DB Config**: Update `db.py` to support Postgres.
4.  **Jobs**: Create `jobs.py` and move logic from `app.py`.
5.  **Worker**: Create `worker.py`.
6.  **Webhooks**: Update `app.py` to enqueue jobs.
7.  **Audit**: Update `audit_logger.py` to persist to DB.
8.  **Observability**: Add Sentry/Structlog config to `app.py`.

## 6. Risks & Rollback

- **Data Migration**: Switching DB engines requires migrating data. **Risk**: Data loss. **Mitigation**: Use `pgloader` or Alembic for schema migration; verify backups before switch.
- **Queue Failure**: If Redis is down, jobs fail. **Risk**: Lost emails/metering. **Mitigation**: Use `rq` error handling/retries; monitor Redis.
- **Rollback**:
    - Revert code changes to previous commit.
    - Point `DATABASE_URL` back to SQLite file.
    - Disable worker process.
