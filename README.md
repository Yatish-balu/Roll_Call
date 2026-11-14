# RollCall AI — Intelligent Attendance Verification & Analytics Platform

RollCall AI is a multi-modal attendance aggregation, validation, and analytics platform built for modern academic institutions and training organizations. It ingests CSV rosters and photographs of paper attendance sheets, reconciles student attendance against institutional constraints, and produces real-time summaries, room-wise rosters, defaulter tracking (<75%), and institutional audit reports.

Designed as a modern full-stack application, RollCall AI couples a high-performance **Python/FastAPI** backend with a responsive **React + Vite + Tailwind CSS** frontend, four-state attendance modeling, cryptographic Bearer JWT authentication with Role-Based Access Control (RBAC), and a deterministic **AI Tool-Calling Agent** with human-in-the-loop confirmation guardrails.

---

## Key Capabilities

- **Interactive AI Attendance Assistant**: Ask questions in natural language, query student rosters, check room allocations, identify attendance defaulters, and initiate attendance modifications with explicit user confirmation.
- **Multi-Modal Attendance Ingestion**: Ingest CSV spreadsheets and attendance sheet photos with optical character recognition (OCR) and vision extraction.
- **Four-State Attendance Model**: Distinguishes verified presence (`PRESENT`) and absence (`ABSENT`) from incomplete data (`PENDING`) and low-confidence/ambiguous marks (`UNREVIEWED`).
- **Defaulter Analytics Engine**: Real-time calculation of defaulters (<75%) and computation of the exact number of additional classes needed to reach eligibility.
- **Cryptographic Security & RBAC**: Tiered roles (`ADMIN`, `FACULTY`, `VIEWER`), hash-chained audit logging, sliding-window rate limiting, and strict input validation.
- **Enterprise Database Layer**: Primary Supabase PostgreSQL backend with connection pooling and SSL, plus in-memory/SQLite testing isolation.

---

## Database Architecture (Supabase-Only)

- **Supabase PostgreSQL is the primary runtime backend**: `DB_BACKEND` defaults to `supabase`; there is no automatic SQLite fallback in production. A missing `DATABASE_URL_SYNC` or an unreachable database is a hard startup blocker.
- **Connectivity verification**: The application performs an authoritative `SELECT 1` connectivity check upon every server startup.
- **SSL enforcement**: PostgreSQL connections require SSL (`sslmode=require` for psycopg, `ssl=require` for asyncpg).
- **Fallback Room Provisioning**: Automatically registers and maintains an `UNALLOCATED` fallback room in the database so sessions created without pre-assigned classrooms can be marked and reconciled without foreign-key errors.
- **Testing Isolation**: SQLite code paths are reserved for fast, isolated test runs when `DB_BACKEND=sqlite` is explicitly configured.

---

## Monorepo Project Structure

