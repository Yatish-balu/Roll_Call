# Form-B Exam Control & AI Attendance Verification Platform (RollCall AI)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18.3+-61DAFB.svg?style=flat&logo=react)](https://react.dev)
[![Gemini Vision AI](https://img.shields.io/badge/Google_Gemini-Vision_AI-4285F4.svg?style=flat&logo=google)](https://ai.google.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Supabase-336791.svg?style=flat&logo=postgresql)](https://supabase.com)
[![Security Audited](https://img.shields.io/badge/Security-RBAC_%26_Tamper_Proof-success.svg?style=flat)](#enterprise-security--integrity-controls)

---

## Executive Overview

**RollCall AI: Form-B Exam Control System** is an enterprise-grade academic examination attendance aggregation, optical seating verification, and invigilation governance platform. Engineered specifically for autonomous collegiate and university examination centers (following the official **Dayananda Sagar College of Engineering (DSCE) / Visvesvaraya Technological University (VTU) Form-B** standard), it eliminates manual paper tally errors, stops exam room impersonation, prevents invigilator-student collusion, and cryptographically seals examination records.

The system combines **Google Gemini Vision AI** for automated multi-exam column OCR, a deterministic **Tool-Calling AI Agent** for invigilation commands, and a **zero-trust, append-only security architecture** to oversee high-stakes examination sessions in real time.

---

## 🏛️ What is Form-B in Examination Governance?

In collegiate and autonomous university exam environments:
- **Form-B** is the official **Examination Hall Attendance and Seating Allocation Roster**.
- A single physical Form-B document governs a specific exam hall (e.g., `CDS10-105`) and contains pre-printed student USNs, candidate names, and up to **5 multi-exam columns** across different dates and session slots (Forenoon **FN** vs. Afternoon **AN**).
- During the examination, the invigilator verifies candidate hall tickets, compares physical likeness, and obtains signatures in the active exam column.
- At the bottom of each column is the **Official Verification Tally**:
  - `Total Registered Candidates`
  - `No. of Candidates Present`
  - `No. of Candidates Absent`
  - `Malpractice / Detained Count`
  - `Invigilator Name, Employee ID & Signature`
- Traditionally, paper Form-B records take hours to reconcile manually in the Chief Superintendent control room. RollCall AI digitizes and automates this entire lifecycle with vision AI, real-time audit locking, and instant absentees statement generation.

---

## System Architecture

```mermaid
flowchart TD
    subgraph ClientLayer["Frontend & Invigilator Client (React + Vite + Tailwind)"]
        UI_Dash["Exam Control Dashboard (/exams)"]
        UI_Camera["Mobile Photo Capture & OCR Scanner"]
        UI_Agent["AI Invigilation Assistant Chat"]
        UI_PDF["Printable Form-B & Absentees PDF Exporter"]
    end

    subgraph GatewayLayer["FastAPI Security & Gateway"]
        AuthMid["Bearer JWT & Session Verification"]
        RateLimiter["3-Strike Lockout Limiter (60s)"]
        JIT_Mask["Just-In-Time (JIT) Anti-Collusion Filter"]
        AuditChain["Append-Only SHA-256 Audit Logger"]
    end

    subgraph ServiceLayer["Core Domain Services"]
        VisionAI["Gemini Vision AI Engine (exam_vision.py)"]
        PDFGen["ReportLab Form-B Generator (exam_pdf.py)"]
        CutoffMon["Automated 45-Min Cutoff Monitor"]
        AgentCore["AttendanceAgent Tool Orchestrator"]
    end

    subgraph StorageLayer["Data & Persistence (Supabase PostgreSQL / SQLite)"]
        DB_Exams["Exams & Room Allocations Table"]
        DB_Seating["Exam Seating & Signatures (Form-B)"]
        DB_Audit["Cryptographic Audit Trail"]
        DB_Chat["User Chat Threads (Cross-Device Synced)"]
    end

    UI_Camera -->|Upload Form-B Photo| AuthMid
    UI_Agent -->|Natural Language Command| AuthMid
    UI_Dash -->|Fetch Seating & Roster| JIT_Mask

    AuthMid --> RateLimiter --> JIT_Mask
    JIT_Mask --> ServiceLayer
    VisionAI -->|Extract Signatures & Tally| DB_Seating
    VisionAI --> AuditChain
    CutoffMon -->|Enforce LATE_LOCKED| DB_Exams
    PDFGen --> UI_PDF
    AgentCore --> DB_Exams
    AuditChain --> DB_Audit
```

---

## How AI Initiates and Drives Form-B

RollCall AI employs artificial intelligence not as a passive search tool, but as an active, deterministic agent orchestrating every phase of Form-B processing:

### 1. Multi-Exam Column Isolation (Gemini Vision AI)
Physical Form-B sheets contain multiple exams side-by-side. Traditional OCR fails because it cannot distinguish today's exam column from yesterday's.
- **Context-Guided Disambiguation**: The system injects target metadata (`target_subject_code`, `target_date`, `target_session_slot` [FN/AN], `target_room_no`) into the Gemini Vision OCR pipeline.
- **Visual Column Pinpointing**: The Vision AI scans table headers across columns (e.g. `24-08-2026 / 22CY51`), locates the exact matching column, and extracts marks strictly within that column's spatial coordinates.
- **Handwritten Signature Recognition**:
  - Valid ink signature / signed initials $\rightarrow$ marked as `PRESENT`.
  - Stamped `Ab`, `AB`, crossed-out cell, or empty/blank box $\rightarrow$ marked as `ABSENT`.
  - Obscured, shadowed, or ambiguous entries $\rightarrow$ marked as `UNREVIEWED` for explicit invigilator verification.
- **Bottom Tally Verification**: The model extracts the invigilator's written bottom summary (`Present: 32`, `Absent: 2`) and cross-verifies that `Total = Present + Absent`. If a discrepancy is detected, the AI flags a reconciliation alert before submission.

### 2. Conversational Exam Hall Assistant (Natural Language Invigilation)
The embedded `AttendanceAgent` provides real-time exam administration via voice and text:
- **Instant Room Lookup**: *"What is the Form-B status for Room CDS10-105?"*
- **Absentees Aggregation**: *"Show me all absentees across 5th Semester Cyber Security exams right now."*
- **Cutoff Tracking**: *"Which exam rooms have pending Form-B submissions nearing the 45-minute cutoff?"*
- **Automated Routing**: If a teacher uploads a photo of an exam sheet into the regular chat, the AI automatically detects the Form-B document layout, extracts exam metadata, and offers one-click redirection to the official Exam Control module.

### 3. Automated Seating Allocation & Room Balancing
- Automatically ingests enrolled students, sorts by USN and branch, and distributes candidates across registered exam rooms according to configured room capacities (e.g., 30 to 40 candidates per hall).
- Prevents adjacent seating of candidates appearing for the same subject code to minimize cheating opportunities.

---

## 🔒 Enterprise Security & Integrity Controls

The Form-B module is hardened against academic fraud, tampering, and denial-of-service:

| Security Feature | Implementation Mechanism | Purpose & Threat Defense |
| :--- | :--- | :--- |
| **Just-In-Time (JIT) Anti-Collusion** | Dynamic masking (`_is_jit_masked`) | Invigilator exam room assignments remain masked until **15 minutes** before exam start. Prevents advance invigilator-student collusion. |
| **Strict 45-Min Cutoff Window** | Auto-transition to `LATE_LOCKED` | Form-B must be submitted within 45 minutes of exam start. Unsubmitted sheets are locked to prevent post-exam grade tampering. |
| **Append-Only Tamper-Proof Audit Lock** | Cryptographic SHA-256 Hash Chain | Every attendance mark modification, scan, and submission generates an append-only audit entry. Submitting permanently seals the record (`SUBMITTED`). |
| **Admin Override Protocol** | Constant-time HMAC Admin Key | Once a room is `SUBMITTED` or `LATE_LOCKED`, invigilators cannot edit it. Unlocking strictly requires administrator override (`admin-override`) with audit logging. |
| **3-Attempt Login Rate Limiter** | Database/Redis Sliding Limiter | Max **3 failed logins per minute** triggers a temporary **60-second block** with `Retry-After: 60` HTTP 429. No permanent account lockout. Passwords are compared exactly - whitespace/punctuation variants are rejected. |
| **OTP Password Reset** | Headless email delivery | `POST /password/forgot` mails a 6-digit OTP (10-minute TTL); `verify-otp` consumes it once and returns a reset token or sets a new bcrypt password and revokes all sessions. In development only, the code is echoed to aid testing - production never returns it. |
| **Centralized Profile Governance** | Backend RBAC Restriction | Faculty names and usernames are locked centrally. Neither teachers nor the AI assistant can alter user identities; only `ADMIN` can update faculty names. |
| **Magic-Byte & Upload Gatekeeper** | Binary header validation | Verifies uploaded files via magic bytes (`%PDF`, `\xFF\xD8\xFF`, `\x89PNG`) and optical quality gates (Laplacian variance sharpness $\ge 15.0$). |
| **Cross-Device Chat Isolation** | Server-backed DB thread persistence | Real-time chat sync across multiple devices and browsers with concurrency locks and per-account isolation. |

---

## ⏱️ Step-by-Step Form-B Exam Lifecycle

```mermaid
sequenceDiagram
    autonumber
    actor Admin as Chief Superintendent (Admin)
    actor Invigilator as Hall Invigilator (Faculty)
    participant System as RollCall AI Backend
    participant VisionAI as Gemini Vision Engine
    participant DB as Supabase PostgreSQL

    Admin->>System: 1. Create Exam & Generate Seating Allocations
    System->>DB: Persist exam sitting & room assignments
    Admin->>System: 2. Download Printable Blank Form-B PDF
    System-->>Admin: Generates official DSCE Form-B PDF with student USNs
    
    Note over Invigilator,System: T - 15 Minutes: JIT Reveal Window
    Invigilator->>System: 3. View Room Assignment
    System-->>Invigilator: Unmasks Room (e.g. CDS10-105)
    
    Note over Invigilator: Exam Starts (Physical Verification)
    Invigilator->>Invigilator: Collects student signatures on paper Form-B
    
    Invigilator->>System: 4. Snap and upload photo of completed Form-B
    System->>VisionAI: 5. Analyze multi-exam column & signatures
    VisionAI-->>System: Returns student states (PRESENT/ABSENT) + bottom tally
    System-->>Invigilator: Displays parsed marks for visual confirmation
    
    alt Submitted within 45 mins
        Invigilator->>System: 6. Confirm & Submit Form-B
        System->>DB: Status -> SUBMITTED (Cryptographically Sealed)
        System-->>Admin: Real-time update in Chief Superintendent Dashboard
    else Past 45 mins cutoff
        System->>DB: Status -> LATE_LOCKED
        Invigilator->>Admin: Requests manual review
        Admin->>System: 7. Issues Admin Override with reason
        System->>DB: Unlocked with full audit log entry
    end
    
    Admin->>System: 8. Export Consolidated Absentees Statement PDF
    System-->>Admin: Official PDF ready for Exam Center submission
```

---

## Key Form-B API Endpoints

All examination endpoints are protected with Bearer JWT tokens and strict RBAC (`/api/v1/exams`):

### 1. Examination Sitting & Room Management
- `POST /api/v1/exams` — Create a new examination sitting (Subject code, date, start time, cutoff minutes, duration).
- `GET /api/v1/exams` — List all active and scheduled examinations with JIT room masking.
- `GET /api/v1/exams/{exam_id}` — Retrieve examination sitting details, allocated rooms, and real-time room statuses.
- `POST /api/v1/exams/{exam_id}/allocate-rooms` — Automatically assign rooms, allocate candidates, and configure invigilators.

### 2. Form-B Seating, Vision Scan & Submission
- `GET /api/v1/exams/{exam_id}/rooms/{room_no}/roster` — Retrieve the Form-B student roster for an assigned room.
- `PUT /api/v1/exams/{exam_id}/rooms/{room_no}/attendance` — Manually toggle student attendance states (`PRESENT`, `ABSENT`, `UNREVIEWED`).
- `POST /api/v1/exams/{exam_id}/rooms/{room_no}/scan-photo` — Upload a photo of the physical Form-B for Gemini Vision AI signature extraction and bottom tally reconciliation.
- `POST /api/v1/exams/{exam_id}/rooms/{room_no}/submit` — Permanently submit and seal Form-B with SHA-256 audit locking.
- `POST /api/v1/exams/{exam_id}/rooms/{room_no}/admin-override` — Administrator override to unlock a `SUBMITTED` or `LATE_LOCKED` room.

### 3. Official PDF Exports
- `GET /api/v1/exams/{exam_id}/rooms/{room_no}/sign-sheet-pdf` — Download the official printable blank Form-B PDF with institution headers, room number, USNs, and signature boxes.
- `GET /api/v1/exams/{exam_id}/absentees-statement-pdf` — Download the official consolidated Absentees Statement PDF for the Exam Control Center.

---

## 🗄️ Database Schema for Form-B

```mermaid
erDiagram
    exams ||--o{ room_assignments : has
    room_assignments ||--o{ exam_seating : contains
    users ||--o{ room_assignments : invigilates
    users ||--o{ audit_logs : logs

    exams {
        string exam_id PK
        string exam_name
        string subject_code
        string date
        string start_time
        string end_time
        int cutoff_minutes
        string created_at
    }

    room_assignments {
        string assignment_id PK
        string exam_id FK
        string room_no
        string invigilator_id FK
        string status "DRAFT | IN_PROGRESS | SUBMITTED | LATE_LOCKED"
        int total_students
        int present_count
        int absent_count
        string submitted_at
        string submitted_by
    }

    exam_seating {
        string seating_id PK
        string exam_id FK
        string room_no
        string usn FK
        string student_name
        string branch
        int seat_number
        string attendance_status "PRESENT | ABSENT | UNREVIEWED"
        string signature_detected
        string marked_at
    }

    audit_logs {
        string log_id PK
        string actor_id
        string action "FORM_B_SUBMIT | ADMIN_OVERRIDE | SCAN"
        string entity_type "room_assignment"
        string entity_id
        string prev_hash
        string current_hash
        string timestamp
    }
```

---

## 🚀 Quickstart & Verification

### 1. Environment Setup

Ensure your backend `.env` configuration contains:
```env
# Server & Environment
APP_ENV=development
SECRET_KEY=your-production-256-bit-secret-key
ADMIN_KEY=your-secure-admin-secret-key

# Database Connection (Supabase PostgreSQL)
DATABASE_URL_SYNC=postgresql://postgres.xxx:pass@aws-0-ap-south-1.pooler.supabase.com:6543/postgres?sslmode=require
DB_BACKEND=supabase

# Google Gemini Vision AI
GEMINI_API_KEY=your-gemini-api-key

# Security & Rate Limiting
SEC_LOGIN_LIMIT=3
SEC_LOGIN_WINDOW_SECONDS=60
SEC_LOGIN_LOCKOUT_SECONDS=60

# Seed credentials are required (no hardcoded defaults in source)
SEED_ADMIN_PASSWORD=...
SEED_FACULTY_1_PASSWORD=...
SEED_FACULTY_2_PASSWORD=...
SEED_FACULTY_3_PASSWORD=...
SEED_PASSWORD_ADMIN_ROOT=...
SEED_PASSWORD_TEACHER_CN=...
SEED_PASSWORD_TEACHER_ML=...
SEED_PASSWORD_TEACHER_DB=...

# Vision OCR & photo quality gate
VISION_TIMEOUT_MS=20000
IMAGE_QUALITY_MAX_BRIGHTNESS=250.0
ENABLE_LEGACY_API_PREFIX=true
```

> Seeding fails fast when the `SEED_*` variables are missing. See
> `docs/SECURITY_OPERATIONS.md` §8 for the secret-rotation runbook.

### 2. Run Backend & Frontend

```bash
# Terminal 1: Launch FastAPI Backend
cd Roll_Call/backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2: Launch React Frontend
cd Roll_Call/frontend-react
npm install
npm run dev
```

### 3. Run Automated Form-B Test Suite

```bash
cd Roll_Call/backend
# Execute the full Form-B and security test suite (972 tests)
pytest tests -q
```

Recent fixes worth knowing:
- Tab switches no longer refetch all data (persistent shell + 60s GET cache).
- Analytics and exam summaries use single scoped queries instead of N+1 loops; `docs/database-query-reduction.md`.
- Vision calls are time-bounded and overexposed sharp photos are auto-normalised; `docs/image-upload-performance.md`.
- Natural-language session dates understand weekdays ("on friday") and extract subject/instructor/room from chat prompts.

---

## 📜 Compliance & Institutional Integrity

RollCall AI is engineered in strict compliance with:
- **Autonomous College Examination Manuals (DSCE / VTU Regulations)**.
- **Append-only non-repudiation audit standards**.
- **Role separation guidelines** (Invigilators cannot alter rosters after submission; Chief Superintendent retains administrative override authority).
- **FERPA & Institutional Privacy Standards** (student data never utilized for model training; biometric signatures evaluated ephemerally in RAM).

---
*Maintained by the RollCall AI Engineering Team &copy; 2026 Dayananda Sagar College of Engineering.*
