#!/usr/bin/env bash
# run_dev.sh — Start the RollCall AI backend in development mode.
#
# Usage: ./run_dev.sh
#
# Starts the FastAPI backend on http://127.0.0.1:8000
# with DB_BACKEND=sqlite for isolated local development.

set -euo pipefail

cd "$(dirname "$0")"

# Use the isolated test database for local dev
export DB_BACKEND=sqlite
export SQLITE_PATH="data/attendance.db"
export APP_ENV=development
export DEBUG=true

# JWT secret (development only — never commit real values)
if [ -z "${JWT_SECRET:-}" ]; then
  export JWT_SECRET="dev-secret-do-not-use-in-production-32chars"
fi

echo "==> Rolling back any stale migrations..."
# (Alembic migrations are managed separately; this script just starts the app.)

echo "==> Starting backend on http://127.0.0.1:8000..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
