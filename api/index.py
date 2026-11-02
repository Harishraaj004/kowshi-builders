"""Vercel entrypoint: exposes the FastAPI app from app/main.py as a serverless function."""
from app.main import app  # noqa: F401