```text
Roll_Call/
├── backend/                                   # Python FastAPI Backend API & Services
│   ├── app/                                   # Application core package
│   │   ├── main.py                            # FastAPI entrypoint, lifespan startup, CORS, exception handlers
│   │   ├── config.py                          # Application settings, thresholds & environment variables
│   │   ├── dependencies.py                    # Database dependency injection (get_db)
│   │   ├── agent/                             # Attendance AI Agent Framework
│   │   │   ├── legacy_agent.py                # AttendanceAgent core orchestrator & conversation loop
│   │   │   ├── orchestrator.py                # LLM Tool-Calling orchestrator
│   │   │   ├── provider.py                    # Multi-provider LLM connector (Gemini / fallback)
│   │   │   ├── guardrails.py                  # Safety boundaries & query guardrails
│   │   │   ├── audit.py                       # AI action auditing & hash tracking
│   │   │   └── tools/                         # Agent tools (attendance, timetable, profile, database)
│   │   ├── auth/                              # Authentication & Authorization
│   │   │   ├── dependencies.py                # get_current_user, require_roles (ADMIN, FACULTY, VIEWER)
│   │   │   ├── jwt.py                         # Cryptographic JWT verification & claims validation
│   │   │   ├── rate_limiter.py                # In-memory sliding-window rate limiter
│   │   │   └── roles.py                       # Role hierarchy & permission evaluation
│   │   ├── db/                                # Database & ORM layer
│   │   │   ├── base.py                        # SQLAlchemy DeclarativeBase
│   │   │   ├── connection.py                  # PostgreSQL engine & connection pool management
│   │   │   ├── crud.py                        # CRUD operations (Students, Rooms, Sessions, Attendance)
│   │   │   └── models.py                      # SQLAlchemy ORM models (AuditLog, Student, Room, Session, etc.)
│   │   ├── routers/                           # FastAPI API v1 Endpoints
│   │   │   ├── admin.py                       # System administration & audit log inspection
│   │   │   ├── agent.py                       # /api/v1/agent (Chat, file upload, confirm mutations)
│   │   │   ├── analytics.py                   # /api/v1/analytics (Session, date & institutional metrics)
│   │   │   ├── attendance.py                  # /api/v1/attendance (Rosters, bulk updates, reconciliation)
│   │   │   ├── auth.py                        # /api/v1/auth (Login, logout, session verification)
│   │   │   ├── calendar.py                    # /api/v1/calendar (Academic calendar & schedule slots)
│   │   │   ├── defaulters.py                  # /api/v1/defaulters (Attendance defaulters & recovery)
│   │   │   ├── reports.py                     # /api/v1/reports (Student attendance & institutional reports)
│   │   │   ├── rooms.py                       # /api/v1/rooms (Classroom & laboratory master data)
│   │   │   ├── sessions.py                    # /api/v1/sessions (Session listing, creation, and details)
│   │   │   ├── students.py                    # /api/v1/students (Student records, search & pagination)
│   │   │   └── timetable.py                   # /api/v1/timetable (Timetable allocations & slots)
│   │   ├── schemas/                           # Pydantic v2 request/response schemas
│   │   ├── security/                          # Advanced security controls
│   │   │   ├── ai_input.py                    # Prompt injection detection & sanitization
│   │   │   ├── headers.py                     # Strict HTTP security headers (CSP, HSTS, etc.)
│   │   │   ├── uploads.py                     # Magic-byte validation & upload file size limits
│   │   │   └── rate_limit.py                  # Shared Redis / database rate-limiting
│   │   └── services/                          # Domain services
│   │       ├── attendance_edit.py             # Pending attendance edit service
│   │       ├── image_pipeline.py              # Photo OCR & vision processing
│   │       ├── session_initialization.py      # Timetable-driven daily session initialization
│   │       └── student_pdf.py                 # Student attendance PDF report generator
│   ├── tools/                                 # Deterministic attendance tools
│   │   ├── query_tool.py                      # Read-only SQL inspection with strict AST validation
│   │   ├── summary_tool.py                    # Four-state metrics aggregation
│   │   ├── defaulter_tool.py                  # Defaulter math & classes-needed calculation
│   │   ├── read_photo_tool.py                 # Vision / OCR extraction pipeline
│   │   ├── read_csv_tool.py                   # CSV normalization & validation
│   │   └── export_tool.py                     # Excel & formatted data export
│   ├── tests/                                 # Pytest test suite (870+ automated tests)
│   ├── alembic/                               # Alembic migration scripts
│   ├── scripts/                               # Seeding & evaluation utilities
│   │   ├── seed_users.py                      # Idempotent user account seed script
│   │   ├── seed_demo.py                       # Demonstration data seeder
│   │   ├── sync.py                            # Database synchronization utility
│   │   └── evaluate_agent.py                  # 15-scenario agent benchmark evaluator
│   ├── requirements.txt                       # Backend Python dependencies
│   └── pytest.ini                             # Pytest configuration
│
├── frontend-react/                            # Modern React + Vite Web Client
│   ├── src/
│   │   ├── components/                        # Layout (AppShell, Header, Sidebar) & Auth guards
│   │   ├── features/                          # Feature views & modular components
│   │   │   ├── dashboard/                     # Institutional dashboard, stats, & recent sessions
│   │   │   ├── assistant/                     # Interactive AI Attendance Assistant drawer
│   │   │   ├── attendance/                    # Session attendance verification & quick-toggle roster
│   │   │   ├── defaulters/                    # Real-time defaulter analytics (<75%) & recovery list
│   │   │   ├── timetable/                     # Weekly academic timetable view
│   │   │   ├── calendar/                      # Academic calendar view
│   │   │   ├── sessions/                      # Session management & filtering
│   │   │   ├── students/                      # Student roster master view
│   │   │   ├── rooms/                         # Room allocations & vacancy view
│   │   │   ├── reports/                       # Report generation & exports
│   │   │   └── audit/                         # Cryptographic audit log viewer
│   │   ├── services/api/                      # Typed API clients (Axios/Fetch with JWT interceptors)
│   │   ├── context/                           # Auth & application state context
│   │   └── hooks/                             # Custom React hooks (useAuth, useBackendHealth)
│   ├── package.json                           # Frontend NPM dependencies
│   ├── tailwind.config.js                     # Tailwind CSS styling configuration
│   └── vite.config.ts                         # Vite build & proxy configuration
│
├── data/                                      # Reference data & sample assets
│   ├── test1.csv                              # Sample attendance CSV dataset
│   ├── demo/                                  # Demonstration sample datasets
│   └── photos/                                # Sample attendance sheet photos for OCR testing
│
├── deploy/                                    # Deployment configurations (Nginx, Caddy, backups)
├── reports/                                   # Audit reports & benchmark evaluations
├── .env.example                               # Root environment configuration template
└── README.md                                  # Project documentation
```

---

## Core System Architecture & Features

### 1. Interactive AI Assistant with Confirmation Guardrails
- Natural language questions about student attendance, sessions, and defaulters.
- Read-only queries execute instantly via deterministic SQL tools.
- Mutation intents (e.g. creating sessions, updating attendance marks, changing profile details) produce structured confirmation cards with explicit details (`[Proceed]` / `[Cancel]`). Mutations are only executed after user approval.

