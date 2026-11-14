# RollCall AI — Backend Run Guide

## Quick start

```bash
# 1. Clone the repo
git clone <repo-url> Roll_Call
cd Roll_Call/backend

# 2. Create .env from .env.example (never commit real values)
cp .env.example .env
# Edit .env: set JWT_SECRET, DATABASE_URL_SYNC if using Supabase

# 3. Install dependencies
pip install -r requirements.txt

# 4. Seed demo data (optional but recommended)
python scripts/seed_demo.py

# 5. Start the backend
./run_dev.sh
# or: python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

The API is available at `http://127.0.0.1:8000`.
Interactive docs: `http://127.0.0.1:8000/docs`.

## Seeded demo users

| User ID | Role | Password | Purpose |
|---------|------|----------|---------|
| admin_root | ADMIN | admin_key_2026 | Full institutional access |
| teacher_cn | FACULTY | teacher_cn_pw | CN + OS subjects |
| teacher_ml | FACULTY | teacher_ml_pw | ML subject |
| teacher_db | FACULTY | teacher_db_pw | DB subject |

## CORS

The backend allows origins from `ALLOWED_ORIGINS` in `.env` (default `http://localhost:5173`).
Headers: `Authorization`, `Content-Type`. Methods: `GET`, `POST`, `PUT`, `DELETE`.

## Running tests

```bash
# Full suite
pytest

# Specific area
pytest tests/test_agent_guardrails.py tests/test_agent_audit.py -v
```

## Frontend

See `frontend-react/` for the React app. Point `VITE_API_BASE_URL` at `http://127.0.0.1:8000`
and set `VITE_USE_MOCK=false` to use the real backend.
