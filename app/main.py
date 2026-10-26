from fastapi import FastAPI
from dotenv import load_dotenv
import os

load_dotenv()

# AUDIT FIX (L-9): disable the interactive API docs and OpenAPI schema outside
# development. A production deployment must not serve /docs, /redoc or
# /openapi.json publicly - they disclose the full API surface.
_IS_DEV = os.getenv("APP_ENV", "development").strip().lower() in ("", "development", "dev")

app = FastAPI(
    title="RollCall AI",
    description="Automated roll call processing and reporting API",
    version="0.1.0",
    **({} if _IS_DEV else {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    })
)


@app.get("/")
def read_root():
    return {"message": "Welcome to RollCall AI API"}


@app.get("/health")
def health_check():
    # AUDIT FIX (L-5): do not disclose the deployment environment on an
    # unauthenticated endpoint.
    return {"status": "healthy"}


def run_streamlit_ui():
    """Optional launcher for the Streamlit UI entrypoint used by Phase 3."""
    import subprocess
    import sys
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", "app/ui.py", "--server.port=8501", "--server.headless=true"],
        cwd=os.path.join(os.path.dirname(__file__), os.pardir),
    )


if __name__ == "__main__":
    run_streamlit_ui()
