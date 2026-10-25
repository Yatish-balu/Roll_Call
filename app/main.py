from fastapi import FastAPI
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(
    title="RollCall AI",
    description="Automated roll call processing and reporting API",
    version="0.1.0",
)


@app.get("/")
def read_root():
    return {"message": "Welcome to RollCall AI API"}


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "environment": os.getenv("APP_ENV", "development"),
    }


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
