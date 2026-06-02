#!/usr/bin/env python3
"""
Local development server for the InvestingAssistant API.

Runs the FastAPI app on port 8000 with hot-reload and local storage.

Usage:
    python scripts/run_api.py
    # or
    uvicorn src.api.handler:app --reload --port 8000
"""

import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

# Force local storage mode
os.environ.setdefault("INVESTING_ASSISTANT_ENV", "local")

if __name__ == "__main__":
    import uvicorn

    print("=" * 60)
    print("  InvestingAssistant API — Local Development Server")
    print("  Storage: LocalDynamoStorage (file-based)")
    print("  URL: http://localhost:8000")
    print("  Docs: http://localhost:8000/docs")
    print("=" * 60)

    uvicorn.run(
        "src.api.handler:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=[str(project_root / "src")],
    )
