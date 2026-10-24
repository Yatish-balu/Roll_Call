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