### 2. Four-State Attendance Model
- **`PRESENT`**: Student confirmed present.
- **`ABSENT`**: Student confirmed absent.
- **`PENDING`**: Unverified roster entries or missing attendance marks.
- **`UNREVIEWED`**: Ambiguous marks, low-confidence OCR results, or illegible photos requiring manual review.
- Attendance percentage formula: `PRESENT / (PRESENT + ABSENT) * 100`. Unverified marks are never forced into binary assumptions.

### 3. Role-Based Access Control (RBAC)
- **`ADMIN`**: Full administrative access across all master data, audit logs, system configurations, and record management.
- **`FACULTY`**: Roster verification, photo/CSV attendance uploads, attendance reconciliation, and AI assistant interaction.
- **`VIEWER`**: Read-only access to master data, attendance summaries, and analytics.

### 4. Advanced Security Controls
- Cryptographic Bearer JWT verification (HS256/RS256, expiration check, issuer/audience validation).
- Privilege escalation defense: User-editable metadata is never trusted for elevated roles; only server-controlled claims grant privileges.
- Sliding-window rate limiting on all resource-intensive endpoints (`/agent/chat`, `/agent/process-file`, `/reports/*`).
- File upload security: Streaming 10 MB limit enforcement, executable binary signature filtering (`MZ`, `ELF`), null-byte checks, and image magic-byte verification.

---

## Getting Started

### Prerequisites

- **Python 3.10+** (Python 3.13 tested)
- **Node.js 18+** & **npm**
- **Git**

---

### 1. Environment Configuration

Copy the template to create `.env` in the repository root:

```bash
cp .env.example .env
```

Ensure the key variables are configured:
```dotenv
APP_ENV=development
DB_BACKEND=supabase
DATABASE_URL_SYNC=postgresql://postgres.xxx:[PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require
JWT_SECRET_KEY=your-secure-32-character-secret-key
ADMIN_KEY=your-admin-master-key
GEMINI_API_KEY=your-optional-gemini-api-key
```

---

### 2. Backend Setup & Startup

1. **Activate Python Virtual Environment:**
   ```bash
   # Windows (PowerShell)
   cd backend
   python -m venv venv
   .\venv\Scripts\Activate.ps1

   # Linux / macOS
   cd backend
   python3 -m venv venv
   source venv/bin/activate
   ```

2. **Install Dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Database Migrations & Initial Seeding (if starting fresh):**
   ```bash
   alembic upgrade head
   python -m scripts.seed_users
   ```

4. **Start the FastAPI Backend Server:**
   ```bash
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

   - **Health Check:** [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
   - **Interactive API Docs (Swagger):** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
   - **Alternative Docs (ReDoc):** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

### 3. Frontend Setup & Startup

1. **Navigate to the frontend directory:**
   ```bash
   cd frontend-react
   ```

2. **Install NPM dependencies:**
   ```bash
   npm install
   ```

3. **Start the Vite Development Server:**
   ```bash
   npm run dev
   ```

4. **Open the Application:**
   Visit [http://127.0.0.1:5173](http://127.0.0.1:5173) in your browser.

---

## Running the Automated Test Suite

The test suite contains over 870 automated tests covering unit logic, RBAC security, API contracts, attendance reconciliation, and agent orchestration.

Run the tests from `backend/`:

```bash
cd backend
pytest -v
```

To run targeted test suites:
```bash
# Attendance API & session verification
pytest tests/test_attendance_api.py -v

# Agent orchestration & teacher queries
pytest tests/test_agent_teacher_queries.py -v

# Security regression & RBAC enforcement
pytest tests/test_security_regression.py -v
```

---

## Security & Operations

- **Dependency Security Audit**: Run dependency scans via `scripts/security-scan.ps1`.
- **Database Backup**: Automated backup scripts are available in `deploy/backup/backup.ps1`.
- **Reverse Proxy**: Production Nginx and Caddy configuration templates with security headers live in `deploy/`.

---

## Implementation Status

| Component | Status | Technology |
| :--- | :---: | :--- |
| **FastAPI Backend API** | Implemented | FastAPI, Pydantic v2, Python 3.13 |
| **React Web Frontend** | Implemented | React 19, Vite, Tailwind CSS, Lucide Icons |
| **Authentication & RBAC** | Implemented | Cryptographic Bearer JWT, Supabase claims |
| **Database Architecture** | Implemented | Supabase PostgreSQL + Connection Pooling + SSL |
| **AI Tool-Calling Agent** | Implemented | Multi-Provider Agent with Human Confirmation Guardrails |
| **Multi-Modal OCR Ingestion**| Implemented | Image pipeline + CSV Normalization |
| **Defaulter Analytics** | Implemented | Real-time threshold calculation & recovery metrics |
| **Automated Test Suite** | 870+ Passing | Pytest, TestClient, In-Memory Isolation |
| **Audit Log Hash Chaining** | Implemented | SHA-256 tamper-evident audit log trail |
