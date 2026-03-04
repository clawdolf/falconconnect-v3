#!/bin/bash
set -e

# Run database migrations
alembic upgrade head

# Start the app
exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-10000}"
