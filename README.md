# RollCall AI

RollCall AI is a Python-based platform designed for attendance and roll-call data processing, automated validation, and reporting.

---

## Project Structure

```text
Roll_Call/
├── app/                  # FastAPI application and route definitions
│   ├── __init__.py
│   └── main.py           # Application entry point
├── tools/                # Utility modules and data processing helpers
│   └── __init__.py
├── data/                 # Data storage (git-ignored)
│   └── .gitkeep
├── tests/                # Test suite for pytest
│   ├── __init__.py
│   └── test_sample.py
├── docs/                 # Documentation and guides
│   └── README.md
├── .env.example          # Sample environment variables
├── .gitignore            # Git ignore configuration
├── requirements.txt      # Project dependencies
└── README.md             # Project documentation
```

---

## Tech Stack & Dependencies

- **FastAPI**: Modern, fast web framework for building APIs.
- **Uvicorn**: ASGI web server implementation.
- **Pandas**: High-performance data manipulation and analysis.
- **openpyxl**: Excel file read/write operations.
- **ReportLab**: PDF report generation.
- **pytest**: Test framework.
- **python-dotenv**: Environment variable management.

---

## Getting Started

### 1. Prerequisites
Ensure you have Python 3.10+ installed.

### 2. Create and Activate a Virtual Environment

**Windows (PowerShell):**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables
Copy `.env.example` to create your local `.env`:
```powershell
cp .env.example .env
```

---

## Running the Application

Start the local development server:
```bash
uvicorn app.main:app --reload --port 8000
```

Once running, access:
- **API Root**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
- **Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)
- **Interactive Swagger Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **ReDoc**: [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)

---

## Running Tests

Execute test suite using `pytest`:
```bash
pytest
```
