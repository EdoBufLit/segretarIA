#!/bin/bash
set -e

# Run migrations
echo "Running database migrations..."
alembic upgrade heads

# Start the application
echo "Starting application..."
exec uvicorn app:app --host 0.0.0.0 --port 8000
